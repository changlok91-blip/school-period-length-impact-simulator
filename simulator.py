"""Pure calculations and Excel IO for the period-length decision aid."""
from io import BytesIO
from decimal import Decimal, ROUND_CEILING
import datetime as dt
import pandas as pd
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment

elective_input_version = 1

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
    if 'Elective group' not in subjects:
        subjects['Elective group'] = ''
    subjects['Elective group'] = subjects['Elective group'].fillna('').astype(str).str.strip()
    columns = [column for column in subjects.columns if column != 'Stream']
    columns.insert(columns.index('Level') + 1 if 'Level' in columns else 0, 'Stream')
    return subjects.loc[:, columns]


COMMON_TARGETS = ['G3', 'G2', 'G1']


def normalize_common_streams(values):
    result = []
    for value in values:
        if pd.isna(value) or not str(value).strip():
            continue
        value = str(value).strip()
        if value.upper() == 'CMN':
            raise ValueError('CMN is the common label; list only actual student streams as its recipients.')
        if value.upper() in COMMON_TARGETS:
            value = value.upper()
        if value not in result:
            result.append(value)
    return result


def common_targets_for(subjects):
    """Workbook setting when present; preserve legacy G3/G2/G1 behavior otherwise."""
    return normalize_common_streams(subjects.attrs.get('common_streams', COMMON_TARGETS))


RULE_COLUMNS = ['Stream', 'Type', 'Applies to']


def validate_stream_rules(rules):
    if not set(RULE_COLUMNS) <= set(rules):
        raise ValueError('Stream Rules needs Stream, Type and Applies to columns.')
    rules = rules[RULE_COLUMNS].copy().fillna('')
    for column in RULE_COLUMNS:
        rules[column] = rules[column].astype(str).str.strip()
    if rules.empty or rules.Stream.eq('').any() or rules.Stream.duplicated().any():
        raise ValueError('Stream Rules: enter unique, non-blank stream names.')
    if not rules.Type.isin(['Student', 'Common']).all():
        raise ValueError('Stream Rules: Type must be Student or Common.')
    actual = set(rules.loc[rules.Type == 'Student', 'Stream'])
    for _, row in rules.iterrows():
        targets = parse_choices(row['Applies to'])
        if row.Type == 'Common' and (not targets or not set(targets) <= actual):
            raise ValueError(f'{row.Stream}: choose at least one recipient classified as Student. Common groups cannot receive other common groups.')
        if row.Type == 'Student' and targets:
            raise ValueError(f'{row.Stream}: a Student stream must have blank Applies to.')
    return rules


def stream_rules_for(subjects, names=None):
    """Restore explicit classifications, or migrate the previous CMN settings."""
    subjects = with_stream(subjects)
    names = list(dict.fromkeys(list(subjects.Stream.unique()) + list(names or [])))
    if 'stream_rules' in subjects.attrs:
        rules = pd.DataFrame(subjects.attrs['stream_rules'], columns=RULE_COLUMNS)
        missing = [name for name in names if name not in set(rules.Stream)]
        if missing:
            rules = pd.concat([rules, pd.DataFrame([[name, 'Student', ''] for name in missing], columns=RULE_COLUMNS)], ignore_index=True)
        return rules
    common = next((name for name in names if name.upper() == 'CMN'), None)
    targets = common_targets_for(subjects) if common else []
    names = list(dict.fromkeys(names + targets))
    return pd.DataFrame([[name, 'Common' if name == common else 'Student', '\n'.join(targets) if name == common else ''] for name in names], columns=RULE_COLUMNS)


