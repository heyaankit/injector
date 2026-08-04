# injector.world: Professional QA Test Reports

An independent QA testing campaign of the live aesthetic-injector directory at https://www.injector.world/ ("Find Your Injector."). This repo contains the findings, evidence, and two severity-ranked DOCX bug reports produced by the audit.

## What this is

A software-tester style QA audit combining visual and logical checks, executed with Playwright (Python) against the production Next.js (App Router) site. The campaign covered desktop (Chromium at 1920x1080, plus responsive widths 1366, 1024, and 768) and two mobile profiles (iPhone 13 and Pixel 7 emulation), producing two DOCX bug reports with screenshot evidence for every issue.

All testing was read-only against the public site, and the campaign ran August 1-2, 2026.

## Headline findings

- **CRITICAL: Directory claim vs. reality mismatch.** The homepage advertises "17,020+ clinics" and "12,400+ verified injectors" while the clinics directory renders "No verified clinics or injectors match." for the same data.
- **HIGH: 12 broken navigation links.** Nine `/guides/*` URLs and three `/services/*` URLs linked from the header and footer return HTTP 404.
- **HIGH: Site-wide search returns 0 results.** A search for "Botox" returns 0 results on both desktop and mobile.
- **HIGH (mobile): Hamburger menu treatment links don't navigate.** In the mobile menu, treatment links are covered by overlapping panel content, so a tap lands on the wrong element and the menu stays open.
- **MEDIUM: Accessibility and content issues.** Newsletter inputs lack accessible labels, mobile menu links have 18px tap targets (below the 44px WCAG 2.5.8 minimum), several pages have broken images, and the `/news` page logs console errors.

Note: the homepage stats counters (17,020+, 12,400+) were investigated and work correctly. They are a scroll-triggered count-up animation, not a bug.

## Deliverables

| Artifact | Contents |
|---|---|
| `reports/injector-world-desktop-bug-report.docx` | 35 issues (1 CRITICAL, 13 HIGH, 20 MEDIUM, 1 LOW), a "Verified: Not Reproducible" section, a performance appendix, and a coverage section (67 pages) |
| `reports/injector-world-mobile-bug-report.docx` | 8 issues (1 CRITICAL, 2 HIGH, 5 MEDIUM), a "Verified: Not Reproducible" section (7 items), a performance appendix, and a coverage section (134 pages) |
| `data/findings.json` | 70 machine-readable findings (49 desktop, 21 mobile) |
| `data/crawl-manifest.json` | 201 audited pages (67 URLs, each under desktop, iPhone 13, and Pixel 7), 0 failed crawls |
| `data/seed-urls.json` | The 67-URL seed list used for the crawl |
| `evidence/` | Screenshot evidence per device and page. Gitignored and regenerable via the harness |
| `reports/injector-world-ux-desktop-report.docx` | 15 UX findings (2 Critical, 4 Most Important, 8 Important, 1 Normal), /10 score 4.0, coverage (67 pages) |
| `reports/injector-world-ux-mobile-report.docx` | 12 UX findings (1 Critical, 4 Most Important, 5 Important, 2 Normal), /10 score 4.3, coverage (67 pages) |
| `reports/injector-world-ux-proposal.docx` | Client proposal: executive summary, desktop + mobile findings, priority-wise list (20 dedup entries), overall /10 score 4.2 |
| `data/ux-desktop-findings.json` | 15 machine-readable desktop UX findings |
| `data/ux-mobile-findings.json` | 12 machine-readable mobile UX findings |
| `data/ux-scores.json` | /10 scores (desktop 4.0, mobile 4.3, overall 4.2) + tier counts + formula |
| `data/ux-priority-dedup.json` | 20-entry cross-device priority map (7 Both / 8 Desktop / 5 Mobile) |
| `data/ux-coverage.json` | 67 audited pages |
| `data/ux-manifest.json` | Crawl manifest for the UX audit (device profiles) |

