"""Seeded episode pools for RL training (PR-C / WS-4).

Training samples episode seeds from a large pool; evaluation **pins** a
held-out canary set that includes seed 42 (the V8 evaluation baseline, so
existing pilots stay reproducible). The split rule is one-line —
``set(train_seeds) ∩ set(eval_seeds) == ∅`` — and is asserted at load time
so a misconfigured file fails loudly rather than leaking eval seeds into
training (which would defeat the held-out evaluation contract).

Pools live in two text files in ``configs/rl/``:

- ``seeds_eval.txt``  — pinned canary set. Iterate in order; never sample.
- ``seeds_train.txt`` — large pool. Sample one per training rollout.

Files use ``#``-prefixed comments and one integer per line.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_SEEDS_DIR = Path(__file__).parents[3] / "configs" / "rl"


def _load_seeds_file(path: Path) -> tuple[int, ...]:
    """Read a seed file: one int per line; ``#`` comments and blanks ignored."""
    if not path.exists():
        raise FileNotFoundError(f"Seeds file not found: {path}")
    seeds: list[int] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            seeds.append(int(line))
        except ValueError as exc:
            raise ValueError(f"{path}: expected one integer per line; got {line!r}") from exc
    return tuple(seeds)


@dataclass(frozen=True)
class SeedPool:
    """Train/eval seed split. Disjoint by construction (asserted).

    Usage::

        pool = SeedPool.load_default()
        rng = random.Random(0)
        for episode in range(N):
            seed = pool.sample(rng)
            env.reset(task=task, episode_seed=seed, system_prompt=prompt)
            ...
        # eval: pin the canary set
        for seed in pool.eval_seeds:
            env.reset(task=task, episode_seed=seed, system_prompt=prompt)
            ...
    """

    train_seeds: tuple[int, ...]
    eval_seeds: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.train_seeds:
            raise ValueError("Training seed pool is empty.")
        if not self.eval_seeds:
            raise ValueError("Eval seed pool is empty.")
        overlap = set(self.train_seeds) & set(self.eval_seeds)
        if overlap:
            sample = sorted(overlap)[:5]
            raise ValueError(
                f"train and eval seed pools overlap on {sample}... — "
                "training must NEVER see eval seeds (held-out invariant)."
            )
        # Soft duplicate check — duplicates inside a pool are pointless but
        # not fatal; warn via repr only.
        if len(set(self.train_seeds)) < len(self.train_seeds):
            # Acceptable; sampling still works. (No raise.)
            pass

    def sample(self, rng: random.Random) -> int:
        """Draw one seed from the training pool (uniform random)."""
        return rng.choice(self.train_seeds)

    @classmethod
    def load_default(cls) -> SeedPool:
        """Load from ``configs/rl/seeds_train.txt`` and ``seeds_eval.txt``."""
        return cls(
            train_seeds=_load_seeds_file(_DEFAULT_SEEDS_DIR / "seeds_train.txt"),
            eval_seeds=_load_seeds_file(_DEFAULT_SEEDS_DIR / "seeds_eval.txt"),
        )

    @classmethod
    def load(cls, train_path: Path, eval_path: Path) -> SeedPool:
        """Load from explicit file paths (useful for tests + custom pools)."""
        return cls(
            train_seeds=_load_seeds_file(train_path),
            eval_seeds=_load_seeds_file(eval_path),
        )
