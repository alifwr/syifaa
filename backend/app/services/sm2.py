"""Spaced-repetition scheduler — SM-2 variant.

Inputs:
    ease         : ease factor, clamped to [1.3, 3.0].
    interval_days: 0 for first pass, otherwise prior interval.
    quality      : 0.0..1.0 from the Feynman grader.

Output:
    (new_ease, new_interval_days)

We map quality to SuperMemo's 0..5 grade by `q5 = round(quality * 5)`.
A 0..1 score below 0.6 (q5 < 3) is treated as a "lapse": interval
resets to 1 day and ease shrinks. Otherwise the canonical SM-2
schedule applies: 1 → 6 → prior_interval * NEW_ease (Wozniak: the
just-updated easiness factor multiplies the prior interval).
"""
EASE_MIN = 1.3
EASE_MAX = 3.0


def sm2_update(*, ease: float, interval_days: int, quality: float) -> tuple[float, int]:
    q = max(0.0, min(1.0, quality))
    q5 = round(q * 5)

    if q5 < 3:
        new_ease = max(EASE_MIN, ease - 0.20)
        new_interval = 1
        return new_ease, new_interval

    delta = 0.1 - (5 - q5) * (0.08 + (5 - q5) * 0.02)
    new_ease = max(EASE_MIN, min(EASE_MAX, ease + delta))

    if interval_days <= 0:
        new_interval = 1
    elif interval_days == 1:
        new_interval = 6
    else:
        new_interval = round(interval_days * new_ease)

    return new_ease, new_interval