Each DOCX report contains an executive summary, a severity summary table, issues ordered CRITICAL to LOW with color-coded severity, steps to reproduce, expected vs. actual behavior, and embedded screenshot evidence.

## Repo layout

```
injector-world-qa/
├── .editorconfig
├── .github/
│   └── workflows/
│       └── ci.yml
├── .gitignore
├── LICENSE
├── README.md
├── pyproject.toml
├── requirements.txt
├── data/
│   ├── crawl-manifest-schema.json
│   ├── crawl-manifest.json
│   ├── findings.json
│   ├── seed-urls.json
│   ├── ux-coverage.json
│   ├── ux-desktop-findings.json
│   ├── ux-manifest.json
│   ├── ux-mobile-findings.json
│   ├── ux-priority-dedup.json
│   └── ux-scores.json
├── legacy/
│   ├── data/
│   │   ├── t11-final-diagnostic.json
│   │   ├── t11-mobile-functional-results.json
│   │   ├── t11-retest-results.json
│   │   ├── t12-fix-results.json
│   │   ├── t12-mobile-results.json
│   │   └── t5-data-suspects.json
│   └── scripts-*/  (scripts-f3, scripts-t7, scripts-t10, scripts-t11, scripts-t12, scripts-t16)
├── reports/
│   ├── injector-world-desktop-bug-report.docx
│   ├── injector-world-mobile-bug-report.docx
│   ├── injector-world-testing-summary.docx
│   ├── injector-world-testing-summary.md
│   ├── injector-world-ux-desktop-report.docx
│   ├── injector-world-ux-mobile-report.docx
│   └── injector-world-ux-proposal.docx
├── scripts/
│   ├── build_seed.py
│   ├── harness.py
│   ├── report_builder.py
│   ├── rubric.py
│   ├── smoke_test.py
│   ├── ux_harness.py
│   ├── ux_report_builder.py
│   ├── ux_rubric.py
│   ├── validate_reports.py
│   └── validate_ux_reports.py
└── tests/
    └── test_validation.py
```

## Project structure

The repository follows standard Python project conventions:

- **`requirements.txt`** at the repo root pins the runtime dependencies; `pyproject.toml` mirrors them under `[project.dependencies]` and adds tooling config for `ruff` (line length 100) and `pytest`.
- **`scripts/`** holds the active QA/UX toolchain. All validators run from the repo root and use relative paths to `data/` and `reports/`.
- **`tests/`** contains pytest tests that import every `scripts/` module and run both validation gates as subprocesses.
- **`legacy/`** archives historical QA working scripts and intermediate data from earlier campaign phases.
- **`.github/workflows/ci.yml`** runs the smoke test and both validation gates on every push/PR to `main` (Ubuntu, Python 3.14, LibreOffice for the render check).
- **`LICENSE`** (MIT), **`.editorconfig`**, and **`.gitignore`** provide standard project hygiene.

## For developers

This section is for developers who want to use, extend, or contribute to the QA/UX toolchain. It covers how the pieces fit together, the module surface, the extension points, the findings schema, and the contribution workflow.

### Architecture and data flow

The toolchain is a linear pipeline: crawl, store, build, validate.

```
scripts/ux_harness.py (crawl + probes)  ->  data/ux-desktop-findings.json
                                            data/ux-mobile-findings.json
                                            data/ux-manifest.json
                                            data/ux-coverage.json
scripts/ux_report_builder.py (DOCX)     ->  reports/injector-world-ux-*.docx
scripts/validate_ux_reports.py (gate)   ->  exit 0 "ALL CHECKS PASSED"
tests/ + .github/workflows/ci.yml       ->  pytest suite + CI gate
```

The QA bug-report pipeline mirrors this with `scripts/harness.py`, `scripts/report_builder.py`, and `scripts/validate_reports.py`. Both pipelines share the same shape: a harness writes machine-readable findings to `data/`, a builder renders them into DOCX, and a validator gates the artifacts before they ship.