def expand_stream_rules(subjects, rules):
    rules = validate_stream_rules(rules)
    subjects = with_stream(subjects)
    for column in ['Level', 'Subject']:
        if column not in subjects:
            raise ValueError(f'Subject Requirements: missing columns {column}')
        if subjects[column].isna().any() or any(not str(v).strip() for v in subjects[column]):
            raise ValueError(f'{column} must be filled for every subject row.')
    if subjects.duplicated(['Level', 'Stream', 'Subject']).any():
        raise ValueError('Duplicate subject rows are not allowed within the same level and stream.')
    missing = set(subjects.Stream) - set(rules.Stream)
    if missing:
        raise ValueError('Classify these streams in Stream Rules: ' + ', '.join(sorted(missing)))
    if subjects.empty:
        return subjects
    common_map = {r.Stream: parse_choices(r['Applies to']) for _, r in rules[rules.Type == 'Common'].iterrows()}
    pieces = []
    for level, group in subjects.groupby('Level', sort=False):
        common_rows = group[group.Stream.isin(common_map)]
        own_rows = group[~group.Stream.isin(common_map)]
        targets = list(dict.fromkeys(list(own_rows.Stream) + [target for label in common_rows.Stream.unique() for target in common_map[label]]))
        for target in targets:
            own = own_rows[own_rows.Stream == target].copy()
            inherited = common_rows[common_rows.Stream.map(lambda label: target in common_map[label]) & ~common_rows.Subject.isin(own.Subject)].copy()
            if inherited.Subject.duplicated().any():
                duplicates = ', '.join(inherited.loc[inherited.Subject.duplicated(), 'Subject'].astype(str))
                raise ValueError(f'{level} / {target}: overlapping common groups define {duplicates}. Remove the overlap or enter a specific Student row to override it.')
            inherited['Requirement source'] = inherited.Stream
            inherited['Stream'] = target
            own['Requirement source'] = target
            inherited.attrs = {}; own.attrs = {}
            pieces.extend([own, inherited])
    result = pd.concat(pieces, ignore_index=True)
    result.attrs = subjects.attrs.copy()
    return result


def expand_common_requirements(subjects, common_streams=None):
    """CMN is inherited by configured actual streams at the same level."""
    targets = common_targets_for(subjects) if common_streams is None else normalize_common_streams(common_streams)
    subjects = with_stream(subjects)
    if not targets and subjects.Stream.str.upper().eq('CMN').any():
        raise ValueError('Enter at least one actual stream receiving CMN requirements.')
    for column in ['Level', 'Subject']:
        if column not in subjects:
            raise ValueError(f'Subject Requirements: missing columns {column}')
        if subjects[column].isna().any() or any(not str(v).strip() for v in subjects[column]):
            raise ValueError(f'{column} must be filled for every subject row.')
    subjects['Stream'] = subjects.Stream.map(lambda v: v.upper() if v.upper() in COMMON_TARGETS + ['CMN'] else v)
    if subjects.duplicated(['Level', 'Stream', 'Subject']).any():
        raise ValueError('Duplicate subject rows are not allowed within the same level and stream.')
    if subjects.empty:
        return subjects
    expanded = []
    for level, group in subjects.groupby('Level', sort=False):
        common = group[group.Stream == 'CMN']
        specific = group[group.Stream != 'CMN']
        streams = list(dict.fromkeys((targets if not common.empty else []) + list(specific.Stream)))
        for stream in streams:
            own = specific[specific.Stream == stream].copy()
            inherited = common[~common.Subject.isin(own.Subject)].copy() if stream in targets else common.iloc[:0].copy()
            inherited['Stream'] = stream
            inherited['Requirement source'] = 'CMN'
            own['Requirement source'] = stream
            inherited.attrs = {}; own.attrs = {}
            expanded.extend([inherited, own])
    result = pd.concat(expanded, ignore_index=True)
    result.attrs = subjects.attrs.copy()
    return result


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


