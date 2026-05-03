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


def _format_min(value: float) -> str:
    value = max(0.0, float(value or 0.0))
    if value >= 60:
        hours = int(value // 60)
        minutes = int(round(value % 60))
        if minutes == 0:
            return f"{hours} ч"
        return f"{hours} ч {minutes} мин"
    return f"{round(value, 1)} мин"


def _clean_physical_text(text: str) -> str:
    """Remove non-physical fragments from old source plans.

    The uploaded plans often contain shooting blocks. The current application is
    physical-load only, so we remove obvious shooting clauses from the rendered
    method text while keeping the original method structure.
    """
    text = str(text or "")
    text = re.sub(r"(?:След обяд:\s*)?\d*\.?\s*Стрелба[^\.\n;]*(?:[\.;]|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Стрелба[^\.\n;]*(?:[\.;]|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip(" -;\n\t")
    return text


def _component_minutes(target_loads: Mapping[str, float] | None) -> Dict[str, float]:
    target_loads = target_loads or {}
    return {cid: round(max(0.0, float(target_loads.get(cid, 0.0) or 0.0)), 1) for cid in COMPONENT_IDS}


def _planned_summary(cleaned: Mapping[str, float]) -> str:
    planned_parts = [f"{cid}: {minutes:g} мин" for cid, minutes in cleaned.items() if minutes > 0]
    return "Планови обеми за деня: " + (", ".join(planned_parts) if planned_parts else "няма зададен товар") + "."


def _interval_prescription(primary: str, minutes: float, phase: str) -> str:
    """Create a concrete interval dose from target minutes."""
    minutes = max(0.0, float(minutes or 0.0))
    if minutes <= 0:
        return ""

    if primary == "Z3":
        desired = 10 if phase == "early" else (8 if phase == "middle" else 6)
        reps = max(2, min(8, round(minutes / desired)))
        interval = round(minutes / reps, 1)
        return f"Основна част: {reps} × {interval:g} мин в Z3, с 1–2 мин леко възстановяване между отсечките."

    if primary == "Z4":
        desired = 5 if phase in {"early", "middle"} else 4
        reps = max(3, min(8, round(minutes / desired)))
        interval = round(minutes / reps, 1)
        return f"Основна част: {reps} × {interval:g} мин в Z4, с 2–3 мин леко възстановяване."

    if primary == "Z5":
        desired = 3
        reps = max(4, min(10, round(minutes / desired)))
        interval = round(minutes / reps, 1)
        return f"Основна част: {reps} × {interval:g} мин в Z5, с 2–4 мин възстановяване според пулса и техниката."

    if primary == "Z6":
        # Convert total Z6 minutes to short accelerations/sprints.
        total_seconds = minutes * 60
        reps = max(6, min(16, round(total_seconds / 20)))
        sec = max(10, min(30, round(total_seconds / reps)))
        return f"Основна част: {reps} × {sec} сек скоростни отсечки в Z6, с пълно възстановяване между тях."

    return ""


def _strength_prescription(primary: str, minutes: float, phase: str) -> str:
    minutes = max(0.0, float(minutes or 0.0))
    if minutes <= 0:
        return ""
    if primary == "OSI":
        if phase == "early":
            return f"Силова част: {minutes:g} мин ОСИ — кръгова/зала, 6–8 упражнения, 2–4 серии, контролирана техника."
        return f"Силова част: {minutes:g} мин ОСИ — поддържаща обща силова издръжливост, без излишна остатъчна умора."
    if primary == "SSI":
        return f"Силова част: {minutes:g} мин ССИ — специална силова издръжливост, близка до спортното движение и ритъм."
    return ""


def _build_dosed_session(method: Mapping, target_loads: Mapping[str, float], phase: str, tref_weekly: Mapping[str, float] | None = None, key_threshold: float = 0.40) -> str:
    """Build a methodologically coherent session from planned component minutes.

    This is the important part: the selected database method provides the type
    and context, while the actual dose is automatically scaled from the daily
    loads generated by the model.
    """
    cleaned = _component_minutes(target_loads)
    tref_weekly = tref_weekly or {}
    primary = str(method.get("primary_component") or method.get("component") or "Z1")
    if primary not in COMPONENT_IDS:
        primary = "Z1"

    primary_min = cleaned.get(primary, 0.0)
    tref = max(1e-9, float(tref_weekly.get(primary, 0.0) or 0.0))
    percent_tref = primary_min / tref if tref > 0 else 0.0
    is_key = percent_tref >= float(key_threshold)

    z1 = cleaned.get("Z1", 0.0)
    z2 = cleaned.get("Z2", 0.0)
    z3 = cleaned.get("Z3", 0.0)
    z4 = cleaned.get("Z4", 0.0)
    z5 = cleaned.get("Z5", 0.0)
    z6 = cleaned.get("Z6", 0.0)
    osi = cleaned.get("OSI", 0.0)
    ssi = cleaned.get("SSI", 0.0)

    lines: List[str] = []
    level = "КЛЮЧОВА" if is_key else "поддържаща/дозирана"
    lines.append(f"Автоматично дозирана {level} тренировка по модела. Основен фокус: {primary}. Натоварване на фокуса: {primary_min:g} мин ({percent_tref*100:.1f}% от Tref).")

    # Endurance part.
    endurance_minutes = z1 + z2 + z3 + z4 + z5 + z6
    if endurance_minutes > 0:
        warmup = min(max(10.0, z1 * 0.35), max(10.0, z1)) if z1 > 0 else 10.0
        cooldown = max(0.0, z1 - warmup)
        if primary in {"Z3", "Z4", "Z5", "Z6"} and primary_min > 0:
            lines.append(f"Загрявка: около {_format_min(warmup)} в Z1/Z2 + бегови упражнения/ускорения според метода.")
            interval = _interval_prescription(primary, primary_min, phase)
            if interval:
                lines.append(interval)
            if z2 > 0:
                lines.append(f"Допълваща аеробна работа: {_format_min(z2)} в Z2, разположена преди или след основната част според терена.")
            if cooldown > 0:
                lines.append(f"Разпускане: около {_format_min(cooldown)} в Z1.")
        elif primary == "Z2":
            lines.append(f"Основна аеробна част: общо {_format_min(z1 + z2)} в Z1–Z2, от които приблизително {_format_min(z2)} в Z2.")
            if z3 + z4 + z5 + z6 > 0:
                lines.append(f"Кратки активации/ускорения: Z3 {_format_min(z3)}, Z4 {_format_min(z4)}, Z5 {_format_min(z5)}, Z6 {_format_min(z6)} — без натрупване на излишна умора.")
        else:
            lines.append(f"Лека аеробна част: {_format_min(z1)} Z1" + (f" + {_format_min(z2)} Z2." if z2 > 0 else "."))

    # Strength part.
    strength_lines = []
    if osi > 0:
        strength_lines.append(_strength_prescription("OSI", osi, phase))
    if ssi > 0:
        strength_lines.append(_strength_prescription("SSI", ssi, phase))
    for ln in strength_lines:
        if ln:
            lines.append(ln)

    if not is_key and primary in {"Z3", "Z4", "Z5", "Z6", "OSI", "SSI"}:
        lines.append(f"Забележка: фокусът е под {int(float(key_threshold)*100)}% от Tref, затова тренировката се третира като дозирана/поддържаща, а не като тежък развиващ стимул.")
    elif is_key:
        lines.append("Методическа бележка: натоварването е над прага за ключов стимул; следващият сходен стимул трябва да се постави само при достатъчно възстановяване на компонента.")

    return "\n".join([ln for ln in lines if ln])


def render_method_text(
    method: Mapping,
    target_loads: Mapping[str, float] | None = None,
    tref_weekly: Mapping[str, float] | None = None,
    phase_fraction: float | None = None,
    key_threshold: float = 0.40,
) -> str:
    """Render a database method as a concrete, automatically dosed session.

    The database provides the method type. The model-generated daily loads set
    the actual dosage. This avoids confusing text such as old fixed times that
    do not match the generated zone loads.
    """
    target_loads = target_loads or {}
    phase = phase_name(float(phase_fraction or 0.0))
    cleaned = _component_minutes(target_loads)
    planned_summary = _planned_summary(cleaned)

    dosed = _build_dosed_session(method, cleaned, phase, tref_weekly=tref_weekly, key_threshold=key_threshold)

    source_text = str(method.get("template_text") or method.get("description") or "").strip()
    source_text = _clean_physical_text(source_text)

    # Replace explicit placeholders in source text, but keep it as reference only.
    values = {f"{cid}_min": cleaned[cid] for cid in COMPONENT_IDS}
    values["total_min"] = round(sum(cleaned.values()), 1)
    values["време"] = _format_min(sum(cleaned.get(cid, 0.0) for cid in ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"]))
    values["часове"] = round(sum(cleaned.get(cid, 0.0) for cid in ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"]) / 60, 1)
    values["мин"] = "според плана"
    values["сек"] = "10–30"
    values["повторения"] = "според дозировката"
    values["дължина"] = "подходяща дистанция"
    for key, value in values.items():
        source_text = source_text.replace("{" + key + "}", str(value))

    title = str(method.get("title") or "Метод от базата")
    method_id = str(method.get("method_id") or "")
    parts = [planned_summary, "", f"Избран метод от базата: {title}" + (f" ({method_id})" if method_id else "") + ".", "", dosed]
    if source_text:
        parts += ["", "Оригинална методическа рамка от базата:", source_text]
    return "\n".join(parts)
