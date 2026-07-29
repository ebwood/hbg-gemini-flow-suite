"""Runtime hooks that let containerized gflow attach to a host Chrome CDP session."""

from __future__ import annotations

import os
import socket
from contextlib import asynccontextmanager


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


# Flow's July 2026 editor cohort changed the I2V Start/End frame slots from
# custom ``div[type=button]`` elements to native iconless ``button`` elements.
# gflow-cli 0.43.0 still carries only the older selector, so extend it without
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

    async def _launch_or_attach(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        endpoint = _resolved_cdp_endpoint()
        if not endpoint or self.name != "chromium":
            # gflow-cli 0.43.0 deliberately removes Playwright's default
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
            return await _original_launch_persistent_context(self, *args, **kwargs)
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