def curriculum_allocation(subjects, period_length, adjustments=None, elective_choices=None, common_streams=None, stream_rules=None):
    """Subject minima plus signed deltas; no school-day capacity assumptions.

    Adjustments are keyed by (Level, Stream, Subject) for the selected duration.
    Returns all option rows and totals for compulsory subjects plus one choice per group.
    """
    duration = number(period_length, 'Minutes per period', True)
    if duration != int(duration):
        raise ValueError('Minutes per period must be a whole number.')
    duration = int(duration)
    if stream_rules is not None or 'stream_rules' in subjects.attrs:
        subjects = expand_stream_rules(subjects, stream_rules if stream_rules is not None else stream_rules_for(subjects))
    else:
        subjects = expand_common_requirements(subjects, common_streams)
    needed = ['Level', 'Stream', 'Subject', SUB[2], 'Unit', SUB[4]]
    if not set(needed) <= set(subjects):
        raise ValueError('Subject Requirements: missing columns ' + ', '.join(c for c in needed if c not in subjects))
    if subjects.empty:
        raise ValueError('Enter at least one subject requirement.')
    for column in ['Level', 'Stream', 'Subject']:
        if subjects[column].isna().any() or any(not str(v).strip() for v in subjects[column]):
            raise ValueError(f'{column} must be filled for every subject row.')
    if subjects.duplicated(['Level', 'Stream', 'Subject']).any():
        raise ValueError('Duplicate subject rows are not allowed within the same level and stream.')
    rows = []
    for _, r in subjects.iterrows():
        required = number(r[SUB[2]], f'{r.Subject}: minimum weekly requirement')
        if r.Unit not in ['minutes', 'periods']:
            raise ValueError('Unit must be minutes or periods.')
        if r.Unit == 'periods' or (pd.notna(r[SUB[4]]) and str(r[SUB[4]]).strip()):
            reference = number(r[SUB[4]], f'{r.Subject}: reference period duration', True)
            if r.Unit == 'periods':
                required *= reference
        minimum = int((required / Decimal(duration)).to_integral_value(rounding=ROUND_CEILING))
        raw = (adjustments or {}).get((r.Level, r.Stream, r.Subject), 0)
        try:
            adjustment = Decimal(str(raw))
            if not adjustment.is_finite() or adjustment != int(adjustment):
                raise ValueError()
        except Exception:
            raise ValueError(f'{r.Subject}: adjustment must be a signed whole number of periods.')
        adjustment = int(adjustment)
        allocated = minimum + adjustment
        if allocated < 0:
            raise ValueError(f'{r.Level} / {r.Stream} / {r.Subject}: adjustment cannot make allocated periods negative (minimum {minimum}).')
        actual = allocated * duration
        rows.append({'Level': r.Level, 'Stream': r.Stream, 'Subject': r.Subject,
                     'Required minutes': float(required), 'Minimum periods': minimum,
                     'Adjustment (periods)': adjustment, 'Allocated periods': allocated,
                     'Actual minutes': actual, 'Balance minutes': float(Decimal(actual) - required),
                     'Requirement status': 'Shortfall' if Decimal(actual) < required else 'Met',
                     'Elective group': r['Elective group'], 'Requirement source': r['Requirement source']})
    detail = pd.DataFrame(rows)
    detail['Selected'] = detail['Elective group'] == ''
    for (level, stream, name), options in detail[detail['Elective group'] != ''].groupby(['Level', 'Stream', 'Elective group'], sort=False):
        chosen = (elective_choices or {}).get((level, stream, name), options.iloc[0].Subject)
        if chosen not in set(options.Subject):
            raise ValueError(f'{level} / {stream} / {name}: choose one of its listed subjects.')
        detail.loc[options.index, 'Selected'] = options.Subject == chosen
    totals = []
    for (level, stream), all_options in detail.groupby(['Level', 'Stream'], sort=False):
        group = all_options[all_options.Selected]
        compulsory_minutes = int(all_options.loc[all_options['Elective group'] == '', 'Actual minutes'].sum())
        minimum_minutes = maximum_minutes = compulsory_minutes
        for _, options in all_options[all_options['Elective group'] != ''].groupby('Elective group'):
            minimum_minutes += int(options['Actual minutes'].min())
            maximum_minutes += int(options['Actual minutes'].max())
        minutes = int(group['Actual minutes'].sum())
        totals.append({'Level': level, 'Stream': stream,
                       'Required minutes': group['Required minutes'].sum(),
                       'Minimum periods': int(group['Minimum periods'].sum()),
                       'Adjustment (periods)': int(group['Adjustment (periods)'].sum()),
                       'Allocated periods': int(group['Allocated periods'].sum()),
                       'Curriculum minutes': minutes, 'Curriculum hours': minutes / 60,
                       'Curriculum time': f'{minutes // 60}h {minutes % 60:02d}m',
                       'Subjects below minimum': int((group['Requirement status'] == 'Shortfall').sum()),
                       'Minimum pathway hours': minimum_minutes / 60, 'Maximum pathway hours': maximum_minutes / 60})
    return detail, pd.DataFrame(totals)


