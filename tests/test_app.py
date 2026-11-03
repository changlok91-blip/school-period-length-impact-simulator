import json
from pathlib import Path
from streamlit.testing.v1 import AppTest
from streamlit.proto.WidgetStates_pb2 import WidgetState


APP = str(Path(__file__).resolve().parents[1] / 'app.py')


def edit_adjustment(app, row, adjustment):
    """Send the real data-editor widget event (AppTest lacks a public editor API)."""
    editor = next(item for item in app.dataframe if 'Adjustment (periods)' in item.value and 'Subject' in item.value)
    states = app._tree.get_widget_states()
    state = WidgetState(id=editor.proto.id, string_value=json.dumps({
        'edited_rows': {str(row): {'Adjustment (periods)': adjustment}},
        'added_rows': [], 'deleted_rows': []}))
    states.widgets.append(state)
    app._run(states)
    return app


def subject_table(app):
    return next(item.value for item in app.dataframe if 'Requirement status' in item.value)


def totals_table(app):
    return next(item.value for item in app.dataframe if 'Curriculum hours' in item.value)


def test_focused_outputs_and_live_adjustment():
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    assert len(app.select_slider) == 1
    assert app.select_slider[0].label == 'Minutes per period'
    assert len(app.get('plotly_chart')) == 1
    assert not any('Four-scenario comparison' in item.value for item in app.subheader)
    initial = totals_table(app).iloc[0]['Curriculum minutes']
    edit_adjustment(app, 0, 2)
    assert not app.exception
    assert subject_table(app).iloc[0]['Allocated periods'] == 9  # 210 / 30 + 2
    assert totals_table(app).iloc[0]['Curriculum minutes'] == initial + 60
    # A second edit applies immediately; no second click is needed.
    edit_adjustment(app, 0, -1)
    assert subject_table(app).iloc[0]['Allocated periods'] == 6
    assert subject_table(app).iloc[0]['Requirement status'] == 'Shortfall'
    assert totals_table(app).iloc[0]['Subjects below minimum'] == 1
    assert app.warning


def test_scenario_adjustments_persist_and_reset():
    app = AppTest.from_file(APP).run(timeout=30)
    edit_adjustment(app, 0, 2)
    app.select_slider[0].set_value(35).run()
    assert subject_table(app).iloc[0]['Minimum periods'] == 6
    assert subject_table(app).iloc[0]['Adjustment (periods)'] == 0
    edit_adjustment(app, 0, 1)
    app.select_slider[0].set_value(30).run()
    assert subject_table(app).iloc[0]['Adjustment (periods)'] == 2
    assert subject_table(app).iloc[0]['Allocated periods'] == 9
    next(button for button in app.button if button.label == 'Reset all period adjustments').click().run()
    assert subject_table(app).iloc[0]['Adjustment (periods)'] == 0
    app.select_slider[0].set_value(35).run()
    assert subject_table(app).iloc[0]['Adjustment (periods)'] == 0
    assert not app.exception


def test_invalid_adjustment_can_be_corrected():
    app = AppTest.from_file(APP).run(timeout=30)
    edit_adjustment(app, 0, -100)
    assert not app.exception
    assert app.error and 'negative' in app.error[0].value
    assert not any('Curriculum hours' in item.value for item in app.dataframe)
    edit_adjustment(app, 0, 1)
    assert not app.exception and not app.error
    assert subject_table(app).iloc[0]['Allocated periods'] == 8
    assert totals_table(app).iloc[0]['Curriculum hours'] > 0


def test_stream_totals_and_row_identity(monkeypatch):
    import pandas as pd
    import simulator
    subjects, days, activities = simulator.sample_data()
    other = subjects.copy()
    other['Stream'] = 'G2'
    other['Minimum weekly requirement'] *= 2
    data = pd.concat([subjects, other], ignore_index=True)
    monkeypatch.setattr(simulator, 'sample_data', lambda: (data, days, activities))
    app = AppTest.from_file(APP).run(timeout=30)
    before = totals_table(app).set_index(['Level', 'Stream'])
    edit_adjustment(app, 0, 2)
    after = totals_table(app).set_index(['Level', 'Stream'])
    assert after.loc[('Sec 1', 'General'), 'Curriculum minutes'] == before.loc[('Sec 1', 'General'), 'Curriculum minutes'] + 60
    assert after.loc[('Sec 1', 'G2'), 'Curriculum minutes'] == before.loc[('Sec 1', 'G2'), 'Curriculum minutes']
    # Reordering requirements must never move the adjustment to a different subject.
    data = data.iloc[::-1].reset_index(drop=True)
    app.run()
    detail = subject_table(app).set_index(['Level', 'Stream', 'Subject'])
    assert detail.loc[('Sec 1', 'General', 'English'), 'Adjustment (periods)'] == 2
    assert detail['Adjustment (periods)'].sum() == 2
    assert not app.exception


