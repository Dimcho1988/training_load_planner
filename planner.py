"""Daily microcycle generator."""

from __future__ import annotations

from typing import Dict, List, Mapping, Tuple

import pandas as pd

from config import BASELINE_DAILY_LOADS, DEFAULT_MODEL_PARAMS, RECOVERY_MULTIPLIERS, STRENGTH_COMPONENTS, ZONE_ORDER
from load_model import calculate_effective_day_load
from methods_library import FALLBACK_METHODS, select_best_method, render_method_text
from recovery_model import (
    apply_fatigue_spillover,
    recover_readiness_exponential,
    update_readiness_after_load,
)

DAYS_BG = ["Понеделник", "Вторник", "Сряда", "Четвъртък", "Петък", "Събота", "Неделя"]

# Daily distribution templates. Values per component sum to ~1.
DISTRIBUTION_TEMPLATES = {
    "Z1": [0.12, 0.08, 0.12, 0.12, 0.08, 0.35, 0.13],
    "Z2": [0.08, 0.15, 0.15, 0.20, 0.10, 0.25, 0.07],
    "Z3": [0.00, 0.45, 0.05, 0.10, 0.30, 0.10, 0.00],
    "Z4": [0.00, 0.25, 0.00, 0.15, 0.45, 0.15, 0.00],
    "Z5": [0.00, 0.15, 0.00, 0.05, 0.60, 0.20, 0.00],
    "Z6": [0.00, 0.20, 0.00, 0.10, 0.50, 0.20, 0.00],
    "OSI": [0.00, 0.00, 0.50, 0.00, 0.00, 0.30, 0.20],
    "SSI": [0.00, 0.35, 0.00, 0.00, 0.45, 0.20, 0.00],
}


def session_fraction_for_phase(phase_fraction: float, params: Mapping[str, float]) -> float:
    if phase_fraction < 1 / 3:
        lo = float(params.get("phase_1_key_session_min", 0.40))
        hi = float(params.get("phase_1_key_session_max", 0.50))
    elif phase_fraction < 2 / 3:
        lo = float(params.get("phase_2_key_session_min", 0.50))
        hi = float(params.get("phase_2_key_session_max", 0.60))
    else:
        lo = float(params.get("phase_3_key_session_min", 0.60))
        hi = float(params.get("phase_3_key_session_max", 0.70))
    return (lo + hi) / 2.0


def _normalize_template(values: List[float]) -> List[float]:
    total = sum(values)
    if total <= 0:
        return [1 / 7] * 7
    return [v / total for v in values]


def create_initial_daily_loads(week_plan_df: pd.DataFrame, component_ids: List[str]) -> List[Dict[str, float]]:
    daily = [{cid: 0.0 for cid in component_ids} for _ in range(7)]
    for _, row in week_plan_df.iterrows():
        cid = row["component_id"]
        weekly_load = float(row.get("real_weekly_load", 0.0))
        template = _normalize_template(DISTRIBUTION_TEMPLATES.get(cid, [1 / 7] * 7))
        for day_idx in range(7):
            daily[day_idx][cid] += weekly_load * template[day_idx]
    return daily


def adjust_load_for_readiness(load: float, readiness: float, params: Mapping[str, float]) -> Tuple[float, str]:
    key_thr = float(params.get("minimum_readiness_for_key_workout", 90.0))
    mod_thr = float(params.get("minimum_readiness_for_moderate_workout", 80.0))
    easy_thr = float(params.get("minimum_readiness_for_easy_workout", 60.0))
    if load <= 0:
        return 0.0, ""
    if readiness >= key_thr:
        return load, ""
    if readiness >= mod_thr:
        return load * 0.75, "Readiness 80–90%: натоварването е намалено до умерено."
    if readiness >= easy_thr:
        return load * 0.50, "Readiness 60–80%: разрешено е само леко/поддържащо натоварване."
    return load * 0.10, "Readiness <60%: значимото натоварване е почти премахнато."




