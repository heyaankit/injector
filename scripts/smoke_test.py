#!/usr/bin/env python3
"""Smoke test: launch headless Chromium, load injector.world, assert content.

Reusable entrypoint. Writes screenshot to evidence/smoke-test.png.

Exit codes:
  0  all assertions passed
  1  page failed to load or assertions failed
  2  usage error (bad --screenshot path)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_URL = "https://www.injector.world/"
DEFAULT_SCREENSHOT = Path(__file__).resolve().parent.parent / "evidence" / "smoke-test.png"
TITLE_ASSERT = "title is non-empty"
BODY_ASSERT = "body contains 'Find Your Injector'"
NAV_TIMEOUT_MS = 30_000


def run_smoke(url: str, screenshot_path: Path) -> tuple[bool, str, str, Path]:
    ok = False
    title = ""
    full_body = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            # Network-idle can stall on Next.js; cap it, tolerate timeout (best effort).
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            page.wait_for_timeout(1500)  # let hydration/render settle
            title = page.title()
            full_body = page.locator("body").inner_text()
            if title.strip() and "Find Your Injector" in full_body:
                ok = True
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_path), full_page=False)
        except Exception:
            raise
        finally:
            browser.close()
    return ok, title, full_body, screenshot_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL, help="URL to smoke-test")
    ap.add_argument("--screenshot", default=str(DEFAULT_SCREENSHOT), help="PNG output path")
    args = ap.parse_args()
    shot = Path(args.screenshot)
    if shot.suffix.lower() != ".png":
        print(f"error: screenshot path must end in .png (got {shot})", file=sys.stderr)
        return 2

    try:
        ok, title, full_body, shot = run_smoke(args.url, shot)
    except Exception as exc:  # noqa: BLE001 - report any failure as exit 1
        print(f"SMOKE FAIL: exception during navigation: {exc!r}", file=sys.stderr)
        return 1

    size = shot.stat().st_size if shot.exists() else 0
    body_sample = full_body[:300]
    print(f"url          : {args.url}")
    print(f"title        : {title!r} -> {TITLE_ASSERT}: {'PASS' if title.strip() else 'FAIL'}")
    found = "Find Your Injector" in full_body
    print(f"body contains : {BODY_ASSERT}: {'PASS' if found else 'FAIL'}")
    print(f"body sample  : {body_sample[:120]!r}")
    print(f"screenshot   : {shot} ({size} bytes)")
    if ok and size > 10 * 1024:
        print("SMOKE PASS")
        return 0
    print("SMOKE FAIL", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