### Module reference

| Module | What it does | Key entry points |
|---|---|---|
| `scripts/harness.py` | QA crawl harness: screenshots, load timing, findings + manifest recording | `python scripts/harness.py desktop\|iphone-13\|pixel-7` |
| `scripts/report_builder.py` | QA DOCX bug report generator | `python scripts/report_builder.py --device mobile\|desktop --out <docx> --as-of <ISO>` |
| `scripts/rubric.py` | Single source of truth for QA severity colors and ordering | imported by the QA builder and validator |
| `scripts/validate_reports.py` | 6-check validation gate for the QA reports | `python scripts/validate_reports.py` |
| `scripts/build_seed.py` | Generates the 67-URL seed list | `python scripts/build_seed.py` |
| `scripts/smoke_test.py` | Environment smoke test (launches Chromium) | `python scripts/smoke_test.py` |
| `scripts/ux_harness.py` | Interaction-capable UX crawl harness: probes + discovery pass | `python3 scripts/ux_harness.py desktop\|iphone-13\|pixel-7 [--urls FILE] [--discover] [--validate]` |
| `scripts/ux_rubric.py` | Single source of truth for the 17 UX areas, 4 severity tiers, and /10 score | `UX_AREAS`, `UX_TIERS`, `ux_score()`, `overall_score()` |
| `scripts/ux_report_builder.py` | DOCX UX report + proposal generator | `python3 scripts/ux_report_builder.py --device desktop\|mobile --out <docx> [--as-of <ISO>]` or `--proposal --out <docx>` |
| `scripts/validate_ux_reports.py` | 6-check validation gate for the UX audit artifacts | `python3 scripts/validate_ux_reports.py [--findings f1.json f2.json] [--reports r1.docx r2.docx r3.docx] [--score] [--expect-fail]` |

### Key extension points

- **Add a new UX area.** Edit `UX_AREAS` in `scripts/ux_rubric.py` (currently 17 areas). The list must stay schema-synced with the validators, which check `primary_area` against it.
- **Add a new severity tier.** Edit `UX_TIERS` in `scripts/ux_rubric.py`. Each tier carries a `color`, a problem-class `def`, a `decision` rule, and `calibration` examples. Add the tier to `TIER_CEILINGS`, `SEVERITY_ORDER`, and `PENALTY` so scoring stays consistent.
- **Change the /10 scoring.** Edit `ux_score` and `overall_score` in `scripts/ux_rubric.py`. The current formula is `max(1.0, highest_present_ceiling - 0.2*(n_crit-1) - 0.1*n_mi - 0.05*n_imp - 0.02*n_norm)`, where the ceiling is set by the most severe tier present (Critical 5.0, Most Important 7.0, Important 8.5, Normal 9.5), clamped to `[1.0, 10.0]` and rounded to 1 decimal. `overall_score` is `round((desktop + mobile) / 2, 1)`.
- **Add a finding.** Append to `data/ux-desktop-findings.json` or `data/ux-mobile-findings.json` following the schema below. Use sequential ids (`UX-D-###` for desktop, `UX-M-###` for mobile).
- **Add a check to the gate.** Edit `scripts/validate_ux_reports.py`. The gate currently runs 6 checks: schema, format, coverage, dedup, score, and render.

### Findings JSON schema

Each finding in the UX stores must satisfy the validator's schema check:

| Field | Requirement |
|---|---|
| `id` | Matches `UX-[DM]-###` (e.g. `UX-D-001`, `UX-M-012`) |
| `device` | One of `desktop`, `iphone-13`, `pixel-7`, `both` |
| `url` | Non-empty string |
| `primary_area` | One of the 17 `UX_AREAS` |
| `tier` | One of the 4 `UX_TIERS` (Critical, Most Important, Important, Normal) |
| `title` | Non-empty string |
| `description` | At most 160 chars, a single sentence, no solution tokens (`fix:`, `recommend`, `should be`, `consider`, `suggest`) |
| `screenshot_path` | An existing, non-empty `.png` file |
| `qa_ref` OR `qa_independent` | `qa_ref` must resolve to an id in `data/findings.json`, or `qa_independent` must be `true` |

