"""
Tests d'intégration : poller + détection + validation, avec Firebase et MongoDB simulés.
Couvre aussi la simulation de coupure réseau (Firebase injoignable).
"""
import threading

import pytest
import requests
from fastapi.testclient import TestClient

from app import main as main_module
from app import poller
from app.detection import BreachTracker


def make_raw(temp, ts, **extra):
    raw = {"temperature": temp, "lat": 36.8, "lon": 10.18, "speed": 80, "ts": ts}
    raw.update(extra)
    return raw


@pytest.fixture
def env(monkeypatch):
    """Remplace Firebase et MongoDB par des doublures et accélère la boucle."""
    monkeypatch.setattr(poller.settings, "POLL_SECONDS", 0.001)
    state = poller.PollerState()
    stop = threading.Event()
    saved = {"readings": [], "alerts": [], "firebase_alerts": []}

    monkeypatch.setattr(poller, "save_reading", lambda doc: saved["readings"].append(doc) or True)
    monkeypatch.setattr(poller, "save_alert", lambda doc: saved["alerts"].append(doc) or True)
    monkeypatch.setattr(
        poller, "put_alert", lambda url, aid, doc, timeout=8.0: saved["firebase_alerts"].append(doc) or True
    )

    def run(feed):
        """feed : liste de mesures (dict) ou d'exceptions renvoyées tour à tour par Firebase."""
        items = list(feed)

        def fake_get(url, timeout=8.0):
            if not items:
                stop.set()
                return None
            item = items.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(poller, "get_current_reading", fake_get)
        tracker = BreachTracker(2.0, 8.0, 3)
        t = threading.Thread(target=poller.poller_worker, args=(tracker, state, stop), daemon=True)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "le poller ne s'est pas arrêté"
        return state, saved

    return run


def test_full_scenario_normal_hot_alert_then_recovery(env):
    base = 1_760_000_000_000
    temps = [5.0, 5.0, 12.0, 12.5, 13.0, 13.5, 5.0]
    feed = [make_raw(t, base + i * 5000) for i, t in enumerate(temps)]
    state, saved = env(feed)

    assert len(saved["readings"]) == 7
    assert saved["readings"][2]["out_of_range"] is True
    assert saved["readings"][0]["out_of_range"] is False

    statuses = [a["status"] for a in saved["alerts"]]
    assert statuses == ["open", "open", "closed"]
    assert saved["alerts"][0]["kind"] == "hot"
    assert saved["alerts"][-1]["peak"] == 13.5
    assert len(saved["firebase_alerts"]) == 3          # alertes publiées dans Firebase


def test_invalid_reading_is_counted_and_not_stored(env):
    base = 1_760_000_000_000
    state, saved = env([make_raw(500.0, base), make_raw(5.0, base + 5000)])
    assert state.invalid_readings == 1
    assert len(saved["readings"]) == 1


def test_duplicate_timestamp_is_processed_once(env):
    base = 1_760_000_000_000
    state, saved = env([make_raw(5.0, base), make_raw(5.0, base), make_raw(5.0, base)])
    assert len(saved["readings"]) == 1


def test_server_recomputes_out_of_range(env):
    """Le serveur ne fait pas confiance au champ out_of_range envoyé par l'ESP32."""
    base = 1_760_000_000_000
    state, saved = env([make_raw(20.0, base, out_of_range=False)])
    assert saved["readings"][0]["out_of_range"] is True


def test_network_outage_is_survived_and_counted(env):
    """Coupure réseau : les erreurs sont comptées, le poller continue et reprend après."""
    base = 1_760_000_000_000
    feed = [
        requests.ConnectionError("réseau coupé"),
        requests.Timeout("timeout"),
        make_raw(5.0, base),
    ]
    state, saved = env(feed)
    assert state.network_errors == 2
    assert len(saved["readings"]) == 1                 # reprise après la panne
    assert state.firebase_last_ok_ts is not None


def test_health_endpoint_reports_state(monkeypatch):
    monkeypatch.setattr(main_module.db, "is_mongo_connected", lambda: True)
    client = TestClient(main_module.app)               # sans « with » : pas de poller démarré
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["api"] == "ok"
    assert body["mongo"] is True


def test_readings_returns_503_when_mongo_is_down(monkeypatch):
    from pymongo.errors import ServerSelectionTimeoutError

    def boom(*args, **kwargs):
        raise ServerSelectionTimeoutError("down")

    monkeypatch.setattr(main_module.db, "get_readings_history", boom)
    client = TestClient(main_module.app)
    assert client.get("/api/readings").status_code == 503


def test_readings_query_validation():
    client = TestClient(main_module.app)
    assert client.get("/api/readings?limit=0").status_code == 422
    assert client.get("/api/readings?limit=5000").status_code == 422
