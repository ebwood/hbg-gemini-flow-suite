#!/usr/bin/env python3
"""Print the visible Flow I2V frame-slot DOM without cookies or account data."""

from __future__ import annotations

import asyncio
import json
import socket

from playwright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as playwright:
        host_ip = socket.gethostbyname("host.docker.internal")
        browser = await playwright.chromium.connect_over_cdp(f"http://{host_ip}:9223")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://labs.google/fx/tools/flow?hl=en")
        await page.wait_for_timeout(3500)
        await page.locator("button:has(i.google-symbols:text('add_2'))").first.click()
        await page.wait_for_url("**/project/**", timeout=30_000)
        await page.wait_for_timeout(5000)

        settings = page.locator(
            "button[aria-haspopup='menu']:has(i.google-symbols:text('crop_9_16')),"
            "button[aria-haspopup='menu']:has(i.google-symbols:text('crop_16_9'))"
        ).first
        await settings.click()
        await page.locator("[role='tab'][id$='-trigger-VIDEO']").click()
        await page.wait_for_timeout(800)
        await page.locator(
            "button[aria-haspopup='menu']:has(i.google-symbols:text-is('arrow_drop_down'))"
        ).click()
        await page.locator(
            "[role='menuitem']:has-text('Veo 3.1 - Lite'):not(:has-text('[Lower Priority]'))"
        ).click()
        await page.wait_for_timeout(800)
        await page.locator("[role='tab'][id$='-trigger-VIDEO_FRAMES']").click()
        await page.wait_for_timeout(800)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(250)
        await page.keyboard.press("Escape")
        await page.mouse.click(260, 470)
        await page.wait_for_timeout(1200)

        nodes = await page.locator("[aria-haspopup='dialog']").evaluate_all(
            """
            els => els.map((el, index) => ({
              index,
              tag: el.tagName,
              type: el.getAttribute('type'),
              role: el.getAttribute('role'),
              ariaLabel: el.getAttribute('aria-label'),
              text: (el.innerText || '').trim().slice(0, 80),
              icons: Array.from(el.querySelectorAll('i')).map(i => (i.textContent || '').trim()),
              visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
              classes: String(el.className || '').slice(0, 160)
            }))
            """
        )
        overlays = await page.locator(
            "[data-state='open'], [role='menu'], [data-radix-popper-content-wrapper]"
        ).evaluate_all(
            """
            els => els.map((el, index) => {
              const r = el.getBoundingClientRect();
              return {
                index,
                tag: el.tagName,
                role: el.getAttribute('role'),
                state: el.getAttribute('data-state'),
                text: (el.innerText || '').trim().slice(0, 160),
                classes: String(el.className || '').slice(0, 160),
                box: {x:r.x, y:r.y, w:r.width, h:r.height}
              };
            })
            """
        )
        start_slot = page.locator("div[type='button'][aria-haspopup='dialog']").first
        await start_slot.click(force=True)
        await page.wait_for_timeout(1200)
        dialog_nodes = await page.locator("button").evaluate_all(
            """
            els => els.map((el, index) => ({
              index,
              tag: el.tagName,
              type: el.getAttribute('type'),
              role: el.getAttribute('role'),
              ariaLabel: el.getAttribute('aria-label'),
              text: (el.innerText || '').trim().slice(0, 100),
              icons: Array.from(el.querySelectorAll('i')).map(i => ({
                text: (i.textContent || '').trim(),
                classes: String(i.className || '')
              })),
              visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
              classes: String(el.className || '').slice(0, 160)
            }))
            """
        )
        inputs = await page.locator("input").evaluate_all(
            """
            els => els.map((el, index) => ({
              index,
              type: el.getAttribute('type'),
              id: el.id,
              accept: el.getAttribute('accept'),
              ariaLabel: el.getAttribute('aria-label'),
              visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
            }))
            """
        )
        print(
            json.dumps(
                {"frame_slots": nodes, "overlays": overlays, "dialog_buttons": dialog_nodes, "dialog_inputs": inputs},
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
