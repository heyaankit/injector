#!/usr/bin/env python3
"""UX rubric for the injector.world UX audit.

Single source of truth for the 17 UX audit areas, the 4 severity tiers, and
the /10 scoring formula. This module is read-only reference for downstream
audit tooling; it does not crawl or modify anything.

Tier definitions describe the PROBLEM CLASS ONLY (what the defect is and its
impact). They deliberately contain NO solution text (no "should be",
"recommend", or "fix by") so the rubric stays a classification instrument.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# UX_AREAS — the 17 audit areas. Names are verbatim from the audit spec.
# ---------------------------------------------------------------------------
UX_AREAS = [
    "broken_links",
    "navigation",
    "layout_responsive",
    "mobile_responsiveness",
    "forms_validation",
    "buttons_ctas",
    "images_icons",
    "typography_readability",
    "spacing_alignment",
    "header_footer",
    "menus_dropdowns",
    "scrolling_behavior",
    "accessibility_basics",
    "performance_ux",
    "console_errors",
    "visual_consistency",
    "journey_friction",
]

# ---------------------------------------------------------------------------
# UX_TIERS — 4 tiers. Colors reuse the QA rubric hex values but with new names.
# Each tier: {color, def (problem class), decision_rule, calibration}.
# ---------------------------------------------------------------------------
UX_TIERS = {
    "Critical": {
        "color": "#C00000",
        "def": (
            "UX blocker: the core task cannot be completed by most users, or "
            "the page presents real-world harm / misleading claims."
        ),
        "decision": (
            "A problem is Critical when it prevents the primary user journey "
            "for the majority of users, or when content is materially "
            "misleading with potential for real-world harm."
        ),
        "calibration": [
            "mobile menu entirely unusable",
            "search returning 0 results for normal queries",
            '"0 verified clinics" vs "17,020+" claim',
        ],
    },
    "Most Important": {
        "color": "#ED7D31",
        "def": (
            "Major friction for a significant user segment; a workaround "
            "exists but the interaction is meaningfully degraded."
        ),
        "decision": (
            "Arial is Most Important if a large subset of users hits "
            "significant friction on a core interaction, even though a "
            "workaround lets some users proceed."
        ),
        "calibration": [
            "18px tap targets",
            "dropdown opens but mis-hits",
        ],
    },
    "Important": {
        "color": "#FFC000",
        "def": (
            "Noticeable quality defect affecting some users or some pages; "
            "the task still completes."
        ),
        "decision": (
            "Arial is Important if it is a visible quality defect that "
            "degrades a subset of pages or users without blocking the task."
        ),
        "calibration": [
            "broken images on a page category",
            "inconsistent header on a subset",
            "spacing misalignment on a template",
        ],
    },
    "Normal": {
        "color": "#70AD47",
        "def": (
            "Minor polish / cosmetic issue with no impact on task completion."
        ),
        "decision": (
            "Arial is Normal if it is cosmetic or minor polish that does not "
            "affect the user's ability to complete the task."
        ),
        "calibration": [
            "single misaligned element",
            "minor contrast nuance",
        ],
    },
}

# ---------------------------------------------------------------------------
# UX_SCORE — the /10 ceiling model.
#
#   tier_ceilings = {Critical: 5.0, 'Most Important': 7.0, Important: 8.5,
#                    Normal: 9.5}
#   score = max(1.0, highest_present_ceiling
#               - 0.2*(n_crit-1) - 0.1*n_mi - 0.05*n_imp - 0.02*n_norm)
#
# The ceiling is set by the highest tier present; each additional issue in any
# tier subtracts a small penalty. The result is clamped to [1.0, 10.0] and
# rounded to 1 decimal.
# ---------------------------------------------------------------------------
TIER_CEILINGS = {
    "Critical": 5.0,
    "Most Important": 7.0,
    "Important": 8.5,
    "Normal": 9.5,
}

# Severity order: most severe first. The ceiling is set by the most severe
# tier present (Critical caps the score at 5.0).
SEVERITY_ORDER = ["Critical", "Most Important", "Important", "Normal"]

# Per-issue penalty for each tier. Only Critical gets a -1 exemption (the
# first Critical issue is the ceiling itself, per the spec formula).
PENALTY = {
    "Critical": 0.2,
    "Most Important": 0.1,
    "Important": 0.05,
    "Normal": 0.02,
}


def ux_score(tier_counts: dict[str, int]) -> float:
    """Return a /10 score from a {tier: count} dict.

    Implements the spec ceiling model verbatim:
        score = max(1.0, highest_present_ceiling
                    - 0.2*(n_crit-1) - 0.1*n_mi - 0.05*n_imp - 0.02*n_norm)
    where highest_present_ceiling is the ceiling of the most severe tier
    present. Result is clamped to [1.0, 10.0] and rounded to 1 decimal.
    """
    counts = {t: max(0, int(tier_counts.get(t, 0))) for t in TIER_CEILINGS}
    present = [t for t in SEVERITY_ORDER if counts[t] > 0]
    if not present:
        return 10.0
    ceiling = TIER_CEILINGS[present[0]]
    n_crit = counts["Critical"]
    n_mi = counts["Most Important"]
    n_imp = counts["Important"]
    n_norm = counts["Normal"]
    score = (
        ceiling
        - 0.2 * max(0, n_crit - 1)
        - 0.1 * n_mi
        - 0.05 * n_imp
        - 0.02 * n_norm
    )
    return round(max(1.0, min(10.0, score)), 1)


def overall_score(desktop: float, mobile: float) -> float:
    """Combine desktop and mobile /10 scores into a single overall score."""
    return round((desktop + mobile) / 2, 1)


# Convenience alias matching the spec's function name.
UX_SCORE = ux_score