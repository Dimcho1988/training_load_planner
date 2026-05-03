from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import streamlit as st

try:
    import plotly.express as px
    import plotly.graph_objects as go
except ModuleNotFoundError:
    px = None
    go = None

from config import (
    BASELINE_DAILY_LOADS,
    CASCADE_COEFFICIENTS,
    COMPONENTS,
    DEFAULT_EVENTS,
    DEFAULT_MODEL_PARAMS,
    RECOVERY_MULTIPLIERS,
)
from export_utils import dataframes_to_excel_bytes
from load_model import (
    classify_stress,
    diagnostic_checks,
    generate_weekly_plan,
    scale_components_to_total_volume,
    validate_components,
)
from methods_library import load_methods, methods_to_dataframe
from planner import compare_weekly_target_vs_plan, generate_microcycle

st.set_page_config(
    page_title="Training Load Dynamics Planner",
    page_icon="🎯",
    layout="wide",
)

if px is None or go is None:
    st.error("Липсва plotly. Добави plotly в requirements.txt и рестартирай приложението.")
    st.stop()


# Robust fallback defaults. This prevents KeyError if Streamlit Cloud is still using
# an older config.py or cached config values.
MODEL_DEFAULTS = {
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
}
MODEL_DEFAULTS.update(DEFAULT_MODEL_PARAMS)

st.title("🎯 Training Load Dynamics Planner")
st.caption("Планов генератор на тренировъчна програма: вълнообразна 7/40 динамика, ефективен товар и recovery модел.")


def init_state():
    if "components_df" not in st.session_state:
        st.session_state.components_df = pd.DataFrame(COMPONENTS)
    if "events_df" not in st.session_state:
        st.session_state.events_df = pd.DataFrame(DEFAULT_EVENTS)
    if "baseline_df" not in st.session_state:
        st.session_state.baseline_df = pd.DataFrame(
            [{"component_id": k, "baseline_daily_load": v} for k, v in BASELINE_DAILY_LOADS.items()]
        )
    if "cascade_df" not in st.session_state:
        st.session_state.cascade_df = pd.DataFrame(
            [{"distance": k, "coefficient": v} for k, v in CASCADE_COEFFICIENTS.items()]
        )
    if "recovery_df" not in st.session_state:
        st.session_state.recovery_df = pd.DataFrame(
            [{"component_id": k, "recovery_multiplier": v} for k, v in RECOVERY_MULTIPLIERS.items()]
        )


init_state()

# ------------------------------ Sidebar ------------------------------
with st.sidebar:
    st.header("Основни настройки")
    start_date = st.date_input("Начална дата", value=date.today())
    total_weeks = st.slider("Брой седмици до основния старт", 4, 40, int(MODEL_DEFAULTS["total_weeks"]), 1)
    initial_weekly_volume_hours = st.number_input("Начален седмичен обем (часове)", 2.0, 40.0, float(MODEL_DEFAULTS["initial_weekly_volume_hours"]), 0.5)
    auto_scale_to_initial_volume = st.checkbox(
        "Автоматично свържи компонентите с началния седмичен обем",
        value=True,
        help=(
            "Когато е включено, сумата на компонентите се мащабира пропорционално "
            "към зададения начален седмичен обем. Така промяната от 12 ч на 16 ч "
            "веднага променя динамиката на обема по часове, без да натискаш допълнителен бутон."
        ),
    )

    st.header("Прогресия и пик")
    monthly_progression_rate = st.slider("Месечна прогресия", 0.00, 0.12, float(MODEL_DEFAULTS["monthly_progression_rate"]), 0.005, format="%.3f")
    peak_fraction = st.slider("Пик на общия товар като част от периода", 0.30, 0.75, float(MODEL_DEFAULTS["peak_fraction"]), 0.01)
    post_peak_reduction = st.slider("Редукция след пика", 0.00, 0.35, float(MODEL_DEFAULTS["post_peak_reduction"]), 0.01)

    st.header("Мезоцикъл и акценти")
    mesocycle_len = st.selectbox("Дължина на мезоцикъл", [3, 4, 5], index=1)
    max_accents = st.slider("Максимум акценти в мезоцикъл", 1, 5, int(MODEL_DEFAULTS["max_accents"]), 1)
    wave_amplitude = st.slider("Амплитуда на компонентната вълна", 0.00, 0.60, float(MODEL_DEFAULTS["wave_amplitude"]), 0.01)

    st.header("Стрес прагове")
    intro_stress = st.slider("Вработваща седмица — акцент", 1.00, 1.45, float(MODEL_DEFAULTS["intro_stress"]), 0.01)
    dev1_stress = st.slider("Развиваща 1 — акцент", 1.05, 1.65, float(MODEL_DEFAULTS["dev1_stress"]), 0.01)
    dev2_stress = st.slider("Развиваща 2 — акцент", 1.05, 1.75, float(MODEL_DEFAULTS["dev2_stress"]), 0.01)
    maintenance_stress = st.slider("Поддържащ стрес", 0.75, 1.10, float(MODEL_DEFAULTS["maintenance_stress"]), 0.01)
    recovery_stress = st.slider("Възстановителен стрес", 0.50, 0.95, float(MODEL_DEFAULTS["recovery_stress"]), 0.01)
    risk_limit = st.slider("Горна рискова граница", 1.20, 1.90, float(MODEL_DEFAULTS["risk_limit"]), 0.01)

