"""Optional local Leafly CSV adapter, for a legitimately licensed export.

CannaBot's public service uses a CSV with Strain, Effects, Flavor and Rating
columns, but does not ship the CSV itself. This parser supports the same basic
column names without copying content, querying Leafly, or storing user data.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import re
import unicodedata


@dataclass(frozen=True)
class LocalLeaflyRow:
    name: str
    rating: str
    effects: tuple[str, ...]
    flavors: tuple[str, ...]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value.casefold())
    return re.sub("[^a-z0-9]", "", value)


def _clean(value: str, maximum: int = 45) -> str:
    return re.sub(r"[^A-Za-z0-9 -]", "", value).strip()[:maximum]


def _field(row: dict[str, str | None], *keys: str) -> str:
    for name in keys:
        value = row.get(name)
        if value:
            return str(value).strip()
    return ""


def _terms(value: str) -> tuple[str, ...]:
    terms = [_clean(x, 26) for x in value.split(",")[:6]]
    return tuple(x for x in terms if x)[:5]


@lru_cache(maxsize=4)
def _read_csv(filename: str, size: int, mtime_ns: int) -> dict[str, LocalLeaflyRow]:
    """File identity cache avoids repeated disk parsing; no remote fetch."""
    rows: dict[str, LocalLeaflyRow] = {}
    with Path(filename).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for index, row in enumerate(reader):
            if index >= 100_000:
                break
            name = _clean(_field(row, "Strain", "strain", "Name", "name"), 80)
            key = normalize(name)
            if len(key) < 2 or key in rows:
                continue
            rating = _field(row, "Rating", "rating")
            try:
                numeric = float(rating)
                rating = f"{numeric:.1f}/5" if 0 <= numeric <= 5 else ""
            except ValueError:
                rating = ""
            rows[key] = LocalLeaflyRow(
                name, rating,
                _terms(_field(row, "Effects", "effects")),
                _terms(_field(row, "Flavor", "Flavors", "flavors")),
            )
    return rows


def local_profile(name: str) -> LocalLeaflyRow | None:
    """Opt-in only, no CSV is shipped or downloaded as part of The Weed Doctor."""
    path = os.getenv("LEAFLY_LICENSED_CSV_PATH", "").strip()
    if not path:
        return None
    try:
        file = Path(path)
        stat = file.stat()
        if not file.is_file() or stat.st_size > 16 * 1024 * 1024:
            return None
        return _read_csv(str(file.resolve()), stat.st_size, stat.st_mtime_ns).get(normalize(name))
    except (OSError, UnicodeError, csv.Error, ValueError):
        return None


def licensed_data_summary(name: str) -> str:
    record = local_profile(name)
    if record is None:
        return ""
    fields = [f"**Licensed local Leafly dataset:** {record.name}"]
    if record.rating:
        fields.append("User rating recorded in supplied snapshot: " + record.rating)
    if record.effects:
        fields.append("Reported effects: " + ", ".join(record.effects))
    if record.flavors:
        fields.append("Reported flavors: " + ", ".join(record.flavors))
    fields.append(
        "This is an owner-supplied static export, not current live Leafly data. "
        "User reports do not establish medical benefit, dosage, or product potency."
    )
    return "\n".join(fields)
