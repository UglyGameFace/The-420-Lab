"""Private Cloudflare Worker + R2 staging transport (no R2 credentials in the bot).

The Worker pulls original Discord attachments directly into a private bucket.
Only small signed request metadata crosses the bot's 256 MiB process. Downloads
for serial image processing are streamed into bounded temporary disk files.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote, urlsplit

import aiohttp

MAX_BYTES = 8 * 1024 * 1024
CDN_HOSTS = frozenset(("cdn.discordapp.com", "media.discordapp.net"))


class IntakeError(RuntimeError):
    pass


class GrowerIntake:
    def __init__(self, endpoint: str, token: str, session: aiohttp.ClientSession):
        url = urlsplit(endpoint.rstrip("/"))
        if url.scheme != "https" or not url.netloc or url.username or url.password:
            raise ValueError("Grower staging endpoint must be a private HTTPS Worker.")
        if len(token) < 32:
            raise ValueError("Grower staging token must be at least 32 characters.")
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.session = session

    @classmethod
    def from_env(cls, session):
        url = os.getenv("LAB_GROWER_QUEUE_ENDPOINT", "").strip()
        token = os.getenv("LAB_GROWER_QUEUE_TOKEN", "").strip()
        if not url or not token:
            raise ValueError("Grower staging endpoint/token are not configured.")
        return cls(url, token, session)

    @staticmethod
    def _source(url: str):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in CDN_HOSTS or
                not (parsed.path.startswith("/attachments/") or
                     parsed.path.startswith("/ephemeral-attachments/")) or
                parsed.username or parsed.password or parsed.port):
            raise ValueError("Only original Discord image attachments can be queued.")

    def _endpoint(self, key: str):
        if (not key.startswith("photos/") or not all(
                segment.isdigit() or (len(segment) == 32 and
                all(c in "0123456789abcdef" for c in segment))
                for segment in key.split("/")[1:]) or len(key.split("/")) != 4):
            raise ValueError("Invalid private grower object key.")
        return self.endpoint + "/v1/objects/" + quote(key, safe="/")

    async def stage(self, key: str, url: str, size: int):
        self._source(url)
        if size <= 0 or size > MAX_BYTES:
            raise ValueError("Original photo exceeds 8 MiB.")
        timeout = aiohttp.ClientTimeout(total=80)
        async with self.session.post(
            self._endpoint(key), headers={"Authorization": "Bearer " + self.token},
            json={"url": url, "size": size}, timeout=timeout,
            allow_redirects=False
        ) as response:
            if response.status != 201:
                raise IntakeError(f"Private photo intake returned HTTP {response.status}.")

    async def exists(self, key: str) -> bool:
        async with self.session.head(
            self._endpoint(key), headers={"Authorization": "Bearer " + self.token},
            timeout=aiohttp.ClientTimeout(total=12), allow_redirects=False
        ) as response:
            if response.status == 404:
                return False
            if response.status != 200:
                raise IntakeError(f"Photo storage status returned HTTP {response.status}.")
            return True

    async def download(self, key: str, path: Path):
        count = 0
        async with self.session.get(
            self._endpoint(key), headers={"Authorization": "Bearer " + self.token},
            timeout=aiohttp.ClientTimeout(total=75), allow_redirects=False
        ) as response:
            if response.status != 200:
                raise IntakeError(f"Queued photo download returned HTTP {response.status}.")
            with path.open("wb") as output:
                async for chunk in response.content.iter_chunked(64 * 1024):
                    count += len(chunk)
                    if count > MAX_BYTES:
                        raise IntakeError("Queued image exceeded allowed bytes.")
                    output.write(chunk)
        if count == 0:
            raise IntakeError("Queued image is empty.")

    async def delete(self, key: str):
        async with self.session.delete(
            self._endpoint(key), headers={"Authorization": "Bearer " + self.token},
            timeout=aiohttp.ClientTimeout(total=18), allow_redirects=False
        ) as response:
            if response.status not in (200, 204):
                raise IntakeError(f"Private photo deletion returned HTTP {response.status}.")
