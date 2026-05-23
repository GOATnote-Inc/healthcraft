"""Tests for healthcraft.rl.seed_pool (PR-C / WS-4)."""

from __future__ import annotations

import random

import pytest

from healthcraft.rl.seed_pool import SeedPool


def test_default_pool_loads_with_no_overlap():
    pool = SeedPool.load_default()
    overlap = set(pool.train_seeds) & set(pool.eval_seeds)
    assert overlap == set()


def test_default_pool_sizes():
    pool = SeedPool.load_default()
    assert len(pool.train_seeds) == 5000
    assert len(pool.eval_seeds) == 50


def test_default_pool_pins_v8_baseline_seed():
    """seed=42 (V8 evaluation baseline) must be in eval; never in train."""
    pool = SeedPool.load_default()
    assert 42 in pool.eval_seeds
    assert 42 not in pool.train_seeds


def test_overlap_rejected_by_construction():
    with pytest.raises(ValueError, match="overlap"):
        SeedPool(train_seeds=(1, 2, 3), eval_seeds=(2, 99, 100))


def test_empty_train_rejected():
    with pytest.raises(ValueError, match="Training"):
        SeedPool(train_seeds=(), eval_seeds=(42,))


def test_empty_eval_rejected():
    with pytest.raises(ValueError, match="Eval"):
        SeedPool(train_seeds=(1, 2), eval_seeds=())


def test_sample_reproducible_with_seeded_rng():
    pool = SeedPool(train_seeds=tuple(range(1, 101)), eval_seeds=(1000,))
    rng_a = random.Random(0)
    rng_b = random.Random(0)
    a = [pool.sample(rng_a) for _ in range(10)]
    b = [pool.sample(rng_b) for _ in range(10)]
    assert a == b


def test_sample_diverges_across_distinct_rngs():
    pool = SeedPool(train_seeds=tuple(range(1, 1001)), eval_seeds=(1000000,))
    a = [pool.sample(random.Random(1)) for _ in range(20)]
    b = [pool.sample(random.Random(2)) for _ in range(20)]
    assert a != b


def test_load_from_custom_paths(tmp_path):
    train_f = tmp_path / "t.txt"
    eval_f = tmp_path / "e.txt"
    train_f.write_text("# header\n1\n2\n3\n", encoding="utf-8")
    eval_f.write_text("100\n", encoding="utf-8")
    pool = SeedPool.load(train_f, eval_f)
    assert pool.train_seeds == (1, 2, 3)
    assert pool.eval_seeds == (100,)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        SeedPool.load(tmp_path / "no-such-train.txt", tmp_path / "no-such-eval.txt")


def test_non_integer_line_raises(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("1\nnot-an-int\n", encoding="utf-8")
    good = tmp_path / "good.txt"
    good.write_text("100\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected one integer"):
        SeedPool.load(bad, good)


def test_blank_and_comment_lines_ignored(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("# comment\n\n42\n  \n# another\n100\n", encoding="utf-8")
    good = tmp_path / "g.txt"
    good.write_text("999\n", encoding="utf-8")
    pool = SeedPool.load(f, good)
    assert pool.train_seeds == (42, 100)
