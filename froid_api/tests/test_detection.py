"""Tests unitaires de la détection des ruptures (app/detection.py)."""
import pytest

from app.detection import BreachTracker, is_out_of_range

TMIN, TMAX = 2.0, 8.0


def reading(temp, ts, lat=36.8, lon=10.18):
    return {"temperature": temp, "ts": ts, "lat": lat, "lon": lon}


# ---------- is_out_of_range ----------
@pytest.mark.parametrize(
    "temp, expected",
    [
        (5.0, False),    # milieu de la plage
        (2.0, False),    # borne basse incluse
        (8.0, False),    # borne haute incluse
        (1.99, True),    # juste en dessous
        (8.01, True),    # juste au-dessus
        (-10.0, True),
        (25.88, True),
    ],
)
def test_is_out_of_range(temp, expected):
    assert is_out_of_range(temp, TMIN, TMAX) is expected


# ---------- BreachTracker ----------
def test_no_alert_for_normal_readings():
    t = BreachTracker(TMIN, TMAX, 3)
    assert all(t.feed(reading(5.0, i * 5000)) is None for i in range(10))


def test_alert_opens_at_third_consecutive_reading():
    t = BreachTracker(TMIN, TMAX, 3)
    assert t.feed(reading(10.0, 1_000_000_000_000)) is None
    assert t.feed(reading(10.5, 1_000_000_005_000)) is None
    alert = t.feed(reading(11.0, 1_000_000_010_000))
    assert alert is not None
    assert alert["status"] == "open"
    assert alert["kind"] == "hot"
    assert alert["readings"] == 3
    assert alert["peak"] == 11.0
    assert alert["started_ts"] == 1_000_000_000_000
    assert alert["id"] == str(alert["started_ts"])
    assert alert["duration_s"] == 10


def test_isolated_normal_reading_resets_counter():
    t = BreachTracker(TMIN, TMAX, 3)
    t.feed(reading(10.0, 1))
    t.feed(reading(10.0, 2))
    assert t.feed(reading(5.0, 3)) is None      # remise à zéro, pas d'alerte
    assert t.feed(reading(10.0, 4)) is None     # on repart de 1
    assert t.feed(reading(10.0, 5)) is None


def test_alert_keeps_updating_while_breach_continues():
    t = BreachTracker(TMIN, TMAX, 3)
    for i in range(1, 4):
        t.feed(reading(10.0, i))
    alert = t.feed(reading(12.0, 4))
    assert alert["status"] == "open"
    assert alert["readings"] == 4
    assert alert["peak"] == 12.0


def test_alert_closes_on_first_normal_reading():
    t = BreachTracker(TMIN, TMAX, 3)
    for i in range(1, 4):
        t.feed(reading(10.0, i))
    closed = t.feed(reading(5.0, 4))
    assert closed["status"] == "closed"
    assert closed["readings"] == 3
    # Après fermeture, plus d'événement tant que tout est conforme
    assert t.feed(reading(5.0, 5)) is None


def test_new_alert_after_closure_starts_fresh():
    t = BreachTracker(TMIN, TMAX, 3)
    for i in range(1, 4):
        t.feed(reading(10.0, i))
    t.feed(reading(5.0, 4))
    assert t.feed(reading(10.0, 5)) is None
    assert t.feed(reading(10.0, 6)) is None
    alert = t.feed(reading(10.0, 7))
    assert alert["started_ts"] == 5
    assert alert["readings"] == 3


def test_cold_alert_uses_minimum_as_peak():
    t = BreachTracker(TMIN, TMAX, 3)
    t.feed(reading(1.0, 1))
    t.feed(reading(0.0, 2))
    alert = t.feed(reading(-1.5, 3))
    assert alert["kind"] == "cold"
    assert alert["peak"] == -1.5


def test_reading_without_temperature_is_ignored():
    t = BreachTracker(TMIN, TMAX, 3)
    assert t.feed({"ts": 1, "lat": 0, "lon": 0}) is None


def test_min_readings_is_configurable():
    t = BreachTracker(TMIN, TMAX, 1)
    assert t.feed(reading(10.0, 1))["status"] == "open"
