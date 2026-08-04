#!/usr/bin/env python3
"""F3 - independent evidence & reproducibility spot-check sample selection.

Draws a 10-issue stratified random sample (fixed seed 20260801, per the F3
spec) from the reported issue set, i.e. exactly what the reports did:
  - mobile device (iphone/pixel) -> mobile issues; desktop -> desktop issues
  - status != not_reproducible
  - kind != performance

Sampling structure differs from T16's draw (T16: 3 mobile / 7 desktop with 1
mobile HIGH; F3: 4 mobile / 6 desktop with BOTH mobile HIGH issues) so this is
an independent gate despite sharing the seed. The seed is fixed so the sample
is reproducible and documentable.

Guarantees:
  - >= 2 mobile + >= 2 desktop
  - >= 1 issue per severity bucket present in the combined set (CRITICAL,
    HIGH, MEDIUM, LOW) — CRITICAL has exactly 1 per device, LOW exactly 1
    desktop, so those are force-included; HIGH/MEDIUM are sampled.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINDINGS_PATH = ROOT / "data" / "findings.json"

SAMPLE_SEED = 20260801
SAMPLE_SIZE = 10

MOBILE_POOL = {
    "CRITICAL": 1,
    "HIGH": 2,
    "MEDIUM": 1,
}
DESKTOP_POOL = {
    "CRITICAL": 1,
    "HIGH": 1,
    "MEDIUM": 3,
    "LOW": 1,
}


def is_mobile_dev(dev: str) -> bool:
    d = (dev or "").lower()
    return "iphone" in d or "pixel" in d or d == "mobile"


def main() -> int:
    data = json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))
    mobile = [f for f in data
              if is_mobile_dev(f.get("device"))
              and f.get("status") != "not_reproducible"
              and f.get("kind") != "performance"]
    desktop = [f for f in data
               if (f.get("device") or "").lower() == "desktop"
               and f.get("status") != "not_reproducible"
               and f.get("kind") != "performance"]

    print(f"reported pools: mobile={len(mobile)} desktop={len(desktop)} "
          f"(total {len(mobile) + len(desktop)})")

    rng = random.Random(SAMPLE_SEED)
    sample: list[dict] = []

    def pick(pool, sev, n):
        cands = [f for f in pool if f["severity"] == sev]
        got = rng.sample(cands, n)
        sample.extend(got)
        print(f"  mobile {sev:<8} {n} -> {[f['id'] for f in got]}")

    for sev, n in MOBILE_POOL.items():
        pick(mobile, sev, n)
    for sev, n in DESKTOP_POOL.items():
        pick(desktop, sev, n)

    ids = [f["id"] for f in sample]
    assert len(ids) == SAMPLE_SIZE, f"sample size {len(ids)} != {SAMPLE_SIZE}"
    assert len(set(ids)) == SAMPLE_SIZE, "duplicate ids in sample"

    n_mobile = sum(1 for f in sample if is_mobile_dev(f.get("device")))
    n_desktop = SAMPLE_SIZE - n_mobile
    assert n_mobile >= 2 and n_desktop >= 2, "device stratification violated"

    sevs = sorted({f["severity"] for f in sample})
    print(f"\nfinal sample: {len(sample)} issues "
          f"({n_mobile} mobile / {n_desktop} desktop) severities={sevs}")
    for f in sample:
        print(f"  {f['id']:30s} {f['severity']:<8} {f['title'][:60]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