def estimate_week(allocations, days, activities, period_length):
    """Illustrative teaching slots only; earliest dismissal is a mandatory floor.

    Find an early common clock-time horizon with enough slots, then assign the
    next period to the day whose resulting dismissal is earliest. No subjects
    are placed. Gaps to the mandatory floor are explicit unallocated school time.
    """
    duration = number(period_length, 'Minutes per period', True)
    if duration != int(duration):
        raise ValueError('Minutes per period must be a whole number.')
    duration = int(duration)
    if 'Selected' in allocations:
        allocations = allocations[allocations.Selected].copy()
    levels = allocations.Level.unique()
    dummy = pd.DataFrame([[level, 'Schedule', 0, 'minutes', None] for level in levels], columns=SUB)
    validate(dummy, days, activities)
    daily, blocks, summaries = [], [], []
    for (level, stream), group in allocations.groupby(['Level', 'Stream'], sort=False):
        demand = 0
        for value in group['Allocated periods']:
            count = number(value, 'Allocated periods')
            if count != int(count):
                raise ValueError('Allocated periods must be whole numbers.')
            demand += int(count)
        ds = [days[(days.Level == level) & (days['Day of week'] == day)].iloc[0] for day in DAYS]
        acts = [activities[(activities.Level == level) & (activities['Day of week'] == day)] for day in DAYS]
        slots = [slots_for_day(day, act, duration) for day, act in zip(ds, acts)]
        floors = [max([minute(day[DAY[3]])] + [minute(v) for v in act.End]) for day, act in zip(ds, acts)]
        capacity = sum(map(len, slots))
        to_place = min(demand, capacity)
        # Small bounded clock-time search; each day's earliest/latest limits remain hard.
        for target in range(min(floors), max(minute(day[DAY[4]]) for day in ds) + 1):
            limits = [min(minute(day[DAY[4]]), max(target, floor)) for day, floor in zip(ds, floors)]
            caps = [sum(end <= limit for end in slot) for slot, limit in zip(slots, limits)]
            if sum(caps) >= to_place:
                break
        counts = [0] * 5
        for _ in range(to_place):
            candidates = [i for i in range(5) if counts[i] < caps[i]]
            i = min(candidates, key=lambda i: (max(floors[i], slots[i][counts[i]]), counts[i], i))
            counts[i] += 1
        finishes = []
        for i, day in enumerate(ds):
            finish = max(floors[i], slots[i][counts[i]-1] if counts[i] else minute(day[DAY[2]]))
            finishes.append(finish)
            occupied = [(end-duration, end, 'Teaching', f'Teaching period {j+1}') for j, end in enumerate(slots[i][:counts[i]])]
            occupied += [(minute(row.Start), minute(row.End), 'Fixed activity', str(row.Activity)) for _, row in acts[i].iterrows()]
            occupied.sort()
            segments, cursor = [], minute(day[DAY[2]])
            for start, end, kind, label in occupied:
                if start > cursor:
                    segments.append((cursor, start, 'Unallocated school time', 'Unallocated school time'))
                segments.append((start, end, kind, label))
                cursor = end
            if cursor < finish:
                segments.append((cursor, finish, 'Unallocated school time', 'Unallocated school time'))
            unallocated = sum(end-start for start, end, kind, _ in segments if kind == 'Unallocated school time')
            daily.append({'Level': level, 'Stream': stream, 'Day': DAYS[i], 'Starting time': clock(minute(day[DAY[2]])),
                          'Earliest dismissal': clock(minute(day[DAY[3]])), 'Latest dismissal': clock(minute(day[DAY[4]])),
                          'Estimated dismissal': clock(finish), 'Assigned periods': counts[i], 'Capacity periods': len(slots[i]),
                          'Unallocated school minutes': unallocated})
            for start, end, kind, label in segments:
                blocks.append({'Level': level, 'Stream': stream, 'Day': DAYS[i], 'Start': clock(start), 'End': clock(end),
                               'Start minute': start, 'End minute': end, 'Type': kind, 'Activity': label})
        summaries.append({'Level': level, 'Stream': stream, 'Allocated periods': demand, 'Placed periods': to_place,
                          'Weekly capacity periods': capacity, 'Unplaced periods': demand-to_place,
                          'Dismissal spread minutes': max(finishes)-min(finishes)})
    return pd.DataFrame(daily), pd.DataFrame(blocks, columns=['Level', 'Stream', 'Day', 'Start', 'End', 'Start minute', 'End minute', 'Type', 'Activity']), pd.DataFrame(summaries)


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
    choices['Elective group'] = pd.Series(list(dict.fromkeys(subjects.loc[subjects['Elective group'] != '', 'Elective group'])), dtype='object')
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

    if 'Elective group' in lists:
        allowed = set(lists['Elective group'].dropna().astype(str).str.strip())
        used = set(with_stream(subjects)['Elective group']) - {''}
        if used - allowed:
            raise ValueError('Elective group values are missing from Lists: ' + ', '.join(sorted(used - allowed)))


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
    if 'Elective group' in positions:
        book.defined_names.add(DefinedName('Choices_ElectiveGroup', attr_text=f"'Lists'!$E$2:INDEX('Lists'!$E$2:$E${LIST_LIMIT+1},MAX(1,COUNTA('Lists'!$E$2:$E${LIST_LIMIT+1})))"))
        rule = DataValidation(type='list', formula1='=Choices_ElectiveGroup', allow_blank=True)
        rule.showDropDown = False
        rule.showErrorMessage = True
        rule.errorStyle = 'stop'
        rule.error = 'Choose a named elective group, or leave blank for compulsory.'
        ws.add_data_validation(rule)
        rule.add(f"{positions['Elective group']}2:{positions['Elective group']}{INPUT_LIMIT+1}")
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
                    existing.get(column, pd.Series(dtype='object')).dropna().astype(str).str.strip().tolist() + current[column].dropna().tolist()
                )), dtype='object') for column in CHOICE_COLUMNS + ['Elective group']})
            sheets['Lists'] = current
        sheets['Lists'] = sheets['Lists'].reindex(columns=CHOICE_COLUMNS + ['Elective group'])
        if 'Stream Rules' not in sheets:
            seed = subjects.copy()
            if 'stream_rules' not in subjects.attrs and 'common_streams' not in subjects.attrs:
                seed.attrs['common_streams'] = normalize_common_streams([v for v in sheets['Lists']['Stream'].dropna() if str(v).upper() != 'CMN']) or COMMON_TARGETS.copy()
            sheets['Stream Rules'] = stream_rules_for(seed, sheets['Lists']['Stream'].dropna().tolist())
        sheets['Stream Rules'] = validate_stream_rules(sheets['Stream Rules'])
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
        if 'Stream Rules' in sheets:
            rule = DataValidation(type='list', formula1='"Student,Common"', allow_blank=False)
            rule.showErrorMessage = True
            rule.errorStyle = 'stop'
            writer.book['Stream Rules'].add_data_validation(rule)
            rule.add('B2:B1001')
            writer.book['Stream Rules'].column_dimensions['C'].width = 40
            for row in writer.book['Stream Rules'].iter_rows(min_row=2):
                row[2].alignment = Alignment(wrap_text=True, vertical='top')
                writer.book['Stream Rules'].row_dimensions[row[0].row].height = 15 * max(1, len(str(row[2].value or '').splitlines()))
    return output.getvalue()


