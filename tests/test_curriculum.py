import pandas as pd
import pytest
from simulator import curriculum_allocation, SUB


def requirements():
    return pd.DataFrame([
        ['Sec 1', 'G1', 'Math', 150, 'minutes', None],
        ['Sec 1', 'G1', 'English', 151, 'minutes', None],
        ['Sec 1', 'G2', 'Math', 180, 'minutes', None],
        ['Sec 2', 'G1', 'Math', 2, 'periods', 35],
    ], columns=['Level', 'Stream', 'Subject', SUB[2], 'Unit', SUB[4]])


@pytest.mark.parametrize('length,periods,minutes', [(15, 10, 150), (20, 8, 160), (30, 5, 150), (35, 5, 175)])
def test_subject_minimums(length, periods, minutes):
    detail, _ = curriculum_allocation(requirements(), length)
    row = detail.iloc[0]
    assert row['Minimum periods'] == periods
    assert row['Actual minutes'] == minutes


def test_adjustments_and_separate_curriculum_hours():
    detail, totals = curriculum_allocation(requirements(), 20, {('Sec 1', 'G1', 'Math'): -1, ('Sec 1', 'G1', 'English'): 2})
    math = detail.iloc[0]
    assert math['Allocated periods'] == 7
    assert math['Actual minutes'] == 140
    assert math['Balance minutes'] == -10
    assert math['Requirement status'] == 'Shortfall'
    totals = totals.set_index(['Level', 'Stream'])
    g1 = totals.loc[('Sec 1', 'G1')]
    assert g1['Minimum periods'] == 16
    assert g1['Allocated periods'] == 17
    assert g1['Curriculum minutes'] == 340
    assert g1['Curriculum hours'] == pytest.approx(340/60)
    assert g1['Curriculum time'] == '5h 40m'
    assert g1['Subjects below minimum'] == 1  # English surplus cannot cancel Math shortfall.
    assert totals.loc[('Sec 1', 'G2'), 'Curriculum minutes'] == 180
    assert totals.loc[('Sec 2', 'G1'), 'Required minutes'] == 70


@pytest.mark.parametrize('adjustment', [-0.5, 1.5, 'abc', None, float('inf'), -9])
def test_invalid_adjustment(adjustment):
    with pytest.raises(ValueError):
        curriculum_allocation(requirements(), 20, {('Sec 1', 'G1', 'Math'): adjustment})


def test_zero_periods_is_allowed_and_flagged():
    detail, totals = curriculum_allocation(requirements().iloc[:1], 20, {('Sec 1', 'G1', 'Math'): -8})
    assert detail.iloc[0]['Allocated periods'] == 0
    assert totals.iloc[0]['Curriculum time'] == '0h 00m'
    assert totals.iloc[0]['Subjects below minimum'] == 1


def test_per_subject_rounding_and_decimal_requirement():
    data = requirements().iloc[:2].copy()
    data[SUB[2]] = [150.000001, 1]
    detail, totals = curriculum_allocation(data, 15)
    assert list(detail['Minimum periods']) == [11, 1]
    assert totals.iloc[0]['Minimum periods'] == 12


@pytest.mark.parametrize('column,value', [('Subject', ''), ('Subject', None), ('Level', None), ('Stream', ''), (SUB[2], None), (SUB[2], -1), ('Unit', 'hours'), (SUB[4], -1)])
def test_invalid_subject_inputs(column, value):
    data = requirements().iloc[:1].copy()
    data[column] = data[column].astype(object)
    data.loc[0, column] = value
    with pytest.raises(ValueError):
        curriculum_allocation(data, 20)


@pytest.mark.parametrize('duration', [0, -5, 0.5, None, 'abc'])
def test_invalid_duration(duration):
    with pytest.raises(ValueError):
        curriculum_allocation(requirements(), duration)


def test_duplicate_subject_and_missing_columns():
    data = requirements().iloc[:1]
    with pytest.raises(ValueError, match='Duplicate'):
        curriculum_allocation(pd.concat([data, data]), 20)
    with pytest.raises(ValueError, match='missing columns'):
        curriculum_allocation(data.drop(columns='Subject'), 20)
    with pytest.raises(ValueError):
        curriculum_allocation(data.iloc[:0], 20)
