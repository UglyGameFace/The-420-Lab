"""Privacy-preserving, process-local operational counters."""
from collections import Counter
import time

class LabHealth:
    """Never records names, questions, guild IDs, or Discord user IDs."""
    def __init__(self):
        self.started = time.monotonic()
        self.counts = Counter()

    def record(self, feature: str) -> None:
        if feature in {"research", "compound", "trials", "fda", "strain", "guides", "panel"}:
            self.counts[feature] += 1

    @property
    def uptime_seconds(self) -> int:
        return max(0, int(time.monotonic() - self.started))

    def report(self, guild_count: int, cache_items: int, *, ai_enabled: bool) -> str:
        uptime = self.uptime_seconds
        hours, rem = divmod(uptime, 3600)
        minutes = rem // 60
        used = ", ".join(f"{key}: {self.counts[key]}" for key in sorted(self.counts)) or "none yet"
        return (
            "**The 420 Lab | Process Health**\n"
            f"Uptime: {hours}h {minutes}m • Connected servers: {guild_count}\n"
            f"In-memory research cache: {cache_items} entries • AI configured: {ai_enabled}\n"
            f"Research calls this process: {used}\n\n"
            "This reports only in-memory activity and does not ping any external provider. "
            "It is not a provider uptime guarantee. Data resets on restarts. "
            "No member questions or identifiable usage history are stored."
        )
