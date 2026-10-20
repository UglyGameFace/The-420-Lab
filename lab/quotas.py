"""Defensive rate budgets shared across interactions and external API calls.

Global counters are anonymous and stored in a small SQLite file. Per-user and
per-guild counters exist only in bounded process memory. Defaults deliberately
prioritize preventing quota exhaustion over maximum throughput.
"""
from __future__ import annotations
from collections import OrderedDict, deque
from contextlib import closing
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
        self._initialize()

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
        self._take_global("gemini", (
            ("minute", 60, self.gemini_minute),
            ("daily", 86400, self.gemini_daily)), now)

    def take_provider(self, *, now: int | None = None):
        self._take_global("provider", (
            ("minute", 60, self.api_minute),
            ("daily", 86400, self.api_daily)), now)

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
        user_wait = self._verify_window(self.users, user_id, tick, 600, self.member_10m)
        guild_wait = self._verify_window(self.guilds, guild_id or 0, tick, 3600, self.guild_hour)
        if user_wait:
            raise QuotaExceeded("member", user_wait)
        if guild_wait:
            raise QuotaExceeded("server", guild_wait)
        self._take_global("command", (
            ("minute", 60, self.global_minute),
            ("daily", 86400, self.global_daily)), utc)
        self.users[user_id].append(tick)
        self.guilds[guild_id or 0].append(tick)

    def usage(self) -> dict[str, tuple[int, int]]:
        """Only anonymous current-day counts; don't expose member identities."""
        window = int(time.time()) // 86400
        caps = {"command": self.global_daily, "gemini": self.gemini_daily,
                "provider": self.api_daily}
        try:
            with closing(self._connect()) as db:
                return {name: (
                    (db.execute("SELECT used FROM budget_counts WHERE scope=? AND window=?",
                                (name + "-daily", window)).fetchone() or (0,))[0], cap)
                    for name, cap in caps.items()}
        except sqlite3.Error:
            return {name: (-1, cap) for name, cap in caps.items()}
