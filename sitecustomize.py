"""Runtime hooks that let containerized gflow attach to a host Chrome CDP session."""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path


def _proxy_server() -> str | None:
    value = os.environ.get("GFLOW_CLI_PROXY_SERVER", "").strip()
    return value or None


try:
    from gflow_cli.auth import real_chrome

    _original_build_chrome_args = real_chrome._build_chrome_args

    def _build_chrome_args_with_proxy(chrome_exe, profile_dir, headless):  # type: ignore[no-untyped-def]
        args = _original_build_chrome_args(chrome_exe, profile_dir, headless)
        proxy = _proxy_server()
        if proxy:
            args.insert(1, f"--proxy-server={proxy}")
        return args

    real_chrome._build_chrome_args = _build_chrome_args_with_proxy
except Exception:
    pass


# Flow's current Omni editor sometimes returns a media ID but never starts its
# usual status polling request. Probe the media redirect as a completion signal
# so a successful generation is downloaded instead of timing out after 10 min.
try:
    import time

    from gflow_cli.api import routes
    from gflow_cli.api.transports import ui_automation_video
    from gflow_cli.api.transports.ui_automation_video import VideoGenerationMixin
    from gflow_cli.api.video import VideoStatus
    from gflow_cli.errors import AuthExpiredError

    async def _poll_video_status_with_download_probe(
        page, captured_status, media_name, *, timeout_s=600.0,
        poll_interval_s=2.0, stall_nudge_s=120.0,
    ):  # type: ignore[no-untyped-def]
        deadline = time.monotonic() + timeout_s
        last_status = None
        seen_count = len(captured_status)
        last_progress = time.monotonic()
        nudged = False
        next_download_probe = time.monotonic() + 10
        while time.monotonic() < deadline:
            terminal, last_status = VideoGenerationMixin._scan_for_terminal_status(
                captured_status, media_name
            )
            if terminal is not None:
                return terminal
            now = time.monotonic()
            if seen_count == 0 and now >= next_download_probe:
                next_download_probe = now + 10
                try:
                    response = await page.request.get(
                        routes.media_download_url(media_name),
                        max_redirects=0,
                        timeout=30_000,
                    )
                    if response.status == 401:
                        raise AuthExpiredError(
                            detail="media redirect returned HTTP 401 while polling video",
                            status=401,
                            route="media.getMediaUrlRedirect",
                        )
                    if response.status == 200 or 300 <= response.status < 400:
                        ui_automation_video.log.info(
                            "ui_automation_video.poll_terminal",
                            media_name=media_name,
                            status="MEDIA_GENERATION_STATUS_SUCCESSFUL",
                            source="media_redirect",
                        )
                        return VideoStatus(
                            media_id=media_name,
                            status="MEDIA_GENERATION_STATUS_SUCCESSFUL",
                        )
                except AuthExpiredError:
                    raise
                except Exception as error:
                    ui_automation_video.log.debug(
                        "ui_automation_video.media_redirect_probe_failed",
                        media_name=media_name,
                        error=str(error),
                    )
            seen_count, last_progress, nudged = (
                await VideoGenerationMixin._nudge_tab_if_stalled(
                    page, captured_status, seen_count, last_progress, nudged,
                    stall_nudge_s, media_name,
                )
            )
            await asyncio.sleep(poll_interval_s)
        cause = (
            "Flow never polled the status route"
            if seen_count == 0
            else "Flow stopped polling before a terminal status"
        )
        raise TimeoutError(
            f"no terminal status for {media_name!r} within {timeout_s:.0f}s — "
            f"{seen_count} status response(s) seen, last status: {last_status}. {cause}."
        )

    VideoGenerationMixin._poll_video_status = staticmethod(
        _poll_video_status_with_download_probe
    )
except Exception:
    pass


# Flow's July 2026 editor cohort changed the I2V Start/End frame slots from
# custom ``div[type=button]`` elements to native iconless ``button`` elements.
# Some gflow releases still carry only the older selector, so extend it without
# removing backward compatibility. Settings/menu buttons contain Material
# Symbols icons; excluding those keeps the positional pair limited to the two
# frame slots after the settings popover closes.
try:
    from gflow_cli.api.transports import ui_automation_video

    ui_automation_video.FRAME_SLOTS_STRUCT = (
        "div[type='button'][aria-haspopup='dialog'], "
        "button[aria-haspopup='dialog']:not(:has(i.google-symbols))"
    )
except Exception:
    pass