def choose_daily_focus(
    adjusted_load: Mapping[str, float],
    week_plan: pd.DataFrame,
    readiness_before: Mapping[str, float],
    tref_weekly: Mapping[str, float] | None = None,
    trigger_percent_tref: float = 0.40,
) -> str:
    """Choose the practical main focus of the day.

    If a component exceeds the key-stimulus threshold, e.g. 40% of Tref, that
    component becomes the methodological focus. This follows the intended logic:
    a large single dose should trigger a concrete method from the database.
    If no component exceeds the threshold, the function falls back to a weighted
    score so that quality work is not hidden by large Z1/Z2 volume.
    """
    if not adjusted_load:
        return "Z1"

    tref_weekly = tref_weekly or {}
    meta = {}
    for _, r in week_plan.iterrows():
        cid = str(r.get("component_id"))
        meta[cid] = {
            "specificity": float(r.get("specificity", 1.0) or 1.0),
            "is_accent": bool(r.get("is_accent", False)),
        }

    total = sum(max(0.0, float(v)) for v in adjusted_load.values())
    if total <= 0:
        return "Z1"

    # Priority 1: components that exceed the key-session threshold.
    triggered = []
    for cid, raw_load in adjusted_load.items():
        load = max(0.0, float(raw_load))
        tref = max(1e-9, float(tref_weekly.get(cid, 0.0) or 0.0))
        frac = load / tref if tref > 0 else 0.0
        if frac >= float(trigger_percent_tref):
            spec = meta.get(cid, {}).get("specificity", 1.0)
            is_accent = meta.get(cid, {}).get("is_accent", False)
            readiness = float(readiness_before.get(cid, 100.0))
            # Prefer more specific and accent components, but keep readiness in the score.
            score = frac * (spec + 1.0) ** 1.25 * (1.5 if is_accent else 1.0) * (0.6 if readiness < 80 else 1.0)
            triggered.append((score, cid))
    if triggered:
        return sorted(triggered, reverse=True)[0][1]

    # Priority 2: no key dose; choose practical support focus.
    best_cid = "Z1"
    best_score = -1.0
    for cid, raw_load in adjusted_load.items():
        load = max(0.0, float(raw_load))
        if load <= 0:
            continue
        spec = meta.get(cid, {}).get("specificity", 1.0)
        is_accent = meta.get(cid, {}).get("is_accent", False)
        readiness = float(readiness_before.get(cid, 100.0))

        # Ignore tiny high-intensity crumbs unless they are meaningful.
        if cid in {"Z4", "Z5", "Z6", "SSI"} and load < 3.0 and total > 30:
            continue
        if cid == "Z3" and load < 5.0 and total > 30:
            continue

        load_share = load / total
        specificity_weight = (spec + 1.0) ** 1.25
        accent_weight = 1.6 if is_accent else 1.0
        readiness_weight = 0.35 if readiness < 60 else (0.70 if readiness < 80 else 1.0)
        base_zone_penalty = 0.75 if cid in {"Z1", "Z2"} else 1.0
        score = load_share * specificity_weight * accent_weight * readiness_weight * base_zone_penalty

        if score > best_score:
            best_score = score
            best_cid = cid
    return best_cid

