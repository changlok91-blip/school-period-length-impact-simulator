import pandas as pd
import pytest
from simulator import curriculum_allocation, estimate_week, sample_data, expand_common_requirements

COLS = ['Level', 'Stream', 'Subject', 'Minimum weekly requirement', 'Unit', 'Reference period duration in minutes', 'Elective group']


def data():
    return pd.DataFrame([
        ['Sec 1', 'CMN', 'PE', 90, 'minutes', None, ''],
        ['Sec 1', 'CMN', 'CCE', 2, 'periods', 35, ''],
        ['Sec 1', 'G1', 'Mathematics', 150, 'minutes', None, ''],
        ['Sec 1', 'G2', 'Mathematics', 180, 'minutes', None, ''],
        ['Sec 1', 'G3', 'Mathematics', 210, 'minutes', None, ''],
    ], columns=COLS)


def test_common_is_included_once_in_each_actual_stream():
    detail, totals = curriculum_allocation(data(), 30)
    assert set(totals.Stream) == {'G1', 'G2', 'G3'}
    assert len(detail) == 9
    rows = totals.set_index('Stream')
    assert rows.loc['G1', 'Curriculum minutes'] == 90 + 90 + 150
    assert rows.loc['G2', 'Curriculum minutes'] == 90 + 90 + 180
    assert rows.loc['G3', 'Curriculum minutes'] == 90 + 90 + 210
    assert set(detail[detail.Subject == 'PE']['Requirement source']) == {'CMN'}


def test_specific_row_replaces_entire_common_subject():
    s = pd.concat([data(), pd.DataFrame([['Sec 1', 'G2', 'PE', 4, 'periods', 30, '']], columns=COLS)], ignore_index=True)
    detail, totals = curriculum_allocation(s, 30)
    pe = detail[detail.Subject == 'PE'].set_index('Stream')
    assert len(pe) == 3
    assert pe.loc['G2', 'Required minutes'] == 120
    assert pe.loc['G1', 'Required minutes'] == 90
    assert pe.loc['G2', 'Requirement source'] == 'G2'
    assert totals.set_index('Stream').loc['G2', 'Curriculum minutes'] == 390


def test_common_only_expands_three_streams_without_other_subject_rows():
    detail, totals = curriculum_allocation(data().iloc[:2], 30)
    assert set(totals.Stream) == {'G3', 'G2', 'G1'}
    assert len(detail) == 6
    assert set(totals['Curriculum minutes']) == {180}


def test_common_is_scoped_to_its_level_and_known_targets():
    s = pd.concat([data(), pd.DataFrame([
        ['Sec 2', 'G1', 'English', 150, 'minutes', None, ''],
        ['Sec 1', 'Custom', 'English', 150, 'minutes', None, ''],
    ], columns=COLS).astype({'Reference period duration in minutes': 'float64'})], ignore_index=True)
    detail, _ = curriculum_allocation(s, 30)
    assert set(detail.loc[detail.Level == 'Sec 2', 'Subject']) == {'English'}
    assert set(detail.loc[detail.Stream == 'Custom', 'Subject']) == {'English'}


def test_common_electives_and_adjustments_stay_independent():
    s = pd.DataFrame([
        ['Sec 1', 'CMN', 'English', 150, 'minutes', None, ''],
        ['Sec 1', 'CMN', 'Art', 60, 'minutes', None, 'Arts'],
        ['Sec 1', 'CMN', 'Music', 90, 'minutes', None, 'Arts'],
    ], columns=COLS)
    detail, totals = curriculum_allocation(s, 30, {('Sec 1', 'G1', 'English'): 1}, {('Sec 1', 'G2', 'Arts'): 'Music'})
    by = totals.set_index('Stream')
    assert by.loc['G3', 'Curriculum minutes'] == 210
    assert by.loc['G2', 'Curriculum minutes'] == 240
    assert by.loc['G1', 'Curriculum minutes'] == 240
    _, days, acts = sample_data()
    _, _, summary = estimate_week(detail, days[days.Level == 'Sec 1'], acts[acts.Level == 'Sec 1'], 30)
    assert set(summary.Stream) == {'G1', 'G2', 'G3'}
    assert summary.set_index('Stream').loc['G1', 'Allocated periods'] == 8


def test_stream_codes_case_insensitive_and_duplicates_rejected():
    s = data(); s['Stream'] = s.Stream.str.lower()
    assert set(curriculum_allocation(s, 30)[1].Stream) == {'G3', 'G2', 'G1'}
    with pytest.raises(ValueError, match='Duplicate'):
        expand_common_requirements(pd.concat([data(), data().iloc[:1]]))


def test_missing_identifiers_not_lost_during_expansion():
    for column in ['Level', 'Subject']:
        s = data(); s.loc[0, column] = None
        with pytest.raises(ValueError):
            curriculum_allocation(s, 30)


def test_configured_arbitrary_streams_receive_common_without_hardcoded_outputs():
    s = pd.DataFrame([
        ['Sec 1', 'CMN', 'PE', 90, 'minutes', None, ''],
        ['Sec 1', 'Alpha', 'Math', 150, 'minutes', None, ''],
    ], columns=COLS)
    detail, totals = curriculum_allocation(s, 30, common_streams=['Alpha', 'Beta', 'Gamma'])
    assert set(totals.Stream) == {'Alpha', 'Beta', 'Gamma'}
    assert set(detail.loc[detail.Subject == 'PE', 'Stream']) == {'Alpha', 'Beta', 'Gamma'}
    assert totals.set_index('Stream').loc['Alpha', 'Curriculum minutes'] == 240
    assert totals.set_index('Stream').loc['Beta', 'Curriculum minutes'] == 90


@pytest.mark.parametrize('targets', [[], ['CMN']])
def test_invalid_common_recipients_rejected(targets):
    with pytest.raises(ValueError):
        curriculum_allocation(data(), 30, common_streams=targets)


def test_recipient_setting_roundtrip_and_common_only_rows():
    from io import BytesIO
    from simulator import custom_template, read_inputs, workbook
    from openpyxl import load_workbook
    payload = custom_template(['Sec 1'], ['Alpha', 'Beta', 'CMN'], ['PE'])
    book = load_workbook(BytesIO(payload))
    assert list(book['Stream Settings'].values) == [('Stream receiving CMN',), ('Alpha',), ('Beta',)]
    s, d, a = read_inputs(BytesIO(payload))
    assert s.attrs['common_streams'] == ['Alpha', 'Beta']
    s = s[s.Stream == 'CMN'].copy()
    s['Minimum weekly requirement'] = 90
    assert set(curriculum_allocation(s, 30)[1].Stream) == {'Alpha', 'Beta'}
    new_payload = workbook({'Subject Requirements': s, 'School Day Settings': d, 'Fixed Activities': a})
    loaded, _, _ = read_inputs(BytesIO(new_payload))
    assert loaded.attrs['common_streams'] == ['Alpha', 'Beta']
    assert set(curriculum_allocation(loaded, 30)[1].Stream) == {'Alpha', 'Beta'}


def test_old_workbook_infers_recipients_from_lists():
    from io import BytesIO
    from simulator import custom_template, read_inputs
    from openpyxl import load_workbook
    book = load_workbook(BytesIO(custom_template(['Sec 1'], ['Alpha', 'Beta', 'CMN'], ['PE'])))
    del book['Stream Settings']
    out = BytesIO(); book.save(out)
    s, _, _ = read_inputs(BytesIO(out.getvalue()))
    assert s.attrs['common_streams'] == ['Alpha', 'Beta']