# Google can inject a site-wide cookie notice after the Flow editor has already
# passed gflow's overlay check. The fixed bottom bar then covers the mode button
# and Playwright waits for 30 seconds because it intercepts every pointer event.
# Dismiss this specific banner immediately before opening either media menu.
try:
    from gflow_cli.api.transports.ui_automation import UiAutomationTransport
    from gflow_cli.api.transports.ui_automation_video import VideoGenerationMixin

    _original_switch_to_image_mode = UiAutomationTransport._switch_to_image_mode
    _original_switch_to_video_mode = VideoGenerationMixin._switch_to_video_mode

    async def _dismiss_google_cookie_notice(page):  # type: ignore[no-untyped-def]
        notice = page.locator(".glue-cookie-notification-bar").first
        if not await notice.is_visible():
            return
        reject = notice.locator("button.glue-cookie-notification-bar__reject").first
        await reject.click(force=True)
        await notice.wait_for(state="hidden", timeout=5_000)

    async def _switch_to_image_mode_without_cookie_bar(
        page, *, out_dir=None  # type: ignore[no-untyped-def]
    ):
        await _dismiss_google_cookie_notice(page)
        await _original_switch_to_image_mode(page, out_dir=out_dir)

    async def _switch_to_video_mode_without_cookie_bar(
        page, *, out_dir=None  # type: ignore[no-untyped-def]
    ):
        await _dismiss_google_cookie_notice(page)
        await _original_switch_to_video_mode(page, out_dir=out_dir)

    UiAutomationTransport._switch_to_image_mode = staticmethod(
        _switch_to_image_mode_without_cookie_bar
    )
    VideoGenerationMixin._switch_to_video_mode = staticmethod(
        _switch_to_video_mode_without_cookie_bar
    )
except Exception:
    pass


# Flow's August 2026 editor labels the single-output tab ``x1``.  gflow-cli
# Older automation probes only the ``1x`` spelling, then silently leaves the
# editor default (x2) in place and doubles credit use.  Select the requested
# count using both labels and fail closed if no unique tab can be found.
try:
    from gflow_cli.api.transports.ui_automation_video import VideoGenerationMixin

    async def _set_output_count_current_ui(
        page, n, out_dir=None  # type: ignore[no-untyped-def]
    ):
        labels = ("x1", "1x") if n == 1 else (f"x{n}",)
        for label in labels:
            tab = page.locator(f"[role='tab']:text-is('{label}')")
            if await tab.count() == 1:
                await tab.click()
                await page.wait_for_timeout(400)
                return
        raise RuntimeError(
            f"Flow output-count tab for x{n} was not found; refusing to risk duplicate credit use"
        )

    VideoGenerationMixin._set_output_count = staticmethod(_set_output_count_current_ui)
except Exception:
    pass


def _resolved_cdp_endpoint() -> str | None:
    endpoint = os.environ.get("GFLOW_CLI_CDP_ENDPOINT", "").strip()
    if not endpoint:
        return None
    if endpoint.startswith("http://host.docker.internal:"):
        host_ip = socket.gethostbyname("host.docker.internal")
        endpoint = endpoint.replace("host.docker.internal", host_ip, 1)
    return endpoint


