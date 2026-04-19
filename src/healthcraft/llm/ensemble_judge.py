"""Multi-judge ensemble for criterion evaluation.

Replaces HealthBench's physician-consensus layer with compute-consensus:
three cross-vendor frontier judges evaluate each ``llm_judge`` criterion
independently, and supermajority (2-of-3) decides the verdict. Per-criterion
agreement scores feed downstream ambiguity-dropout analysis.

Design rules:

- The ensemble ALWAYS skips any judge whose vendor matches the agent's
  vendor (no self-judging). If the remaining pool is smaller than
  ``min_agreement``, the ensemble refuses to run — it does not silently
  degrade.
- Determinism: all judges inherit the existing ``LLMJudge`` contract
  (``temperature=0.0``).
- Per-judge caching: every (judge_model, trajectory_id, criterion_id,
  prompt_version) tuple is memoized to disk. The ensemble is cheap to
  warm-run and cold-runs cost roughly ``n_judges × LLMJudge``.

Usage::

    ensemble = EnsembleJudge(agent_model="claude-opus-4-7")
    result = ensemble.evaluate_criterion(criterion, trajectory_turns, trajectory_id)
    if result.ambiguous:
        # downstream ambiguity dropout
        ...

The ensemble does NOT modify :mod:`healthcraft.llm.judge`; it composes
multiple ``LLMJudge`` instances.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from healthcraft.llm.agent import create_client
from healthcraft.llm.judge import LLMJudge
from healthcraft.tasks.rubrics import Criterion

logger = logging.getLogger("healthcraft.llm.ensemble_judge")


_DEFAULT_JUDGE_POOL: tuple[str, ...] = (
    "gpt-5.4",
    "claude-opus-4-7",
    "gemini-3.1-pro",
)

# Lowercase prefix -> vendor. Checked in order: the first matching prefix wins.
_VENDOR_PREFIXES: tuple[tuple[str, str], ...] = (
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("claude", "anthropic"),
    ("opus", "anthropic"),
    ("sonnet", "anthropic"),
    ("haiku", "anthropic"),
    ("gemini", "google"),
    ("grok", "xai"),
)

# Vendor -> env-var name for the API key.
_VENDOR_ENV_VAR: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
}


def _vendor_of(model: str) -> str:
    """Return the vendor for a model identifier via lowercase-prefix match.

    Raises ``ValueError`` if no known prefix matches.
    """
    lowered = model.lower()
    for prefix, vendor in _VENDOR_PREFIXES:
        if lowered.startswith(prefix):
            return vendor
    raise ValueError(f"Unknown vendor for model: {model!r}")


def _api_key_for(vendor: str) -> str:
    """Return the API key for a vendor, or raise ``RuntimeError`` if unset."""
    env_var = _VENDOR_ENV_VAR.get(vendor)
    if env_var is None:
        raise RuntimeError(f"No known API key env var for vendor: {vendor!r}")
    value = os.environ.get(env_var, "")
    if not value:
        raise RuntimeError(f"Missing required API key: environment variable {env_var} is not set.")
    return value


@dataclass(frozen=True)
class EnsembleResult:
    """Aggregated verdict from a multi-judge ensemble."""

    criterion_id: str
    satisfied: bool
    per_judge: dict[str, bool]
    per_judge_evidence: dict[str, str]
    agreement_score: float
    ambiguous: bool
    n_judges_used: int
    evidence: str


class EnsembleJudge:
    """Multi-judge ensemble with supermajority voting and same-vendor skip.

    Wraps one ``LLMJudge`` per pooled model. For each criterion, each judge
    votes independently; the final verdict is ``satisfied=True`` iff at least
    ``min_agreement`` judges voted True.
    """

    def __init__(
        self,
        agent_model: str,
        judge_pool: list[str] | None = None,
        min_agreement: int = 2,
        prompt_version: str = "v2",
        cache_dir: Path | None = None,
    ) -> None:
        """Initialize the ensemble.

        Args:
            agent_model: The model used by the agent. Any judge whose vendor
                matches ``agent_model``'s vendor is skipped.
            judge_pool: Ordered list of judge model identifiers. Defaults to
                the three-vendor frontier pool.
            min_agreement: Number of judges that must agree for a True
                verdict. A True verdict requires ``>= min_agreement`` True
                votes; otherwise the verdict is False.
            prompt_version: Judge prompt version. Forwarded to ``LLMJudge``.
            cache_dir: Root directory for per-judge caches. Defaults to
                ``results/ensemble_cache/``.

        Raises:
            ValueError: If fewer than ``min_agreement`` judges remain after
                the same-vendor filter.
            RuntimeError: If an API key is missing for a required vendor.
        """
        pool = list(judge_pool) if judge_pool is not None else list(_DEFAULT_JUDGE_POOL)
        if not pool:
            raise ValueError("judge_pool must be non-empty")

        agent_vendor = _vendor_of(agent_model)
        filtered = [m for m in pool if _vendor_of(m) != agent_vendor]

        if len(filtered) < min_agreement:
            raise ValueError(
                f"Ensemble has only {len(filtered)} judge(s) after filtering "
                f"same-vendor ({agent_vendor}) from pool {pool}; "
                f"min_agreement={min_agreement} is unreachable."
            )

        if cache_dir is None:
            cache_dir = Path(__file__).parents[3] / "results" / "ensemble_cache"

        self._agent_model = agent_model
        self._agent_vendor = agent_vendor
        self._judges: list[tuple[str, LLMJudge]] = []
        for judge_model in filtered:
            vendor = _vendor_of(judge_model)
            api_key = _api_key_for(vendor)
            client = create_client(judge_model, api_key)
            judge = LLMJudge(client, judge_model=judge_model, prompt_version=prompt_version)
            self._judges.append((judge_model, judge))

        self._min_agreement = min_agreement
        self._prompt_version = prompt_version
        self._cache_dir = cache_dir

    @property
    def judge_models(self) -> list[str]:
        """Return the judge model identifiers actually used (post-filter)."""
        return [m for m, _ in self._judges]

    def evaluate_criterion(
        self,
        criterion: Criterion,
        trajectory_turns: list[dict[str, Any]],
        trajectory_id: str,
    ) -> EnsembleResult:
        """Evaluate a single criterion with the ensemble.

        Each judge votes independently. Results are cached per (judge,
        trajectory, criterion, prompt_version). Cache hits skip the API call.

        Args:
            criterion: The criterion to evaluate.
            trajectory_turns: The agent trajectory, as the existing
                ``LLMJudge`` expects.
            trajectory_id: Stable identifier for cache keying. Typically the
                trajectory filename stem.

        Returns:
            ``EnsembleResult`` with the aggregated verdict and per-judge
            breakdown.
        """
        per_judge: dict[str, bool] = {}
        per_judge_evidence: dict[str, str] = {}

        for judge_model, judge in self._judges:
            cached = self._read_cache(judge_model, trajectory_id, criterion.id)
            if cached is not None:
                per_judge[judge_model] = bool(cached["satisfied"])
                per_judge_evidence[judge_model] = str(cached.get("evidence", ""))
                continue

            result = judge.evaluate_criterion(criterion, trajectory_turns)
            per_judge[judge_model] = bool(result.satisfied)
            per_judge_evidence[judge_model] = result.evidence
            self._write_cache(
                judge_model,
                trajectory_id,
                criterion.id,
                satisfied=bool(result.satisfied),
                evidence=result.evidence,
            )

        votes = list(per_judge.values())
        trues = sum(1 for v in votes if v)
        falses = len(votes) - trues
        final = trues >= self._min_agreement
        majority_size = max(trues, falses)
        n = len(votes)
        agreement_score = majority_size / n if n > 0 else 0.0
        ambiguous = majority_size < self._min_agreement

        combined_evidence = self._combine_evidence(per_judge, per_judge_evidence, final)

        return EnsembleResult(
            criterion_id=criterion.id,
            satisfied=final,
            per_judge=per_judge,
            per_judge_evidence=per_judge_evidence,
            agreement_score=agreement_score,
            ambiguous=ambiguous,
            n_judges_used=n,
            evidence=combined_evidence,
        )

    def evaluate_criteria(
        self,
        criteria: list[Criterion],
        trajectory_turns: list[dict[str, Any]],
        trajectory_id: str,
    ) -> list[EnsembleResult]:
        """Evaluate multiple criteria; skips non-``llm_judge`` criteria.

        Mirrors :meth:`LLMJudge.evaluate_criteria` — only criteria with
        ``verification == llm_judge`` are evaluated.
        """
        results: list[EnsembleResult] = []
        for criterion in criteria:
            if criterion.verification.value != "llm_judge":
                continue
            results.append(self.evaluate_criterion(criterion, trajectory_turns, trajectory_id))
        return results

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def _cache_path(self, judge_model: str, trajectory_id: str, criterion_id: str) -> Path:
        safe_model = judge_model.replace("/", "_")
        safe_traj = trajectory_id.replace("/", "_")
        safe_crit = criterion_id.replace("/", "_")
        return self._cache_dir / safe_model / safe_traj / f"{safe_crit}.json"

    def _read_cache(
        self, judge_model: str, trajectory_id: str, criterion_id: str
    ) -> dict[str, Any] | None:
        path = self._cache_path(judge_model, trajectory_id, criterion_id)
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Corrupt ensemble cache %s: %s — ignoring", path, exc)
            return None

        if data.get("prompt_version") != self._prompt_version:
            return None
        if "satisfied" not in data:
            return None
        return data

    def _write_cache(
        self,
        judge_model: str,
        trajectory_id: str,
        criterion_id: str,
        *,
        satisfied: bool,
        evidence: str,
    ) -> None:
        path = self._cache_path(judge_model, trajectory_id, criterion_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "satisfied": satisfied,
            "evidence": evidence,
            "model": judge_model,
            "prompt_version": self._prompt_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp_path, path)
        except Exception:
            # Best-effort cleanup; re-raise so caller sees the problem.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Evidence aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def _combine_evidence(
        per_judge: dict[str, bool],
        per_judge_evidence: dict[str, str],
        final: bool,
    ) -> str:
        """Produce a combined evidence string for ``CriterionResult`` compat.

        The string tags each judge's vote and includes its evidence, so the
        downstream trajectory audit trail can show why the ensemble landed
        on its verdict.
        """
        parts = [f"[ensemble verdict: {'satisfied' if final else 'not_satisfied'}]"]
        for judge_model, vote in per_judge.items():
            tag = "T" if vote else "F"
            ev = per_judge_evidence.get(judge_model, "")
            parts.append(f"[{judge_model}={tag}] {ev}")
        return " ".join(parts)
