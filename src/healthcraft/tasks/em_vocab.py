"""Emergency Medicine vocabulary expansion for audit-log matching.

Loads ``configs/em_vocab.yaml`` and provides a single public entrypoint:
``expand_class(name) -> frozenset[str]`` returning the lowercased surface
forms (canonical + synonyms) for a pharmacologic or blood-product class.
Resolution is transitive through the ``hierarchy.includes`` map.

Used by ``evaluator._audit_entry_matches_params``: when a rubric check
names a known class (e.g. "anticoagulant"), the matcher expands to every
surface form and declares a match if any of them appears in the audit
entry's params string.

Data shape forward-compatibility: each member carries a ``rxcui: null``
slot so future RxNorm provenance slots in without a schema migration.
MVP does not use it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_VOCAB_PATH = Path(__file__).resolve().parents[3] / "configs" / "em_vocab.yaml"


def _load_raw() -> dict:
    if not _VOCAB_PATH.exists():
        return {"version": "0.0.0", "classes": {}, "hierarchy": {}}
    return yaml.safe_load(_VOCAB_PATH.read_text()) or {}


@lru_cache(maxsize=1)
def _vocab() -> dict:
    raw = _load_raw()
    classes: dict[str, frozenset[str]] = {}
    for class_name, body in (raw.get("classes") or {}).items():
        members = body.get("members") or []
        forms: set[str] = set()
        for m in members:
            canonical = (m.get("canonical") or "").strip().lower()
            if canonical:
                forms.add(canonical)
            for s in m.get("synonyms") or ():
                s = (s or "").strip().lower()
                if s:
                    forms.add(s)
        classes[class_name.lower()] = frozenset(forms)

    hierarchy: dict[str, list[str]] = {}
    for name, body in (raw.get("hierarchy") or {}).items():
        includes = [c.strip().lower() for c in (body.get("includes") or [])]
        hierarchy[name.lower()] = includes

    return {"classes": classes, "hierarchy": hierarchy}


def _resolve(class_name: str, seen: set[str]) -> frozenset[str]:
    key = class_name.strip().lower()
    if key in seen:
        return frozenset()
    seen.add(key)
    v = _vocab()
    if key not in v["classes"]:
        return frozenset()
    forms = set(v["classes"][key])
    for child in v["hierarchy"].get(key, ()):
        forms |= _resolve(child, seen)
    return frozenset(forms)


def is_known_class(name: str) -> bool:
    """Return True if ``name`` is a class defined in the vocab YAML."""
    return name.strip().lower() in _vocab()["classes"]


def expand_class(name: str) -> frozenset[str]:
    """Return all lowercased surface forms (canonical + synonyms) for a class.

    Unknown class names return an empty set. Resolution follows
    ``hierarchy.includes`` transitively and is cycle-safe.
    """
    return _resolve(name, seen=set())


def available_classes() -> tuple[str, ...]:
    """Return the sorted tuple of class names defined in the vocab YAML."""
    return tuple(sorted(_vocab()["classes"].keys()))
