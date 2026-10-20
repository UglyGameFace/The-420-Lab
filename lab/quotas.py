"""Defensive rate budgets shared across interactions and external API calls.

Global counters are anonymous and stored in a small SQLite file. Per-user and
per-guild counters exist only in bounded process memory. Defaults deliberately
prioritize preventing quota exhaustion over maximum throughput.
"""
from __future__ import annotations
from collections import OrderedDict, deque
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import time


class QuotaExceeded(Exception):
    """Request was rejected before consuming provider quota."""

    def __init__(self, kind: str, retry_after: int = 0):
        self.kind = kind
        self.retry_after = max(1, int(retry_after))
        super().__init__(f"{kind} quota reached")


def _setting(name: str, default: int, minimum: int = 1, maximum: int = 100000) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name}: expected integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"Invalid {name}: must be {minimum}..{maximum}")
    return value


class QuotaGate:
    def __init__(self, db_path: str | None = None):
        self.db_path = str(db_path or os.getenv("LAB_QUOTA_DB_PATH", "lab-quotas.sqlite3"))
        self.member_10m = _setting("LAB_USER_10M_LIMIT", 8)
        self.guild_hour = _setting("LAB_GUILD_HOUR_LIMIT", 80)
        self.global_minute = _setting("LAB_GLOBAL_MINUTE_LIMIT", 15)
        self.global_daily = _setting("LAB_GLOBAL_DAILY_LIMIT", 400)
        self.gemini_minute = _setting("LAB_GEMINI_MINUTE_LIMIT", 2)
        self.gemini_daily = _setting("LAB_GEMINI_DAILY_LIMIT", 30)
        self.api_minute = _setting("LAB_PROVIDER_MINUTE_LIMIT", 45)
        self.api_daily = _setting("LAB_PROVIDER_DAILY_LIMIT", 1200)
        self.users: OrderedDict[int, deque[float]] = OrderedDict()
        self.guilds: OrderedDict[int, deque[float]] = OrderedDict()
        self.ledger_seen_before = False
        self.previous_code_revision = False
        self.boot_number = 0
        self._initialize()

    LIMIT_FIELDS = (
        "member_10m", "guild_hour", "global_minute", "global_daily",
        "gemini_minute", "gemini_daily", "api_minute", "api_daily"
    )

    def _read_limit(self, name: str) -> int:
        """Read the live owner-selected cap, bounded by the deployment's ceiling."""
        if name not in self.LIMIT_FIELDS:
            raise ValueError("Unknown quota setting")
        ceiling = getattr(self, name)
        try:
            with closing(self._connect()) as db:
                row = db.execute("SELECT value FROM guard_settings WHERE name=?", (name,)).fetchone()
            if not row:
                return ceiling
            value = row[0]
            if type(value) is not int or not 1 <= value <= ceiling:
                raise QuotaExceeded("storage-unavailable", 60)
            return value
        except sqlite3.Error as exc:
            raise QuotaExceeded("storage-unavailable", 60) from exc

    def limit(self, name: str) -> int:
        return self._read_limit(name)

    def set_limit(self, name: str, value: int):
        """Bot owner may tighten or restore a cap, never exceed the environment ceiling."""
        if name not in self.LIMIT_FIELDS:
            raise ValueError("Unsupported setting")
        maximum = getattr(self, name)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"Must be an integer from 1 to {maximum}")
        try:
            with closing(self._connect()) as db, db:
                db.execute(
                    """INSERT INTO guard_settings(name,value) VALUES (?,?)
                    ON CONFLICT(name) DO UPDATE SET value=excluded.value""",
                    (name, value))
        except sqlite3.Error as exc:
            raise QuotaExceeded("storage-unavailable", 60) from exc

    def ai_enabled(self) -> bool:
        """Deployment kill switch is absolute; Discord can additionally pause AI."""
        if os.getenv("LAB_AI_ENABLED", "true").strip().lower() not in {"1", "true", "on", "yes"}:
            return False
        try:
            with closing(self._connect()) as db:
                row = db.execute("SELECT value FROM guard_settings WHERE name='ai_enabled'").fetchone()
        except sqlite3.Error as exc:
            raise QuotaExceeded("storage-unavailable", 60) from exc
        if row is None:
            return True
        if row[0] not in (0, 1):
            raise QuotaExceeded("storage-unavailable", 60)
        return bool(row[0])

    def set_ai_enabled(self, enabled: bool):
        if type(enabled) is not bool:
            raise ValueError("AI control expects a boolean")
        if enabled and os.getenv("LAB_AI_ENABLED", "true").strip().lower() not in {"1","true","on","yes"}:
            raise ValueError("AI disabled in hosting environment; Discord cannot override that setting")
        try:
            with closing(self._connect()) as db, db:
                db.execute(
                    """INSERT INTO guard_settings(name,value) VALUES ('ai_enabled',?)
                    ON CONFLICT(name) DO UPDATE SET value=excluded.value""", (int(enabled),))
        except sqlite3.Error as exc:
            raise QuotaExceeded("storage-unavailable", 60) from exc

    def _connect(self):
        # Fail closed on disk / permission errors, rather than silently lifting quotas.
        db = sqlite3.connect(self.db_path, timeout=2.0)
        db.execute("PRAGMA busy_timeout=2000")
        return db

    def _initialize(self):
        path = Path(self.db_path)
        if str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS budget_counts (
                scope TEXT NOT NULL,
                window INTEGER NOT NULL,
                used INTEGER NOT NULL,
                PRIMARY KEY (scope, window)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS guard_settings (
                name TEXT PRIMARY KEY, value INTEGER NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS guard_metadata (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )""")
            prior_boot = db.execute(
                "SELECT value FROM guard_metadata WHERE name='boots'").fetchone()
            prior_hash = db.execute(
                "SELECT value FROM guard_metadata WHERE name='code_hash'").fetchone()
            self.boot_number = int(prior_boot[0]) + 1 if prior_boot else 1
            self.ledger_seen_before = bool(prior_boot)
            # Fingerprint source code only, never member details or API credentials.
            current_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
            self.previous_code_revision = bool(
                prior_hash and prior_hash[0] != current_hash)
            for key, value in (
                ("boots", str(self.boot_number)),
                ("code_hash", current_hash),
                ("last_boot_utc", str(int(time.time()))),
            ):
                db.execute(
                    """INSERT INTO guard_metadata(name,value) VALUES (?,?)
                    ON CONFLICT(name) DO UPDATE SET value=excluded.value""",
                    (key, value))

    def continuity_description(self) -> str:
        if self.previous_code_revision:
            return "Prior quota ledger found after a code revision"
        if self.ledger_seen_before:
            return f"Prior quota ledger found (launch {self.boot_number})"
        return "First observed launch; host-file persistence is unverified"



    def _take_global(self, category: str, quotas: tuple[tuple[str, int, int], ...],
                     now: int | None = None) -> None:
        timestamp = int(time.time()) if now is None else int(now)
        limits = [(category + "-" + suffix, timestamp // seconds,
                   cap, seconds - timestamp % seconds)
                  for suffix, seconds, cap in quotas]
        try:
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                for scope, window, cap, retry in limits:
                    row = db.execute(
                        "SELECT used FROM budget_counts WHERE scope=? AND window=?",
                        (scope, window)).fetchone()
                    if row and row[0] >= cap:
                        raise QuotaExceeded(category, retry)
                for scope, window, _, _ in limits:
                    db.execute(
                        """INSERT INTO budget_counts(scope,window,used) VALUES (?, ?, 1)
                        ON CONFLICT(scope,window) DO UPDATE SET used=used+1""",
                        (scope, window))
                # Bounded data retention (14 days); no member identifiers in DB.
                if timestamp % 97 == 0:
                    for suffix, seconds, _ in quotas:
                        scope = category + "-" + suffix
                        db.execute(
                            "DELETE FROM budget_counts WHERE scope=? AND window<?",
                            (scope, timestamp // seconds - max(2, 14 * 86400 // seconds)))
        except sqlite3.Error as exc:
            raise QuotaExceeded("storage-unavailable", 60) from exc

    def take_gemini(self, *, now: int | None = None):
        if not self.ai_enabled():
            raise QuotaExceeded("ai-paused", 60)
        self._take_global("gemini", (
            ("minute", 60, self.limit("gemini_minute")),
            ("daily", 86400, self.limit("gemini_daily"))), now)

    def take_provider(self, *, now: int | None = None):
        self._take_global("provider", (
            ("minute", 60, self.limit("api_minute")),
            ("daily", 86400, self.limit("api_daily"))), now)

    @staticmethod
    def _verify_window(table: OrderedDict[int, deque[float]], identity: int,
                       now: float, window: int, limit: int) -> int:
        usage = table.get(identity)
        if usage is None:
            usage = deque()
            table[identity] = usage
        while usage and now - usage[0] >= window:
            usage.popleft()
        table.move_to_end(identity)
        # A bounded in-memory map cannot keep unbounded member IDs.
        while len(table) > 4096:
            table.popitem(last=False)
        if len(usage) >= limit:
            return max(1, int(window - (now - usage[0]) + .999))
        return 0

    def admit_member(self, user_id: int, guild_id: int | None,
                     *, now: float | None = None, utc: int | None = None):
        tick = time.monotonic() if now is None else now
        user_wait = self._verify_window(self.users, user_id, tick, 600, self.limit("member_10m"))
        guild_wait = self._verify_window(self.guilds, guild_id or 0, tick, 3600, self.limit("guild_hour"))
        if user_wait:
            raise QuotaExceeded("member", user_wait)
        if guild_wait:
            raise QuotaExceeded("server", guild_wait)
        self._take_global("command", (
            ("minute", 60, self.limit("global_minute")),
            ("daily", 86400, self.limit("global_daily"))), utc)
        self.users[user_id].append(tick)
        self.guilds[guild_id or 0].append(tick)

    def usage(self) -> dict[str, tuple[int, int]]:
        """Only anonymous current-day counts; don't expose member identities."""
        window = int(time.time()) // 86400
        caps = {"command": self.limit("global_daily"), "gemini": self.limit("gemini_daily"),
                "provider": self.limit("api_daily")}
        try:
            with closing(self._connect()) as db:
                return {name: (
                    (db.execute("SELECT used FROM budget_counts WHERE scope=? AND window=?",
                                (name + "-daily", window)).fetchone() or (0,))[0], cap)
                    for name, cap in caps.items()}
        except sqlite3.Error:
            return {name: (-1, cap) for name, cap in caps.items()}
