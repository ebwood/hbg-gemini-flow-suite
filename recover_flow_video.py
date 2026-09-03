#!/usr/bin/env python3
"""Download an already-submitted Flow video without creating a new job."""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

from gflow_cli.api import routes
from playwright.async_api import async_playwright


OUTPUT_ROOT = Path("/data/outputs").resolve()


async def recover(media_id: str, target: Path, wait_seconds: int) -> None:
    resolved = target.resolve()
    if not resolved.is_relative_to(OUTPUT_ROOT):
        raise ValueError("recovery target must be inside /data/outputs")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0, wait_seconds)
    endpoint = os.environ.get("GFLOW_CLI_CDP_ENDPOINT", "").strip()
    if not endpoint:
        raise RuntimeError("GFLOW_CLI_CDP_ENDPOINT is required for recovery")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        if not browser.contexts:
            raise RuntimeError("authenticated Flow browser has no context")
        request = browser.contexts[0].request
        while True:
            response = await request.get(
                routes.media_download_url(media_id),
                timeout=30_000,
            )
            if response.status == 200:
                body = await response.body()
                if not body:
                    raise RuntimeError(f"Flow returned an empty media file: {media_id}")
                temporary = resolved.with_suffix(f"{resolved.suffix}.part")
                temporary.write_bytes(body)
                temporary.replace(resolved)
                print(f"Recovered Flow video: {resolved}")
                return
            if response.status != 404:
                raise RuntimeError(
                    f"Flow media recovery returned HTTP {response.status}: {media_id}"
                )
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Flow media is not downloadable yet (last HTTP 404): {media_id}"
                )
            await asyncio.sleep(min(5, max(0, deadline - time.monotonic())))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("media_id")
    parser.add_argument("target", type=Path)
    parser.add_argument("wait_seconds", nargs="?", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(recover(args.media_id, args.target, args.wait_seconds))


if __name__ == "__main__":
    main()
