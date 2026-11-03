from io import BytesIO
import pandas as pd
import pytest
from openpyxl import load_workbook
from simulator import (template, read_inputs, workbook, selection_lists, calculate,
                       CHOICE_COLUMNS, INPUT_LIMIT, LIST_LIMIT)


def test_template_validation_rules_and_dynamic_names():
    book = load_workbook(BytesIO(template()))
    assert list(book['Lists'].values)[0] == tuple(CHOICE_COLUMNS)
    ws = book['Subject Requirements']
    assert [c.value for c in ws[1]][:3] == ['Level', 'Stream', 'Subject']
    rules = list(ws.data_validations.dataValidation)
    assert len(rules) == 6
    for col, letter in [('Level', 'A'), ('Stream', 'B'), ('Subject', 'C'), ('Unit', 'E')]:
        rule = next(r for r in rules if r.formula1 == f'=Choices_{col}')
        assert rule.type == 'list' and rule.showDropDown is False
        assert rule.errorStyle == 'stop' and rule.showErrorMessage
        assert f'{letter}2:{letter}{INPUT_LIMIT+1}' in str(rule.sqref)
        assert f'${LIST_LIMIT+1}' in book.defined_names[f'Choices_{col}'].attr_text
        assert 'COUNTA' in book.defined_names[f'Choices_{col}'].attr_text
    numeric = [r for r in rules if r.type == 'decimal']
    assert {(str(r.sqref), r.operator, r.allow_blank) for r in numeric} == {
        (f'D2:D{INPUT_LIMIT+1}', 'greaterThanOrEqual', False),
        (f'F2:F{INPUT_LIMIT+1}', 'greaterThan', True)}


def test_custom_choices_upload_and_export_preserved():
    book = load_workbook(BytesIO(template()))
    lists = book['Lists']
    # Each list grows independently of the other columns.
    lists.cell(3, 2, 'Custom stream')
    book['Subject Requirements']['B2'] = 'Custom stream'
    out = BytesIO()
    book.save(out)
    inputs = read_inputs(BytesIO(out.getvalue()))
    assert inputs[0].iloc[0].Stream == 'Custom stream'
    calculate(*inputs)
    data = workbook(dict(zip(['Subject Requirements', 'School Day Settings', 'Fixed Activities'], inputs)))
    result = load_workbook(BytesIO(data))
    assert result['Lists']['B3'].value == 'Custom stream'
    assert len(result['Subject Requirements'].data_validations.dataValidation) == 6


def test_pasted_unknown_choice_is_rejected():
    book = load_workbook(BytesIO(template()))
    book['Subject Requirements']['C2'] = 'Not on list'
    out = BytesIO(); book.save(out)
    with pytest.raises(ValueError, match='missing from Lists'):
        read_inputs(BytesIO(out.getvalue()))


def test_unsupported_unit_list_rejected():
    s, d, a = read_inputs(BytesIO(template()))
    lists = selection_lists(s)
    lists.loc[2, 'Unit'] = 'hours'
    data = workbook({'Subject Requirements': s, 'School Day Settings': d, 'Fixed Activities': a, 'Lists': lists})
    with pytest.raises(ValueError, match='only minutes and periods'):
        read_inputs(BytesIO(data))


@pytest.mark.parametrize('column,value', [('Minimum weekly requirement', 'abc'), ('Reference period duration in minutes', 'abc'), ('Reference period duration in minutes', 0)])
def test_numeric_upload_validation(column, value):
    s, d, a = read_inputs(BytesIO(template()))
    s[column] = s[column].astype(object)
    s.loc[0, column] = value
    with pytest.raises(ValueError):
        calculate(s, d, a)
