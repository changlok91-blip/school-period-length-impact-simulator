from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_dashboard_filters_and_manual_allocations():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
    assert not app.exception
    app.selectbox[0].select('Sec 2').run()
    assert not app.exception
    app.checkbox[0].check().run()
    assert not app.exception
    app.select_slider[0].set_value(35).run()
    assert not app.exception


def test_multiple_stream_dashboard(monkeypatch):
    import pandas as pd
    import simulator
    subjects, days, activities = simulator.sample_data()
    other = subjects.copy()
    other['Stream'] = 'G2'
    other['Minimum weekly requirement'] *= 2
    monkeypatch.setattr(simulator, 'sample_data', lambda: (pd.concat([subjects, other], ignore_index=True), days, activities))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
    assert not app.exception
    app.selectbox[1].select('G2').run()
    assert not app.exception
    app.checkbox[0].check().run()
    assert not app.exception


def test_template_setup_updates_download_choices(monkeypatch):
    import simulator
    calls = []
    original = simulator.custom_template
    def capture(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(simulator, 'custom_template', capture)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
    app.text_area(key='template_levels').set_value('Custom level').run()
    app.text_area(key='template_streams').set_value('Stream A\nStream B').run()
    app.text_area(key='template_subjects').set_value('Biology').run()
    assert not app.exception
    assert calls[-1][:3] == (['Custom level'], ['Stream A', 'Stream B'], ['Biology'])
    app.text_area(key='template_levels').set_value('').run()
    assert not app.exception
    assert any('Level: enter' in item.value for item in app.warning)
    # Invalid setup must not prevent using the existing dashboard.
    assert app.selectbox[0].value == 'All levels'
