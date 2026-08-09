from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
from pathlib import Path


def resolved_endpoint(endpoint: str) -> str:
    if endpoint.startswith("http://host.docker.internal:"):
        host_ip = socket.gethostbyname("host.docker.internal")
        return endpoint.replace("host.docker.internal", host_ip, 1)
    return endpoint


def is_google_cookie(cookie: dict[str, object]) -> bool:
    domain = str(cookie.get("domain", "")).lstrip(".").lower()
    # Flow is hosted on Google's `.google` top-level domain (`labs.google`),
    # while account cookies also live on `google.com`.  Keeping only the
    # latter silently drops Flow's own session cookie after a successful
    # OAuth callback and makes every Docker generation fail with 401.
    return (
        domain == "google.com"
        or domain.endswith(".google.com")
        or domain == "google"
        or domain.endswith(".google")
    )


async def read_cdp_cookies(endpoint: str) -> list[dict[str, object]]:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(resolved_endpoint(endpoint))
        contexts = browser.contexts
        if not contexts:
            raise RuntimeError("The authorized Chrome has no browser context")
        cookies = await contexts[0].cookies()
        return [cookie for cookie in cookies if is_google_cookie(cookie)]


def save_gemini(cookies: list[dict[str, object]], target: Path) -> None:
    cookie_map = {
        str(cookie["name"]): str(cookie["value"])
        for cookie in cookies
        if cookie.get("name") and cookie.get("value")
    }
    if not cookie_map.get("__Secure-1PSID"):
        raise RuntimeError(
            "Gemini authorization is incomplete: __Secure-1PSID was not found"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"cookieMap": cookie_map}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    target.chmod(0o600)


async def save_flow(cookies: list[dict[str, object]], gflow_home: Path, profile: str) -> None:
    from playwright.async_api import async_playwright

    if not cookies:
        raise RuntimeError("Flow authorization is incomplete: no Google cookies were found")

    profile_dir = gflow_home / f"profile_{profile}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / ".gflow_browser_strategy").write_text("chrome", encoding="utf-8")

    previous_endpoint = os.environ.pop("GFLOW_CLI_CDP_ENDPOINT", None)
    try:
        async with async_playwright() as playwright:
            launch_options: dict[str, object] = {
                "user_data_dir": str(profile_dir),
                "executable_path": "/usr/bin/chromium",
                # Use a virtual display instead of Chromium's native headless
                # mode.  On the arm64 Docker runner a persistent profile can
                # launch successfully but never finish Playwright's startup
                # handshake in native headless mode, leaving fresh host-CDP
                # cookies unsaved.  `suite auth` wraps this process in Xvfb.
                "headless": False,
                "args": [
                    "--no-sandbox",
                    "--password-store=basic",
                    "--disable-dev-shm-usage",
                ],
            }
            proxy = os.environ.get("GFLOW_CLI_PROXY_SERVER", "").strip()
            if proxy:
                launch_options["proxy"] = {"server": proxy}
            context = await playwright.chromium.launch_persistent_context(**launch_options)
            try:
                await context.clear_cookies()
                await context.add_cookies(cookies)
            finally:
                await context.close()
    finally:
        if previous_endpoint is not None:
            os.environ["GFLOW_CLI_CDP_ENDPOINT"] = previous_endpoint

    gflow_home.mkdir(parents=True, exist_ok=True)
    (gflow_home / "config.toml").write_text(
        f'default_profile = "{profile}"\n', encoding="utf-8"
    )


async def async_main(args: argparse.Namespace) -> int:
    cookies = await read_cdp_cookies(args.endpoint)
    if args.provider == "gemini":
        save_gemini(cookies, Path(args.target))
        print(f"Gemini authorization saved ({len(cookies)} Google cookies).")
    else:
        await save_flow(cookies, Path(args.target), args.profile)
        print(f"Flow authorization saved as profile '{args.profile}' ({len(cookies)} cookies).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Google authorization from host Chrome CDP.")
    parser.add_argument("provider", choices=("gemini", "flow"))
    parser.add_argument("endpoint")
    parser.add_argument("target")
    parser.add_argument("--profile", default="flow")
    return asyncio.run(async_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
