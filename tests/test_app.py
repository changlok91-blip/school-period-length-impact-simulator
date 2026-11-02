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
