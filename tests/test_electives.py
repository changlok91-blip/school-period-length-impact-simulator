from io import BytesIO
import pandas as pd
import pytest
from openpyxl import load_workbook
from simulator import curriculum_allocation, estimate_week, sample_data, custom_template, read_inputs, workbook


def requirements():
    return pd.DataFrame([
        ['Sec 1', 'G1', 'English', 150, 'minutes', None, ''],
        ['Sec 1', 'G1', 'History', 100, 'minutes', None, 'Humanities'],
        ['Sec 1', 'G1', 'Geography', 150, 'minutes', None, 'Humanities'],
        ['Sec 1', 'G1', 'Art', 60, 'minutes', None, 'Arts'],
        ['Sec 1', 'G1', 'Music', 90, 'minutes', None, 'Arts'],
        ['Sec 1', 'G1', 'Drama', 120, 'minutes', None, 'Arts'],
    ], columns=['Level', 'Stream', 'Subject', 'Minimum weekly requirement', 'Unit', 'Reference period duration in minutes', 'Elective group'])


def test_compulsory_plus_one_per_group_not_sum_of_options():
    detail, totals = curriculum_allocation(requirements(), 30)
    assert set(detail.loc[detail.Selected, 'Subject']) == {'English', 'History', 'Art'}
    row = totals.iloc[0]
    assert row['Allocated periods'] == 5+4+2
    assert row['Curriculum minutes'] == 330
    assert row['Minimum pathway hours'] == 5.5
    assert row['Maximum pathway hours'] == 7
    assert row['Required minutes'] == 310


def test_choices_and_adjustments_change_totals_and_week():
    choices = {('Sec 1', 'G1', 'Humanities'): 'Geography', ('Sec 1', 'G1', 'Arts'): 'Drama'}
    detail, totals = curriculum_allocation(requirements(), 30, {('Sec 1', 'G1', 'Drama'): 2}, choices)
    assert set(detail.loc[detail.Selected, 'Subject']) == {'English', 'Geography', 'Drama'}
    assert totals.iloc[0]['Curriculum minutes'] == 480
    assert totals.iloc[0]['Maximum pathway hours'] == 8
    _, days, activities = sample_data()
    daily, _, summary = estimate_week(detail, days[days.Level == 'Sec 1'], activities[activities.Level == 'Sec 1'], 30)
    assert summary.iloc[0]['Allocated periods'] == 16
    assert daily['Assigned periods'].sum() == 16


def test_streams_groups_independent_and_unselected_shortfalls_not_in_total():
    first = requirements()
    other = first.copy(); other['Stream'] = 'G2'
    data = pd.concat([first, other], ignore_index=True)
    detail, totals = curriculum_allocation(data, 30, {('Sec 1', 'G1', 'Music'): -1}, {('Sec 1', 'G2', 'Arts'): 'Drama'})
    assert totals.iloc[0]['Curriculum minutes'] == 330
    assert totals.iloc[1]['Curriculum minutes'] == 390
    assert totals['Subjects below minimum'].sum() == 0
    assert detail[(detail.Subject == 'Music') & (detail.Stream == 'G1')].iloc[0]['Requirement status'] == 'Shortfall'


def test_invalid_choice_rejected_and_blank_groups_are_compulsory():
    with pytest.raises(ValueError, match='choose one'):
        curriculum_allocation(requirements(), 30, elective_choices={('Sec 1', 'G1', 'Arts'): 'English'})
    data = requirements(); data['Elective group'] = [None, '', ' ', '', None, '']
    detail, totals = curriculum_allocation(data, 30)
    assert detail.Selected.all()
    assert totals.iloc[0]['Allocated periods'] == detail['Allocated periods'].sum()
    detail, _ = curriculum_allocation(data.drop(columns='Elective group'), 30)
    assert detail.Selected.all()


def test_personalized_group_dropdown_and_excel_roundtrip():
    data = custom_template(['Sec 1'], ['G1'], ['English', 'History', 'Art'], elective_groups=['Humanities', 'Arts'])
    book = load_workbook(BytesIO(data))
    assert book['Lists']['E2'].value == 'Humanities'
    assert book['Lists']['E3'].value == 'Arts'
    rule = next(r for r in book['Subject Requirements'].data_validations.dataValidation if r.formula1 == '=Choices_ElectiveGroup')
    assert rule.allow_blank
    assert 'G2:G5001' == str(rule.sqref)
    book['Subject Requirements']['G3'] = 'Humanities'
    output = BytesIO(); book.save(output)
    s, d, a = read_inputs(BytesIO(output.getvalue()))
    assert s.iloc[1]['Elective group'] == 'Humanities'
    output = workbook({'Subject Requirements': s, 'School Day Settings': d, 'Fixed Activities': a})
    assert 'Arts' in read_inputs(BytesIO(output))[0].attrs['selection_lists']['Elective group'].tolist()
