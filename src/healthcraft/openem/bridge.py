"""OpenEM integration bridge for HEALTHCRAFT.

Uses the optional import pattern: when openem is installed, condition data
is loaded from the full corpus. When not installed, falls back to a
bundled JSON subset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from openem.conditions import load_condition_map

    HAS_OPENEM = True
except ImportError:
    HAS_OPENEM = False

# Path to bundled fallback data
_BUNDLED_DATA_PATH = Path(__file__).parent / "bundled_conditions.json"


class OpenEMBridge:
    """Bridge between HEALTHCRAFT and the OpenEM corpus.

    When OpenEM is installed, loads the full 370-condition corpus.
    Otherwise falls back to a bundled subset sufficient for basic
    operation and testing.
    """

    def __init__(self, use_openem: bool = True) -> None:
        """Initialize the bridge.

        Args:
            use_openem: If True and OpenEM is available, load from OpenEM.
                If False or OpenEM is not installed, use bundled data.
        """
        self._conditions: dict[str, dict[str, Any]] = {}
        self._source: str = "none"

        if use_openem and HAS_OPENEM:
            self._load_from_openem()
        else:
            self._load_bundled()

    def _load_from_openem(self) -> None:
        """Load conditions from the OpenEM corpus."""
        try:
            condition_map = load_condition_map()
            self._conditions = dict(condition_map)
            self._source = "openem"
        except Exception:
            # Fall back to bundled if OpenEM loading fails
            self._load_bundled()

    def _load_bundled(self) -> None:
        """Load bundled fallback condition data."""
        if _BUNDLED_DATA_PATH.exists():
            text = _BUNDLED_DATA_PATH.read_text(encoding="utf-8")
            self._conditions = json.loads(text)
            self._source = "bundled_file"
        else:
            # Inline minimal fallback
            from healthcraft.entities.clinical_knowledge import _BUNDLED_CONDITIONS

            self._conditions = dict(_BUNDLED_CONDITIONS)
            self._source = "bundled_inline"

    @property
    def source(self) -> str:
        """The data source currently in use ('openem', 'bundled_file', or 'bundled_inline')."""
        return self._source

    @property
    def condition_count(self) -> int:
        """Number of loaded conditions."""
        return len(self._conditions)

    def load_conditions(self) -> dict[str, dict[str, Any]]:
        """Return all loaded conditions.

        Returns:
            Dict of condition_id -> condition data.
        """
        return dict(self._conditions)

    def get_condition(self, condition_id: str) -> dict[str, Any] | None:
        """Look up a single condition by ID.

        Args:
            condition_id: The condition identifier.

        Returns:
            Condition data dict, or None if not found.
        """
        return self._conditions.get(condition_id)

    def get_confusion_pairs(self, condition_id: str) -> list[dict[str, Any]]:
        """Get confusion pairs for a condition.

        Confusion pairs are conditions commonly confused with the target,
        used to generate realistic differential diagnosis scenarios.

        Args:
            condition_id: The condition identifier.

        Returns:
            List of confusion pair dicts.
        """
        condition = self._conditions.get(condition_id)
        if condition is None:
            return []
        return list(condition.get("confusion_pairs", []))

    def get_decision_rules(self, condition_id: str) -> list[dict[str, Any]]:
        """Get decision rules for a condition.

        Decision rules define the clinical decision points that distinguish
        correct from incorrect management.

        Args:
            condition_id: The condition identifier.

        Returns:
            List of decision rule dicts.
        """
        condition = self._conditions.get(condition_id)
        if condition is None:
            return []
        return list(condition.get("decision_rules", []))

    def search_conditions(self, query: str) -> list[dict[str, Any]]:
        """Search conditions by name or category.

        Simple case-insensitive substring search across condition_name
        and category fields.

        Args:
            query: Search query string.

        Returns:
            List of matching condition dicts.
        """
        query_lower = query.lower()
        results: list[dict[str, Any]] = []
        for condition in self._conditions.values():
            name = condition.get("condition_name", condition.get("name", "")).lower()
            category = condition.get("category", "").lower()
            cid = condition.get("condition_id", "").lower()
            if query_lower in name or query_lower in category or query_lower in cid:
                results.append(condition)
        return results

    def __repr__(self) -> str:
        return f"OpenEMBridge(source={self._source!r}, conditions={len(self._conditions)})"