params = dict(MODEL_DEFAULTS)
params.update(
    {
        "total_weeks": total_weeks,
        "initial_weekly_volume_hours": initial_weekly_volume_hours,
        "monthly_progression_rate": monthly_progression_rate,
        "peak_fraction": peak_fraction,
        "post_peak_reduction": post_peak_reduction,
        "mesocycle_len": mesocycle_len,
        "max_accents": max_accents,
        "wave_amplitude": wave_amplitude,
        "intro_stress": intro_stress,
        "dev1_stress": dev1_stress,
        "dev2_stress": dev2_stress,
        "maintenance_stress": maintenance_stress,
        "recovery_stress": recovery_stress,
        "risk_limit": risk_limit,
    }
)

# ------------------------------ Tabs ------------------------------
tab_settings, tab_model, tab_calendar, tab_methods, tab_weekly, tab_micro, tab_export = st.tabs(
    ["1) Основни", "2) Настройки на модела", "3) Календар", "4) База тренировки", "5) Седмична динамика", "6) Микроцикъл", "7) Експорт"]
)

with tab_settings:
    st.subheader("Физически компоненти")
    st.write("Редактирай компонентите. `specificity` определя реда: от общи към специфични.")
    edited_components = st.data_editor(
        st.session_state.components_df,
        num_rows="dynamic",
        use_container_width=True,
        key="components_editor",
        column_config={
            "id": st.column_config.TextColumn("ID", required=True),
            "name": st.column_config.TextColumn("Компонент", required=True),
            "base_weekly_load": st.column_config.NumberColumn("Начален седмичен обем (мин)", min_value=0.0, step=5.0),
            "group": st.column_config.TextColumn("Група"),
            "specificity": st.column_config.NumberColumn("Специфичност", min_value=1, step=1),
            "enabled": st.column_config.CheckboxColumn("Активен"),
        },
    )
    st.session_state.components_df = edited_components

    if st.button("Запиши текущото пропорционално нагласяне в таблицата", type="secondary"):
        total_minutes = initial_weekly_volume_hours * 60.0
        st.session_state.components_df = scale_components_to_total_volume(edited_components, total_minutes)
        st.rerun()

    if auto_scale_to_initial_volume:
        st.info(
            "Автоматичното свързване е включено: въведените component base_weekly_load стойности се използват "
            "като относително разпределение, а реалната сума се мащабира към началния седмичен обем от sidebar-а. "
            "Бутонът по-горе само записва това мащабиране обратно в таблицата."
        )
    else:
        st.info(
            "Автоматичното свързване е изключено: графиките използват директно минутите от таблицата с компоненти. "
            "Тогава промяната на началния седмичен обем служи само като информационна настройка, докато не натиснеш бутона."
        )

