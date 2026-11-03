import pandas as pd
import pytest
from simulator import ACT, DAY, DAYS, curriculum_allocation, estimate_week, minute, sample_data


def inputs(demand=50):
    allocation = pd.DataFrame([['Sec 1', 'G1', demand]], columns=['Level', 'Stream', 'Allocated periods'])
    days = pd.DataFrame([['Sec 1', day, '08:00', '13:00', '15:00'] for day in DAYS], columns=DAY)
    acts = pd.DataFrame([['Sec 1', day, 'Recess', '10:00', '10:30'] for day in DAYS], columns=ACT)
    return allocation, days, acts


def test_earliest_is_hard_floor_and_gaps_are_not_extra_teaching():
    daily, blocks, summary = estimate_week(*inputs(5), 30)
    assert set(daily['Estimated dismissal']) == {'13:00'}
    assert sum(daily['Assigned periods']) == 5
    assert len(blocks[blocks.Type == 'Teaching']) == 5
    assert daily['Unallocated school minutes'].sum() > 0
    assert summary.iloc[0]['Unplaced periods'] == 0
    for _, group in blocks.groupby('Day'):
        assert group.iloc[0]['Start'] == '08:00'
        assert group.iloc[-1]['End'] == '13:00'
        assert all(group['End minute'].to_numpy()[:-1] == group['Start minute'].to_numpy()[1:])


@pytest.mark.parametrize('duration', [15, 20, 30, 35])
def test_no_teaching_crosses_break_and_periods_are_conserved(duration):
    daily, blocks, summary = estimate_week(*inputs(50), duration)
    teaching = blocks[blocks.Type == 'Teaching']
    assert ((teaching['End minute'] - teaching['Start minute']) == duration).all()
    assert not ((teaching['Start minute'] < 630) & (teaching['End minute'] > 600)).any()
    assert len(teaching) == daily['Assigned periods'].sum() == summary.iloc[0]['Placed periods']
    assert (daily['Estimated dismissal'].map(minute) >= 780).all()
    assert (daily['Estimated dismissal'].map(minute) <= 900).all()


def test_balances_clock_times_with_different_daily_start_times():
    a, d, breaks = inputs(55)
    d.loc[0, 'Starting time'] = '09:00'
    daily, _, summary = estimate_week(a, d, breaks, 30)
    # Equal period counts would dismiss Monday one hour later than other days.
    assert summary.iloc[0]['Dismissal spread minutes'] <= 30
    assert daily.iloc[0]['Assigned periods'] < daily.iloc[1]['Assigned periods']
    assert daily['Assigned periods'].sum() == 55


def test_shortage_is_visible_and_never_extends_past_latest():
    daily, blocks, summary = estimate_week(*inputs(1000), 35)
    row = summary.iloc[0]
    assert row['Unplaced periods'] == 1000 - row['Weekly capacity periods']
    assert daily['Assigned periods'].sum() == row['Weekly capacity periods']
    assert blocks['End minute'].max() <= minute('15:00')


def test_fixed_activity_after_lessons_controls_dismissal():
    a, d, breaks = inputs(0)
    breaks.loc[len(breaks)] = ['Sec 1', 'Monday', 'Assembly', '14:00', '14:30']
    daily, blocks, _ = estimate_week(a, d, breaks, 30)
    assert daily.iloc[0]['Estimated dismissal'] == '14:30'
    assert len(blocks[blocks.Type == 'Teaching']) == 0
    assert daily['Assigned periods'].sum() == 0


def test_streams_and_levels_use_own_adjusted_totals():
    s, d, a = sample_data()
    other = s[s.Level == 'Sec 1'].copy()
    other['Stream'] = 'G1'
    s = pd.concat([s, other], ignore_index=True)
    detail, totals = curriculum_allocation(s, 30, {('Sec 1', 'G1', 'English'): 2})
    daily, blocks, summary = estimate_week(detail, d, a, 30)
    got = summary.set_index(['Level', 'Stream'])['Allocated periods']
    expected = totals.set_index(['Level', 'Stream'])['Allocated periods']
    pd.testing.assert_series_equal(got, expected)
    assert got.loc[('Sec 1', 'G1')] == got.loc[('Sec 1', 'General')] + 2


@pytest.mark.parametrize('bad', ['missing_day', 'overlap', 'invalid_window'])
def test_invalid_school_settings(bad):
    a, d, breaks = inputs()
    if bad == 'missing_day': d = d.iloc[:-1]
    if bad == 'overlap': breaks.loc[len(breaks)] = ['Sec 1', 'Monday', 'Lunch', '10:15', '10:45']
    if bad == 'invalid_window': d.loc[0, 'Desired earliest dismissal time'] = '16:00'
    with pytest.raises(ValueError): estimate_week(a, d, breaks, 30)