ASSUMPTIONS = pd.DataFrame({'Assumption': [
    'Edit Level, Stream and Subject choices on Lists, one value per cell with no blank gaps. Append within rows 2–1001; dropdowns cover Subject Requirements rows 2–5001.',
    'Unit supports only minutes and periods. Weekly requirements must be numeric and non-negative; reference durations must be positive numbers and are required for periods.',
    'Excel validation may be bypassed by paste; uploaded workbooks are validated again. Older workbooks without Lists remain supported.',
    'Stream Rules classifies each label as Student or Common. A Common label applies only to its listed Student recipients at the same level. A Student-specific row overrides the same inherited subject. Common labels have no separate output totals.',
    'A blank Elective group means compulsory. Choose one subject from each named group independently per level/stream. Curriculum and weekly layout use the selected choices only.',
    'Each level and stream is calculated separately. School day settings and fixed activities are shared by all streams in that level.',
    'Workbooks without Stream are loaded as General; blank stream cells in newer workbooks are invalid.',
    'All example requirements are synthetic, not official MOE minimums.',
    'Period-based requirements are converted using the supplied reference duration.',
    'Whole periods are rounded up separately for each subject before totals.',
    'Fixed Activities contains one row per activity linked to School Day Settings by level and day.',
    'Periods pack from each teaching-window start; leftover fragments are unusable.',
    'Weekly layout seeks an early common dismissal horizon, then places each next period on the day with the earliest resulting dismissal. It is a heuristic.',
    'All fixed activities are mandatory; dismissal is after the last assigned lesson or fixed activity.',
    'Weekly layout treats earliest dismissal as mandatory. Any gap to it is unallocated school time, not additional teaching.',
    'Latest dismissal is a hard capacity limit, so excess demand is unplaced rather than extended late.',
    'Estimates do not prove a valid subject timetable, nor model teachers, rooms, combinations or optimisation.'
]})