with tab_model:
    st.subheader("Базов поносим дневен товар")
    st.write("Това е виртуален физиологичен товар. Участва в модела, но не се налага като реална тренировка всеки ден.")
    baseline_df = st.data_editor(
        st.session_state.baseline_df,
        num_rows="dynamic",
        use_container_width=True,
        key="baseline_editor",
        column_config={
            "component_id": st.column_config.TextColumn("Компонент"),
            "baseline_daily_load": st.column_config.NumberColumn("Базов дневен товар", min_value=0.0, step=1.0),
        },
    )
    st.session_state.baseline_df = baseline_df

    st.subheader("Постоянна 100% каскада от високи към ниски зони")
    st.write("По-високата зона се пренася само надолу. При стойност 1.00: 20 мин Z3 се отчитат като 20 мин физиологично участие за Z3, Z2 и Z1, но не и нагоре.")
    cascade_df = st.data_editor(
        st.session_state.cascade_df,
        num_rows="dynamic",
        use_container_width=True,
        key="cascade_editor",
        column_config={
            "distance": st.column_config.NumberColumn("Разстояние надолу", min_value=1, step=1),
            "coefficient": st.column_config.NumberColumn("Коефициент", min_value=0.0, max_value=1.0, step=0.05),
        },
    )
    st.session_state.cascade_df = cascade_df

    st.subheader("Разлив, лагери, стартове, recovery")
    c1, c2, c3 = st.columns(3)
    with c1:
        params["spill_threshold"] = st.slider("Праг за разлив от Tref", 0.10, 0.90, float(MODEL_DEFAULTS["spill_threshold"]), 0.05)
        params["spill_down_percent"] = st.slider("Разлив надолу към по-ниска съседна зона", 0.00, 0.50, float(MODEL_DEFAULTS["spill_down_percent"]), 0.01)
        params["spill_up_percent"] = st.slider("Разлив нагоре към по-висока съседна зона", 0.00, 0.50, float(MODEL_DEFAULTS["spill_up_percent"]), 0.01)
        params["drop_sensitivity"] = st.slider("Чувствителност на readiness към товар", 20.0, 120.0, float(MODEL_DEFAULTS["drop_sensitivity"]), 1.0)
    with c2:
        params["camp_load_bonus"] = st.slider("Бонус натоварване при лагер", 0.00, 0.40, float(MODEL_DEFAULTS["camp_load_bonus"]), 0.01)
        params["camp_accent_bonus"] = st.slider("Доп. бонус за акцент при лагер", 0.00, 0.30, float(MODEL_DEFAULTS["camp_accent_bonus"]), 0.01)
        params["post_camp_reduction"] = st.slider("Редукция след лагер", 0.00, 0.50, float(MODEL_DEFAULTS["post_camp_reduction"]), 0.01)
    with c3:
        params["taper_length_weeks"] = st.slider("Тейпър седмици", 1, 4, int(MODEL_DEFAULTS["taper_length_weeks"]), 1)
        params["taper_reduction_week_1"] = st.slider("Тейпър редукция седмица 1", 0.00, 0.70, float(MODEL_DEFAULTS["taper_reduction_week_1"]), 0.01)
        params["taper_reduction_week_2"] = st.slider("Тейпър редукция седмица 2", 0.00, 0.80, float(MODEL_DEFAULTS["taper_reduction_week_2"]), 0.01)
        params["high_intensity_preservation"] = st.slider("Запазване на интензивността", 0.30, 1.00, float(MODEL_DEFAULTS["high_intensity_preservation"]), 0.01)

    st.subheader("Recovery множители")
    recovery_df = st.data_editor(st.session_state.recovery_df, num_rows="dynamic", use_container_width=True, key="recovery_editor")
    st.session_state.recovery_df = recovery_df

with tab_calendar:
    st.subheader("Календар на събитията")
    st.write("Типове: `camp`, `control_race`, `main_race`, `recovery_block`.")
    edited_events = st.data_editor(
        st.session_state.events_df,
        num_rows="dynamic",
        use_container_width=True,
        key="events_editor",
        column_config={
            "event_name": st.column_config.TextColumn("Име"),
            "event_type": st.column_config.SelectboxColumn("Тип", options=["camp", "control_race", "main_race", "recovery_block"]),
            "start_week": st.column_config.NumberColumn("Начална седмица", min_value=1, max_value=60, step=1),
            "duration_days": st.column_config.NumberColumn("Дни", min_value=1, max_value=60, step=1),
            "priority": st.column_config.NumberColumn("Приоритет", min_value=1, max_value=3, step=1),
            "notes": st.column_config.TextColumn("Бележки"),
        },
    )
    st.session_state.events_df = edited_events

