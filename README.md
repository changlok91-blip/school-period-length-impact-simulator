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

Subject Requirements columns are **Level → Stream → Subject → Minimum weekly requirement → Unit → Reference period duration in minutes → Elective group**. A subject may appear once in each level/stream combination. Different streams can have different subjects and different requirements. Blank identifiers and duplicate rows within the same combination are rejected.

Minimum weekly requirement must be a finite number >= 0. Unit must be `minutes` or `periods`. For period-based requirements a positive reference duration is required: for example 5 periods at 30 minutes means 150 required teaching minutes. For minute-based requirements the reference may be blank; if supplied it must be a positive number and is ignored in the conversion. Fractional requirements are accepted; allocations are whole periods.

The **Lists** sheet holds independent Level, Stream, Subject, Unit and Elective group choices, one per cell. Rename or append entries without blank gaps within rows 2–1001. These list columns do not define combinations by row. Unit choices must remain `minutes` and/or `periods`. Dropdowns and numeric validation cover Subject Requirements rows 2–5001. Keep sheet names and column headings unchanged.

Excel paste operations can bypass validation. The app checks list membership on upload and validates subject calculations again. Older workbooks without Stream load as `General`; older workbooks without Lists also remain supported. Dynamic dropdown compatibility may differ in spreadsheet software other than Microsoft Excel.

## Adjust periods and see curriculum hours

1. Move **Minutes per period** to 15, 20, 30 or 35.
2. In the subject table, read **Minimum periods**: `ceiling(required minutes / selected period length)`. Each subject is rounded separately before totals.
3. Edit **Adjustment (periods)**: enter `1` or `2` to add periods, `-1` or `-2` to subtract, or `0` to use the minimum. Any signed whole number is allowed if the final allocation remains non-negative.
4. The same table updates **Allocated periods**, **Actual minutes**, **Balance minutes** and **Requirement status**. A negative balance is a shortfall; zero or positive meets the requirement. Subject surpluses never satisfy another subject's shortfall.
5. Read **Weekly curriculum hours by level and stream**. It totals allocated periods × selected minutes for compulsory subjects and one selected elective per group, separately for each level/stream. **Curriculum hours** is decimal hours displayed to two decimals; **Curriculum minutes** and **Curriculum time** give exact minutes and hours/minutes. Totals include both rounding and adjustments. **Subjects below minimum** keeps shortfalls visible even if overall minutes are sufficient.

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

The layout uses the current slider, adjusted allocations, compulsory subjects and the selected elective from each group. Different elective choices can yield different dismissal times. School Day Settings and Fixed Activities apply to all streams in that level. Earliest dismissal is now a **mandatory floor**, not a preference, in this output. Latest dismissal is a hard upper limit. Periods pack from the start of uninterrupted teaching windows; no period crosses a fixed activity, and leftover fragments cannot be joined across breaks. All fixed activities remain mandatory, including those after the last teaching period.

To balance clock times, the estimator finds the earliest common clock-time horizon that offers enough slots across all five days, clamped to each day's mandatory floor and latest limit. It then repeatedly assigns the next period to the day with the earliest resulting dismissal, breaking ties by period count and weekday. This is a heuristic; it does not guarantee the smallest possible dismissal spread. Different start times and daily limits may yield different dismissal times.

If lessons end before the earliest dismissal (or before a later fixed activity), the gap is labelled **unallocated school time**. This is not counted as teaching or curriculum hours; the school must decide activities/supervision for it. A late mandatory activity can also determine dismissal. Insufficient weekly capacity is flagged as unplaced periods: the layout contains only periods that fit and does not imply the whole curriculum has been placed.

Teaching blocks are generic numbered periods. No subjects, teachers or rooms are assigned, and the layout is not a valid subject timetable. Adjusting periods changes both curriculum hours and this layout immediately. Invalid day settings hide only the layout, preserving the curriculum table above.

## Compulsory subjects and elective groups

Each student takes all compulsory subjects and **one subject from each independent elective group** in their level/stream. Group names are configurable: for example Humanities choice and Arts choice. The same group name may be reused across levels/streams; its options and selections are independent for each combination.

