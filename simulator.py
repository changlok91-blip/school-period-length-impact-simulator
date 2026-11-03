"""Pure calculations and Excel IO for the period-length decision aid."""
from io import BytesIO
from decimal import Decimal, ROUND_CEILING
import datetime as dt
import pandas as pd
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.utils import get_column_letter

DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
LENGTHS = [15, 20, 30, 35]
SUB = ['Level', 'Subject', 'Minimum weekly requirement', 'Unit', 'Reference period duration in minutes']
DAY = ['Level', 'Day of week', 'Starting time', 'Desired earliest dismissal time', 'Latest permitted dismissal time']
ACT = ['Level', 'Day of week', 'Activity', 'Start', 'End']


def minute(value):
    if isinstance(value, (dt.datetime, dt.time, pd.Timestamp)):
        return value.hour * 60 + value.minute
    try:
        parts = str(value).strip().split(':')
        if len(parts) != 2:
            raise ValueError()
        h, m = map(int, parts)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError()
        return h * 60 + m
    except (TypeError, ValueError):
        raise ValueError(f'Invalid time {value!r}; use HH:MM (24-hour).')


def clock(value):
    return f'{int(value)//60:02d}:{int(value)%60:02d}'


def number(value, label, positive=False):
    try:
        x = Decimal(str(value))
        if not x.is_finite() or x < 0 or (positive and x == 0):
            raise ValueError()
        return x
    except Exception:
        raise ValueError(f'{label} must be a finite {"positive" if positive else "non-negative"} number.')


def validate(subjects, days, activities):
    for frame, columns, name in [(subjects, SUB, 'Subject Requirements'), (days, DAY, 'School Day Settings'), (activities, ACT, 'Fixed Activities')]:
        if not set(columns) <= set(frame.columns):
            raise ValueError(f'{name}: missing columns {set(columns)-set(frame.columns)}')
        if frame[columns[:2]].isna().any().any():
            raise ValueError(f'{name}: level and subject/day must be filled.')
        if any(not str(v).strip() for v in frame[columns[:2]].to_numpy().flatten()):
            raise ValueError(f'{name}: blank identifiers are not allowed.')
    if subjects.empty or days.empty:
        raise ValueError('Subject requirements and school day settings cannot be empty.')
    if subjects.duplicated(['Level', 'Subject']).any() or days.duplicated(['Level', 'Day of week']).any():
        raise ValueError('Duplicate subject or day rows are not allowed for a level.')
    if set(days.Level) != set(subjects.Level):
        raise ValueError('Levels in subject requirements and school day settings must match.')
    for level in subjects.Level.unique():
        if set(days.loc[days.Level == level, 'Day of week']) != set(DAYS):
            raise ValueError(f'{level}: provide exactly Monday through Friday.')
    for _, r in subjects.iterrows():
        number(r[SUB[2]], 'Requirement')
        if r.Unit not in ['minutes', 'periods']:
            raise ValueError('Unit must be minutes or periods.')
        if r.Unit == 'periods' or (pd.notna(r[SUB[4]]) and str(r[SUB[4]]).strip()):
            number(r[SUB[4]], 'Reference period duration', True)
    for _, r in days.iterrows():
        start, early, late = [minute(r[c]) for c in DAY[2:]]
        if not start <= early <= late or start == late:
            raise ValueError('Day times must satisfy start <= earliest <= latest, with start < latest.')
    for _, r in activities.iterrows():
        match = days[(days.Level == r.Level) & (days['Day of week'] == r['Day of week'])]
        if match.empty:
            raise ValueError('Activity has an unknown level or day.')
        s, e = minute(r.Start), minute(r.End)
        d = match.iloc[0]
        if not minute(d[DAY[2]]) <= s < e <= minute(d[DAY[4]]):
            raise ValueError('Activities must have positive duration and lie inside the school day.')
    for _, group in activities.groupby(['Level', 'Day of week']):
        intervals = sorted((minute(r.Start), minute(r.End)) for _, r in group.iterrows())
        if any(a[1] > b[0] for a, b in zip(intervals, intervals[1:])):
            raise ValueError('Fixed activities must not overlap.')