with tab_methods:
    st.subheader("База от тренировъчни методи")
    st.write(
        "Качи Excel/CSV база с тренировъчни методи. Препоръчителен лист в Excel: `Methods_DB`. "
        "Минимални колони: `method_id`, `primary_component`, `phase`, `title`, `template_text`, `Z1`...`SSI` "
        "или `zone_distribution`."
    )
    uploaded_methods_file = st.file_uploader(
        "Качи training_methods.xlsx или training_methods.csv",
        type=["xlsx", "xls", "csv"],
        key="methods_uploader",
    )
    if uploaded_methods_file is not None:
        active_methods = load_methods(uploaded_methods_file, file_name=uploaded_methods_file.name)
        st.success(f"Заредени са {len(active_methods)} метода от файла: {uploaded_methods_file.name}")
    else:
        active_methods = load_methods("training_methods.xlsx")
        if active_methods and len(active_methods) == 8:
            # If no xlsx exists, load_methods returns the 8 fallback methods. Try CSV too.
            csv_methods = load_methods("training_methods.csv")
            if len(csv_methods) != 8 or csv_methods != active_methods:
                active_methods = csv_methods
        if active_methods:
            st.info(
                "Не е качен външен файл. Използва се `training_methods.csv`, ако съществува в проекта, "
                "или вградената fallback база."
            )

    methods_preview_df = methods_to_dataframe(active_methods)
    st.dataframe(methods_preview_df, use_container_width=True, height=420)
    st.caption(
        "Важно: `template_text` може да съдържа placeholders като `{Z1_min}`, `{Z3_min}`, `{OSI_min}`, `{total_min}`. "
        "При генериране на микроцикъл приложението ги заменя с плановите минути за конкретния ден."
    )

# Shared generation
try:
    components_valid_raw = validate_components(st.session_state.components_df)
    if auto_scale_to_initial_volume:
        components_valid = scale_components_to_total_volume(
            components_valid_raw,
            float(initial_weekly_volume_hours) * 60.0,
        )
    else:
        components_valid = components_valid_raw
    baseline_loads = dict(zip(st.session_state.baseline_df["component_id"], st.session_state.baseline_df["baseline_daily_load"]))
    cascade_coeff = {int(r["distance"]): float(r["coefficient"]) for _, r in st.session_state.cascade_df.iterrows()}
    recovery_mult = dict(zip(st.session_state.recovery_df["component_id"], st.session_state.recovery_df["recovery_multiplier"]))
    # Update global recovery config through params-like dict; planner reads config defaults but recovery multipliers are used from config only.
    # For simplicity, edited recovery table is shown and saved, but full custom use can be added next.
    weekly_plan_df, weekly_summary_df = generate_weekly_plan(
        components_valid,
        st.session_state.events_df,
        params=params,
        baseline_daily_loads=baseline_loads,
        cascade_coefficients=cascade_coeff,
    )
except Exception as exc:
    st.error(f"Грешка при генериране: {exc}")
    st.stop()

