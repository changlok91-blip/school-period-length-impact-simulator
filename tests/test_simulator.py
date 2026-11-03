from io import BytesIO
import pandas as pd
import pytest
from simulator import *


def fixture_inputs():
    s, d, a = sample_data()
    s = pd.DataFrame([['Sec 1', 'Test', 150, 'minutes', None]], columns=SUB)
    return s, d[d.Level == 'Sec 1'].copy(), a[a.Level == 'Sec 1'].copy()


def test_required_example():
    result = calculate(*fixture_inputs())['Subject Calculations']
    assert list(result['Minimum periods']) == [10, 8, 5, 5]
    assert list(result['Actual minutes']) == [150, 160, 150, 175]


def test_round_per_subject_and_decimal():
    s, d, a = fixture_inputs()
    s[SUB[2]] = s[SUB[2]].astype(float)
    s.loc[0, SUB[2]] = 150.000001
    s.loc[1] = ['Sec 1', 'Second', 1, 'minutes', None]
    r = calculate(s, d, a)
    assert r['Comparison'].iloc[0]['Minimum periods'] == 12


def test_reference_conversion_and_override():
    s, d, a = fixture_inputs()
    s.loc[0, [SUB[2], 'Unit', SUB[4]]] = [5, 'periods', 30]
    r = calculate(s, d, a, {(20, 'Sec 1', 'Test'): 7})
    row = r['Subject Calculations'].query('`Period length` == 20').iloc[0]
    assert row['Required minutes'] == 150
    assert row['Balance minutes'] == -10
    assert not r['Warnings'].empty


def test_break_boundaries():
    day = pd.Series(['Sec 1', 'Monday', '08:00', '09:00', '10:00'], index=DAY)
    a = pd.DataFrame([['Sec 1', 'Monday', 'Break', '08:30', '09:00']], columns=ACT)
    assert slots_for_day(day, a, 30) == [510, 570, 600]
    assert slots_for_day(day, a, 35) == [575]


def test_level_start_times():
    s, d, a = sample_data()
    r = calculate(s, d, a)['Dismissal Estimates']
    x = r[(r.Day == 'Tuesday') & (r['Period length'] == 15)].set_index('Level')
    assert x.loc['Sec 1', 'Capacity periods'] == x.loc['Sec 3', 'Capacity periods'] + 1


@pytest.mark.parametrize('change', ['missing_column', 'missing_day', 'missing_requirement', 'zero_reference', 'invalid_time', 'overlap', 'negative', 'bad_unit'])
def test_invalid_inputs(change):
    s, d, a = fixture_inputs()
    if change == 'missing_column': s = s.drop(columns='Unit')
    if change == 'missing_day': d = d.iloc[:-1]
    if change == 'missing_requirement': s.loc[0, SUB[2]] = None
    if change == 'zero_reference': s.loc[0, ['Unit', SUB[4]]] = ['periods', 0]
    if change == 'invalid_time': d.iloc[0, 2] = '25:00'
    if change == 'overlap': a.loc[len(a)] = ['Sec 1', 'Monday', 'Bad', '10:15', '10:45']
    if change == 'negative': s.loc[0, SUB[2]] = -1
    if change == 'bad_unit': s.loc[0, 'Unit'] = 'hours'
    with pytest.raises(ValueError): calculate(s, d, a)


def test_capacity_and_hard_latest_limit():
    s, d, a = fixture_inputs()
    s.loc[0, SUB[2]] = 10000
    r = calculate(s, d, a)
    assert (r['Comparison']['Insufficient periods'] > 0).all()
    assert (r['Dismissal Estimates']['Dismissal minute'] <= minute('14:30')).all()
    assert (r['Dismissal Estimates']['Unused periods'] == 0).all()
    assert r['Warnings'].Warning.str.contains('Capacity shortage').any()


def test_fixed_activity_controls_dismissal_and_zero_demand():
    s, d, a = fixture_inputs()
    s.loc[0, SUB[2]] = 0
    r = calculate(s, d, a)['Dismissal Estimates']
    assert (r['Estimated dismissal'] == '13:00').all()
    assert (r['Assigned periods'] == 0).all()


def test_invalid_override():
    with pytest.raises(ValueError): calculate(*fixture_inputs(), {(15, 'Sec 1', 'Test'): 1.5})


def test_excel_roundtrip():
    inputs = read_inputs(BytesIO(template()))
    result = calculate(*inputs)
    sheets = pd.read_excel(BytesIO(workbook(result)), sheet_name=None)
    assert len(sheets['Comparison']) == 16


def test_streams_calculated_independently():
    s, d, a = fixture_inputs()
    s['Stream'] = 'G1'
    other = s.copy()
    other['Stream'] = 'G2'
    other[SUB[2]] = 300
    s = pd.concat([s, other], ignore_index=True)
    result = calculate(s, d, a, {(15, 'Sec 1', 'G1', 'Test'): 9})
    rows = result['Comparison'].query('`Period length` == 15').set_index('Stream')
    assert rows.loc['G1', 'Minimum periods'] == 10
    assert rows.loc['G2', 'Minimum periods'] == 20
    assert rows.loc['G1', 'Allocated periods'] == 9
    assert rows.loc['G2', 'Allocated periods'] == 20
    assert rows.loc['G1', 'Capacity periods'] == rows.loc['G2', 'Capacity periods']
    detail = result['Subject Calculations'].query('`Period length` == 15').set_index('Stream')
    assert detail.loc['G1', 'Balance minutes'] == -15
    assert detail.loc['G2', 'Balance minutes'] == 0
    assert len(result['Dismissal Estimates']) == 40


@pytest.mark.parametrize('value', [None, '', '   '])
def test_blank_stream_rejected(value):
    s, d, a = fixture_inputs()
    s['Stream'] = value
    with pytest.raises(ValueError, match='Stream'):
        calculate(s, d, a)


def test_duplicate_within_stream_rejected():
    s, d, a = fixture_inputs()
    s['Stream'] = 'G1'
    with pytest.raises(ValueError, match='Duplicate'):
        calculate(pd.concat([s, s]), d, a)


def test_legacy_and_stream_excel_roundtrip():
    s, d, a = fixture_inputs()
    data = workbook({'Subject Requirements': s, 'School Day Settings': d, 'Fixed Activities': a})
    loaded = read_inputs(BytesIO(data))
    assert loaded[0].Stream.tolist() == ['General']
    loaded[0]['Stream'] = 'G3'
    data = workbook({'Subject Requirements': loaded[0], 'School Day Settings': d, 'Fixed Activities': a})
    assert read_inputs(BytesIO(data))[0].Stream.tolist() == ['G3']