try:
    from playwright.async_api import BrowserContext, BrowserType

    _original_launch_persistent_context = BrowserType.launch_persistent_context
    _original_context_close = BrowserContext.close

    def _clear_container_singletons(args, kwargs):  # type: ignore[no-untyped-def]
        if os.environ.get("GFLOW_CONTAINER_CLEAR_STALE_SINGLETONS", "").lower() != "true":
            return False
        raw_dir = kwargs.get("user_data_dir")
        if raw_dir is None and args:
            raw_dir = args[0]
        if not raw_dir:
            return False
        profile_dir = Path(str(raw_dir))
        cleared = False
        for name in ("SingletonCookie", "SingletonSocket", "SingletonLock"):
            target = profile_dir / name
            try:
                if target.exists() or target.is_symlink():
                    target.unlink()
                    cleared = True
            except OSError:
                pass
        return cleared

    async def _launch_or_attach(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        endpoint = _resolved_cdp_endpoint()
        if not endpoint or self.name != "chromium":
            # gflow deliberately removes Playwright's default
            # ``--no-sandbox`` flag.  The suite runs Chromium as root inside a
            # Docker container, where Chromium exits immediately unless the
            # flag is restored.  Keep the upstream hardening everywhere else,
            # but make the local container launchable when CDP attach is not
            # being used.
            launch_args = list(kwargs.get("args") or [])
            if "--no-sandbox" not in launch_args:
                launch_args.append("--no-sandbox")
            kwargs["args"] = launch_args
            ignored = list(kwargs.get("ignore_default_args") or [])
            kwargs["ignore_default_args"] = [
                value for value in ignored if value != "--no-sandbox"
            ]
            if _clear_container_singletons(args, kwargs):
                # The cookie pre-read fallback closes its temporary Chromium
                # context immediately before the real generation context. On
                # Docker Desktop the process can outlive the lock symlink by a
                # short interval, so give it time to exit before relaunching.
                await asyncio.sleep(2)
                _clear_container_singletons(args, kwargs)
            try:
                return await _original_launch_persistent_context(self, *args, **kwargs)
            except Exception as exc:
                if os.environ.get("GFLOW_CONTAINER_DEBUG_LAUNCH", "").lower() == "true":
                    print(f"GFLOW_CONTAINER_BROWSER_LAUNCH_ERROR\n{exc}", file=sys.stderr, flush=True)
                raise
        browser = await self.connect_over_cdp(endpoint)
        contexts = browser.contexts
        context = contexts[0] if contexts else await browser.new_context()
        context._gflow_host_cdp = True  # type: ignore[attr-defined]
        return context

    async def _close_without_stopping_host_chrome(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if getattr(self, "_gflow_host_cdp", False):
            return None
        return await _original_context_close(self, *args, **kwargs)

    BrowserType.launch_persistent_context = _launch_or_attach
    BrowserContext.close = _close_without_stopping_host_chrome
except Exception:
    pass


# The Linux profile already uses Chromium's basic password store.  gflow's
# cross-platform cookie pre-read fallback opens a short-lived second browser on
# the same profile immediately before the real generation browser; on Docker
# Desktop that process can still own the profile when the real launch begins.
# Allow the arm64-only runner to skip that redundant pre-read and let the real
# persistent context load the cookie jar directly.
try:
    from gflow_cli.api.client import FlowApiClient

    _original_preread_flow_session_cookies = FlowApiClient._preread_flow_session_cookies

    async def _container_preread_flow_session_cookies(self):  # type: ignore[no-untyped-def]
        if os.environ.get("GFLOW_CONTAINER_SKIP_COOKIE_PREREAD", "").lower() == "true":
            self._preread_flow_cookies = {}
            return
        await _original_preread_flow_session_cookies(self)
        if os.environ.get("GFLOW_CONTAINER_CLEAR_STALE_SINGLETONS", "").lower() == "true":
            await asyncio.sleep(2)
            for name in ("SingletonCookie", "SingletonSocket", "SingletonLock"):
                target = Path(self.profile_dir) / name
                try:
                    if target.exists() or target.is_symlink():
                        target.unlink()
                except OSError:
                    pass

    FlowApiClient._preread_flow_session_cookies = _container_preread_flow_session_cookies
except Exception:
    pass


# Flow's July 2026 composer can visually accept text while the generic submit
# cascade fails to fire the Create action over a host-CDP connection.  Use the
# exact locale-independent Material Symbols ligature, wait for the button to be
# enabled, and force the final click so T2V requests are actually dispatched.
try:
    from gflow_cli.api.transports.ui_automation import UiAutomationTransport

    async def _send_prompt_via_create_button(
        self, page, prompt_text, out_dir=None  # type: ignore[no-untyped-def]
    ):
        # The end-frame upload response can arrive before Flow has finished
        # committing the slot state into the composer.  A short settle avoids
        # the first Create click being accepted visually but producing no
        # generation request.
        await page.wait_for_timeout(2000)
        await self._dismiss_blocking_overlays(page, out_dir)
        input_box = await self._locate_prompt_box(page, out_dir)
        await input_box.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await page.keyboard.insert_text(prompt_text)
        await page.wait_for_timeout(700)

        submit = page.locator(
            "button:has(i.google-symbols:text-is('arrow_forward'))"
        ).first
        await submit.wait_for(state="visible", timeout=10_000)
        deadline = 10
        while await submit.is_disabled() and deadline > 0:
            await page.wait_for_timeout(500)
            deadline -= 1
        await submit.click(force=True)
        await page.wait_for_timeout(1800)
        # Successful Flow submissions clear the Slate editor.  Retry once when
        # the text is still present; this is safe because a successful first
        # click makes the condition false and prevents duplicate credit use.
        if (await input_box.inner_text()).strip():
            await submit.click(force=True)

    UiAutomationTransport._send_prompt = _send_prompt_via_create_button
except Exception:
    pass


# The reference-entity request route is only needed when character entities
# are actually present.  On the host-CDP transport, installing this route for
# an empty set can stall before ``send_prompt`` indefinitely.  Skip the no-op
# interception for ordinary T2V/I2V jobs while preserving upstream behaviour
# for real character-reference requests.
try:
    from gflow_cli.api.transports.ui_automation_video import VideoGenerationMixin

    _original_intercept_reference_entities = (
        VideoGenerationMixin._intercept_reference_entities
    )

    @asynccontextmanager
    async def _intercept_only_when_needed(self, page, expected_entities):  # type: ignore[no-untyped-def]
        if not expected_entities:
            yield
            return
        async with _original_intercept_reference_entities(
            self, page, expected_entities
        ):
            yield

    VideoGenerationMixin._intercept_reference_entities = (
        _intercept_only_when_needed
    )
except Exception:
    pass
