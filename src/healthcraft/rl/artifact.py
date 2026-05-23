"""Trained-checkpoint metadata helper (PR-D / WS-6).

A model trained against HealthCraft is a **research artifact**. This
module emits and validates the metadata file that travels with every
checkpoint so downstream tooling can recognise the deployment-status
flag and refuse to score the trained model on the same benchmark as
evidence of clinical competence.

The firewall is enforced at the **API level** —
:class:`ResearchArtifactMetadata` refuses to construct with
``deployment_status`` set to anything other than ``"research_artifact"``.
A would-be deployer cannot simply override the string and pretend the
model is something else without rewriting the dataclass.

Downstream tooling (the leaderboard regenerator, the eval-harness
gates) should call :func:`verify_research_artifact` and refuse to score
trained checkpoints on the benchmark they were trained against.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FIREWALL_TEXT = (
    "A strong HealthCraft training score does NOT constitute evidence "
    "of clinical readiness. Held-out prospective physician-blind "
    "validation is required before any deployment conversation. "
    "See docs/RL_COUPLING.md."
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ResearchArtifactMetadata:
    """Metadata travelling with every HealthCraft-trained checkpoint.

    Written as ``research_artifact.json`` next to the model weights.
    Downstream tooling MUST validate ``deployment_status ==
    "research_artifact"`` before scoring against HealthCraft's eval set.

    The class enforces ``deployment_status == "research_artifact"`` at
    construction time — a downstream consumer cannot quietly flip it.
    """

    base_model: str  # required
    trained_against: str  # required, e.g. "healthcraft_v8"
    training_run_id: str  # required
    deployment_status: str = "research_artifact"
    rl_framework: str = "slime"
    algorithm: str = "dapo"
    reward_config: str = ""
    seed_pool_train: tuple[int, ...] = ()
    seed_pool_eval: tuple[int, ...] = ()
    created_at: str = field(default_factory=_utcnow_iso)
    score_disclaimer: str = _FIREWALL_TEXT
    notes: str = ""

    def __post_init__(self) -> None:
        if self.deployment_status != "research_artifact":
            raise ValueError(
                f"deployment_status MUST be 'research_artifact' for a "
                f"HealthCraft-trained checkpoint; got "
                f"{self.deployment_status!r}. The firewall is intentional — "
                "see docs/RL_COUPLING.md."
            )
        if not self.base_model:
            raise ValueError("base_model is required (open-weights identifier).")
        if not self.trained_against:
            raise ValueError(
                "trained_against is required (e.g., 'healthcraft_v8'); "
                "downstream tooling needs it to refuse to score the model "
                "on the benchmark it was trained against."
            )
        if not self.training_run_id:
            raise ValueError("training_run_id is required (e.g., 'run-20260523-094500').")
        if self.score_disclaimer != _FIREWALL_TEXT:
            raise ValueError(
                "score_disclaimer must match the canonical firewall text "
                "verbatim. Customising this would let a downstream consumer "
                "quietly weaken the disclaimer — refused."
            )

    def save(self, path: Path) -> Path:
        """Write metadata to a JSON file next to the checkpoint.

        ``path`` may point at a directory (writes ``research_artifact.json``
        inside) or at a specific ``.json`` file path.
        """
        if path.suffix != ".json":
            path = path / "research_artifact.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path) -> ResearchArtifactMetadata:
        """Load metadata from a JSON file (or from a directory).

        Raises :class:`FileNotFoundError` or :class:`ValueError` if the
        file is missing or the firewall is violated.
        """
        if path.is_dir():
            path = path / "research_artifact.json"
        if not path.exists():
            raise FileNotFoundError(f"Metadata not found: {path}")
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        # Tuples lose round-tripping through JSON; restore.
        for tuple_field in ("seed_pool_train", "seed_pool_eval"):
            if isinstance(data.get(tuple_field), list):
                data[tuple_field] = tuple(data[tuple_field])
        return cls(**data)


def verify_research_artifact(path: Path) -> bool:
    """Return True iff ``path`` carries a valid research-artifact metadata file.

    This is the function downstream eval gates should call before scoring
    a checkpoint on the benchmark it was trained against. Returns False
    on any error (missing file, parse error, firewall violation) — never
    raises, because the failure mode is "treat as deployable, but be
    silently safe".
    """
    try:
        ResearchArtifactMetadata.load(path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return False
    return True
