import pytest
from app.services.sm2 import sm2_update


def test_first_pass_high_quality_sets_one_day():
    ease, interval = sm2_update(ease=2.5, interval_days=0, quality=1.0)
    assert interval == 1
    assert ease >= 2.5


def test_second_pass_high_quality_sets_six_days():
    _, interval = sm2_update(ease=2.5, interval_days=1, quality=1.0)
    assert interval == 6


def test_third_pass_multiplies_by_ease():
    _, interval = sm2_update(ease=2.5, interval_days=6, quality=1.0)
    assert interval == 15


def test_low_quality_resets_streak():
    _, interval = sm2_update(ease=2.5, interval_days=10, quality=0.3)
    assert interval == 1


def test_low_quality_decreases_ease():
    ease, _ = sm2_update(ease=2.5, interval_days=10, quality=0.3)
    assert ease < 2.5


def test_ease_clamped_min():
    ease, _ = sm2_update(ease=1.4, interval_days=10, quality=0.0)
    assert ease >= 1.3


def test_ease_clamped_max():
    ease, _ = sm2_update(ease=2.9, interval_days=10, quality=1.0)
    assert ease <= 3.0


@pytest.mark.parametrize("q", [-0.5, 1.5, 999.0, -10])
def test_quality_clamped_to_unit_interval(q: float):
    sm2_update(ease=2.5, interval_days=0, quality=q)  # must not raise