with tab_weekly:
    st.subheader("Седмична вълнообразна динамика")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Седмици", total_weeks)
    m2.metric("Начален обем", f"{initial_weekly_volume_hours:.1f} ч")
    m3.metric("Месечна прогресия", f"{monthly_progression_rate*100:.1f}%")
    m4.metric("Пик около седмица", round(total_weeks * peak_fraction))
    st.caption(
        f"Нарастването на общия обем е до {peak_fraction*100:.0f}% от периода до основния старт "
        f"(около седмица {round(total_weeks * peak_fraction)}), след което се прилага редукция {post_peak_reduction*100:.0f}% "
        "и акцентът се измества към по-специфичните/скоростни компоненти."
    )
    actual_base_hours = float(components_valid["base_weekly_load"].sum()) / 60.0
    st.caption(f"Активна базова сума на компонентите за изчисленията: {actual_base_hours:.2f} ч/седмица.")

    st.markdown("### 1) 7/40 индекс по компоненти")
    fig_index = px.line(
        weekly_plan_df,
        x="week",
        y="target_7_40_index",
        color="component_id",
        markers=True,
        hover_data=["component", "week_type", "status", "real_weekly_load", "effective_weekly_load", "note"],
        title="Целеви 7/40 индекс — вълнообразна динамика по компоненти",
    )
    fig_index.add_hrect(y0=0.00, y1=0.85, fillcolor="green", opacity=0.08, line_width=0)
    fig_index.add_hrect(y0=0.85, y1=1.10, fillcolor="yellow", opacity=0.08, line_width=0)
    fig_index.add_hrect(y0=1.10, y1=1.60, fillcolor="orange", opacity=0.08, line_width=0)
    fig_index.add_hrect(y0=1.60, y1=2.00, fillcolor="red", opacity=0.08, line_width=0)
    fig_index.add_hline(y=0.85, line_dash="dash", annotation_text="0.85 възстановително")
    fig_index.add_hline(y=1.10, line_dash="dash", annotation_text="1.10 развиващо")
    fig_index.add_hline(y=1.60, line_dash="dash", annotation_text="1.60 риск")
    fig_index.update_layout(height=650, xaxis=dict(dtick=1), yaxis_title="Target 7/40")
    st.plotly_chart(fig_index, use_container_width=True)

    st.markdown("### 2) Общ седмичен обем")
    fig_total = go.Figure()
    fig_total.add_trace(go.Scatter(x=weekly_summary_df["week"], y=weekly_summary_df["total_real_load"] / 60.0, mode="lines+markers", name="Реален планиран обем (ч)"))
    fig_total.add_trace(go.Scatter(x=weekly_summary_df["week"], y=weekly_summary_df["total_effective_load"] / 60.0, mode="lines+markers", name="Ефективен физиологичен товар (ч екв.)"))
    fig_total.update_layout(title="Общ товар по седмици", height=450, xaxis_title="Седмица", yaxis_title="Часове / еквивалентни часове", xaxis=dict(dtick=1))
    st.plotly_chart(fig_total, use_container_width=True)

    st.markdown("### 3) Реален седмичен обем по компоненти")
    fig_area = px.area(
        weekly_plan_df,
        x="week",
        y="real_weekly_load",
        color="component_id",
        hover_data=["component", "target_7_40_index", "computed_7_40_index"],
        title="Реален планиран седмичен обем по компоненти",
    )
    fig_area.update_layout(height=550, yaxis_title="Минути")
    st.plotly_chart(fig_area, use_container_width=True)

    st.markdown("### 4) Карта на стреса")
    heat = weekly_plan_df.pivot(index="component_id", columns="week", values="target_7_40_index")
    fig_heat = px.imshow(heat, aspect="auto", color_continuous_scale="RdYlGn_r", title="Heatmap на target 7/40 индекса")
    fig_heat.update_layout(height=420)
    st.plotly_chart(fig_heat, use_container_width=True)

    st.markdown("### 5) Таблица — седмични цели")
    st.dataframe(weekly_plan_df, use_container_width=True, height=420)

    st.markdown("### Автоматична проверка")
    issues = diagnostic_checks(weekly_plan_df, weekly_summary_df, params)
    if issues:
        for issue in issues:
            st.warning(issue)
    else:
        st.success("Планът спазва основните ограничения за акценти, риск и възстановителни седмици.")