def slots_for_day(day, activities, length):
    number(length, 'Period length', True)
    cursor, limit = minute(day[DAY[2]]), minute(day[DAY[4]])
    ends = []
    for start, end in sorted((minute(r.Start), minute(r.End)) for _, r in activities.iterrows()) + [(limit, limit)]:
        while cursor + length <= start:
            cursor += length
            ends.append(cursor)
        cursor = end
    return ends


def _calculate_level(subjects, days, activities, overrides=None):
    validate(subjects, days, activities)
    overrides = overrides or {}
    detail, daily, summary, warnings = [], [], [], []
    for length in LENGTHS:
        for level in subjects.Level.unique():
            rows = []
            for _, r in subjects[subjects.Level == level].iterrows():
                required = number(r[SUB[2]], 'Requirement')
                if r.Unit == 'periods':
                    required *= number(r[SUB[4]], 'Reference duration', True)
                auto = int((required / Decimal(length)).to_integral_value(rounding=ROUND_CEILING))
                allocated = number(overrides.get((length, level, r.Subject), auto), 'Allocated periods')
                if allocated != int(allocated):
                    raise ValueError('Allocated periods must be whole numbers.')
                rows.append({'Period length': length, 'Level': level, 'Subject': r.Subject,
                             'Required minutes': float(required), 'Minimum periods': auto,
                             'Automatic minutes': auto*length, 'Rounding excess minutes': float(auto*length-required),
                             'Allocated periods': int(allocated), 'Actual minutes': int(allocated)*length,
                             'Balance minutes': float(int(allocated)*length-required)})
            detail.extend(rows)
            demand = sum(r['Allocated periods'] for r in rows)
            ds = [days[(days.Level == level) & (days['Day of week'] == d)].iloc[0] for d in DAYS]
            slots = [slots_for_day(d, activities[(activities.Level == level) & (activities['Day of week'] == d['Day of week'])], length) for d in ds]
            counts = [0]*5
            # Water-fill whole period counts, respecting each day's capacity. Ties favor Monday first.
            for _ in range(min(demand, sum(map(len, slots)))):
                candidates = [i for i in range(5) if counts[i] < len(slots[i])]
                i = min(candidates, key=lambda i: (counts[i], i))
                counts[i] += 1
            for i, d in enumerate(ds):
                acts = activities[(activities.Level == level) & (activities['Day of week'] == DAYS[i])]
                fixed_end = max([minute(x) for x in acts.End] or [minute(d[DAY[2]])])
                finish = max(slots[i][counts[i]-1] if counts[i] else minute(d[DAY[2]]), fixed_end)
                status = 'Early' if finish < minute(d[DAY[3]]) else 'Late' if finish > minute(d[DAY[4]]) else 'Within window'
                daily.append({'Period length': length, 'Level': level, 'Day': DAYS[i], 'Capacity periods': len(slots[i]), 'Assigned periods': counts[i], 'Unused periods': len(slots[i])-counts[i], 'Estimated dismissal': clock(finish), 'Dismissal minute': finish, 'Status': status})
                if status != 'Within window':
                    warnings.append({'Period length': length, 'Level': level, 'Warning': f'{DAYS[i]} estimated dismissal {clock(finish)}: {status.lower()}.'})
            capacity = sum(map(len, slots))
            summary.append({'Period length': length, 'Level': level, 'Required minutes': sum(r['Required minutes'] for r in rows), 'Minimum periods': sum(r['Minimum periods'] for r in rows), 'Allocated periods': demand, 'Actual minutes': sum(r['Actual minutes'] for r in rows), 'Rounding excess minutes': sum(r['Rounding excess minutes'] for r in rows), 'Balance minutes': sum(r['Balance minutes'] for r in rows), 'Capacity periods': capacity, 'Unused capacity periods': max(0, capacity-demand), 'Insufficient periods': max(0, demand-capacity)})
            if demand > capacity:
                warnings.append({'Period length': length, 'Level': level, 'Warning': f'Capacity shortage: {demand-capacity} allocated periods cannot fit. Dismissal estimates include only periods that fit.'})
            if any(r['Balance minutes'] < 0 for r in rows):
                warnings.append({'Period length': length, 'Level': level, 'Warning': 'Manual allocations leave one or more subject requirements unmet.'})
    return {'Comparison': pd.DataFrame(summary), 'Subject Calculations': pd.DataFrame(detail), 'Dismissal Estimates': pd.DataFrame(daily), 'Warnings': pd.DataFrame(warnings, columns=['Period length', 'Level', 'Warning'])}



