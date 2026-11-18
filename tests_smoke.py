"""Smoke test: the app runs end to end without exceptions (Streamlit AppTest), and every tab renders."""
from streamlit.testing.v1 import AppTest


def test_app_runs():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception
    assert len(at.metric) >= 8          # 4 KPI tiles + 4 drill-down tiles
    assert len(at.tabs) == 3


def test_filter_to_one_field():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    at.sidebar.multiselect[0].set_value(["Field A"]).run()
    assert not at.exception
