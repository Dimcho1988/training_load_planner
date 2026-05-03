"""Default configuration for the Training Load Dynamics Planner."""

from __future__ import annotations

COMPONENTS = [
    {
        "id": "Z1",
        "name": "Z1 възстановителна / нискоинтензивна аеробна работа",
        "base_weekly_load": 180.0,
        "group": "Аеробна работа",
        "specificity": 1,
        "enabled": True,
    },
    {
        "id": "Z2",
        "name": "Z2 основна аеробна издръжливост",
        "base_weekly_load": 300.0,
        "group": "Аеробна работа",
        "specificity": 2,
        "enabled": True,
    },
    {
        "id": "OSI",
        "name": "ОСИ обща силова издръжливост",
        "base_weekly_load": 80.0,
        "group": "Сила",
        "specificity": 3,
        "enabled": True,
    },
    {
        "id": "Z3",
        "name": "Z3 темпова / смесена издръжливост",
        "base_weekly_load": 70.0,
        "group": "Смесена издръжливост",
        "specificity": 4,
        "enabled": True,
    },
    {
        "id": "SSI",
        "name": "ССИ специална силова издръжливост",
        "base_weekly_load": 55.0,
        "group": "Сила",
        "specificity": 5,
        "enabled": True,
    },
    {
        "id": "Z4",
        "name": "Z4 прагова / високоинтензивна издръжливост",
        "base_weekly_load": 45.0,
        "group": "Висока интензивност",
        "specificity": 6,
        "enabled": True,
    },
    {
        "id": "Z5",
        "name": "Z5 VO₂max / високоинтензивни интервали",
        "base_weekly_load": 25.0,
        "group": "Висока интензивност",
        "specificity": 7,
        "enabled": True,
    },
    {
        "id": "Z6",
        "name": "Z6 скорост / нервно-мускулна мощност",
        "base_weekly_load": 12.0,
        "group": "Скорост",
        "specificity": 8,
        "enabled": True,
    },
]

# Virtual physiologic baseline per day. It stabilizes the model, but is not forced
# into the visible daily training plan as real training.
BASELINE_DAILY_LOADS = {
    "Z1": 50.0,
    "Z2": 30.0,
    "Z3": 10.0,
    "Z4": 5.0,
    "Z5": 3.0,
    "Z6": 1.5,
    "OSI": 10.0,
    "SSI": 5.0,
}

ZONE_ORDER = ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"]
STRENGTH_COMPONENTS = ["OSI", "SSI"]

# Constant physiologic inclusion cascade from higher zones to lower zones by distance.
# Default is 100% downward inclusion: e.g. Z3 20 min counts as 20 min
# physiologic participation for Z3, Z2 and Z1, but never upward by cascade.
CASCADE_COEFFICIENTS = {
    1: 1.00,
    2: 1.00,
    3: 1.00,
    4: 1.00,
    5: 1.00,
}

STRESS_ZONES = {
    "Възстановително": (0.00, 0.85),
    "Поддържащо": (0.85, 1.10),
    "Развиващо": (1.10, 1.60),
    "Рисково": (1.60, 10.00),
}

RECOVERY_MULTIPLIERS = {
    "Z1": 0.70,
    "Z2": 0.90,
    "Z3": 1.00,
    "Z4": 1.20,
    "Z5": 1.40,
    "Z6": 1.50,
    "OSI": 1.20,
    "SSI": 1.30,
}

DEFAULT_EVENTS = [
    {"event_name": "Лагер 1", "event_type": "camp", "start_week": 7, "duration_days": 14, "priority": 2, "notes": "Изграждащ лагер"},
    {"event_name": "Контролен старт 1", "event_type": "control_race", "start_week": 12, "duration_days": 2, "priority": 2, "notes": "Контролен старт"},
    {"event_name": "Лагер 2", "event_type": "camp", "start_week": 13, "duration_days": 14, "priority": 2, "notes": "Специализиран лагер"},
    {"event_name": "Контролен старт 2", "event_type": "control_race", "start_week": 18, "duration_days": 2, "priority": 2, "notes": "Контролен старт"},
    {"event_name": "Основен старт", "event_type": "main_race", "start_week": 24, "duration_days": 3, "priority": 3, "notes": "Основен старт"},
]

DEFAULT_MODEL_PARAMS = {
    "total_weeks": 24,
    "initial_weekly_volume_hours": 12.0,
    "monthly_progression_rate": 0.04,
    "peak_fraction": 0.60,
    "post_peak_reduction": 0.15,
    "mesocycle_len": 4,
    "max_accents": 3,
    "intro_stress": 1.20,
    "dev1_stress": 1.35,
    "dev2_stress": 1.45,
    "maintenance_stress": 0.98,
    "recovery_stress": 0.75,
    "wave_amplitude": 0.25,
    "risk_limit": 1.60,
    "spill_threshold": 0.50,
    "spill_down_percent": 0.20,
    "spill_up_percent": 0.10,
    "camp_load_bonus": 0.15,
    "camp_accent_bonus": 0.10,
    "post_camp_reduction": 0.25,
    "control_race_reduction": 0.10,
    "control_race_intensity_preservation": 0.85,
    "taper_length_weeks": 2,
    "taper_reduction_week_1": 0.25,
    "taper_reduction_week_2": 0.45,
    "strength_taper_reduction": 0.60,
    "high_intensity_preservation": 0.70,
    "drop_sensitivity": 70.0,
    "minimum_readiness_for_key_workout": 90.0,
    "minimum_readiness_for_moderate_workout": 80.0,
    "minimum_readiness_for_easy_workout": 60.0,
    "phase_1_key_session_min": 0.40,
    "phase_1_key_session_max": 0.50,
    "phase_2_key_session_min": 0.50,
    "phase_2_key_session_max": 0.60,
    "phase_3_key_session_min": 0.60,
    "phase_3_key_session_max": 0.70,
}
