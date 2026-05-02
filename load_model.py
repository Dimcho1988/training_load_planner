"""Weekly load dynamics model.

This module generates the first model: continuous wave dynamics of weekly load,
7/40 indices, effective physiological load, cascade, spillover and Tref.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Mapping, Tuple

import pandas as pd

from config import (
    BASELINE_DAILY_LOADS,
    CASCADE_COEFFICIENTS,
    COMPONENTS,
    DEFAULT_MODEL_PARAMS,
    STRESS_ZONES,
    STRENGTH_COMPONENTS,
    ZONE_ORDER,
)

EPS = 1e-9


def classify_stress(value: float) -> str:
    for name, (lo, hi) in STRESS_ZONES.items():
        if lo <= float(value) < hi:
            return name
    return "Неопределено"


def validate_components(components_df: pd.DataFrame) -> pd.DataFrame:
    required = {"id", "name", "base_weekly_load", "group", "specificity", "enabled"}
    missing = required - set(components_df.columns)
    if missing:
        raise ValueError(f"Липсват колони в компонентите: {sorted(missing)}")

    df = components_df.copy()
    df["id"] = df["id"].astype(str).str.strip()
    df["name"] = df["name"].astype(str).str.strip()
    df["group"] = df["group"].astype(str).str.strip()
    df["base_weekly_load"] = pd.to_numeric(df["base_weekly_load"], errors="coerce").fillna(0.0)
    df["specificity"] = pd.to_numeric(df["specificity"], errors="coerce").fillna(1).astype(int)
    df["enabled"] = df["enabled"].astype(bool)

    df = df[df["enabled"]].copy()
    if df.empty:
        raise ValueError("Трябва да има поне един активен компонент.")
    if (df["base_weekly_load"] < 0).any():
        raise ValueError("base_weekly_load трябва да бъде >= 0.")

    # Ensure IDs are unique.
    if df["id"].duplicated().any():
        raise ValueError("Компонентните id трябва да бъдат уникални.")

    return df.sort_values("specificity").reset_index(drop=True)


def scale_components_to_total_volume(components_df: pd.DataFrame, total_minutes: float) -> pd.DataFrame:
    """Scale base weekly component loads proportionally to a total weekly volume."""
    df = validate_components(components_df)
    current = float(df["base_weekly_load"].sum())
    if current <= 0:
        df["base_weekly_load"] = total_minutes / max(1, len(df))
    else:
        df["base_weekly_load"] = df["base_weekly_load"] * (float(total_minutes) / current)
    return df


def global_progression_factor(
    week: int,
    total_weeks: int,
    monthly_growth_rate: float = 0.04,
    peak_fraction: float = 0.50,
    post_peak_reduction: float = 0.15,
) -> float:
    """General volume trend: grows until peak_fraction, then slowly declines."""
    weeks_per_month = 4.345
    peak_week = max(1, round(total_weeks * peak_fraction))

    if week <= peak_week:
        return (1.0 + monthly_growth_rate) ** ((week - 1) / weeks_per_month)

    peak_factor = (1.0 + monthly_growth_rate) ** ((peak_week - 1) / weeks_per_month)
    decline_fraction = (week - peak_week) / max(1, total_weeks - peak_week)
    return max(0.1, peak_factor * (1.0 - post_peak_reduction * decline_fraction))


def mesocycle_week_type(week: int, mesocycle_len: int) -> str:
    position = ((week - 1) % mesocycle_len) + 1
    if position == 1:
        return "Вработваща"
    if mesocycle_len >= 4 and position == mesocycle_len:
        return "Възстановителна"
    if mesocycle_len == 3 and position == 3:
        return "Възстановителна"
    return "Развиваща"


def accent_stress_for_week(week: int, params: Mapping[str, float]) -> float:
    mesocycle_len = int(params.get("mesocycle_len", 4))
    position = ((week - 1) % mesocycle_len) + 1
    if position == 1:
        return float(params.get("intro_stress", 1.20))
    if position == 2:
        return float(params.get("dev1_stress", 1.35))
    if position == 3 and mesocycle_len >= 4:
        return float(params.get("dev2_stress", 1.45))
    if position == mesocycle_len:
        return float(params.get("recovery_stress", 0.75))
    return float(params.get("dev1_stress", 1.35))


def component_phase_envelope(
    week: int,
    weeks: int,
    specificity_rank: int,
    max_specificity: int,
    amplitude: float,
) -> float:
    """Smoothly moves emphasis from general to specific components.

    More general components peak earlier; more specific components peak later.
    """
    if weeks <= 1 or max_specificity <= 1:
        return 1.0

    target_week = 1 + ((specificity_rank - 1) / (max_specificity - 1)) * (weeks - 1)
    sigma = max(1.5, weeks / 5)
    gaussian = math.exp(-0.5 * ((week - target_week) / sigma) ** 2)
    sinus = 0.5 + 0.5 * math.sin(2 * math.pi * (week - 1) / 4)
    return 1.0 + amplitude * (0.65 * gaussian + 0.35 * sinus - 0.35)


def select_accents_for_mesocycle(
    components_df: pd.DataFrame,
    meso_index: int,
    total_mesocycles: int,
    max_accents: int,
) -> List[str]:
    ordered = components_df.sort_values("specificity").reset_index(drop=True)
    n_components = len(ordered)
    max_accents = max(1, min(max_accents, n_components))

    if total_mesocycles <= 1:
        center = min(n_components - 1, max_accents // 2)
    else:
        center = round((meso_index / (total_mesocycles - 1)) * (n_components - 1))

    half = max_accents // 2
    start = max(0, center - half)
    end = start + max_accents
    if end > n_components:
        end = n_components
        start = max(0, end - max_accents)
    return ordered.iloc[start:end]["id"].tolist()


def event_weeks(events_df: pd.DataFrame, event_type: str) -> set[int]:
    if events_df is None or events_df.empty:
        return set()
    if "event_type" not in events_df.columns:
        return set()
    rows = events_df[events_df["event_type"] == event_type]
    weeks = set()
    for _, row in rows.iterrows():
        try:
            start_week = int(row.get("start_week", 0))
            duration_days = int(row.get("duration_days", 1))
            duration_weeks = max(1, math.ceil(duration_days / 7))
        except Exception:
            continue
        for offset in range(duration_weeks):
            weeks.add(start_week + offset)
    return weeks


def main_race_week(events_df: pd.DataFrame, default_week: int) -> int:
    if events_df is not None and not events_df.empty and "event_type" in events_df.columns:
        rows = events_df[events_df["event_type"] == "main_race"]
        if not rows.empty:
            return int(rows.iloc[0].get("start_week", default_week))
    return default_week


def is_high_intensity_component(component_id: str) -> bool:
    return component_id in {"Z4", "Z5", "Z6", "SSI"}


def is_strength_component(component_id: str) -> bool:
    return component_id in set(STRENGTH_COMPONENTS)


def apply_event_modifiers(
    target_index: float,
    component_id: str,
    week: int,
    is_accent: bool,
    events_df: pd.DataFrame,
    params: Mapping[str, float],
) -> Tuple[float, str]:
    """Modify target index based on camps, control races and main race taper."""
    note = ""
    camp_weeks = event_weeks(events_df, "camp")
    control_weeks = event_weeks(events_df, "control_race")
    recovery_weeks = event_weeks(events_df, "recovery_block")
    race_week = main_race_week(events_df, int(params.get("total_weeks", 24)))

    if week in camp_weeks:
        target_index *= 1.0 + float(params.get("camp_load_bonus", 0.15))
        if is_accent:
            target_index *= 1.0 + float(params.get("camp_accent_bonus", 0.10))
        note += "Лагер: разрешен по-висок изграждащ товар. "

    if (week - 1) in camp_weeks and week not in camp_weeks:
        target_index *= 1.0 - float(params.get("post_camp_reduction", 0.25))
        note += "След лагер: възстановителна редукция. "

    if week in control_weeks:
        reduction = float(params.get("control_race_reduction", 0.10))
        preservation = float(params.get("control_race_intensity_preservation", 0.85))
        if is_high_intensity_component(component_id):
            target_index *= max(1.0 - reduction, preservation)
            note += "Контролен старт: запазен кратък интензивен стимул. "
        else:
            target_index *= 1.0 - reduction
            note += "Контролен старт: леко сваляне на обема. "

    if week in recovery_weeks:
        target_index *= 0.75
        note += "Ръчен възстановителен блок. "

    # Taper before main race.
    taper_len = int(params.get("taper_length_weeks", 2))
    for step in range(taper_len, 0, -1):
        taper_week = race_week - step + 1
        if week == taper_week:
            if step == taper_len:
                reduction = float(params.get("taper_reduction_week_1", 0.25))
            else:
                reduction = float(params.get("taper_reduction_week_2", 0.45))
            if is_strength_component(component_id):
                reduction = max(reduction, float(params.get("strength_taper_reduction", 0.60)))
            if is_high_intensity_component(component_id):
                preservation = float(params.get("high_intensity_preservation", 0.70))
                target_index *= max(1.0 - reduction, preservation)
                note += "Тейпър: обемът пада, но интензивността се запазва частично. "
            else:
                target_index *= 1.0 - reduction
                note += "Тейпър: редукция на обема. "

    return target_index, note.strip()


def calculate_effective_day_load(
    real_day_loads: Mapping[str, float],
    baseline_daily_loads: Mapping[str, float] | None = None,
    cascade_coefficients: Mapping[int, float] | None = None,
    tref_weekly: Mapping[str, float] | None = None,
    spill_threshold: float = 0.50,
    spill_percent: float = 0.20,
    include_base: bool = True,
) -> Dict[str, float]:
    """Calculate effective physiologic daily load.

    It adds virtual baseline, cascade from higher to lower zones, and spillover to
    adjacent zones when daily real load exceeds a fraction of Tref.
    """
    baseline = dict(BASELINE_DAILY_LOADS if baseline_daily_loads is None else baseline_daily_loads)
    cascade = dict(CASCADE_COEFFICIENTS if cascade_coefficients is None else cascade_coefficients)
    component_ids = set(real_day_loads.keys()) | set(baseline.keys())
    effective = {cid: 0.0 for cid in component_ids}

    if include_base:
        for cid, value in baseline.items():
            if cid in component_ids:
                effective[cid] = effective.get(cid, 0.0) + float(value)

    for cid, value in real_day_loads.items():
        effective[cid] = effective.get(cid, 0.0) + max(0.0, float(value))

    # Cascade only among Z1-Z6.
    for source_idx, source_id in enumerate(ZONE_ORDER):
        source_load = max(0.0, float(real_day_loads.get(source_id, 0.0)))
        if source_load <= 0:
            continue
        for target_idx in range(source_idx):
            target_id = ZONE_ORDER[target_idx]
            distance = source_idx - target_idx
            coeff = float(cascade.get(distance, 0.0))
            if coeff > 0:
                effective[target_id] = effective.get(target_id, 0.0) + source_load * coeff

    # Spillover to adjacent zones if very large daily load.
    if tref_weekly:
        for idx, cid in enumerate(ZONE_ORDER):
            daily_load = max(0.0, float(real_day_loads.get(cid, 0.0)))
            tref = max(EPS, float(tref_weekly.get(cid, 0.0)))
            threshold_load = spill_threshold * tref
            if daily_load > threshold_load:
                excess = daily_load - threshold_load
                spill = excess * spill_percent
                if idx > 0:
                    effective[ZONE_ORDER[idx - 1]] = effective.get(ZONE_ORDER[idx - 1], 0.0) + spill
                if idx < len(ZONE_ORDER) - 1:
                    effective[ZONE_ORDER[idx + 1]] = effective.get(ZONE_ORDER[idx + 1], 0.0) + spill

    return {cid: round(max(0.0, val), 3) for cid, val in effective.items()}


def calculate_effective_weekly_load(
    real_weekly_loads: Mapping[str, float],
    baseline_daily_loads: Mapping[str, float] | None = None,
    cascade_coefficients: Mapping[int, float] | None = None,
    tref_weekly: Mapping[str, float] | None = None,
    spill_threshold: float = 0.50,
    spill_percent: float = 0.20,
) -> Dict[str, float]:
    daily_real = {cid: float(val) / 7.0 for cid, val in real_weekly_loads.items()}
    eff_daily = calculate_effective_day_load(
        daily_real,
        baseline_daily_loads=baseline_daily_loads,
        cascade_coefficients=cascade_coefficients,
        tref_weekly=tref_weekly,
        spill_threshold=spill_threshold,
        spill_percent=spill_percent,
        include_base=True,
    )
    return {cid: round(val * 7.0, 3) for cid, val in eff_daily.items()}


def _expand_daily_effective_history(weekly_effective: pd.DataFrame, component_ids: Iterable[str]) -> pd.DataFrame:
    rows = []
    for _, row in weekly_effective.iterrows():
        week = int(row["week"])
        for day_in_week in range(1, 8):
            day_index = (week - 1) * 7 + day_in_week
            for cid in component_ids:
                rows.append({
                    "day_index": day_index,
                    "week": week,
                    "component_id": cid,
                    "effective_load": float(row.get(cid, 0.0)) / 7.0,
                })
    return pd.DataFrame(rows)


def calculate_rolling_7_40(weekly_effective: pd.DataFrame, component_ids: List[str]) -> pd.DataFrame:
    daily = _expand_daily_effective_history(weekly_effective, component_ids)
    rows = []
    for week in sorted(weekly_effective["week"].unique()):
        end_day = int(week) * 7
        for cid in component_ids:
            cdf = daily[(daily["component_id"] == cid) & (daily["day_index"] <= end_day)].copy()
            last7 = cdf[cdf["day_index"] > end_day - 7]["effective_load"]
            last40 = cdf[cdf["day_index"] > end_day - 40]["effective_load"]
            acute = float(last7.mean()) if not last7.empty else 0.0
            chronic = float(last40.mean()) if not last40.empty else acute
            idx = acute / max(EPS, chronic)
            rows.append({
                "week": int(week),
                "component_id": cid,
                "acute_7_eff_daily": acute,
                "chronic_40_eff_daily": chronic,
                "computed_7_40_index": idx,
                "tref": chronic * 7.0,
            })
    return pd.DataFrame(rows)


def generate_weekly_plan(
    components_df: pd.DataFrame,
    events_df: pd.DataFrame,
    params: Mapping[str, float] | None = None,
    baseline_daily_loads: Mapping[str, float] | None = None,
    cascade_coefficients: Mapping[int, float] | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Generate weekly plan and weekly summary.

    Returns:
        plan_df: long table by week and component.
        summary_df: one row per week.
    """
    cfg = dict(DEFAULT_MODEL_PARAMS)
    if params:
        cfg.update(params)
    baseline = dict(BASELINE_DAILY_LOADS if baseline_daily_loads is None else baseline_daily_loads)
    cascade = dict(CASCADE_COEFFICIENTS if cascade_coefficients is None else cascade_coefficients)

    total_weeks = int(cfg.get("total_weeks", 24))
    mesocycle_len = int(cfg.get("mesocycle_len", 4))
    max_accents = int(cfg.get("max_accents", 3))
    risk_limit = float(cfg.get("risk_limit", 1.60))

    components = validate_components(components_df)
    component_ids = components["id"].tolist()
    total_mesocycles = math.ceil(total_weeks / mesocycle_len)
    max_specificity = int(components["specificity"].max())

    accents_by_meso = {
        m: select_accents_for_mesocycle(components, m, total_mesocycles, max_accents)
        for m in range(total_mesocycles)
    }

    # Build weekly real load first.
    rows = []
    weekly_effective_records = []
    previous_tref = None

    for week in range(1, total_weeks + 1):
        meso_index = (week - 1) // mesocycle_len
        week_type = mesocycle_week_type(week, mesocycle_len)
        accents = accents_by_meso[meso_index]
        global_factor = global_progression_factor(
            week=week,
            total_weeks=total_weeks,
            monthly_growth_rate=float(cfg.get("monthly_progression_rate", 0.04)),
            peak_fraction=float(cfg.get("peak_fraction", 0.50)),
            post_peak_reduction=float(cfg.get("post_peak_reduction", 0.15)),
        )

        week_real_loads: Dict[str, float] = {}
        temp_rows = []
        for _, comp in components.iterrows():
            cid = comp["id"]
            is_accent = cid in accents
            if is_accent:
                base_stress = accent_stress_for_week(week, cfg)
            elif week_type == "Възстановителна":
                base_stress = float(cfg.get("recovery_stress", 0.75))
            else:
                base_stress = float(cfg.get("maintenance_stress", 0.98))

            envelope = component_phase_envelope(
                week=week,
                weeks=total_weeks,
                specificity_rank=int(comp["specificity"]),
                max_specificity=max_specificity,
                amplitude=float(cfg.get("wave_amplitude", 0.25)),
            )
            target_index = base_stress * global_factor * envelope

            if not is_accent and week_type != "Възстановителна":
                target_index = min(target_index, 1.10)
            if week_type == "Възстановителна":
                target_index = min(target_index, 0.90)

            target_index, event_note = apply_event_modifiers(
                target_index=target_index,
                component_id=cid,
                week=week,
                is_accent=is_accent,
                events_df=events_df,
                params=cfg,
            )
            target_index = min(max(0.0, target_index), risk_limit)
            real_weekly_load = float(comp["base_weekly_load"]) * target_index
            week_real_loads[cid] = real_weekly_load

            if event_note:
                note = event_note
            elif is_accent and week_type != "Възстановителна":
                note = "Планиран развиващ акцент."
            elif week_type == "Възстановителна":
                note = "Възстановителна вълна: целево сваляне на товара."
            else:
                note = "Поддържащ компонент."

            temp_rows.append({
                "week": week,
                "mesocycle": meso_index + 1,
                "week_type": week_type,
                "component_id": cid,
                "component": comp["name"],
                "group": comp["group"],
                "specificity": int(comp["specificity"]),
                "is_accent": bool(is_accent),
                "status": "Акцент" if is_accent else ("Разтоварване" if target_index < 0.85 else "Поддържане"),
                "target_7_40_index": round(target_index, 3),
                "target_index_zone": classify_stress(target_index),
                "base_weekly_load": round(float(comp["base_weekly_load"]), 2),
                "real_weekly_load": round(real_weekly_load, 2),
                "global_progression_factor": round(global_factor, 3),
                "component_envelope": round(envelope, 3),
                "note": note,
            })

        eff_weekly = calculate_effective_weekly_load(
            week_real_loads,
            baseline_daily_loads=baseline,
            cascade_coefficients=cascade,
            tref_weekly=previous_tref,
            spill_threshold=float(cfg.get("spill_threshold", 0.50)),
            spill_percent=float(cfg.get("spill_percent", 0.20)),
        )
        previous_tref = eff_weekly
        weekly_effective_records.append({"week": week, **{cid: eff_weekly.get(cid, 0.0) for cid in component_ids}})
        for r in temp_rows:
            r["effective_weekly_load"] = round(eff_weekly.get(r["component_id"], 0.0), 2)
            rows.append(r)

    plan_df = pd.DataFrame(rows)
    weekly_eff_df = pd.DataFrame(weekly_effective_records)
    rolling = calculate_rolling_7_40(weekly_eff_df, component_ids)
    plan_df = plan_df.merge(rolling, on=["week", "component_id"], how="left")
    plan_df["computed_7_40_index"] = plan_df["computed_7_40_index"].round(3)
    plan_df["acute_7_eff_daily"] = plan_df["acute_7_eff_daily"].round(2)
    plan_df["chronic_40_eff_daily"] = plan_df["chronic_40_eff_daily"].round(2)
    plan_df["tref"] = plan_df["tref"].round(2)

    summary_df = (
        plan_df.groupby(["week", "mesocycle", "week_type"], as_index=False)
        .agg(
            total_real_load=("real_weekly_load", "sum"),
            total_effective_load=("effective_weekly_load", "sum"),
            mean_target_index=("target_7_40_index", "mean"),
            max_target_index=("target_7_40_index", "max"),
            mean_computed_7_40=("computed_7_40_index", "mean"),
            accent_count=("is_accent", "sum"),
        )
        .round(2)
    )
    return plan_df, summary_df


def diagnostic_checks(plan_df: pd.DataFrame, summary_df: pd.DataFrame, params: Mapping[str, float]) -> List[str]:
    issues: List[str] = []
    risk_limit = float(params.get("risk_limit", 1.60))
    max_accents = int(params.get("max_accents", 3))

    if (plan_df["target_7_40_index"] >= risk_limit).any():
        issues.append(f"Има компоненти, достигнали горната рискова граница {risk_limit:.2f}.")
    if (summary_df["accent_count"] > max_accents).any():
        issues.append("Има седмици с повече акценти от позволеното.")

    recovery = plan_df[plan_df["week_type"] == "Възстановителна"]
    if not recovery.empty and (recovery["target_7_40_index"] > 0.95).any():
        issues.append("Някои възстановителни седмици не свалят достатъчно индекса.")

    hidden = plan_df[(~plan_df["is_accent"]) & (plan_df["target_7_40_index"] > 1.12)]
    if not hidden.empty:
        issues.append("Има неакцентирани компоненти, които преминават в развиваща зона.")

    return issues