def with_stream(subjects):
    """Legacy workbooks form one General stream; explicit stream cells are required."""
    subjects = subjects.copy()
    if 'Stream' not in subjects:
        subjects['Stream'] = 'General'
    if subjects['Stream'].isna().any() or any(not str(v).strip() for v in subjects['Stream']):
        raise ValueError('Stream must be filled for every subject row.')
    subjects['Stream'] = subjects['Stream'].astype(str).str.strip()
    columns = [column for column in subjects.columns if column != 'Stream']
    columns.insert(columns.index('Level') + 1 if 'Level' in columns else 0, 'Stream')
    return subjects.loc[:, columns]


def calculate(subjects, days, activities, overrides=None):
    subjects = with_stream(subjects)
    # Validate all levels/settings together, then reuse the single-level engine per stream.
    validation = subjects.copy()
    validation['Subject'] = range(len(validation))
    validate(validation, days, activities)
    if subjects.duplicated(['Level', 'Stream', 'Subject']).any():
        raise ValueError('Duplicate subject rows are not allowed within the same level and stream.')
    pieces = {}
    for (level, stream), group in subjects.groupby(['Level', 'Stream'], sort=False):
        scoped = {}
        for key, value in (overrides or {}).items():
            if len(key) == 4 and key[1:3] == (level, stream):
                scoped[(key[0], level, key[3])] = value
            elif len(key) == 3 and stream == 'General' and key[1] == level:
                scoped[key] = value
        result = _calculate_level(group, days[days.Level == level], activities[activities.Level == level], scoped)
        for name, frame in result.items():
            frame.insert(2, 'Stream', stream)
            pieces.setdefault(name, []).append(frame)
    return {name: pd.concat(frames, ignore_index=True) for name, frames in pieces.items()}


def sample_data():
    subjects, days, acts = [], [], []
    for n in range(1, 5):
        level = f'Sec {n}'
        for subject, requirement in [('English', 210), ('Mathematics', 210), ('Mother Tongue', 180), ('Science', 180), ('Humanities', 150), ('Physical Education', 90), ('Arts / Electives', 150)]:
            subjects.append([level, subject, requirement, 'minutes', None])
        subjects.append([level, 'Character & Citizenship', 2, 'periods', 35])
        for day in DAYS:
            days.append([level, day, '07:30' if n < 3 else '07:45', '13:00', '14:30'])
            acts.extend([[level, day, 'Recess', '10:00', '10:30'], [level, day, 'Lunch', '12:30', '13:00']])
        acts.append([level, 'Monday', 'Assembly', '08:00', '08:30'])
    return with_stream(pd.DataFrame(subjects, columns=SUB)), pd.DataFrame(days, columns=DAY), pd.DataFrame(acts, columns=ACT)


CHOICE_COLUMNS = ['Level', 'Stream', 'Subject', 'Unit']
LIST_LIMIT = 1000
INPUT_LIMIT = 5000


def selection_lists(subjects):
    """Seed editable lists from the actual workbook inputs."""
    subjects = with_stream(subjects)
    choices = {}
    for column in CHOICE_COLUMNS:
        values = list(dict.fromkeys(str(v).strip() for v in subjects[column].dropna() if str(v).strip()))
        if column == 'Unit':
            values = ['minutes', 'periods']
        choices[column] = pd.Series(values, dtype='object')
    return pd.DataFrame(choices)