1. Before downloading, optionally enter your group names under **Elective groups**. The downloaded Lists sheet includes these choices.
2. On Subject Requirements, leave **Elective group** blank for compulsory subjects. Give alternative subjects the same group name. Example: English blank, Mathematics blank, History and Geography both Humanities choice, Art/Music/Drama all Arts choice.
3. Upload the completed file. The app shows one selector per level/stream/group; the first option is selected initially. Select the electives for the example student pathway you want to inspect.
4. The adjustment table shows all options, with **Selected** marking the rows counted. Curriculum totals and weekly layouts count only compulsory subjects and the selected options, never all alternatives together. Subject warnings and below-minimum counts refer to this selected pathway.
5. **Minimum pathway hours** and **Maximum pathway hours** show the range across all independent choices, after per-subject rounding and manual adjustments. Curriculum hours/time are for the specific selected pathway. Change a selector to explore another pathway's weekly layout and dismissal.

You can also type group names directly in the app's Subject Requirements editor. When editing Excel, add group names to Lists first and use the dropdown. Old files without Elective group remain entirely compulsory. Each subject can belong to one group at most within a level/stream and appears only once. The model does not support combinations that restrict choices across groups, choosing multiple subjects within a group, elective synchronisation, or class/teacher allocation. A weekly layout for one selected pathway does not represent all students' pathways simultaneously.

## Common requirements: CMN

The template setup defaults to **G3, G2, G1, CMN**. CMN is a shared input label, not a fourth student curriculum. Enter common subjects once with Stream = CMN. At that level their requirements are inherited independently by the configured recipient streams, even if a target stream has no other subject rows. Common rows are never inherited by other levels. Custom stream names receive CMN when listed as recipients.

Example: Sec 1 / CMN / PE / 90 minutes and Sec 1 / G1 / Mathematics / 150 minutes gives G1 both PE and Mathematics; G2 and G3 each inherit PE. If Sec 1 / G2 / PE / 120 minutes is also entered, G2 uses 120 minutes for PE instead of 90; it does not add both. The specific row replaces the whole common subject row, including unit, reference duration and elective group. Subject names must match exactly for an override. Stream codes G3/G2/G1/CMN are case-insensitive.

Delete unused placeholder rows in the custom template, including blank specific rows for subjects represented by CMN. All retained rows need complete requirements. The **Requirement source** column in the adjustment table shows whether a subject came from CMN or a specific stream. Period adjustments are made separately for each actual stream; to change a common baseline, edit its CMN input row. CMN does not appear as a separate curriculum total or weekly view.

CMN elective groups are inherited too. Students still choose one option per named group, independently for G3, G2 and G1. A stream-specific subject can replace a common option and its group membership. This does not model mixed-level subject placement or synchronised common classes.

## Use CMN with different stream names

CMN recipients are configurable, rather than fixed to G3/G2/G1. In template setup, enter all actual stream names plus CMN under Streams. The download creates **Stream Settings**, with one actual stream per row under **Stream receiving CMN**; CMN itself is excluded. For example, entering Alpha, Beta, Gamma and CMN creates recipients Alpha, Beta and Gamma. Every level containing a CMN requirement inherits it into each configured recipient, even when that recipient has no specific subject rows.

When uploading, the app restores this setting. Expand **Common stream settings** below Edit inputs to inspect or change **Streams receiving CMN** before calculating. Change this list when changing names in the subject editor; changing only a subject row does not rename its configuration. The displayed CMN recipients list makes the active scope explicit. Do not leave it empty when using common requirements and do not list CMN itself. Specific rows for the same subject still replace the inherited row.

The setting applies across all levels containing CMN. If different levels have entirely different stream sets, split the workbooks by context. Adding a recipient with no specific rows still produces its common-only curriculum. Unsupported recipient names are not silently discarded.

Older workbooks without Stream Settings infer recipients from the Stream column on Lists, excluding CMN; if no actual streams are available, legacy G3/G2/G1 defaults are used. Direct calculation callers can pass `common_streams=[...]` or set `subjects.attrs['common_streams']`. Files without Lists retain the legacy defaults. Workbook exports preserve an uploaded common-stream configuration.
