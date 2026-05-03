"""Training method library and selection utilities.

Supports fallback methods, CSV, and XLSX method databases. The expected fields are:
method_id, component or primary_component, phase, title, description/original_text/template_text,
zone_distribution or explicit Z1..SSI columns, default_duration_min, min_readiness,
max_percent_tref, tags.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Mapping, Any

import pandas as pd

COMPONENT_IDS = ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6", "OSI", "SSI"]


FALLBACK_METHODS = [
    {
        "method_id": "z1_easy_aerobic",
        "component": "Z1",
        "primary_component": "Z1",
        "phase": "any",
        "title": "Продължителна нискоинтензивна аеробна работа",
        "description": "Равномерно нискоинтензивно натоварване с цел възстановяване, капиляризация и поддържане на обем.",
        "template_text": "{Z1_min} мин нискоинтензивна аеробна работа в Z1.",
        "zone_distribution": {"Z1": 60.0},
        "default_duration_min": 60,
        "min_readiness": 60,
        "max_percent_tref": 0.35,
        "tags": "easy,aerobic,base",
    },
    {
        "method_id": "z2_base_aerobic",
        "component": "Z2",
        "primary_component": "Z2",
        "phase": "early",
        "title": "Основна аеробна тренировка",
        "description": "Умерена аеробна работа в Z2 с контролирана техника и без натрупване на висок лактат.",
        "template_text": "{Z1_min} мин леко + {Z2_min} мин основна аеробна работа в Z2.",
        "zone_distribution": {"Z1": 20.0, "Z2": 70.0},
        "default_duration_min": 90,
        "min_readiness": 80,
        "max_percent_tref": 0.50,
        "tags": "aerobic,base",
    },
    {
        "method_id": "z3_tempo_intervals",
        "component": "Z3",
        "primary_component": "Z3",
        "phase": "middle",
        "title": "Темпови интервали",
        "description": "Например 4×8 мин или 5×6 мин в Z3 с контролирано възстановяване.",
        "template_text": "{Z1_min} мин загрявка/разпускане + интервали с общо {Z3_min} мин в Z3.",
        "zone_distribution": {"Z1": 25.0, "Z3": 32.0},
        "default_duration_min": 57,
        "min_readiness": 90,
        "max_percent_tref": 0.55,
        "tags": "tempo,threshold-development",
    },
    {
        "method_id": "z4_threshold_intervals",
        "component": "Z4",
        "primary_component": "Z4",
        "phase": "late",
        "title": "Прагови интервали",
        "description": "Кратки серии в Z4, насочени към специфична прагово-интензивна издръжливост.",
        "template_text": "{Z1_min} мин леко + интервали с общо {Z4_min} мин в Z4.",
        "zone_distribution": {"Z1": 30.0, "Z4": 20.0},
        "default_duration_min": 50,
        "min_readiness": 90,
        "max_percent_tref": 0.60,
        "tags": "threshold,quality",
    },
    {
        "method_id": "z5_vo2_intervals",
        "component": "Z5",
        "primary_component": "Z5",
        "phase": "late",
        "title": "VO₂max интервали",
        "description": "Например 5×3 мин или 6×2 мин в Z5 с непълно, но контролирано възстановяване.",
        "template_text": "{Z1_min} мин леко + интервали с общо {Z5_min} мин в Z5.",
        "zone_distribution": {"Z1": 30.0, "Z5": 15.0},
        "default_duration_min": 45,
        "min_readiness": 90,
        "max_percent_tref": 0.65,
        "tags": "vo2max,intensity",
    },
    {
        "method_id": "z6_speed",
        "component": "Z6",
        "primary_component": "Z6",
        "phase": "late",
        "title": "Скоростни отсечки / нервно-мускулна мощност",
        "description": "Кратки скоростни отсечки с пълно възстановяване и малък общ обем.",
        "template_text": "{Z1_min} мин леко + кратки скоростни отсечки с общо {Z6_min} мин Z6.",
        "zone_distribution": {"Z1": 30.0, "Z6": 5.0},
        "default_duration_min": 35,
        "min_readiness": 90,
        "max_percent_tref": 0.70,
        "tags": "speed,neuromuscular",
    },
    {
        "method_id": "osi_general_strength",
        "component": "OSI",
        "primary_component": "OSI",
        "phase": "early",
        "title": "Обща силова издръжливост",
        "description": "Кръгова или комплексна силова работа с акцент върху обща силова издръжливост.",
        "template_text": "{OSI_min} мин обща силова издръжливост.",
        "zone_distribution": {"OSI": 45.0},
        "default_duration_min": 45,
        "min_readiness": 80,
        "max_percent_tref": 0.50,
        "tags": "strength,general",
    },
    {
        "method_id": "ssi_specific_strength",
        "component": "SSI",
        "primary_component": "SSI",
        "phase": "middle",
        "title": "Специална силова издръжливост",
        "description": "Специална силова работа, близка до движението и ритъма на спортната дейност.",
        "template_text": "{SSI_min} мин специална силова издръжливост.",
        "zone_distribution": {"SSI": 40.0},
        "default_duration_min": 40,
        "min_readiness": 85,
        "max_percent_tref": 0.55,
        "tags": "strength,specific",
    },
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
            if value == "":
                return default
        return float(value)
    except Exception:
        return default


def _parse_zone_distribution(value: Any, row: Mapping | None = None) -> Dict[str, float]:
    if isinstance(value, dict):
        return {k: _safe_float(v) for k, v in value.items() if k in COMPONENT_IDS and _safe_float(v) > 0}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return {k: _safe_float(v) for k, v in parsed.items() if k in COMPONENT_IDS and _safe_float(v) > 0}
        except Exception:
            pass
    if row:
        dist = {cid: _safe_float(row.get(cid, 0.0)) for cid in COMPONENT_IDS}
        return {k: v for k, v in dist.items() if v > 0}
    return {}


def normalize_method_record(record: Mapping, idx: int = 0) -> Dict:
    rec = dict(record)
    component = str(rec.get("component") or rec.get("primary_component") or "Z1").strip()
    if component not in COMPONENT_IDS:
        component = str(rec.get("primary_component") or "Z1").strip()
    if component not in COMPONENT_IDS:
        component = "Z1"
    rec["component"] = component
    rec["primary_component"] = str(rec.get("primary_component") or component).strip()
    if rec["primary_component"] not in COMPONENT_IDS:
        rec["primary_component"] = component
    rec["method_id"] = str(rec.get("method_id") or f"method_{idx:03d}")
    rec["phase"] = str(rec.get("phase") or "any").strip().lower()
    if rec["phase"] in {"1/3", "phase_1", "early", "начална"}:
        rec["phase"] = "early"
    elif rec["phase"] in {"2/3", "phase_2", "middle", "средна"}:
        rec["phase"] = "middle"
    elif rec["phase"] in {"3/3", "phase_3", "late", "крайна"}:
        rec["phase"] = "late"
    elif rec["phase"] not in {"early", "middle", "late", "any"}:
        rec["phase"] = "any"
    rec["title"] = str(rec.get("title") or f"Тренировка за {rec['primary_component']}").strip()
    text = rec.get("template_text") or rec.get("description") or rec.get("original_text") or ""
    rec["template_text"] = str(text)
    rec["description"] = str(rec.get("description") or rec.get("original_text") or rec["template_text"])
    rec["zone_distribution"] = _parse_zone_distribution(rec.get("zone_distribution"), rec)
    if not rec["zone_distribution"]:
        rec["zone_distribution"] = {rec["primary_component"]: _safe_float(rec.get("default_duration_min"), 45.0)}
    rec["default_duration_min"] = _safe_float(rec.get("default_duration_min"), sum(rec["zone_distribution"].values()) or 45.0)
    rec["min_readiness"] = _safe_float(rec.get("min_readiness"), 60.0)
    rec["max_percent_tref"] = _safe_float(rec.get("max_percent_tref"), 0.50)
    rec["tags"] = str(rec.get("tags") or "")
    return rec


def dataframe_to_methods(df: pd.DataFrame) -> List[Dict]:
    if df is None or df.empty:
        return FALLBACK_METHODS
    # Normalize column names by stripping spaces.
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    records = []
    for idx, (_, row) in enumerate(df.iterrows(), 1):
        rec = normalize_method_record(row.to_dict(), idx)
        # Skip rows with no meaningful title/text.
        if not rec.get("title") and not rec.get("description"):
            continue
        records.append(rec)
    return records or FALLBACK_METHODS


def load_methods(path_or_file: str | Path | Any = "training_methods.csv", file_name: str | None = None) -> List[Dict]:
    """Load methods from a CSV/XLSX path or Streamlit uploaded file.

    If no usable file exists, fallback methods are returned.
    """
    # Streamlit UploadedFile or file-like object
    if hasattr(path_or_file, "read"):
        name = (file_name or getattr(path_or_file, "name", "")).lower()
        try:
            if name.endswith(".xlsx") or name.endswith(".xls"):
                df = pd.read_excel(path_or_file, sheet_name="Methods_DB")
            elif name.endswith(".csv"):
                df = pd.read_csv(path_or_file)
            else:
                # Try Excel first, then CSV.
                try:
                    df = pd.read_excel(path_or_file, sheet_name="Methods_DB")
                except Exception:
                    path_or_file.seek(0)
                    df = pd.read_csv(path_or_file)
            return dataframe_to_methods(df)
        except Exception:
            return FALLBACK_METHODS

    p = Path(path_or_file)
    if not p.exists():
        json_path = p.with_suffix(".json")
        if json_path.exists():
            try:
                with json_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                return [normalize_method_record(r, i) for i, r in enumerate(data, 1)] if isinstance(data, list) else FALLBACK_METHODS
            except Exception:
                return FALLBACK_METHODS
        return FALLBACK_METHODS
    try:
        if p.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(p, sheet_name="Methods_DB")
        else:
            df = pd.read_csv(p)
        return dataframe_to_methods(df)
    except Exception:
        return FALLBACK_METHODS


def methods_to_dataframe(methods: List[Mapping]) -> pd.DataFrame:
    rows = []
    for m in methods:
        row = dict(m)
        zd = row.get("zone_distribution", {})
        if isinstance(zd, dict):
            for cid in COMPONENT_IDS:
                row[cid] = float(zd.get(cid, 0.0) or 0.0)
            row["zone_distribution"] = json.dumps(zd, ensure_ascii=False)
        rows.append(row)
    return pd.DataFrame(rows)


def phase_name(phase_fraction: float) -> str:
    if phase_fraction < 1 / 3:
        return "early"
    if phase_fraction < 2 / 3:
        return "middle"
    return "late"


def _method_match_score(method: Mapping, component_id: str, phase: str, readiness: float, target_loads: Mapping[str, float] | None = None) -> float:
    score = 0.0
    method_component = str(method.get("primary_component") or method.get("component") or "")
    if method_component == component_id:
        score += 100.0
    elif str(method.get("component") or "") == component_id:
        score += 80.0
    method_phase = str(method.get("phase") or "any")
    if method_phase == phase:
        score += 35.0
    elif method_phase == "any":
        score += 15.0
    if float(method.get("min_readiness", 60)) <= readiness:
        score += 20.0
    else:
        score -= 50.0
    # Match target loads against method distribution shape.
    if target_loads:
        zd = method.get("zone_distribution", {}) or {}
        if isinstance(zd, str):
            zd = _parse_zone_distribution(zd)
        target_total = sum(float(v) for v in target_loads.values() if v)
        method_total = sum(float(v) for v in zd.values() if v)
        if target_total > 0 and method_total > 0:
            # closeness of total and component distribution
            score -= abs(method_total - target_total) / max(10.0, target_total) * 10.0
            for cid in COMPONENT_IDS:
                target_share = float(target_loads.get(cid, 0.0)) / target_total
                method_share = float(zd.get(cid, 0.0)) / method_total
                score -= abs(target_share - method_share) * 8.0
    return score


def select_best_method(
    component_id: str,
    phase_fraction: float,
    readiness: float,
    methods: List[Mapping] | None = None,
    target_loads: Mapping[str, float] | None = None,
) -> Mapping:
    methods = list(methods or FALLBACK_METHODS)
    phase = phase_name(phase_fraction)
    candidates = [m for m in methods if str(m.get("primary_component") or m.get("component")) == component_id or str(m.get("component")) == component_id]
    if not candidates:
        candidates = methods
    if not candidates:
        return FALLBACK_METHODS[0]
    candidates = sorted(candidates, key=lambda m: _method_match_score(m, component_id, phase, readiness, target_loads), reverse=True)
    return candidates[0]


def render_method_text(method: Mapping, target_loads: Mapping[str, float] | None = None) -> str:
    """Render template placeholders with planned component minutes.

    Supports placeholders such as {Z1_min}, {Z3_min}, {OSI_min}, plus {total_min}.
    Generic placeholders like {мин}, {повторения} remain for manual editing.
    """
    text = str(method.get("template_text") or method.get("description") or "")
    target_loads = target_loads or {}
    values = {f"{cid}_min": round(float(target_loads.get(cid, 0.0)), 1) for cid in COMPONENT_IDS}
    values["total_min"] = round(sum(float(v) for v in target_loads.values()), 1)
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text