def template():
    s, d, a = sample_data()
    return workbook({'Subject Requirements': s, 'School Day Settings': d, 'Fixed Activities': a, 'Read Me': ASSUMPTIONS})


def parse_choices(value):
    """One choice per line, normalized and deduplicated in input order."""
    return list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))


def custom_template(levels, streams, subjects, units=None, elective_groups=None, stream_rules=None):
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
    groups = list(dict.fromkeys(str(v).strip() for v in (elective_groups or []) if str(v).strip()))
    if len(groups) > LIST_LIMIT:
        raise ValueError(f'Enter at most {LIST_LIMIT} elective groups.')
    lists['Elective group'] = pd.Series(groups, dtype='object')
    notes = pd.concat([pd.DataFrame({'Assumption': [
        'Custom template: enter every weekly requirement before upload. Blank requirements are incomplete, not zero.',
        'One row is created for every level/stream/subject combination. Delete rows that do not apply. Leave Elective group blank for compulsory; give alternative subjects the same group name.',
        'School day settings and activities are illustrative defaults. Replace them with your own school settings.'
    ]}), ASSUMPTIONS], ignore_index=True)
    if stream_rules is not None:
        requirements.attrs['stream_rules'] = validate_stream_rules(stream_rules).to_dict('records')
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
    if 'Stream Rules' in sheets:
        rules = validate_stream_rules(sheets['Stream Rules'])
        missing = set(sheets['Subject Requirements'].Stream) - set(rules.Stream)
        if missing:
            raise ValueError('Classify these streams in Stream Rules: ' + ', '.join(sorted(missing)))
        sheets['Subject Requirements'].attrs['stream_rules'] = rules.to_dict('records')
    elif 'Stream Settings' in sheets:
        if 'Stream receiving CMN' not in sheets['Stream Settings']:
            raise ValueError('Stream Settings needs a Stream receiving CMN column.')
        targets = normalize_common_streams(sheets['Stream Settings']['Stream receiving CMN'])
        if not targets and sheets['Subject Requirements'].Stream.str.upper().eq('CMN').any():
            raise ValueError('Stream Settings: list at least one actual stream receiving CMN.')
        sheets['Subject Requirements'].attrs['common_streams'] = targets
    elif 'Lists' in sheets:
        targets = normalize_common_streams([v for v in sheets['Lists']['Stream'].dropna() if str(v).strip().upper() != 'CMN'])
        sheets['Subject Requirements'].attrs['common_streams'] = targets or COMMON_TARGETS.copy()
    return tuple(sheets[n] for n in names)