### Developer workflow and contribution checklist

1. Install dependencies: `pip install -r requirements.txt`. For the test suite, also `pip install pytest`, or install the dev extras with `pip install -e ".[dev]"` (the `pyproject.toml` declares `dev = ["pytest"]`).
2. Run the tests: `python3 -m pytest tests/ -q`.
3. Run both gates before pushing. `python3 scripts/validate_reports.py` and `python3 scripts/validate_ux_reports.py` must each exit 0 with "ALL CHECKS PASSED".
4. CI (`.github/workflows/ci.yml`) runs the smoke test and both validators on every push/PR to `main`. It installs the Playwright browser (`python -m playwright install --with-deps chromium`, which downloads the browser as the runner user and handles system dependencies via sudo internally) and LibreOffice for the render check.
5. Follow the style config: `ruff` with line length 100, `.editorconfig` (4-space Python), and the `ruff` + `pytest` settings in `pyproject.toml`.

## How it was tested

The audit is reproducible:

1. Install dependencies: `pip install -r requirements.txt`
2. Crawl a device profile: `python scripts/harness.py desktop|iphone-13|pixel-7`
   The harness walks the seed list, captures full-page and viewport screenshots, records load times, console errors, broken images, and bot-protection signals, and appends results to `data/findings.json` and `data/crawl-manifest.json`.
3. Regenerate a report: `python scripts/report_builder.py --device mobile|desktop --out <docx> --as-of <ISO>`
   Reports are device-filtered and rebuilt from `data/findings.json`.
4. Validate: `python scripts/validate_reports.py`
   Runs six checks against both reports and exits 0 with "ALL CHECKS PASSED".

The crawl is conservative by design: pages load to `domcontentloaded` plus a capped `networkidle`, with a settle delay before measurement. Bot protection is detected and recorded, never bypassed.

## UI/UX audit

On top of the QA bug campaign, a dedicated UI/UX audit was completed against the same live site. It evaluates the experience across **17 UX areas** (navigation, forms, buttons, scrolling, hover states, and more) and classifies each finding into one of **4 severity tiers**: Critical, Most Important, Important, and Normal. The audit produces a **/10 UX quality score** per device and overall.

Coverage mirrors the QA campaign: desktop (Chromium at 1920x1080, plus responsive widths 1366, 1024, and 768) and two mobile profiles (iPhone 13 and Pixel 7 emulation). Unlike a passive crawl, the UX harness runs **interaction probes** against menus, forms, buttons, scrolling, and hover states, and includes a **discovery pass** that samples internal links to surface reachable pages not yet in the coverage list.

The UX audit is fully reproducible with the scripts below.

## How to run the UX audit

The UX audit is reproducible end-to-end:

1. Install dependencies: `pip install -r requirements.txt`
2. Run the desktop crawl: `python3 scripts/ux_harness.py desktop`
   Crawls the desktop profile with base crawl plus interaction probes, writing to `evidence/ux/` and `data/ux-manifest.json`.
3. Run the mobile crawls: `python3 scripts/ux_harness.py iphone-13` and `python3 scripts/ux_harness.py pixel-7`
   Same crawl and probes under each mobile emulation profile.
4. Run the discovery pass: `python3 scripts/ux_harness.py desktop --discover`
   Collects internal links across crawled pages, diffs them against `data/ux-coverage.json`, and records the bounded delta.
5. Validate the audit artifacts: `python3 scripts/validate_ux_reports.py`
   Runs six checks (schema, format, coverage, dedup, score, render) and exits 0 with "ALL CHECKS PASSED".

