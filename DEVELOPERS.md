# DEVELOPERS.md

This is the deep-dive companion to the "For developers" section of `README.md`. It documents every script in `scripts/`, how the QA and UX pipelines move data, how to extend the toolchain, and how to fix the common failures. Everything here was verified against the real CLI surfaces (`--help`) and the committed data files. All scripts run from the repo root; they use relative paths to `data/` and `reports/`.

## Table of Contents

- [Environment setup](#environment-setup)
- [The scripts](#the-scripts)
  - [QA pipeline](#qa-pipeline)
  - [UX pipeline](#ux-pipeline)
  - [Shared and tooling scripts](#shared-and-tooling-scripts)
- [Data flow pipeline](#data-flow-pipeline)
- [Data file reference](#data-file-reference)
- [UX findings JSON schema](#ux-findings-json-schema)
- [Extending the toolchain](#extending-the-toolchain)
- [Testing and CI](#testing-and-ci)
- [Troubleshooting](#troubleshooting)

## Environment setup

The toolchain needs Python, Playwright, python-docx, and (for the render checks only) LibreOffice.

### Python version

Python 3.14 is recommended; CI uses `actions/setup-python` with version `"3.14"`. Python 3.10+ works for the scripts.

### Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` pins `playwright==1.62.0` and `python-docx==1.2.0`, plus the transitive pins `greenlet`, `lxml`, `pyee`, and `typing_extensions`. `pyproject.toml` mirrors these under `[project.dependencies]`.

For the test suite, install the dev extras:

```bash
pip install -e ".[dev]"
```

The `pyproject.toml` declares `dev = ["pytest"]`, so this adds pytest.

### Install the Playwright browser

First time only:

```bash
python -m playwright install --with-deps chromium
```

Why `--with-deps` matters: it runs `apt-get` internally to install Chromium's system libraries (fonts, libnss, libatk, and friends). On a bare Ubuntu image the plain `install chromium` fails at launch because those libraries are missing.

One install covers both launch modes. The default `install chromium` downloads the full Chromium build *and* the headless shell. Headless launches use the headless shell; headed launches (the `--headed` flag) use full Chromium. If you only ever run headless (CI-style), `--only-shell` gives a smaller install, but the smoke test and the demo mode with `--headed` need the full install, so keep the default.

### Install LibreOffice

LibreOffice (`soffice`) is used only by the validators for the render check (headless DOCX to PDF conversion). The harnesses and builders do not need it.

```bash
sudo apt-get install -y --no-install-recommends libreoffice-writer
```

### Run the test suite

```bash
python3 -m pytest tests/ -q
```

This runs 12 tests. See [Testing and CI](#testing-and-ci).

## The scripts

There are ten modules in `scripts/`. Two of them, `rubric.py` and `ux_rubric.py`, are libraries with no CLI. The other eight have a real command line. All exit codes and flags below were confirmed from `--help`.

### QA pipeline

#### `scripts/smoke_test.py`

Environment smoke test: launches headless Chromium, loads the live site, and asserts the page is real.

```bash
python scripts/smoke_test.py
```

Loads `https://www.injector.world/` (override with `--url`), asserts the page title is non-empty and the body contains "Find Your Injector", then writes `evidence/smoke-test.png`. Screenshot path must end in `.png` (`--screenshot`). Exit codes: 0 all assertions passed, 1 page failed to load or assertions failed, 2 usage error. Navigation is the standard pattern used everywhere in this repo: `goto` with `domcontentloaded`, a capped `networkidle` (10 s), then a 1.5 s settle.

#### `scripts/harness.py`

QA crawl harness. Crawls a device profile against the seed list, records findings and a crawl manifest, and captures screenshots.

```bash
python scripts/harness.py desktop              # seed list on 1920x1080
python scripts/harness.py iphone-13            # iPhone 13 emulation
python scripts/harness.py pixel-7              # Pixel 7 emulation
python scripts/harness.py desktop URL [URL...] # explicit URL list
```

Positional `device` is one of `desktop`, `iphone-13`, `pixel-7`. Optional positional `urls` override the seed list. Flags: `--headed` (visible browser window), `--slowmo MS` (pause between actions), `--max-urls N` (crawl at most N URLs, 0 = unlimited). Reads `data/seed-urls.json` when present. Writes append-only to `data/findings.json` and `data/crawl-manifest.json`, and screenshots to `evidence/`. Per page it records load timing (Navigation Timing API), broken images, console errors, bot-protection signals (record-only, never bypassed), and dismisses the consent banner. Load is `domcontentloaded` + 10 s-capped `networkidle` + 1.5 s settle. Viewport: desktop 1920x1080; `iphone-13` and `pixel-7` use Playwright device presets.

#### `scripts/report_builder.py`

QA DOCX bug report builder.

```bash
python scripts/report_builder.py --device mobile --out reports/injector-world-mobile-bug-report.docx --as-of 2026-08-01
python scripts/report_builder.py --device desktop --out reports/injector-world-desktop-bug-report.docx
```

Reads `data/findings.json` (device-filtered by `--device mobile|desktop`) plus `data/crawl-manifest.json`. Emits the bug report: cover and executive summary, severity summary table, issues ordered CRITICAL to HIGH to MEDIUM to LOW, a "Verified: Not Reproducible" section, a coverage section, and a performance appendix. `--as-of` takes an ISO timestamp (default today). The builder fails loudly with a `ValueError` on findings that are missing required fields; it never writes placeholders.

#### `scripts/rubric.py`

QA severity rubric. Single source of truth for severity ordering and colors, imported by `report_builder.py` and `validate_reports.py`. No CLI; do not run it directly.

### UX pipeline

#### `scripts/ux_harness.py`

Interaction-capable UX crawl harness. Same crawl foundations as `harness.py`, plus interaction probes (menus, forms, buttons, hover, scrolling) and a discovery pass.

```bash
python3 scripts/ux_harness.py desktop
python3 scripts/ux_harness.py iphone-13 --urls chunk1.json
python3 scripts/ux_harness.py desktop --discover
python3 scripts/ux_harness.py desktop --validate
python3 scripts/ux_harness.py desktop --headed --slowmo 250 --max-urls 5
```

Flags: `--urls FILE` (JSON list or coverage object), `--discover` (run the discovery pass after the crawl), `--validate` (probe-crawl the homepage only), `--headed`, `--slowmo MS`, `--max-urls N`. Writes ONLY to `evidence/ux/` and `data/ux-manifest.json`; it never touches the QA `evidence/` tree. `--validate` is a quick probe of the homepage that produces at least one screenshot. `--discover` samples internal links (capped at 10 by `DISCOVERY_SAMPLE_CAP`), diffs them against `data/ux-coverage.json`, and records the bounded delta in its `discovery` section. Probes are non-destructive: newsletter forms receive invalid or empty data only, never a real submission.

#### `scripts/ux_rubric.py`

UX rubric library. Holds the 17 UX areas, the 4 severity tiers, and the /10 scoring formula. Read-only; imported by the UX builder and validator. No CLI.

Constants (exact values):

```python
UX_AREAS = [
    "broken_links", "navigation", "layout_responsive", "mobile_responsiveness",
    "forms_validation", "buttons_ctas", "images_icons", "typography_readability",
    "spacing_alignment", "header_footer", "menus_dropdowns", "scrolling_behavior",
    "accessibility_basics", "performance_ux", "console_errors",
    "visual_consistency", "journey_friction",
]  # 17 areas

UX_TIERS = {"Critical", "Most Important", "Important", "Normal"}
TIER_CEILINGS = {"Critical": 5.0, "Most Important": 7.0, "Important": 8.5, "Normal": 9.5}
PENALTY = {"Critical": 0.2, "Most Important": 0.1, "Important": 0.05, "Normal": 0.02}
SEVERITY_ORDER = ["Critical", "Most Important", "Important", "Normal"]
```

Score formula (used by `ux_score`):

```
max(1.0, highest_present_ceiling - 0.2*(n_crit-1) - 0.1*n_mi - 0.05*n_imp - 0.02*n_norm)
```

The result is clamped to `[1.0, 10.0]` and rounded to 1 decimal. Only the Critical tier gets the `-1` exemption. The ceiling is set by the most severe tier present (so any Critical finding caps the score at 5.0). An empty findings set scores 10.0. `overall_score` is `round((desktop + mobile) / 2, 1)`.

#### `scripts/ux_report_builder.py`

UX DOCX report and proposal builder.

```bash
python3 scripts/ux_report_builder.py --device desktop --out reports/injector-world-ux-desktop-report.docx
python3 scripts/ux_report_builder.py --device mobile --out reports/injector-world-ux-mobile-report.docx
python3 scripts/ux_report_builder.py --proposal --out reports/injector-world-ux-proposal.docx
```

Each command accepts an optional `--as-of <ISO>` date (default today). Device mode reads the matching findings store plus `data/ux-coverage.json`; proposal mode reads both findings stores, `data/ux-scores.json`, and `data/ux-priority-dedup.json`. Output is compact and Word-copyable: it uses only standard Word styles (Title, Heading 1/2/3, Normal, Table Grid). Screenshots live in the `evidence/ux/` library and are listed in the Evidence Index appendix rather than embedded in the DOCX.

#### `scripts/validate_ux_reports.py`

UX validation gate. Exit code 0 with a final line "ALL CHECKS PASSED".

```bash
python3 scripts/validate_ux_reports.py
python3 scripts/validate_ux_reports.py --findings data/ux-desktop-findings.json data/ux-mobile-findings.json
python3 scripts/validate_ux_reports.py --reports reports/injector-world-ux-desktop-report.docx reports/injector-world-ux-mobile-report.docx reports/injector-world-ux-proposal.docx --score
python3 scripts/validate_ux_reports.py --findings /tmp/opencode/ux-fixture-bad.json --expect-fail
```

Six checks: Schema (see the [schema table](#ux-findings-json-schema)), Format (no solution tokens in descriptions), Coverage (all 67 pages tested per device and all 17 areas covered), Dedup (no duplicate title/URL pairs), Score (`--score` recomputes desktop/mobile/overall and compares to the proposal's embedded numbers), Render (DOCX reopens, soffice converts to a non-empty PDF, zero placeholders). `--expect-fail` inverts the exit code so you can test the gate's negative path. Checks whose artifacts do not exist yet are skipped with a note, so the gate runs incrementally during an audit.

### Shared and tooling scripts

#### `scripts/build_seed.py`

Builds the crawl seed list.

```bash
python scripts/build_seed.py
```

Writes `data/seed-urls.json` (67 URLs, a plain list of strings). `--output` overrides the destination (default `data/seed-urls.json`). Sources, in order: every static sitemap page from `/sitemaps/pages` (16 URLs), the nav/footer whitelist (`/login`, `/list-your-practice`, `/search`, `/states`), the first 10 guides from `/sitemaps/guides`, the first 10 news items from `/sitemaps/news`, and brand pages from the homepage nav (capped). Only the Python stdlib is used (urllib + xml.etree), so it runs anywhere.

#### `scripts/validate_reports.py`

QA validation gate. Exit code 0 with a final line "ALL CHECKS PASSED".

```bash
python3 scripts/validate_reports.py
python3 scripts/validate_reports.py --desktop PATH --mobile PATH
```

Six checks: Reopen (python-docx parses the file, at least 30 paragraphs, at least 1 table), Render (soffice headless converts to a non-empty PDF), Images (number of `word/media/` parts is at least the issue count), Placeholders (zero TBD / `[insert` / TODO / lorem), Dedup (no two issues share the same title and URL), Coverage (every issue URL is present in `data/crawl-manifest.json` for the report's device, and the static seed pages are present). Flags: `--mobile`, `--desktop`, `--findings`, `--manifest`, `--seed`.

## Data flow pipeline

Both pipelines share one shape: a harness crawls and writes machine-readable JSON to `data/`, a builder renders it into DOCX, and a validator gates the artifacts before they ship.

UX pipeline:

```
scripts/ux_harness.py (crawl + probes)   -> data/ux-desktop-findings.json
                                             data/ux-mobile-findings.json
                                             data/ux-manifest.json
                                             data/ux-coverage.json
scripts/ux_report_builder.py             -> reports/injector-world-ux-*.docx
scripts/validate_ux_reports.py           -> exit 0 "ALL CHECKS PASSED"
```

QA pipeline:

```
scripts/harness.py             -> data/findings.json
                                  data/crawl-manifest.json
scripts/report_builder.py      -> reports/injector-world-*-bug-report.docx
scripts/validate_reports.py    -> exit 0 "ALL CHECKS PASSED"
```

The `data/` files are the source of truth. Reports are throwaway renderings: delete a DOCX and rebuild it from `data/` with the builder. The findings stores are append-only during a crawl, so re-running a harness adds new entries rather than replacing old ones.

## Data file reference

All of these are committed and regenerable. Counts verified against the files on disk.

| File | Format | Count / shape |
|---|---|---|
| `data/seed-urls.json` | list of strings | 67 URLs |
| `data/findings.json` | list of finding objects | 70 findings |
| `data/crawl-manifest.json` | list of crawl records | QA crawl records; `crawl-manifest-schema.json` is its JSON Schema |
| `data/ux-coverage.json` | object | keys: `methodology`, `pages` (67, each `{url, group, tested}`), `discovery` |
| `data/ux-desktop-findings.json` | object | 15 findings; keys: `generated_at`, `device`, `methodology`, `calibration`, `findings`, `checked_no_issues`, `observations` |
| `data/ux-mobile-findings.json` | object | 12 findings; `device` is `"iphone-13, pixel-7"`; cross-device issues reference `UX-D-###` ids instead of duplicating them |
| `data/ux-scores.json` | object | desktop 4.0, mobile 4.3, overall 4.2, each with `tier_counts`; plus the `formula` string |
| `data/ux-priority-dedup.json` | object | keys: `generated_at`, `methodology`, `entries` (20) |
| `data/ux-manifest.json` | list of crawl records | 274 records |

A finding in `data/findings.json` looks like this (id format `desktop-20260801-174747-1`):

```json
{
  "id": "desktop-20260801-174747-1",
  "device": "desktop",
  "url": "https://www.injector.world/",
  "severity": "HIGH",
  "title": "...",
  "actual": "...",
  "expected": "...",
  "steps": "...",
  "screenshot_path": "evidence/desktop/home/....png"
}
```

`device` is one of `desktop`, `iphone-13`, `pixel-7`.

A `data/ux-manifest.json` record looks like this:

```json
{
  "url": "https://www.injector.world/",
  "device": "desktop",
  "status": 200,
  "load_time_ms": 2345,
  "console_errors": 4,
  "broken_images": 0,
  "bot_blocked": false,
  "tested_at": "2026-08-03T..."
}
```

The `formula` string in `data/ux-scores.json`, verbatim:

```
max(1.0, highest_present_ceiling - 0.2*(n_crit-1) - 0.1*n_mi - 0.05*n_imp - 0.02*n_norm), clamped to [1.0, 10.0], rounded to 1 decimal; ceilings {Critical: 5.0, Most Important: 7.0, Important: 8.5, Normal: 9.5}; overall = round((desktop + mobile) / 2, 1)
```

An entry in `data/ux-priority-dedup.json` `entries` looks like this:

```json
{
  "root_cause": "header and footer navigation links return HTTP 404",
  "title": "Header and footer navigation links return HTTP 404",
  "finding_ids": ["UX-D-001", "UX-M-008"],
  "devices": "Both",
  "tier": "Most Important"
}
```

`devices` is one of `Both`, `Desktop`, `Mobile`. The `methodology` field explains the dedup rule: findings with the same root cause collapse into one entry at the worst tier, with `devices` set to `Both` when the cause spans devices.

## UX findings JSON schema

Every finding in `data/ux-desktop-findings.json` and `data/ux-mobile-findings.json` must satisfy the validator's schema check:

| Field | Requirement |
|---|---|
| `id` | Matches `UX-[DM]-###` (for example `UX-D-001`, `UX-M-012`) |
| `device` | One of `desktop`, `iphone-13`, `pixel-7`, `both` |
| `url` | Non-empty string |
| `primary_area` | One of the 17 `UX_AREAS` |
| `tier` | One of the 4 `UX_TIERS` (Critical, Most Important, Important, Normal) |
| `title` | Non-empty string |
| `description` | At most 160 chars, a single sentence, no solution tokens (`fix:`, `recommend`, `should be`, `consider`, `suggest`) |
| `screenshot_path` | An existing, non-empty `.png` file |
| `qa_ref` OR `qa_independent` | `qa_ref` must resolve to an id in `data/findings.json`, or `qa_independent` must be `true` |

Mobile findings use `device: "both"` when one finding covers both iPhone 13 and Pixel 7. Cross-device issues that already have a desktop finding reference the desktop id in their notes rather than duplicating the investigation.

## Extending the toolchain

All extension points live in `scripts/ux_rubric.py` and `scripts/validate_ux_reports.py`; the validators import the constants from the rubric, so a change in the rubric is picked up automatically as long as the data stays schema-synced.

- **Add a UX area.** Edit `UX_AREAS` in `scripts/ux_rubric.py`. The list must stay schema-synced with the validators, which check `primary_area` against it.
- **Add a severity tier.** Edit `UX_TIERS`, `TIER_CEILINGS`, `SEVERITY_ORDER`, and `PENALTY` in `scripts/ux_rubric.py`. Each tier also carries a `color`, a problem-class `def`, a `decision` rule, and `calibration` examples in `UX_TIERS`.
- **Change the scoring.** Edit `ux_score` and `overall_score` in `scripts/ux_rubric.py`. The formula is documented in [The scripts](#the-scripts). Remember the only-Critical `-1` exemption and the 1-decimal rounding.
- **Add a finding.** Append to `data/ux-desktop-findings.json` or `data/ux-mobile-findings.json` with sequential ids (`UX-D-###` desktop, `UX-M-###` mobile). Follow the [schema table](#ux-findings-json-schema); `qa_ref` ids must be copied verbatim from `data/findings.json`, or use `qa_independent: true`.
- **Add a gate check.** Edit `scripts/validate_ux_reports.py`. The gate currently runs 6 checks (schema, format, coverage, dedup, score, render). A new check should follow the same pattern: collect evidence, print `[PASS]` or `[FAIL]`, and return `False` on failure so the exit code goes non-zero.
- **Add a QA-side check.** Edit `scripts/validate_reports.py` the same way.

## Testing and CI

### Test suite

```bash
python3 -m pytest tests/ -q
```

`tests/test_validation.py` defines 3 test functions:

1. `test_scripts_modules_import`, parametrized over every module in `scripts/`; each must import without raising.
2. `test_ux_validator_gate`, runs `scripts/validate_ux_reports.py` as a subprocess and asserts exit 0 plus "ALL CHECKS PASSED".
3. `test_qa_validator_gate`, runs `scripts/validate_reports.py` as a subprocess and asserts the same.

The subprocess gates run from the repo root, matching CI. They depend only on `data/` and `reports/`, so the tests stay green even when the gitignored `evidence/` directory is absent.

### CI workflow

`.github/workflows/ci.yml` runs on push and pull request to `main`. Job steps, in order:

1. `actions/checkout@v4`
2. `actions/setup-python@v5` with `python-version: "3.14"`
3. `sudo apt-get install -y --no-install-recommends libreoffice-writer`
4. `pip install -r requirements.txt`
5. `python -m playwright install --with-deps chromium` (followed by a diagnostic `ls` of the Playwright cache)
6. `python scripts/smoke_test.py`
7. `python scripts/validate_reports.py`
8. `python scripts/validate_ux_reports.py`

### CI gotchas (historically fixed)

Two failures have bitten the CI workflow before; both are environment issues, not script bugs.

1. **Never run the browser install under `sudo`.** `sudo python -m playwright install --with-deps chromium` fails on a clean runner with `/usr/bin/python: No module named playwright`. `actions/setup-python` puts the interpreter in the hosted toolcache and pip installs playwright into that interpreter, but `sudo` resets `PATH` to secure defaults, so `python` resolves to `/usr/bin/python`, which has no playwright. Use plain `python -m playwright install --with-deps chromium`. The system libraries are handled inside `--with-deps`; it runs the apt step itself, so no `sudo` is needed around the whole command. If you must elevate, resolve the interpreter first: `sudo "$(which python)" -m playwright install --with-deps chromium`.
2. **Install browsers as the same user that runs the tests.** If the install runs as root, Chromium lands in `/root/.cache/ms-playwright/` while the tests run as the runner user, and every launch fails with `Executable doesn't exist at /home/runner/.cache/ms-playwright/...`. Install as the runner user, then verify the cache path exists: `ls ~/.cache/ms-playwright/`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Executable doesn't exist at .../chromium_headless_shell-...` | Run `python -m playwright install --with-deps chromium` as the same user running the script, then verify `ls ~/.cache/ms-playwright/` |
| `No module named playwright` | `pip install -r requirements.txt` in the active environment |
| Render check fails in a validator | Install LibreOffice: `sudo apt-get install -y --no-install-recommends libreoffice-writer` |
| Crawl seems to hang on `networkidle` (Next.js site) | Normal. The site streams background traffic; the harnesses cap `networkidle` at 10 s (`NETWORKIDLE_CAP_MS`) by design, then settle 1.5 s and move on |
| `evidence/` screenshots missing after a fresh clone | `evidence/` is gitignored (628 MB). Regenerate by re-running the harness: `python scripts/harness.py desktop` or `python3 scripts/ux_harness.py desktop --validate` |
| Validator score mismatch against the proposal | Recompute and compare: `python3 scripts/validate_ux_reports.py --score` |
| Want to test the gate itself, including the negative path | Use `--expect-fail`; it inverts the exit code (exit 0 when validation fails, exit 1 when it unexpectedly passes) |
| Mobile crawl crashes after a few pages (`TargetClosedError`) | Split the URL list into small chunk files and run `ux_harness.py <device> --urls chunkN.json` sequentially, each chunk in a fresh browser. Run iPhone 13 and Pixel 7 one after the other, never concurrently |

A final note on the data files: they are append-only during crawls, so retries can accumulate duplicate manifest entries. The validators dedupe by URL and by title/host pairs, so the duplicates are harmless. If you want a clean manifest, delete `data/ux-manifest.json` (or `data/crawl-manifest.json`) before re-crawling.
