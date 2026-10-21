"""Per-server opt-in grower showcase with human-reviewed photographs.

Uploaded photos are held in a private Discord review channel, never promoted
to the global strain catalog. The profile database stores only a salted member
digest and a contributor-selected public byline, not Discord member IDs.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone, timedelta
from io import BytesIO
import re
import secrets
import sqlite3

from PIL import Image, ImageOps, UnidentifiedImageError

from .strains import compact, find_matches

STAGES = ("seedling", "vegetative", "flowering", "harvest")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 8_000_000
RECOVERY_AFTER = timedelta(minutes=5)


def verified_strain(name: str) -> str:
    entries = find_matches(name, limit=1)
    if not entries or entries[0].approximate or compact(entries[0].name) != compact(name):
        raise ValueError("Use an exact name from /straininfo, not an approximate match.")
    return entries[0].name


def clean_caption(value: str, *, maximum: int) -> str:
    value = re.sub(r"[\x00-\x1f<>@]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > maximum or "http://" in value.lower() or "https://" in value.lower():
        raise ValueError("Keep the caption short and free of mentions or external links.")
    return value


def photo_as_jpeg(data: bytes) -> bytes:
    """Re-encode a bounded real image without GPS, EXIF, or user metadata."""
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Upload one JPEG, PNG, or WebP photo under 8 MiB.")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("Only JPEG, PNG, and WebP photos are supported.")
            if source.width * source.height > MAX_PIXELS or min(source.size) < 64:
                raise ValueError("Use a photo at least 64 px wide and no larger than 8 megapixels.")
            corrected = ImageOps.exif_transpose(source)
            corrected.thumbnail((2048, 2048))
            picture = corrected.convert("RGB")
            output = BytesIO()
            picture.save(output, format="JPEG", quality=83, optimize=True)
            value = output.getvalue()
            if len(value) > MAX_UPLOAD_BYTES:
                raise ValueError("The normalized photo is too large.")
            return value
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The attachment is not a supported, readable photo.") from exc


class GrowerHub:
    """Storage shares the existing per-server strain profile SQLite database."""

    def __init__(self, profiles):
        self.profiles = profiles
        # New each process, never printed or exposed through commands.
        self._process_marker = secrets.token_hex(20)
        with closing(self.profiles._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS grower_config (
                guild TEXT PRIMARY KEY, review_channel TEXT NOT NULL,
                gallery_channel TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1)""")
            db.execute("""CREATE TABLE IF NOT EXISTS grower_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild TEXT NOT NULL, author_hash TEXT NOT NULL,
                byline TEXT NOT NULL, strain TEXT NOT NULL,
                stage TEXT NOT NULL, caption TEXT NOT NULL,
                review_message TEXT NOT NULL, gallery_message TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_utc TEXT NOT NULL, review_channel TEXT NOT NULL,
                gallery_channel TEXT, operation_utc TEXT NOT NULL DEFAULT '')""")
            # Existing deployments have this table without the operation timestamp.
            # Migrate in place; never rebuild or discard submissions.
            columns = {column[1] for column in db.execute("PRAGMA table_info(grower_submissions)")}
            if "operation_utc" not in columns:
                db.execute("""ALTER TABLE grower_submissions
                    ADD COLUMN operation_utc TEXT NOT NULL DEFAULT ''""")
            db.execute("""CREATE TABLE IF NOT EXISTS grower_storage_probe (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                armed_process TEXT NOT NULL, armed_utc TEXT NOT NULL,
                verified_utc TEXT NOT NULL DEFAULT ''
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_grower_pending
                ON grower_submissions(guild,status,id)""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_grower_author
                ON grower_submissions(guild,author_hash,status)""")

    def _probe(self):
        with closing(self.profiles._connect()) as db:
            result = db.execute("PRAGMA quick_check(1)").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("The Grower Showcase database integrity check failed.")
            return db.execute(
                """SELECT armed_process,armed_utc,verified_utc
                FROM grower_storage_probe WHERE singleton=1""").fetchone()

    def storage_status(self) -> tuple[str, str]:
        """Return safe state and its timestamp; no filesystem paths or tokens."""
        row = self._probe()
        if row is None:
            return "unarmed", ""
        if row[2]:
            return "verified", row[2]
        if row[0] == self._process_marker:
            return "armed_this_process", row[1]
        return "ready_to_verify", row[1]

    def arm_storage_probe(self) -> None:
        """Run before intentionally restarting/redeploying the application."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with closing(self.profiles._connect()) as db, db:
            db.execute(
                """INSERT INTO grower_storage_probe
                (singleton,armed_process,armed_utc,verified_utc)
                VALUES(1,?,?,'')
                ON CONFLICT(singleton) DO UPDATE SET
                armed_process=excluded.armed_process,
                armed_utc=excluded.armed_utc,
                verified_utc=''""",
                (self._process_marker, now))

    def verify_storage_probe(self) -> str:
        """Require a different bot process and the same persisted database."""
        with closing(self.profiles._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT armed_process FROM grower_storage_probe
                WHERE singleton=1""").fetchone()
            if not row:
                raise ValueError("First run /growerstorage action:arm before restarting.")
            if row[0] == self._process_marker:
                raise ValueError("Still in the same bot process. Restart or redeploy, then verify.")
            result = db.execute("PRAGMA quick_check(1)").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("Database integrity check failed after process restart.")
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            db.execute(
                "UPDATE grower_storage_probe SET verified_utc=? WHERE singleton=1",
                (now,))
            return now

    def storage_ready(self) -> bool:
        """This proves at least one cross-process DB continuity check, not backups."""
        return self.storage_status()[0] == "verified"

    def configuration(self, guild_id: int):
        with closing(self.profiles._connect()) as db:
            return db.execute(
                "SELECT review_channel,gallery_channel,enabled FROM grower_config WHERE guild=?",
                (str(guild_id),)).fetchone()

    def configure(self, guild_id: int, review_id: int, gallery_id: int, enabled: bool = True):
        if review_id == gallery_id:
            raise ValueError("The private review and public gallery channels must differ.")
        with closing(self.profiles._connect()) as db, db:
            db.execute("""INSERT INTO grower_config VALUES(?,?,?,?)
                ON CONFLICT(guild) DO UPDATE SET
                review_channel=excluded.review_channel,
                gallery_channel=excluded.gallery_channel,
                enabled=excluded.enabled""",
                (str(guild_id), str(review_id), str(gallery_id), int(enabled)))

    def _identity(self, guild_id: int, user_id: int) -> str:
        return self.profiles.member_hash(guild_id, user_id)

    def begin_upload(self, guild_id: int, user_id: int, byline: str,
                     strain: str, stage: str, caption: str,
                     review_channel: int) -> int:
        """Reserve a durable ID before the first Discord send can occur."""
        setting = self.configuration(guild_id)
        if not setting or not setting[2]:
            raise ValueError("Grower Showcase has not been configured in this server.")
        if int(setting[0]) != review_channel:
            raise ValueError("The review channel changed while uploading. Please retry.")
        name = verified_strain(strain)
        if stage not in STAGES:
            raise ValueError("Select a supported growth stage.")
        byline = clean_caption(byline, maximum=45) or "Community grower"
        caption = clean_caption(caption, maximum=220)
        identity = self._identity(guild_id, user_id)
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with closing(self.profiles._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute(
                "SELECT COUNT(*) FROM grower_submissions "
                "WHERE guild=? AND author_hash=? AND status IN ('pending','uploading')",
                (str(guild_id), identity)).fetchone()[0]
            cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            daily = db.execute(
                "SELECT COUNT(*) FROM grower_submissions "
                "WHERE guild=? AND author_hash=? AND created_utc>=?",
                (str(guild_id), identity, cutoff)).fetchone()[0]
            if daily >= 3 or pending >= 5:
                raise ValueError("Grower uploads are limited to 3 per day and 5 pending.")
            cursor = db.execute(
                """INSERT INTO grower_submissions
                (guild,author_hash,byline,strain,stage,caption,review_message,
                 created_utc,review_channel,status,operation_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (str(guild_id), identity, byline, name, stage, caption,
                 "0", created, str(review_channel), "uploading", created))
            return cursor.lastrowid

    def finish_upload(self, guild_id: int, submission_id: int, review_message: int):
        """Confirm a photo by attaching the Discord ID to the reserved record."""
        if review_message <= 0:
            raise ValueError("A valid Discord review message is required.")
        with closing(self.profiles._connect()) as db, db:
            changed = db.execute(
                """UPDATE grower_submissions
                SET review_message=?,status='pending',operation_utc=''
                WHERE guild=? AND id=? AND status='uploading'""",
                (str(review_message), str(guild_id), submission_id)).rowcount
            if changed != 1:
                raise ValueError("The upload state changed before confirmation.")

    def upload_is_interrupted(self, guild_id: int, submission_id: int) -> bool:
        with closing(self.profiles._connect()) as db:
            row = db.execute(
                """SELECT status,operation_utc FROM grower_submissions
                WHERE guild=? AND id=?""",
                (str(guild_id), submission_id)).fetchone()
        return bool(row and row[0] == "uploading" and self._stale(row[1]))

    def discard_interrupted_upload(self, guild_id: int, submission_id: int):
        """Only after staff confirms no review-channel post exists."""
        with closing(self.profiles._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT status,operation_utc FROM grower_submissions
                WHERE guild=? AND id=?""",
                (str(guild_id), submission_id)).fetchone()
            if not row or row[0] != "uploading" or not self._stale(row[1]):
                raise ValueError("The upload is still active or no longer interrupted.")
            db.execute(
                "DELETE FROM grower_submissions WHERE guild=? AND id=? AND status='uploading'",
                (str(guild_id), submission_id))

    def pending(self, guild_id: int):
        with closing(self.profiles._connect()) as db:
            return db.execute(
                """SELECT id,byline,strain,stage,review_message,review_channel FROM grower_submissions
                WHERE guild=? AND status='pending' ORDER BY id LIMIT 10""",
                (str(guild_id),)).fetchall()

    def item(self, guild_id: int, submission_id: int):
        with closing(self.profiles._connect()) as db:
            return db.execute(
                """SELECT id,author_hash,byline,strain,stage,caption,
                          review_message,gallery_message,status,review_channel,gallery_channel
                FROM grower_submissions WHERE guild=? AND id=?""",
                (str(guild_id), submission_id)).fetchone()

    @staticmethod
    def _stale(value: str) -> bool:
        """Legacy empty timestamps are treated as interrupted operations."""
        cutoff = (datetime.now(timezone.utc) - RECOVERY_AFTER).strftime("%Y-%m-%dT%H:%M:%SZ")
        return not value or value < cutoff

    def interrupted(self, guild_id: int):
        """Only stale non-final states; ordinary ongoing requests are not shown."""
        cutoff = (datetime.now(timezone.utc) - RECOVERY_AFTER).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        with closing(self.profiles._connect()) as db:
            return db.execute(
                """SELECT id,status FROM grower_submissions
                WHERE guild=? AND status IN ('uploading','reviewing','removing')
                AND (operation_utc='' OR operation_utc<?)
                ORDER BY id LIMIT 20""", (str(guild_id), cutoff)).fetchall()

    def review_is_interrupted(self, guild_id: int, submission_id: int) -> bool:
        with closing(self.profiles._connect()) as db:
            row = db.execute(
                """SELECT status,operation_utc FROM grower_submissions
                WHERE guild=? AND id=?""", (str(guild_id), submission_id)).fetchone()
        return bool(row and row[0] == "reviewing" and self._stale(row[1]))

    def prepare_review(self, guild_id: int, submission_id: int, gallery_channel: int):
        """Record publication destination BEFORE sending a gallery post."""
        with closing(self.profiles._connect()) as db, db:
            changed = db.execute(
                """UPDATE grower_submissions SET gallery_channel=?
                WHERE guild=? AND id=? AND status='reviewing'""",
                (str(gallery_channel), str(guild_id), submission_id)).rowcount
            if changed != 1:
                raise ValueError("The review state changed before publication.")

    def requeue_interrupted_review(self, guild_id: int, submission_id: int):
        """Only call after a moderator confirms the photo was NOT published."""
        with closing(self.profiles._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT status,operation_utc FROM grower_submissions
                WHERE guild=? AND id=?""", (str(guild_id), submission_id)).fetchone()
            if not row or row[0] != "reviewing" or not self._stale(row[1]):
                raise ValueError("The review is not interrupted or is still running.")
            db.execute(
                """UPDATE grower_submissions SET status='pending', gallery_channel=NULL,
                operation_utc='' WHERE guild=? AND id=?""",
                (str(guild_id), submission_id))

    def lock(self, guild_id: int, submission_id: int, *,
             purpose: str, user_id: int | None = None):
        if purpose not in ("review", "remove", "reject"):
            raise ValueError("Unsupported submission action")
        allowed = ("pending",) if purpose in ("review", "reject") else ("pending", "approved")
        status = "reviewing" if purpose == "review" else "removing"
        with closing(self.profiles._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            item = db.execute(
                """SELECT id,author_hash,byline,strain,stage,caption,
                          review_message,gallery_message,status,review_channel,gallery_channel
                FROM grower_submissions WHERE guild=? AND id=?""",
                (str(guild_id), submission_id)).fetchone()
            if not item:
                raise ValueError("Submission not found.")
            if user_id is not None and item[1] != self._identity(guild_id, user_id):
                raise ValueError("You may only withdraw your own submissions.")
            if item[8] not in allowed:
                if not (purpose == "remove" and item[8] == "removing"):
                    raise ValueError("Submission is already being processed.")
                prior = db.execute(
                    "SELECT operation_utc FROM grower_submissions WHERE guild=? AND id=?",
                    (str(guild_id), submission_id)).fetchone()[0]
                if not self._stale(prior):
                    raise ValueError("A removal is already in progress. Try again in five minutes.")
            started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            db.execute(
                """UPDATE grower_submissions SET status=?,operation_utc=?
                WHERE guild=? AND id=?""",
                (status, started, str(guild_id), submission_id))
            return item

    def unlock(self, guild_id: int, submission_id: int, old_status: str):
        if old_status not in ("pending", "approved"):
            raise ValueError("Unsupported recovery status")
        with closing(self.profiles._connect()) as db, db:
            db.execute(
                """UPDATE grower_submissions SET status=?,operation_utc=''
                WHERE guild=? AND id=? AND status IN ('reviewing','removing')""",
                (old_status, str(guild_id), submission_id))

    def approve(self, guild_id: int, submission_id: int,
                gallery_message: int, gallery_channel: int):
        with closing(self.profiles._connect()) as db, db:
            count = db.execute(
                """UPDATE grower_submissions
                SET status='approved', gallery_message=?, gallery_channel=?, operation_utc=''
                WHERE guild=? AND id=? AND status='reviewing'""",
                (str(gallery_message), str(gallery_channel), str(guild_id), submission_id)).rowcount
            if count != 1:
                raise RuntimeError("Submission review state changed during publication")

    def delete(self, guild_id: int, submission_id: int, status: str):
        if status not in ("reviewing", "removing"):
            raise ValueError("Unsupported deletion status")
        with closing(self.profiles._connect()) as db, db:
            db.execute(
                "DELETE FROM grower_submissions WHERE guild=? AND id=? AND status=?",
                (str(guild_id), submission_id, status))

    def my_uploads(self, guild_id: int, user_id: int):
        """Recover submission IDs for private withdrawal, even after restart."""
        with closing(self.profiles._connect()) as db:
            return db.execute(
                """SELECT id,strain,status FROM grower_submissions
                WHERE guild=? AND author_hash=?
                AND status IN ('uploading','pending','approved')
                ORDER BY id DESC LIMIT 10""",
                (str(guild_id), self._identity(guild_id, user_id))).fetchall()

    def journal(self, guild_id: int, user_id: int, name: str = ""):
        """A contributor's approved progress timeline, never other members' posts."""
        selected = verified_strain(name) if name else ""
        with closing(self.profiles._connect()) as db:
            return db.execute(
                """SELECT id,strain,stage,caption,gallery_message,created_utc,gallery_channel
                FROM grower_submissions WHERE guild=? AND author_hash=?
                AND status='approved' AND (?='' OR strain=?)
                ORDER BY created_utc DESC,id DESC LIMIT 12""",
                (str(guild_id), self._identity(guild_id, user_id), selected, selected)).fetchall()

    def stats(self, guild_id: int, user_id: int):
        with closing(self.profiles._connect()) as db:
            approved, pending, varieties = db.execute(
                """SELECT COUNT(*) FILTER(WHERE status='approved'),
                    COUNT(*) FILTER(WHERE status IN ('pending','uploading')),
                    COUNT(DISTINCT CASE WHEN status='approved' THEN strain END)
                FROM grower_submissions WHERE guild=? AND author_hash=?""",
                (str(guild_id), self._identity(guild_id, user_id))).fetchone()
        badge = ("🏆 Garden Legend" if approved >= 20 else
                 "🌳 Cultivator" if approved >= 5 else
                 "🌱 First Showcase" if approved >= 1 else
                 "🌿 Aspiring Contributor")
        return approved, pending, varieties, badge
