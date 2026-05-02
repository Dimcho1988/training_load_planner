"""Recovery/readiness model for daily planning."""

from __future__ import annotations

import math
from typing import Dict, Mapping

from config import RECOVERY_MULTIPLIERS, ZONE_ORDER

EPS = 1e-9


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def recover_readiness_exponential(R0: float, k: float, days: float = 1.0) -> float:
    """Saturating exponential recovery curve.

    R(t) = 100 - (100 - R0) * exp(-k*t)
    """
    R0 = clamp(R0)
    k = max(0.0, float(k))
    days = max(0.0, float(days))
    return clamp(100.0 - (100.0 - R0) * math.exp(-k * days))


def estimate_recovery_days(
    daily_effective_load: float,
    chronic_40_effective_daily_load: float,
    recovery_multiplier: float = 1.0,
) -> float:
    chronic = max(EPS, float(chronic_40_effective_daily_load))
    return max(0.05, (float(daily_effective_load) / chronic) * float(recovery_multiplier))


def calculate_dynamic_k(R0: float, estimated_recovery_days: float, target_readiness: float = 95.0, default_k: float = 1.2) -> float:
    """Choose k so readiness reaches target_readiness at estimated_recovery_days."""
    R0 = clamp(R0)
    target = clamp(target_readiness, 1.0, 99.0)
    if estimated_recovery_days <= 0 or R0 >= target:
        return default_k
    denominator = max(EPS, 100.0 - R0)
    numerator = max(EPS, 100.0 - target)
    return max(0.05, -math.log(numerator / denominator) / max(EPS, estimated_recovery_days))


def update_readiness_after_load(
    readiness_before: float,
    daily_effective_load: float,
    tref_weekly: float,
    chronic_40_effective_daily_load: float,
    recovery_multiplier: float = 1.0,
    drop_sensitivity: float = 70.0,
) -> tuple[float, float, float]:
    """Apply fatigue drop and return readiness_after, recovery_days, dynamic_k."""
    tref = max(EPS, float(tref_weekly))
    load_fraction = max(0.0, float(daily_effective_load)) / tref
    readiness_drop = load_fraction * float(drop_sensitivity)
    readiness_after = clamp(float(readiness_before) - readiness_drop)
    rec_days = estimate_recovery_days(
        daily_effective_load=daily_effective_load,
        chronic_40_effective_daily_load=chronic_40_effective_daily_load,
        recovery_multiplier=recovery_multiplier,
    )
    k = calculate_dynamic_k(readiness_after, rec_days)
    return readiness_after, rec_days, k


def apply_fatigue_spillover(
    readiness: Dict[str, float],
    real_day_loads: Mapping[str, float],
    tref_weekly: Mapping[str, float],
    spill_threshold: float = 0.50,
    spill_percent: float = 0.20,
    drop_sensitivity: float = 70.0,
) -> Dict[str, float]:
    """Additional fatigue spillover to adjacent zones after very large daily load."""
    updated = dict(readiness)
    for idx, cid in enumerate(ZONE_ORDER):
        load = max(0.0, float(real_day_loads.get(cid, 0.0)))
        tref = max(EPS, float(tref_weekly.get(cid, 0.0)))
        threshold = float(spill_threshold) * tref
        if load <= threshold:
            continue
        excess = load - threshold
        # Convert excess to additional readiness drop in adjacent zones.
        spill_load = excess * float(spill_percent)
        spill_drop = (spill_load / tref) * float(drop_sensitivity)
        if idx > 0:
            target = ZONE_ORDER[idx - 1]
            updated[target] = clamp(updated.get(target, 100.0) - spill_drop)
        if idx < len(ZONE_ORDER) - 1:
            target = ZONE_ORDER[idx + 1]
            updated[target] = clamp(updated.get(target, 100.0) - spill_drop)
    return updated
