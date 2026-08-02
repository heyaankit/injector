#!/usr/bin/env python3
"""Shared severity rubric for the injector.world QA campaign.

Single source of truth used by report_builder.py (and any validator) so both
the mobile and desktop reports classify issues identically.
"""
from __future__ import annotations

# Severity -> {color (hex, used for headings + summary-table shading), definition}
RUBRIC = {
    'CRITICAL': {'color': '#C00000', 'def': 'Core functionality broken for all/most users; data loss; security exposure; broken primary navigation; misleading claims with real-world harm potential'},
    'HIGH':     {'color': '#ED7D31', 'def': 'Major feature broken for a significant user segment (search broken, nav unusable, dynamic pages 404, newsletter broken)'},
    'MEDIUM':   {'color': '#FFC000', 'def': 'Significant visual/UX defects, partial feature issues, meaningful accessibility barriers'},
    'LOW':      {'color': '#70AD47', 'def': 'Cosmetic/minor (typos, empty anchors, duplicated footer line, minor spacing/contrast)'},
}

# Report ordering: CRITICAL first, then HIGH, MEDIUM, LOW.
# Within a severity the source order is preserved (stable sort).
SEVERITY_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
