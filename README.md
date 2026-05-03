# Training Load Dynamics Planner

Streamlit прототип за планово генериране на тренировъчна динамика и микроцикъл.

## Какво включва

- Само физически компоненти: Z1, Z2, OSI, Z3, SSI, Z4, Z5, Z6.
- Вълнообразна седмична динамика на 7/40 индекса.
- Прогресия на общия товар чрез `monthly_progression_rate`, напр. 4% на месец.
- Пик на общото натоварване около `peak_fraction`, напр. 0.50 от периода.
- След пика: леко намаляване на общия обем и изместване към по-специфични компоненти.
- Ефективен физиологичен товар: базов дневен товар + каскада + разлив.
- Recovery/readiness модел с насищаща експоненциална крива.
- Генериране на микроцикъл по дни.
- Excel/CSV експорт.

## Стартиране

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Файлове

- `app.py` — Streamlit интерфейс.
- `config.py` — настройки и начални стойности.
- `load_model.py` — седмична динамика, ефективен товар, 7/40 индекс.
- `recovery_model.py` — recovery/readiness модел.
- `planner.py` — микроцикъл по дни.
- `methods_library.py` — fallback тренировъчни методи и бъдеща библиотека.
- `export_utils.py` — Excel export.

## По желание: training_methods.csv

Можеш да добавиш файл `training_methods.csv` със следните колони:

```text
method_id,component,phase,title,description,zone_distribution,default_duration_min,min_readiness,max_percent_tref,tags
```

Пример:

```csv
method_id,component,phase,title,description,zone_distribution,default_duration_min,min_readiness,max_percent_tref,tags
z3_4x8,Z3,middle,4 x 8 мин Z3,Темпово натоварване в средна/горна Z3,"{""Z1"": 0.35, ""Z3"": 0.65}",52,90,0.55,"threshold,tempo"
```

Ако този файл липсва, приложението използва вътрешни примерни методи.


## Update: cascade and spillover logic

The default model now uses a one-way 100% cascade from higher zones to all lower zones. This reflects full physiological participation of lower-threshold fibres during higher-intensity work. Lower zones do not cascade upward automatically.

Threshold spillover is separate and activates only when the daily load in a zone exceeds the configured fraction of Tref. By default, spillover is asymmetric: 20% of the excess goes downward to the lower neighboring zone, and 10% of the excess goes upward to the higher neighboring zone.

## База от тренировъчни методи

Версия v6 поддържа зареждане на външен файл с тренировъчни методи през таб **База тренировки**.

Поддържани формати:
- `training_methods.xlsx` с лист `Methods_DB`
- `training_methods.csv`

Основни колони:
- `method_id`
- `primary_component` или `component` — Z1, Z2, Z3, Z4, Z5, Z6, OSI, SSI
- `phase` — `early`, `middle`, `late`, `any`
- `title`
- `template_text` или `description`
- `Z1`, `Z2`, `Z3`, `Z4`, `Z5`, `Z6`, `OSI`, `SSI` — примерни минути/обем от метода
- `zone_distribution` — JSON алтернатива, напр. `{\"Z1\": 20, \"Z3\": 32}`
- `min_readiness`
- `max_percent_tref`
- `tags`

Шаблонът `template_text` може да съдържа placeholders като `{Z1_min}`, `{Z2_min}`, `{Z3_min}`, `{Z4_min}`, `{Z5_min}`, `{Z6_min}`, `{OSI_min}`, `{SSI_min}`, `{total_min}`. При генериране на микроцикъл те се заменят с плановите минути за конкретния ден.
