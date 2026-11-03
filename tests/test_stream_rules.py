from io import BytesIO
import pandas as pd
import pytest
from simulator import (RULE_COLUMNS, validate_stream_rules, curriculum_allocation,
                       sample_data, estimate_week, custom_template, read_inputs, workbook)


def rules():
    return pd.DataFrame([
        ['A', 'Student', ''], ['B', 'Student', ''], ['CMN', 'Student', ''],
        ['Shared PE', 'Common', 'A\nB\nCMN'], ['Shared Arts', 'Common', 'B'],
    ], columns=RULE_COLUMNS)


def subjects():
    return pd.DataFrame([
        ['Sec 1', 'A', 'Math', 150, 'minutes', None, ''],
        ['Sec 1', 'B', 'Math', 180, 'minutes', None, ''],
        ['Sec 1', 'CMN', 'Math', 210, 'minutes', None, ''],
        ['Sec 1', 'Shared PE', 'PE', 90, 'minutes', None, ''],
        ['Sec 1', 'Shared Arts', 'Art', 60, 'minutes', None, 'Arts'],
        ['Sec 1', 'Shared Arts', 'Music', 120, 'minutes', None, 'Arts'],
    ], columns=['Level', 'Stream', 'Subject', 'Minimum weekly requirement', 'Unit', 'Reference period duration in minutes', 'Elective group'])


def test_arbitrary_multiple_common_labels_and_cmn_student():
    detail, totals = curriculum_allocation(subjects(), 30, stream_rules=rules())
    t = totals.set_index('Stream')
    assert set(t.index) == {'A', 'B', 'CMN'}
    assert t.loc['A', 'Curriculum minutes'] == 240
    assert t.loc['B', 'Curriculum minutes'] == 330
    assert t.loc['CMN', 'Curriculum minutes'] == 300
    assert set(detail.loc[detail.Subject == 'PE', 'Requirement source']) == {'Shared PE'}
    assert set(detail.loc[detail.Subject == 'Art', 'Stream']) == {'B'}
    _, days, acts = sample_data()
    _, _, summary = estimate_week(detail, days[days.Level == 'Sec 1'], acts[acts.Level == 'Sec 1'], 30)
    assert set(summary.Stream) == {'A', 'B', 'CMN'}


def test_student_specific_override_and_overlapping_common_conflict():
    s = subjects()
    extra = pd.DataFrame([['Sec 1', 'Shared Arts', 'PE', 30, 'minutes', None, '']], columns=s.columns)
    with pytest.raises(ValueError, match='overlapping common'):
        curriculum_allocation(pd.concat([s, extra]), 30, stream_rules=rules())
    own = extra.copy(); own['Stream'] = 'B'; own['Minimum weekly requirement'] = 120
    detail, _ = curriculum_allocation(pd.concat([s, extra, own]), 30, stream_rules=rules())
    pe = detail[detail.Subject == 'PE'].set_index('Stream')
    assert len(pe) == 3
    assert pe.loc['B', 'Actual minutes'] == 120
    assert pe.loc['B', 'Requirement source'] == 'B'


@pytest.mark.parametrize('change', ['no_recipients', 'common_target', 'unknown_target', 'student_targets', 'duplicate', 'bad_type', 'blank_name'])
def test_invalid_rules(change):
    r = rules()
    if change == 'no_recipients': r.loc[3, 'Applies to'] = ''
    if change == 'common_target': r.loc[3, 'Applies to'] = 'Shared Arts'
    if change == 'unknown_target': r.loc[3, 'Applies to'] = 'Missing'
    if change == 'student_targets': r.loc[0, 'Applies to'] = 'B'
    if change == 'duplicate': r.loc[0, 'Stream'] = 'B'
    if change == 'bad_type': r.loc[0, 'Type'] = 'Maybe'
    if change == 'blank_name': r.loc[0, 'Stream'] = ''
    with pytest.raises(ValueError): validate_stream_rules(r)


def test_rule_classification_persists_through_excel_and_direct_calculation():
    payload = custom_template(['Sec 1'], list(rules().Stream), ['PE'], stream_rules=rules())
    s, d, a = read_inputs(BytesIO(payload))
    assert s.attrs['stream_rules'] == rules().to_dict('records')
    s = s[s.Stream == 'Shared PE'].copy(); s['Minimum weekly requirement'] = 90
    assert set(curriculum_allocation(s, 30)[1].Stream) == {'A', 'B', 'CMN'}
    out = workbook({'Subject Requirements': s, 'School Day Settings': d, 'Fixed Activities': a})
    loaded, _, _ = read_inputs(BytesIO(out))
    assert loaded.attrs['stream_rules'] == rules().to_dict('records')


def test_unclassified_input_is_rejected():
    s = subjects(); s.loc[0, 'Stream'] = 'New label'
    with pytest.raises(ValueError, match='Classify'):
        curriculum_allocation(s, 30, stream_rules=rules())
