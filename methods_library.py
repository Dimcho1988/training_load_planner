"""Training method library and selection utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping

import pandas as pd


FALLBACK_METHODS = [
    {
        "method_id": "z1_easy_aerobic",
        "component": "Z1",
        "phase": "any",
        "title": "Продължителна нискоинтензивна аеробна работа",
        "description": "Равномерно нискоинтензивно натоварване с цел възстановяване, капиляризация и поддържане на обем.",
        "zone_distribution": {"Z1": 1.0},
        "default_duration_min": 60,
        "min_readiness": 60,
        "max_percent_tref": 0.35,
        "tags": "easy,aerobic,base",
    },
    {
        "method_id": "z2_base_aerobic",
        "component": "Z2",
        "phase": "early",
        "title": "Основна аеробна тренировка",
        "description": "Умерена аеробна работа в Z2 с контролирана техника и без натрупване на висок лактат.",
        "zone_distribution": {"Z1": 0.25, "Z2": 0.75},
        "default_duration_min": 90,
        "min_readiness": 80,
        "max_percent_tref": 0.50,
        "tags": "aerobic,base",
    },
    {
        "method_id": "z3_tempo_intervals",
        "component": "Z3",
        "phase": "middle",
        "title": "Темпови интервали",
        "description": "Например 4×8 мин или 5×6 мин в Z3 с контролирано възстановяване.",
        "zone_distribution": {"Z1": 0.35, "Z3": 0.65},
        "default_duration_min": 65,
        "min_readiness": 90,
        "max_percent_tref": 0.55,
        "tags": "tempo,threshold-development",
    },
    {
        "method_id": "z4_threshold_intervals",
        "component": "Z4",
        "phase": "late",
        "title": "Прагови интервали",
        "description": "Кратки серии в Z4, насочени към специфична прагово-интензивна издръжливост.",
        "zone_distribution": {"Z1": 0.45, "Z4": 0.55},
        "default_duration_min": 55,
        "min_readiness": 90,
        "max_percent_tref": 0.60,
        "tags": "threshold,quality",
    },
    {
        "method_id": "z5_vo2_intervals",
        "component": "Z5",
        "phase": "late",
        "title": "VO₂max интервали",
        "description": "Например 5×3 мин или 6×2 мин в Z5 с непълно, но контролирано възстановяване.",
        "zone_distribution": {"Z1": 0.55, "Z5": 0.45},
        "default_duration_min": 45,
        "min_readiness": 90,
        "max_percent_tref": 0.65,
        "tags": "vo2max,intensity",
    },
    {
        "method_id": "z6_speed",
        "component": "Z6",
        "phase": "late",
        "title": "Скоростни отсечки / нервно-мускулна мощност",
        "description": "Кратки скоростни отсечки с пълно възстановяване и малък общ обем.",
        "zone_distribution": {"Z1": 0.75, "Z6": 0.25},
        "default_duration_min": 35,
        "min_readiness": 90,
        "max_percent_tref": 0.70,
        "tags": "speed,neuromuscular",
    },
    {
        "method_id": "osi_general_strength",
        "component": "OSI",
        "phase": "early",
        "title": "Обща силова издръжливост",
        "description": "Кръгова или комплексна силова работа с акцент върху обща силова издръжливост.",
        "zone_distribution": {"OSI": 1.0},
        "default_duration_min": 45,
        "min_readiness": 80,
        "max_percent_tref": 0.50,
        "tags": "strength,general",
    },
    {
        "method_id": "ssi_specific_strength",
        "component": "SSI",
        "phase": "middle",
        "title": "Специална силова издръжливост",
        "description": "Специална силова работа, близка до движението и ритъма на спортната дейност.",
        "zone_distribution": {"SSI": 1.0},
        "default_duration_min": 40,
        "min_readiness": 85,
        "max_percent_tref": 0.55,
        "tags": "strength,specific",
    },
]


def load_methods(path: str | Path = "training_methods.csv") -> List[Dict]:
    p = Path(path)
    if not p.exists():
        json_path = p.with_suffix(".json")
        if json_path.exists():
            with json_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else FALLBACK_METHODS
        return FALLBACK_METHODS
    df = pd.read_csv(p)
    records = []
    for _, row in df.iterrows():
        record = row.to_dict()
        if isinstance(record.get("zone_distribution"), str):
            try:
                record["zone_distribution"] = json.loads(record["zone_distribution"])
            except Exception:
                record["zone_distribution"] = {}
        records.append(record)
    return records or FALLBACK_METHODS


def phase_name(phase_fraction: float) -> str:
    if phase_fraction < 1 / 3:
        return "early"
    if phase_fraction < 2 / 3:
        return "middle"
    return "late"


def select_best_method(component_id: str, phase_fraction: float, readiness: float, methods: List[Mapping] | None = None) -> Mapping:
    methods = list(methods or FALLBACK_METHODS)
    phase = phase_name(phase_fraction)
    candidates = [m for m in methods if str(m.get("component")) == component_id]
    if not candidates:
        return {
            "method_id": f"{component_id}_generic",
            "component": component_id,
            "phase": "any",
            "title": f"Тренировка за {component_id}",
            "description": "Автоматично генерирана тренировка според седмичната цел и готовността.",
            "zone_distribution": {component_id: 1.0},
            "default_duration_min": 45,
            "min_readiness": 60,
            "max_percent_tref": 0.50,
            "tags": "generic",
        }

    # Prefer phase match and enough readiness.
    suitable = [m for m in candidates if m.get("phase") in {phase, "any"} and float(m.get("min_readiness", 60)) <= readiness]
    if suitable:
        return suitable[0]
    return candidates[0]
