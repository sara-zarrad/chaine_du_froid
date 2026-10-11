"""Tests de validation des mesures (app/models.py, Pydantic v2)."""
import pytest
from pydantic import ValidationError

from app.models import Reading

VALID = {"temperature": 5.0, "lat": 36.8065, "lon": 10.1815, "speed": 81, "ts": 1_760_000_000_000}


def test_valid_reading_is_accepted():
    r = Reading.model_validate(VALID)
    assert r.temperature == 5.0
    assert r.out_of_range is None


@pytest.mark.parametrize(
    "field, value",
    [
        ("temperature", 150.0),   # trop chaud pour être vrai
        ("temperature", -80.0),   # trop froid (capteur déconnecté, ex. -127)
        ("temperature", -127.0),
        ("lat", 91.0),
        ("lat", -91.0),
        ("lon", 181.0),
        ("speed", -1.0),
        ("speed", 300.0),
        ("ts", 0),
        ("ts", -5),
    ],
)
def test_impossible_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Reading.model_validate({**VALID, field: value})


@pytest.mark.parametrize("missing", ["temperature", "lat", "lon", "speed", "ts"])
def test_missing_field_is_rejected(missing):
    data = {k: v for k, v in VALID.items() if k != missing}
    with pytest.raises(ValidationError):
        Reading.model_validate(data)


def test_non_numeric_temperature_is_rejected():
    with pytest.raises(ValidationError):
        Reading.model_validate({**VALID, "temperature": "chaud"})


def test_boundary_values_are_accepted():
    Reading.model_validate({**VALID, "temperature": -60.0, "lat": 90.0, "lon": -180.0, "speed": 0})