def test_template_setup_updates_download_choices(monkeypatch):
    import simulator
    calls = []
    original = simulator.custom_template
    def capture(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(simulator, 'custom_template', capture)
    app = AppTest.from_file(APP).run(timeout=30)
    app.text_area(key='template_levels').set_value('Custom level').run()
    app.text_area(key='template_streams').set_value('Stream A\nStream B').run()
    app.text_area(key='template_subjects').set_value('Biology').run()
    assert not app.exception
    assert calls[-1][:3] == (['Custom level'], ['Stream A', 'Stream B'], ['Biology'])
    app.text_area(key='template_levels').set_value('').run()
    assert not app.exception
    assert any('Level: enter' in item.value for item in app.warning)
    assert len(app.select_slider) == 1
    assert not totals_table(app).empty


def test_curriculum_view_does_not_depend_on_day_capacity(monkeypatch):
    import simulator
    subjects, days, activities = simulator.sample_data()
    days = days.iloc[:0]
    monkeypatch.setattr(simulator, 'sample_data', lambda: (subjects, days, activities))
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception and not app.error
    assert not totals_table(app).empty


def test_startup_refreshes_cached_helper_missing_new_function(monkeypatch):
    import simulator
    # Simulate the previous module still loaded in a long-running Cloud process.
    monkeypatch.delattr(simulator, 'curriculum_allocation')
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    assert not totals_table(app).empty
    assert callable(simulator.curriculum_allocation)


def test_weekly_layout_follows_adjustments_and_stream_selection():
    app = AppTest.from_file(APP).run(timeout=30)
    def weekly_summary():
        return next(item.value for item in app.dataframe if 'Unplaced periods' in item.value)
    before = weekly_summary().iloc[0]['Placed periods']
    edit_adjustment(app, 0, 2)
    assert not app.exception
    assert weekly_summary().iloc[0]['Placed periods'] == before + 2
    app.selectbox(key='week_level').select('Sec 3').run()
    daily = next(item.value for item in app.dataframe if 'Unallocated school minutes' in item.value)
    assert set(daily.Level) == {'Sec 3'}
    assert (daily['Estimated dismissal'] >= daily['Earliest dismissal']).all()
    assert (daily['Estimated dismissal'] <= daily['Latest dismissal']).all()


def test_elective_choice_changes_hours_and_week_without_double_counting(monkeypatch):
    import simulator
    import pandas as pd
    subjects, days, activities = simulator.sample_data()
    subjects = subjects[(subjects.Level == 'Sec 1') & subjects.Subject.isin(['English', 'Mathematics', 'Science'])].copy()
    subjects['Elective group'] = ['', 'Choice A', 'Choice A']
    monkeypatch.setattr(simulator, 'sample_data', lambda: (subjects, days[days.Level == 'Sec 1'], activities[activities.Level == 'Sec 1']))
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    electives = next(widget for widget in app.selectbox if 'Choice A' in widget.label)
    assert electives.value == 'Mathematics'
    assert totals_table(app).iloc[0]['Allocated periods'] == 14
    electives.select('Science').run()
    assert not app.exception
    assert totals_table(app).iloc[0]['Allocated periods'] == 13
    summary = next(item.value for item in app.dataframe if 'Placed periods' in item.value)
    assert summary.iloc[0]['Allocated periods'] == 13
    selected = subject_table(app)
    assert set(selected.loc[selected.Selected, 'Subject']) == {'English', 'Science'}


def test_startup_refreshes_pre_elective_helper(monkeypatch):
    import simulator
    monkeypatch.delattr(simulator, 'elective_input_version')
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    assert hasattr(simulator, 'elective_input_version')


def test_common_inputs_produce_three_real_stream_outputs(monkeypatch):
    import simulator
    import pandas as pd
    _, days, acts = simulator.sample_data()
    subjects = pd.DataFrame([
        ['Sec 1', 'CMN', 'PE', 90, 'minutes', None, ''],
        ['Sec 1', 'G1', 'Mathematics', 150, 'minutes', None, ''],
    ], columns=['Level', 'Stream', 'Subject', 'Minimum weekly requirement', 'Unit', 'Reference period duration in minutes', 'Elective group'])
    monkeypatch.setattr(simulator, 'sample_data', lambda: (subjects, days[days.Level == 'Sec 1'], acts[acts.Level == 'Sec 1']))
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    assert set(totals_table(app).Stream) == {'G3', 'G2', 'G1'}
    assert set(subject_table(app)['Requirement source']) == {'CMN', 'G1'}
    assert 'CMN' not in app.selectbox(key='week_stream').options
    pe = subject_table(app)
    idx = pe[(pe.Stream == 'G1') & (pe.Subject == 'PE')].index[0]
    edit_adjustment(app, int(idx), 1)
    totals = totals_table(app).set_index('Stream')
    assert totals.loc['G1', 'Curriculum minutes'] == 270
    assert totals.loc['G2', 'Curriculum minutes'] == 90


def test_common_recipients_can_be_renamed_in_app(monkeypatch):
    import simulator
    import pandas as pd
    _, days, acts = simulator.sample_data()
    subjects = pd.DataFrame([['Sec 1', 'CMN', 'PE', 90, 'minutes', None]], columns=simulator.SUB[:1] + ['Stream'] + simulator.SUB[1:])
    subjects.attrs['common_streams'] = ['Alpha', 'Beta']
    monkeypatch.setattr(simulator, 'sample_data', lambda: (subjects, days[days.Level == 'Sec 1'], acts[acts.Level == 'Sec 1']))
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    assert set(totals_table(app).Stream) == {'Alpha', 'Beta'}
    next(widget for widget in app.text_area if widget.label.startswith('Streams receiving CMN')).set_value('X\nY\nZ').run()
    assert not app.exception
    assert set(totals_table(app).Stream) == {'X', 'Y', 'Z'}
    assert set(app.selectbox(key='week_stream').options) == {'X', 'Y', 'Z'}