def validate_selections(subjects, lists):
    if not set(CHOICE_COLUMNS) <= set(lists.columns):
        raise ValueError('Lists sheet must contain Level, Stream, Subject and Unit columns.')
    for column in CHOICE_COLUMNS:
        values = lists[column].dropna().astype(str).str.strip()
        allowed = set(values[values != ''])
        if not allowed:
            raise ValueError(f'Lists: {column} needs at least one choice.')
        if column == 'Unit' and not allowed <= {'minutes', 'periods'}:
            raise ValueError('Lists: Unit supports only minutes and periods.')
        invalid = set(subjects[column].dropna().astype(str).str.strip()) - allowed
        if invalid:
            raise ValueError(f'Subject Requirements: {column} values are missing from Lists: {sorted(invalid)}')


def add_excel_validation(book):
    ws = book['Subject Requirements']
    positions = {cell.value: cell.column_letter for cell in ws[1]}
    for index, column in enumerate(CHOICE_COLUMNS, 1):
        letter = get_column_letter(index)
        name = f'Choices_{column}'
        # Dynamic range expands as users append contiguous entries beneath each list.
        source = f"'Lists'!${letter}$2:INDEX('Lists'!${letter}$2:${letter}${LIST_LIMIT+1},MAX(1,COUNTA('Lists'!${letter}$2:${letter}${LIST_LIMIT+1})))"
        book.defined_names.add(DefinedName(name, attr_text=source))
        rule = DataValidation(type='list', formula1=f'={name}', allow_blank=False)
        rule.showDropDown = False
        rule.errorTitle = 'Choose a listed value'
        rule.error = 'Select an option, or add it to the Lists sheet first.'
        rule.promptTitle = column
        rule.prompt = 'Maintain choices on the Lists sheet.'
        rule.showErrorMessage = rule.showInputMessage = True
        rule.errorStyle = 'stop'
        ws.add_data_validation(rule)
        rule.add(f'{positions[column]}2:{positions[column]}{INPUT_LIMIT+1}')
    for column, operator, blank in [('Minimum weekly requirement', 'greaterThanOrEqual', False), ('Reference period duration in minutes', 'greaterThan', True)]:
        rule = DataValidation(type='decimal', operator=operator, formula1='0', allow_blank=blank)
        rule.showErrorMessage = rule.showInputMessage = True
        rule.errorStyle = 'stop'
        rule.errorTitle = 'Enter a number'
        rule.error = 'Enter a number >= 0.' if not blank else 'Enter a number > 0, or leave blank for minute-based requirements.'
        rule.promptTitle = 'Numeric input'
        rule.prompt = rule.error
        ws.add_data_validation(rule)
        rule.add(f'{positions[column]}2:{positions[column]}{INPUT_LIMIT+1}')


def workbook(sheets):
    sheets = dict(sheets)
    if 'Subject Requirements' in sheets:
        subjects = with_stream(sheets['Subject Requirements'])
        sheets['Subject Requirements'] = subjects
        if 'Lists' not in sheets:
            existing = subjects.attrs.get('selection_lists')
            current = selection_lists(subjects)
            if existing is not None:
                current = pd.DataFrame({column: pd.Series(list(dict.fromkeys(
                    existing[column].dropna().astype(str).str.strip().tolist() + current[column].dropna().tolist()
                )), dtype='object') for column in CHOICE_COLUMNS})
            sheets['Lists'] = current
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
            ws = writer.sheets[name]
            ws.freeze_panes = 'A2'
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(15, max(len(str(c.value or '')) for c in col)+2))
        if 'Subject Requirements' in sheets:
            add_excel_validation(writer.book)
    return output.getvalue()


