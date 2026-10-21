"""Isolated Pillow process: release decoded image memory upon exit."""
from __future__ import annotations
import sys
from pathlib import Path
from .growers import MAX_UPLOAD_BYTES, photo_as_jpeg


def main():
    if len(sys.argv) != 3:
        raise SystemExit(2)
    source, output = map(Path, sys.argv[1:])
    if source.stat().st_size > MAX_UPLOAD_BYTES:
        raise SystemExit("Queued original too large")
    # The long-lived Discord bot never materializes either decoded RGB frames
    # or raw image bytes. A short-lived child owns both and exits on completion.
    sanitized = photo_as_jpeg(source.read_bytes())
    output.write_bytes(sanitized)


if __name__ == "__main__":
    main()