def generate_microcycle(
    week_number: int,
    weekly_plan_df: pd.DataFrame,
    all_components_df: pd.DataFrame,
    params: Mapping[str, float] | None = None,
    methods: List[Mapping] | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """Generate a 7-day microcycle for a selected week.

    Returns daily plan table, readiness history table, warnings.
    """
    cfg = dict(DEFAULT_MODEL_PARAMS)
    if params:
        cfg.update(params)
    methods = methods or FALLBACK_METHODS

    week_plan = weekly_plan_df[weekly_plan_df["week"] == int(week_number)].copy()
    if week_plan.empty:
        return pd.DataFrame(), pd.DataFrame(), ["Няма седмичен план за избраната седмица."]

    component_ids = week_plan.sort_values("specificity")["component_id"].tolist()
    component_name = dict(zip(week_plan["component_id"], week_plan["component"]))
    phase_fraction = (int(week_number) - 1) / max(1, int(cfg.get("total_weeks", 24)) - 1)
    key_session_fraction = session_fraction_for_phase(phase_fraction, cfg)

    daily_loads = create_initial_daily_loads(week_plan, component_ids)

    # Limit key-day loads relative to Tref; redistribute a little to Z1 when too high.
    tref = {row["component_id"]: float(row.get("tref", 0.0)) for _, row in week_plan.iterrows()}
    for day_idx, day_load in enumerate(daily_loads):
        for cid in component_ids:
            cap = max(0.0, tref.get(cid, 0.0) * key_session_fraction)
            if cap > 0 and day_load.get(cid, 0.0) > cap and cid not in {"Z1", "Z2"}:
                excess = day_load[cid] - cap
                day_load[cid] = cap
                if "Z1" in day_load:
                    day_load["Z1"] += excess * 0.50

    readiness = {cid: 100.0 for cid in component_ids}
    k_values = {cid: 1.2 for cid in component_ids}
    warnings: List[str] = []
    day_rows: List[Dict] = []
    readiness_rows: List[Dict] = []

    chronic_daily = {row["component_id"]: float(row.get("chronic_40_eff_daily", 1.0)) for _, row in week_plan.iterrows()}
    recovery_multiplier = {cid: float(RECOVERY_MULTIPLIERS.get(cid, 1.0)) for cid in component_ids}

    for day_idx in range(7):
        # Recover one day before the next training stimulus, except day 1 starts fresh.
        if day_idx > 0:
            for cid in component_ids:
                readiness[cid] = recover_readiness_exponential(readiness[cid], k_values.get(cid, 1.2), days=1.0)

        readiness_before = {cid: readiness.get(cid, 100.0) for cid in component_ids}
        original_load = dict(daily_loads[day_idx])
        adjusted_load = dict(original_load)
        adjustment_notes = []

        for cid, load in list(original_load.items()):
            new_load, note = adjust_load_for_readiness(load, readiness_before.get(cid, 100.0), cfg)
            adjusted_load[cid] = new_load
            if note:
                adjustment_notes.append(f"{cid}: {note}")

        effective_day = calculate_effective_day_load(
            adjusted_load,
            baseline_daily_loads=BASELINE_DAILY_LOADS,
            tref_weekly=tref,
            spill_threshold=float(cfg.get("spill_threshold", 0.50)),
            spill_down_percent=float(cfg.get("spill_down_percent", 0.20)),
            spill_up_percent=float(cfg.get("spill_up_percent", 0.10)),
            include_base=True,
        )

        # Apply readiness drop component by component.
        readiness_after = dict(readiness_before)
        for cid in component_ids:
            after, rec_days, k = update_readiness_after_load(
                readiness_before=readiness_before.get(cid, 100.0),
                daily_effective_load=effective_day.get(cid, 0.0),
                tref_weekly=tref.get(cid, 1.0),
                chronic_40_effective_daily_load=chronic_daily.get(cid, 1.0),
                recovery_multiplier=recovery_multiplier.get(cid, 1.0),
                drop_sensitivity=float(cfg.get("drop_sensitivity", 70.0)),
            )
            readiness_after[cid] = after
            k_values[cid] = k

        readiness_after = apply_fatigue_spillover(
            readiness_after,
            adjusted_load,
            tref,
            spill_threshold=float(cfg.get("spill_threshold", 0.50)),
            spill_down_percent=float(cfg.get("spill_down_percent", 0.20)),
            spill_up_percent=float(cfg.get("spill_up_percent", 0.10)),
            drop_sensitivity=float(cfg.get("drop_sensitivity", 70.0)),
        )
        readiness = readiness_after

        # Determine practical focus and select a concrete method from the database.
        dominant = choose_daily_focus(
            adjusted_load,
            week_plan,
            readiness_before,
            tref_weekly=tref,
            trigger_percent_tref=float(cfg.get("method_trigger_percent_tref", 0.40)),
        )
        method = select_best_method(
            dominant,
            phase_fraction,
            readiness_before.get(dominant, 100.0),
            methods,
            target_loads=adjusted_load,
        )
        rendered_method_text = render_method_text(
            method,
            adjusted_load,
            tref_weekly=tref,
            phase_fraction=phase_fraction,
            key_threshold=float(cfg.get("method_trigger_percent_tref", 0.40)),
        )
        accent_components = week_plan[week_plan["is_accent"]]["component_id"].tolist()

        if adjustment_notes:
            warnings.append(f"Седмица {week_number}, ден {day_idx + 1}: " + " | ".join(adjustment_notes))

        row = {
            "week": int(week_number),
            "day": day_idx + 1,
            "day_name": DAYS_BG[day_idx],
            "main_focus": dominant,
            "method": method.get("title", f"Тренировка {dominant}"),
            "method_id": method.get("method_id", ""),
            "session_description": rendered_method_text,
            "method_notes": rendered_method_text,
            "accent_components": ", ".join(accent_components),
            "readiness_before_main": round(readiness_before.get(dominant, 100.0), 1),
            "readiness_after_main": round(readiness_after.get(dominant, 100.0), 1),
        }
        total_real = 0.0
        for cid in component_ids:
            val = round(adjusted_load.get(cid, 0.0), 1)
            row[cid] = val
            total_real += val
            readiness_rows.append({
                "week": int(week_number),
                "day": day_idx + 1,
                "day_name": DAYS_BG[day_idx],
                "component_id": cid,
                "component": component_name.get(cid, cid),
                "readiness_before": round(readiness_before.get(cid, 100.0), 2),
                "readiness_after": round(readiness_after.get(cid, 100.0), 2),
                "real_day_load": round(adjusted_load.get(cid, 0.0), 2),
                "effective_day_load": round(effective_day.get(cid, 0.0), 2),
            })
        row["total_real_min"] = round(total_real, 1)
        row["warnings"] = " | ".join(adjustment_notes)
        day_rows.append(row)

    daily_plan_df = pd.DataFrame(day_rows)
    readiness_df = pd.DataFrame(readiness_rows)
    return daily_plan_df, readiness_df, warnings


def compare_weekly_target_vs_plan(week_plan_df: pd.DataFrame, daily_plan_df: pd.DataFrame) -> pd.DataFrame:
    if week_plan_df.empty or daily_plan_df.empty:
        return pd.DataFrame()
    component_ids = week_plan_df["component_id"].tolist()
    rows = []
    for cid in component_ids:
        planned = float(daily_plan_df[cid].sum()) if cid in daily_plan_df.columns else 0.0
        target = float(week_plan_df.loc[week_plan_df["component_id"] == cid, "real_weekly_load"].iloc[0])
        diff = planned - target
        rows.append({
            "component_id": cid,
            "target_weekly_load": round(target, 1),
            "microcycle_planned_load": round(planned, 1),
            "difference": round(diff, 1),
            "difference_percent": round((diff / target * 100) if target > 0 else 0.0, 1),
        })
    return pd.DataFrame(rows)