For a quick visual demo, `python3 scripts/ux_harness.py desktop --headed --slowmo 250 --max-urls 5` opens a visible browser and crawls the first 5 URLs at a slow, watchable pace. The `--headed`, `--slowmo MS`, and `--max-urls N` flags are also available on `scripts/harness.py`.
6. Regenerate the desktop report: `python3 scripts/ux_report_builder.py --device desktop --out reports/injector-world-ux-desktop-report.docx`
   Builds the compact, Word-copyable desktop report from `data/ux-desktop-findings.json` and `data/ux-coverage.json`.
7. Regenerate the mobile report: `python3 scripts/ux_report_builder.py --device mobile --out reports/injector-world-ux-mobile-report.docx`
   Builds the mobile report from `data/ux-mobile-findings.json` and `data/ux-coverage.json`.
8. Regenerate the client proposal: `python3 scripts/ux_report_builder.py --proposal --out reports/injector-world-ux-proposal.docx`
   Builds the proposal from both findings stores plus `data/ux-scores.json` and `data/ux-priority-dedup.json`. All three commands accept an optional `--as-of <ISO>` report date (default today).

The harness is non-destructive by design: forms receive invalid or empty data only, bot protection is detected and recorded but never bypassed, and a single failed page never aborts the run.

## UX audit results

All UI/UX testing has been completed, and every artifact is committed to this repo. The audit found **27 UX findings** across desktop and mobile: 15 on desktop and 12 on mobile. Each finding is classified into one of **4 severity tiers** (Critical, Most Important, Important, Normal) and mapped to one of **17 UX areas**.

The /10 UX quality scores:

- **Desktop: 4.0** (2 Critical, 4 Most Important, 8 Important, 1 Normal)
- **Mobile: 4.3** (1 Critical, 4 Most Important, 5 Important, 2 Normal)
- **Overall: 4.2** (average of desktop and mobile)

Because several root causes appear on both devices, the cross-device priority map collapses the 27 findings into **20 dedup entries**: 7 affect Both devices, 8 are Desktop-only, and 5 are Mobile-only (2 Critical, 6 Most Important, 10 Important, 2 Normal). This map is what the client proposal presents as the priority-wise list.

The three DOCX deliverables document all of this end-to-end: the desktop report covers the 15 desktop findings, the mobile report covers the 12 mobile findings, and the proposal ties both together with the executive summary, the priority-wise list, and the overall score.

## Quality gates passed

- **20% live re-verification.** 10 issues were sampled across both reports (22.7%, above the 20% gate), covering all four severity buckets. 9 reproduced live; 1 (mobile footer tap interception) was not reproducible and was moved to the "Verified: Not Reproducible" section.
- **Render check.** Both DOCX reports render cleanly via LibreOffice headless (PDF conversion exits 0).
- **Zero placeholders.** No TBD, `[insert]`, TODO, or lorem text in either report, checked across paragraphs, tables, and raw document XML.
- **Non-destructive compliance.** No real form submissions or newsletter signups (only invalid and empty input was used), no requests to `/admin/` or `/api/`, no bot-protection bypass, and no Lighthouse runs.
- **UX validator gate.** `python3 scripts/validate_ux_reports.py` exits 0 with "ALL CHECKS PASSED", covering schema, format, coverage, dedup, score, and render for the UX audit artifacts.
- **UX live re-verification.** 11 of 27 UX findings (40.7%) were independently re-verified live after the audit; 9 reproduced with matching detail. Two findings (site search returning 0 results, and the clinics directory empty state) no longer reproduce because the production site was updated after the audit crawl of August 1-2, 2026. This is documented in a "Re-verification Note" appended to all three UX reports.

## Note on evidence/

The `evidence/` directory is 628 MB of crawl screenshots and is excluded via `.gitignore` to respect GitHub repository size limits. The DOCX reports embed the key screenshots, and the directory can be regenerated at any time by re-running the harness.
