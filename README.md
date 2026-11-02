# School Period Length Impact Simulator

A local Streamlit decision-support dashboard comparing 15-, 20-, 30- and 35-minute teaching periods. All supplied requirements are synthetic examples, **not official MOE minimums**.

## Run locally

Python 3.10 or newer is required. From this directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

On Windows, replace the activation command with `.venv\Scripts\activate`.
Open the local URL printed by Streamlit (normally http://localhost:8501).

Run automated tests:

```bash
python -m pytest -q
```

## Inputs

Download the template in the app or use `school_period_input_template.xlsx`. Upload a completed `.xlsx` file, expand **Edit inputs**, and edit cells or add/remove rows. Calculations refresh on each edit. Invalid or missing inputs produce an error until corrected.

The workbook has three data sheets and a Read Me sheet:

- **Subject Requirements**: one unique level/subject row, non-negative weekly requirement, unit `minutes` or `periods`, and a positive reference duration when unit is `periods`. Fractions are accepted as requirements; allocations must be whole periods.
- **School Day Settings**: exactly one row per level for each Monday–Friday, starting time, desired earliest dismissal and latest permitted dismissal. Enter times as 24-hour `HH:MM` strings or Excel time cells. Overnight days are unsupported.
- **Fixed Activities**: one row per mandatory activity, level, weekday, activity name, start and end. This separate normalized sheet is part of the school-day settings and permits any number of breaks per day without duplicating daily settings. It can be empty with its headers retained. Activities must lie within the day and cannot overlap; adjacent activities are allowed.

Subjects and day settings must contain the same levels. Duplicate subjects per level and duplicate daily settings are rejected. Reference duration is ignored for minute-based requirements.

## Calculations and interpretation

Period-based requirements are explicitly converted to minutes using their stated reference duration. For each subject, `minimum periods = ceiling(required minutes / scenario length)`. Rounding happens per subject before weekly totals. Decimal arithmetic avoids rounding errors at boundaries. Rounding excess refers to automatic allocations; signed balance refers to actual allocated minutes minus required minutes.

Optional manual allocations apply independently to each subject, level and scenario. A positive subject balance is excess; a negative balance is a shortfall. Surplus in one subject never satisfies a shortfall in another.

Daily capacity counts whole periods inside uninterrupted teaching windows. Periods begin at each window's start; fragments before breaks are unused and cannot be combined across breaks. Slots may end exactly when a break starts or start exactly when one ends.

The estimator repeatedly assigns a period to the least-filled day with remaining capacity, breaking ties Monday first. It packs those periods into that day's earliest slots. Dismissal is the later of the final allocated slot and final mandatory fixed activity. This balances counts, not dismissal clock times. There is no padding to the desired earliest time. The desired dismissal window is earliest through latest inclusive.

Latest permitted dismissal is a hard capacity limit: lessons that cannot fit are reported as **insufficient periods**, not placed after the limit. Thus late dismissal is checked but cannot arise under this model; change the latest limit to explore longer days. Early finishes are flagged. During shortages, dismissal charts describe only the lessons that fit. Weekly actual teaching minutes describe requested allocations even when some cannot fit. The comparison separately shows minimum demand, allocated demand, capacity, unused capacity, and shortage.

The all-level view keeps each level separate; capacities are never pooled. Charts include exact values and accompanying tables. The results download always includes all levels and four scenarios, edited inputs, assumptions, allocations, daily estimates and warnings regardless of the chart filter.

## Version 1 limitations

This is not a timetable generator and does not prove a feasible subject timetable. It models one representative teaching week per level, with no teacher or venue allocation, subject combination banding, lesson sequencing, double-period constraints, class differences, travel time, holidays, or OR-Tools optimisation. Daily activities are mandatory even after the last teaching slot. A planner must validate any resulting timetable separately.

## Files

- `app.py`: Streamlit UI and Plotly charts.
- `simulator.py`: validation, independent calculation functions, sample data and Excel IO.
- `school_period_input_template.xlsx`: synthetic editable example workbook.
- `tests/test_simulator.py`: calculation and workbook tests.
- `requirements.txt`: runtime and test dependencies.