ASSUMPTIONS = pd.DataFrame({'Assumption': [
    'Edit Level, Stream and Subject choices on Lists, one value per cell with no blank gaps. Append within rows 2–1001; dropdowns cover Subject Requirements rows 2–5001.',
    'Unit supports only minutes and periods. Weekly requirements must be numeric and non-negative; reference durations must be positive numbers and are required for periods.',
    'Excel validation may be bypassed by paste; uploaded workbooks are validated again. Older workbooks without Lists remain supported.',
    'Each level and stream is calculated separately. School day settings and fixed activities are shared by all streams in that level.',
    'Workbooks without Stream are loaded as General; blank stream cells in newer workbooks are invalid.',
    'All example requirements are synthetic, not official MOE minimums.',
    'Period-based requirements are converted using the supplied reference duration.',
    'Whole periods are rounded up separately for each subject before totals.',
    'Fixed Activities contains one row per activity linked to School Day Settings by level and day.',
    'Periods pack from each teaching-window start; leftover fragments are unusable.',
    'Balanced allocation water-fills daily period counts subject to capacity; ties favor Monday.',
    'All fixed activities are mandatory; dismissal is after the last assigned lesson or fixed activity.',
    'Earliest dismissal is a preference, not a minimum teaching requirement; no filler periods are added.',
    'Latest dismissal is a hard capacity limit, so excess demand is unplaced rather than extended late.',
    'Estimates do not prove a valid subject timetable, nor model teachers, rooms, combinations or optimisation.'
]})


def template():
    s, d, a = sample_data()
    return workbook({'Subject Requirements': s, 'School Day Settings': d, 'Fixed Activities': a, 'Read Me': ASSUMPTIONS})


def parse_choices(value):
    """One choice per line, normalized and deduplicated in input order."""
    return list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))


def custom_template(levels, streams, subjects, units=None):
    """Create a blank requirement workbook from user-defined choices."""
    units = ['minutes', 'periods'] if units is None else units
    choices = {}
    for label, values in zip(CHOICE_COLUMNS, [levels, streams, subjects, units]):
        values = list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))
        if not values or len(values) > LIST_LIMIT:
            raise ValueError(f'{label}: enter between 1 and {LIST_LIMIT} choices.')
        choices[label] = values
    if not set(choices['Unit']) <= {'minutes', 'periods'}:
        raise ValueError('Unit supports only minutes and periods.')
    count = len(choices['Level']) * len(choices['Stream']) * len(choices['Subject'])
    if count > INPUT_LIMIT:
        raise ValueError(f'These choices create {count:,} rows; reduce them to at most {INPUT_LIMIT:,} combinations.')
    rows = [[level, stream, subject, None, choices['Unit'][0], None]
            for level in choices['Level'] for stream in choices['Stream'] for subject in choices['Subject']]
    columns = ['Level', 'Stream', 'Subject', SUB[2], 'Unit', SUB[4]]
    requirements = pd.DataFrame(rows, columns=columns)
    # Copy explicitly illustrative day settings and breaks for each supplied level.
    _, sample_days, sample_activities = sample_data()
    day_parts, activity_parts = [], []
    for level in choices['Level']:
        days = sample_days[sample_days.Level == 'Sec 1'].copy()
        activities = sample_activities[sample_activities.Level == 'Sec 1'].copy()
        days['Level'], activities['Level'] = level, level
        day_parts.append(days)
        activity_parts.append(activities)
    lists = pd.DataFrame({label: pd.Series(values, dtype='object') for label, values in choices.items()})
    notes = pd.concat([pd.DataFrame({'Assumption': [
        'Custom template: enter every weekly requirement before upload. Blank requirements are incomplete, not zero.',
        'One row is created for every level/stream/subject combination. Delete rows that do not apply.',
        'School day settings and activities are illustrative defaults. Replace them with your own school settings.'
    ]}), ASSUMPTIONS], ignore_index=True)
    return workbook({'Subject Requirements': requirements, 'School Day Settings': pd.concat(day_parts, ignore_index=True),
                     'Fixed Activities': pd.concat(activity_parts, ignore_index=True), 'Lists': lists, 'Read Me': notes})


def read_inputs(source):
    sheets = pd.read_excel(source, sheet_name=None)
    names = ['Subject Requirements', 'School Day Settings', 'Fixed Activities']
    if not set(names) <= set(sheets):
        raise ValueError('Workbook must contain: ' + ', '.join(names))
    sheets['Subject Requirements'] = with_stream(sheets['Subject Requirements'])
    if 'Lists' in sheets:
        validate_selections(sheets['Subject Requirements'], sheets['Lists'])
        sheets['Subject Requirements'].attrs['selection_lists'] = sheets['Lists']
    return tuple(sheets[n] for n in names)