with tab_micro:
    st.subheader("Генериране на микроцикъл")

    # Keep the selected week in an explicit session_state key.
    # Without a stable key, Streamlit may visually change the selector while some
    # downstream charts remain bound to the first rendered dataframe in certain
    # cloud reruns. This also protects the app when total_weeks is changed.
    week_options = list(range(1, total_weeks + 1))
    if "micro_week" not in st.session_state or st.session_state["micro_week"] not in week_options:
        st.session_state["micro_week"] = 1

    selected_week = st.selectbox("Избери седмица", options=week_options, key="micro_week")
    st.caption(f"Показани са данни за седмица {selected_week}.")

    methods = active_methods
    daily_plan_df, readiness_df, micro_warnings = generate_microcycle(
        int(selected_week),
        weekly_plan_df,
        components_valid,
        params=params,
        methods=methods,
    )

    # Extra safety: keep only the selected week in the microcycle outputs.
    if not daily_plan_df.empty and "week" in daily_plan_df.columns:
        daily_plan_df = daily_plan_df[daily_plan_df["week"] == int(selected_week)].copy()
    if not readiness_df.empty and "week" in readiness_df.columns:
        readiness_df = readiness_df[readiness_df["week"] == int(selected_week)].copy()

    week_start = start_date + timedelta(days=(int(selected_week) - 1) * 7)
    if not daily_plan_df.empty:
        daily_plan_df["date"] = [week_start + timedelta(days=i) for i in range(len(daily_plan_df))]
        cols = ["week", "day", "date", "day_name", "main_focus", "method", "method_id"] + [cid for cid in components_valid["id"].tolist() if cid in daily_plan_df.columns] + ["total_real_min", "readiness_before_main", "readiness_after_main", "method_notes", "warnings"]
        st.dataframe(daily_plan_df[cols], use_container_width=True, height=360)

        st.markdown(f"### Readiness динамика — седмица {selected_week}")
        fig_readiness = px.line(
            readiness_df,
            x="day",
            y="readiness_after",
            color="component_id",
            markers=True,
            hover_data=["week", "component", "day_name", "real_day_load", "effective_day_load"],
            title=f"Readiness след дневното натоварване — седмица {selected_week}",
        )
        fig_readiness.add_hline(y=90, line_dash="dash", annotation_text="90% ключова тренировка")
        fig_readiness.add_hline(y=80, line_dash="dash", annotation_text="80% умерена")
        fig_readiness.add_hline(y=60, line_dash="dash", annotation_text="60% минимум")
        fig_readiness.update_layout(height=520, yaxis=dict(range=[0, 105]), xaxis=dict(dtick=1))
        st.plotly_chart(fig_readiness, use_container_width=True, key=f"readiness_chart_week_{selected_week}")

        st.markdown(f"### Планирано в микроцикъла спрямо седмичната цел — седмица {selected_week}")
        comparison_df = compare_weekly_target_vs_plan(weekly_plan_df[weekly_plan_df["week"] == int(selected_week)], daily_plan_df)
        fig_compare = px.bar(
            comparison_df,
            x="component_id",
            y=["target_weekly_load", "microcycle_planned_load"],
            barmode="group",
            title=f"Седмична цел срещу разпределение в микроцикъла — седмица {selected_week}",
        )
        st.plotly_chart(fig_compare, use_container_width=True, key=f"compare_chart_week_{selected_week}")
        st.dataframe(comparison_df, use_container_width=True)

        if micro_warnings:
            st.markdown("### Предупреждения")
            for w in micro_warnings:
                st.warning(w)
        else:
            st.success("Микроцикълът не нарушава readiness праговете според текущите настройки.")

with tab_export:
    st.subheader("Експорт")
    export_week_options = list(range(1, total_weeks + 1))
    if "export_week" not in st.session_state or st.session_state["export_week"] not in export_week_options:
        st.session_state["export_week"] = 1
    selected_week_export = st.selectbox("Седмица за експорт на микроцикъл", options=export_week_options, key="export_week")
    daily_plan_export, readiness_export, warnings_export = generate_microcycle(
        int(selected_week_export),
        weekly_plan_df,
        components_valid,
        params=params,
        methods=active_methods,
    )
    if not daily_plan_export.empty and "week" in daily_plan_export.columns:
        daily_plan_export = daily_plan_export[daily_plan_export["week"] == int(selected_week_export)].copy()
    if not readiness_export.empty and "week" in readiness_export.columns:
        readiness_export = readiness_export[readiness_export["week"] == int(selected_week_export)].copy()
    comparison_export = compare_weekly_target_vs_plan(weekly_plan_df[weekly_plan_df["week"] == int(selected_week_export)], daily_plan_export)

    excel_bytes = dataframes_to_excel_bytes(
        {
            "weekly_plan": weekly_plan_df,
            "weekly_summary": weekly_summary_df,
            "microcycle": daily_plan_export,
            "readiness": readiness_export,
            "target_vs_plan": comparison_export,
            "components": components_valid,
            "events": st.session_state.events_df,
        }
    )
    st.download_button(
        "⬇️ Изтегли пълния план като Excel",
        data=excel_bytes,
        file_name="training_load_dynamics_plan.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    csv_bytes = weekly_plan_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Изтегли седмичната динамика като CSV",
        data=csv_bytes,
        file_name="weekly_load_dynamics.csv",
        mime="text/csv",
    )

    st.info("Можеш да качиш база от тренировки в таб `База тренировки`. За постоянна база в GitHub добави файл `training_methods.xlsx` или `training_methods.csv` и го зареждай от приложението.")
