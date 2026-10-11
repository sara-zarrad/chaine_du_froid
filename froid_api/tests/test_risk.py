"""Tests du modèle de risque (app/risk.py) et de la route /api/risk."""
import time

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app import risk


def series(temps, step_s=10, end_ms=None):
    """Mesures espacées de step_s secondes, la dernière à end_ms."""
    end_ms = end_ms or 1_760_000_000_000
    n = len(temps)
    return [{"temperature": t, "ts": end_ms - (n - 1 - i) * step_s * 1000} for i, t in enumerate(temps)]


def test_model_file_is_consistent():
    m = risk.load_model()
    n = len(m["features"])
    assert len(m["mean"]) == len(m["scale"]) == len(m["coef"]) == n
    assert 0 < m["thresholds"]["medium"] < m["thresholds"]["high"] < 1


def test_unknown_with_fewer_than_three_readings():
    assert risk.predict_risk(series([5.0, 5.1]))["level"] == "unknown"
    assert risk.predict_risk([])["level"] == "unknown"


def test_stable_temperature_is_low_risk():
    r = risk.predict_risk(series([5.0, 5.05, 4.95, 5.0, 5.02, 4.98]))
    assert r["level"] == "low"
    assert r["probability"] < 0.1


def test_fast_rise_towards_upper_limit_is_high_risk():
    r = risk.predict_risk(series([5.0, 5.6, 6.2, 6.8, 7.3, 7.8]))
    assert r["level"] == "high"
    assert r["probability"] > 0.6
    assert r["slope_c_min"] > 0
    assert r["eta_s"] is not None and r["eta_s"] < 60


def test_fast_fall_towards_lower_limit_is_high_risk():
    r = risk.predict_risk(series([5.0, 4.4, 3.8, 3.2, 2.7, 2.3]))
    assert r["level"] in ("medium", "high")
    assert r["slope_c_min"] < 0


def test_already_out_of_range_is_breach():
    r = risk.predict_risk(series([7.0, 7.8, 8.5, 9.0, 9.4, 9.8]))
    assert r["level"] == "breach"
    assert r["probability"] == 1.0


def test_probability_increases_with_temperature():
    low = risk.predict_risk(series([4.0, 4.0, 4.0, 4.0, 4.0, 4.0]))["probability"]
    mid = risk.predict_risk(series([6.5, 6.5, 6.5, 6.5, 6.5, 6.5]))["probability"]
    high = risk.predict_risk(series([7.8, 7.8, 7.8, 7.8, 7.8, 7.8]))["probability"]
    assert low < mid < high


def test_probability_is_always_between_0_and_1():
    for temps in ([5, 5, 5], [-5, -3, -1], [7.9, 7.95, 7.99], [2.01, 2.0, 2.02]):
        r = risk.predict_risk(series(temps))
        if r["probability"] is not None:
            assert 0.0 <= r["probability"] <= 1.0


def test_readings_without_valid_timestamps_are_ignored():
    bad = [{"temperature": 5.0}, {"temperature": 5.1, "ts": 0}, {"temperature": "x", "ts": 5}]
    assert risk.predict_risk(bad)["level"] == "unknown"


def test_api_risk_endpoint_uses_recent_readings(monkeypatch):
    now_ms = int(time.time() * 1000)
    monkeypatch.setattr(main_module.poller_state, "recent_readings", series([5.0, 5.6, 6.2, 6.8, 7.3, 7.8], end_ms=now_ms))
    resp = TestClient(main_module.app).get("/api/risk")
    assert resp.status_code == 200
    assert resp.json()["level"] == "high"


def test_api_risk_reports_offline_sensor(monkeypatch):
    old = int(time.time() * 1000) - 10 * 60 * 1000
    monkeypatch.setattr(main_module.poller_state, "recent_readings", series([5.0] * 6, end_ms=old))
    body = TestClient(main_module.app).get("/api/risk").json()
    assert body["level"] == "unknown"
