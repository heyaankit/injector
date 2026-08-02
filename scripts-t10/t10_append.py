#!/usr/bin/env python3
"""T10: append mobile visual QA findings to data/findings.json (append-only)."""
import json, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/heyatoy/Projects/testing")
FP = ROOT / "data" / "findings.json"

unix = int(time.time())
entries = json.loads(FP.read_text())

def nr_id(n):
    return f"mobile-t10-{unix}-{n}"

def check(shot):
    p = ROOT / shot
    if not p.exists():
        print("MISSING SCREENSHOT:", shot)
    return shot

def append(entry):
    entries.append(entry)
    print("appended", entry["id"], "|", entry["severity"], "|", entry["title"])

n = 1
append({
    "id": nr_id(n), "device": "iphone-13, pixel-7",
    "url": "https://www.injector.world/",
    "severity": "MEDIUM",
    "title": "Mobile nav menu links below recommended 44px tap-target height (18px)",
    "actual": "On both iPhone 13 and Pixel 7, opening the hamburger menu (aria-label=\"Open menu\") expands the header nav panel; 33 of its 36 links (Botox, Dysport, Xeomin, Daxxify, Juvederm, Restylane, Sculptra, Radiesse, Kybella, Lip Filler, etc.) render as bare text at height 18px with 0px padding (text-[13px]). Toggle button itself is 44x44px and aria-expanded flips true/false correctly; panel fits within viewport (bottom=446 < innerHeight) with no horizontal or vertical overflow; closes via toggle re-click or Escape.",
    "expected": "Interactive menu links should have a tap-target area of at least 44x44 CSS px (WCAG 2.5.8 / Apple HIG).",
    "repro_steps": "1) Open https://www.injector.world/ in an iPhone 13 or Pixel 7 viewport. 2) Tap the hamburger button (aria-label=\"Open menu\", top-left). 3) Inspect the expanded nav links: text-only, 18px high, no padding. 4) Measure getBoundingClientRect().height of the menu anchors.",
    "screenshot_path": check("evidence/iphone-13/home/20260802-032122-hamburger-open.png"),
    "notes": "Global header nav renders identically on every page, so the small tap targets affect all pages. Evidence shots: evidence/iphone-13/home/20260802-032122-hamburger-open.png + evidence/pixel-7/home/20260802-032227-hamburger-open.png.",
    "affected_pages": ["https://www.injector.world/", "https://www.injector.world/clinics",
                       "https://www.injector.world/clinics/utah/syracuse-ut/sinful-skin-injections-84075",
                       "https://www.injector.world/clinics/missouri/lees-summit-mo/summit-aesthetics-64064"],
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
})

n = 2
append({
    "id": nr_id(n), "device": "iphone-13, pixel-7",
    "url": "https://www.injector.world/",
    "severity": "LOW",
    "title": "Homepage footer disclaimer NOT duplicated on mobile (1 visible instance)",
    "actual": "Footer renders exactly one visible instance of 'Information here is editorial and not medical advice.' on iPhone 13 and Pixel 7 (desktop's second match is an md:hidden mobile <p> that stays hidden).",
    "expected": "Exactly one visible disclaimer line.",
    "repro_steps": "1) Open homepage in iPhone 13 / Pixel 7 viewport. 2) Scroll to footer. 3) Count visible 'Information here is editorial and not medical advice.' elements (visible = offsetParent !== null).",
    "screenshot_path": check("evidence/iphone-13/home/20260802-024255-viewport.png"),
    "notes": "not_reproducible: consistent with T5/T6/T7 desktop result; mobile <p> variant does not double-render.",
    "affected_pages": ["https://www.injector.world/"],
    "status": "not_reproducible",
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
})

n = 3
append({
    "id": nr_id(n), "device": "iphone-13, pixel-7",
    "url": "https://www.injector.world/",
    "severity": "LOW",
    "title": "Footer social anchors NOT empty on mobile (SVG icon + aria-label present)",
    "actual": "Instagram and TikTok footer anchors each render a 15x15px inline SVG and have aria-label ('Instagram'/'TikTok') on iPhone 13 and Pixel 7; anchor box is 36x36px.",
    "expected": "Social anchors expose an icon and an accessible label.",
    "repro_steps": "1) Open homepage in mobile viewport. 2) Inspect footer <a> elements whose aria-label matches Instagram/TikTok. 3) Confirm svg child exists and aria-label is non-empty.",
    "screenshot_path": check("evidence/iphone-13/home/20260802-024255-viewport.png"),
    "notes": "not_reproducible: consistent with T5/T6 desktop result.",
    "affected_pages": ["https://www.injector.world/"],
    "status": "not_reproducible",
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
})

n = 4
append({
    "id": nr_id(n), "device": "iphone-13, pixel-7",
    "url": "https://www.injector.world/",
    "severity": "LOW",
    "title": "Homepage stats '0+' NOT reproduced on mobile (scroll-triggered count-up works)",
    "actual": "After scrolling the stats band into view on iPhone 13 and Pixel 7, counters animate to real values: '17,020+ Clinics', '10+ Brands', '2767+ Markets'. Pre-scroll 0+ state is the intended count-up animation, not a defect.",
    "expected": "Stats band shows the verified counts once scrolled into view.",
    "repro_steps": "1) Open homepage in mobile viewport. 2) Scroll stats band into view. 3) Wait 2.5s and read counter values.",
    "screenshot_path": check("evidence/iphone-13/home/20260802-024255-viewport.png"),
    "notes": "not_reproducible: consistent with T7 desktop verification.",
    "affected_pages": ["https://www.injector.world/"],
    "status": "not_reproducible",
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
})

FP.write_text(json.dumps(entries, indent=2) + "\n")
print("FINDINGS WRITTEN. total:", len(entries))
