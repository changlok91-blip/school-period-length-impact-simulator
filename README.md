# School Period Length Impact Simulator

A local Streamlit decision-support app for Singapore secondary school planners. All supplied requirements are synthetic examples, **not official MOE minimums**.

The dashboard shows minimum whole periods per subject, editable period adjustments, weekly curriculum hours, and an illustrative five-day layout with dismissal estimates for each level and stream. The earlier four-scenario comparison and heatmap remain removed.

## Run locally

Python 3.10 or newer is required. From this directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

On Windows use `.venv\Scripts\activate` instead of the activation command above. Open the local URL printed by Streamlit (normally http://localhost:8501).

Run automated tests:

```bash
python -m pytest -q
```

## Prepare the Excel workbook

1. In **1. Set up your Excel template**, enter levels, streams and subjects, one per line. Choose `minutes`, `periods` or both as the available units. Click outside each edited box so the download updates.
2. Click **Download my Excel template**. The workbook contains your choices and a blank weekly-requirement row for every level × stream × subject combination. Blank lines are ignored and duplicate choices are removed. Up to 1,000 choices per list and 5,000 generated combinations are supported.
3. In Excel, delete combinations that do not apply and fill in every remaining requirement. The first selected unit is prefilled; change it per row as needed. Alternatively, download the populated synthetic example.
4. Review the illustrative School Day Settings and Fixed Activities, then save as `.xlsx` and upload. These sheets determine the weekly layout. The curriculum-hours calculation itself uses subject requirements only.

Setting up a template does not change the active dashboard until you upload the completed workbook. Without an upload the app uses synthetic sample inputs. Expand **Edit inputs** to edit uploaded values directly in the app.

## Subject requirements and dropdowns

Subject Requirements columns are **Level → Stream → Subject → Minimum weekly requirement → Unit → Reference period duration in minutes**. A subject may appear once in each level/stream combination. Different streams can have different subjects and different requirements. Blank identifiers and duplicate rows within the same combination are rejected.

Minimum weekly requirement must be a finite number >= 0. Unit must be `minutes` or `periods`. For period-based requirements a positive reference duration is required: for example 5 periods at 30 minutes means 150 required teaching minutes. For minute-based requirements the reference may be blank; if supplied it must be a positive number and is ignored in the conversion. Fractional requirements are accepted; allocations are whole periods.

The **Lists** sheet holds independent Level, Stream, Subject and Unit choices, one per cell. Rename or append entries without blank gaps within rows 2–1001. These four columns do not define combinations by row. Unit choices must remain `minutes` and/or `periods`. Dropdowns and numeric validation cover Subject Requirements rows 2–5001. Keep sheet names and column headings unchanged.

Excel paste operations can bypass validation. The app checks list membership on upload and validates subject calculations again. Older workbooks without Stream load as `General`; older workbooks without Lists also remain supported. Dynamic dropdown compatibility may differ in spreadsheet software other than Microsoft Excel.

## Adjust periods and see curriculum hours

1. Move **Minutes per period** to 15, 20, 30 or 35.
2. In the subject table, read **Minimum periods**: `ceiling(required minutes / selected period length)`. Each subject is rounded separately before totals.
3. Edit **Adjustment (periods)**: enter `1` or `2` to add periods, `-1` or `-2` to subtract, or `0` to use the minimum. Any signed whole number is allowed if the final allocation remains non-negative.
4. The same table updates **Allocated periods**, **Actual minutes**, **Balance minutes** and **Requirement status**. A negative balance is a shortfall; zero or positive meets the requirement. Subject surpluses never satisfy another subject's shortfall.
5. Read **Weekly curriculum hours by level and stream**. It totals allocated periods × selected minutes separately for each combination. **Curriculum hours** is decimal hours displayed to two decimals; **Curriculum minutes** and **Curriculum time** give exact minutes and hours/minutes. Totals include both rounding and adjustments. **Subjects below minimum** keeps shortfalls visible even if overall minutes are sufficient.

Example: a 150-minute requirement at 20 minutes needs 8 periods and provides 160 minutes. An adjustment of +2 gives 10 periods/200 minutes. An adjustment of -1 gives 7 periods/140 minutes and flags a 10-minute shortfall.

Adjustments are stored per subject identity and period length during the current Streamlit session. Switching period lengths starts with that length's existing adjustments, or zero for a new length; switching back restores earlier adjustments. Reordering rows cannot move adjustments to another subject. **Reset all period adjustments** clears every period-length scenario. Adjustments are not saved into the source Excel file and are lost when the session ends. If a requirement changes so an existing negative adjustment becomes invalid, the editor stays available to correct it; totals are hidden until corrected.

## Limits

These are weekly allocated curriculum hours, not a timetable feasibility check. The weekly layout separately checks whole-period capacity against school-day settings. Teachers, venues, combinations, subject sequencing, class counts, travel time and holidays are not modeled. Totals describe a representative curriculum for each level/stream, not pooled school staffing demand. This app does not generate subject timetables or use OR-Tools.

## Files

- `app.py`: template setup, input editors, minutes-per-period control and focused curriculum output.
- `simulator.py`: Excel IO, validation and separate calculation functions. The UI uses `curriculum_allocation` and `estimate_week`; earlier scenario functions remain for regression tests.
- `school_period_input_template.xlsx`: populated synthetic example with dropdowns and numeric validation.
- `tests/`: Excel, calculation and Streamlit interaction tests.
- `requirements.txt`: runtime and test dependencies.

## Illustrative weekly layout

After the hours table, see Monday–Friday estimated dismissal times for every level/stream. Choose a level and stream to view a colour-coded timeline: teaching periods, fixed activities, and unallocated school time. Exact block start/end times and daily counts are available below the chart.

The layout uses the current slider and adjusted allocations. School Day Settings and Fixed Activities apply to all streams in that level. Earliest dismissal is now a **mandatory floor**, not a preference, in this output. Latest dismissal is a hard upper limit. Periods pack from the start of uninterrupted teaching windows; no period crosses a fixed activity, and leftover fragments cannot be joined across breaks. All fixed activities remain mandatory, including those after the last teaching period.

To balance clock times, the estimator finds the earliest common clock-time horizon that offers enough slots across all five days, clamped to each day's mandatory floor and latest limit. It then repeatedly assigns the next period to the day with the earliest resulting dismissal, breaking ties by period count and weekday. This is a heuristic; it does not guarantee the smallest possible dismissal spread. Different start times and daily limits may yield different dismissal times.

If lessons end before the earliest dismissal (or before a later fixed activity), the gap is labelled **unallocated school time**. This is not counted as teaching or curriculum hours; the school must decide activities/supervision for it. A late mandatory activity can also determine dismissal. Insufficient weekly capacity is flagged as unplaced periods: the layout contains only periods that fit and does not imply the whole curriculum has been placed.

Teaching blocks are generic numbered periods. No subjects, teachers or rooms are assigned, and the layout is not a valid subject timetable. Adjusting periods changes both curriculum hours and this layout immediately. Invalid day settings hide only the layout, preserving the curriculum table above.
