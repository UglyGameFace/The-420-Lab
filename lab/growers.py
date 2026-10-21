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
import sqlite3

from PIL import Image, ImageOps, UnidentifiedImageError

from .strains import compact, find_matches

STAGES = ("seedling", "vegetative", "flowering", "harvest")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 8_000_000


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
                created_utc TEXT NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_grower_pending
                ON grower_submissions(guild,status,id)""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_grower_author
                ON grower_submissions(guild,author_hash,status)""")

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

    def submit(self, guild_id: int, user_id: int, byline: str,
               strain: str, stage: str, caption: str, review_message: int) -> int:
        if not (self.configuration(guild_id) and self.configuration(guild_id)[2]):
            raise ValueError("Grower Showcase has not been configured in this server.")
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
                "WHERE guild=? AND author_hash=? AND status='pending'",
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
                (guild,author_hash,byline,strain,stage,caption,review_message,created_utc)
                VALUES(?,?,?,?,?,?,?,?)""",
                (str(guild_id), identity, byline, name, stage, caption,
                 str(review_message), created))
            return cursor.lastrowid

    def pending(self, guild_id: int):
        with closing(self.profiles._connect()) as db:
            return db.execute(
                """SELECT id,byline,strain,stage,review_message FROM grower_submissions
                WHERE guild=? AND status='pending' ORDER BY id LIMIT 10""",
                (str(guild_id),)).fetchall()

    def item(self, guild_id: int, submission_id: int):
        with closing(self.profiles._connect()) as db:
            return db.execute(
                """SELECT id,author_hash,byline,strain,stage,caption,
                          review_message,gallery_message,status
                FROM grower_submissions WHERE guild=? AND id=?""",
                (str(guild_id), submission_id)).fetchone()

    def lock(self, guild_id: int, submission_id: int, *,
             purpose: str, user_id: int | None = None):
        if purpose not in ("review", "remove"):
            raise ValueError("Unsupported submission action")
        allowed = ("pending",) if purpose == "review" else ("pending", "approved")
        status = "reviewing" if purpose == "review" else "removing"
        with closing(self.profiles._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            item = db.execute(
                """SELECT id,author_hash,byline,strain,stage,caption,
                          review_message,gallery_message,status
                FROM grower_submissions WHERE guild=? AND id=?""",
                (str(guild_id), submission_id)).fetchone()
            if not item or item[8] not in allowed:
                raise ValueError("Submission not found or already being reviewed.")
            if user_id is not None and item[1] != self._identity(guild_id, user_id):
                raise ValueError("You may only withdraw your own submissions.")
            db.execute(
                "UPDATE grower_submissions SET status=? WHERE guild=? AND id=?",
                (status, str(guild_id), submission_id))
            return item

    def unlock(self, guild_id: int, submission_id: int, old_status: str):
        if old_status not in ("pending", "approved"):
            raise ValueError("Unsupported recovery status")
        with closing(self.profiles._connect()) as db, db:
            db.execute(
                """UPDATE grower_submissions SET status=?
                WHERE guild=? AND id=? AND status IN ('reviewing','removing')""",
                (old_status, str(guild_id), submission_id))

    def approve(self, guild_id: int, submission_id: int, gallery_message: int):
        with closing(self.profiles._connect()) as db, db:
            count = db.execute(
                """UPDATE grower_submissions SET status='approved', gallery_message=?
                WHERE guild=? AND id=? AND status='reviewing'""",
                (str(gallery_message), str(guild_id), submission_id)).rowcount
            if count != 1:
                raise RuntimeError("Submission review state changed during publication")

    def delete(self, guild_id: int, submission_id: int, status: str):
        if status not in ("reviewing", "removing"):
            raise ValueError("Unsupported deletion status")
        with closing(self.profiles._connect()) as db, db:
            db.execute(
                "DELETE FROM grower_submissions WHERE guild=? AND id=? AND status=?",
                (str(guild_id), submission_id, status))

    def journal(self, guild_id: int, user_id: int, name: str = ""):
        """A contributor's approved progress timeline, never other members' posts."""
        selected = verified_strain(name) if name else ""
        with closing(self.profiles._connect()) as db:
            return db.execute(
                """SELECT id,strain,stage,caption,gallery_message,created_utc
                FROM grower_submissions WHERE guild=? AND author_hash=?
                AND status='approved' AND (?='' OR strain=?)
                ORDER BY created_utc DESC,id DESC LIMIT 12""",
                (str(guild_id), self._identity(guild_id, user_id), selected, selected)).fetchall()

    def stats(self, guild_id: int, user_id: int):
        with closing(self.profiles._connect()) as db:
            approved, pending, varieties = db.execute(
                """SELECT COUNT(*) FILTER(WHERE status='approved'),
                    COUNT(*) FILTER(WHERE status='pending'),
                    COUNT(DISTINCT CASE WHEN status='approved' THEN strain END)
                FROM grower_submissions WHERE guild=? AND author_hash=?""",
                (str(guild_id), self._identity(guild_id, user_id))).fetchone()
        badge = ("🏆 Garden Legend" if approved >= 20 else
                 "🌳 Cultivator" if approved >= 5 else
                 "🌱 First Showcase" if approved >= 1 else
                 "🌿 Aspiring Contributor")
        return approved, pending, varieties, badge
