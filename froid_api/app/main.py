"""
API FastAPI de la chaîne du froid (phase 2).

Démarrage : py -m uvicorn app.main:app --reload --port 8000   (depuis le dossier froid_api)
Documentation interactive : http://localhost:8000/docs
"""
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo.errors import PyMongoError

from app import db, risk
from app.config import settings
from app.models import HealthResponse, RangeInfo, StatsResponse, StatusResponse
from app.poller import PollerService, poller_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("froid_api.main")

poller_service = PollerService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Démarre l'API : index MongoDB (sans planter si la base est éteinte) puis tâche de fond."""
    db.init_db()
    poller_service.start()
    yield
    poller_service.stop()


app = FastAPI(title="Chaîne du froid : API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def _from_mongo(func: Callable[..., Any], *args: Any) -> Any:
    """Appelle une fonction MongoDB ; répond HTTP 503 si la base est injoignable."""
    try:
        return func(*args)
    except PyMongoError as err:
        logger.warning("MongoDB indisponible : %s", err)
        raise HTTPException(status_code=503, detail="MongoDB indisponible") from err


def _age_seconds(ts_ms: Optional[int]) -> Optional[float]:
    return round(time.time() - ts_ms / 1000.0, 1) if ts_ms else None


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """État de l'API, de MongoDB et du dernier contact Firebase."""
    last_ok = poller_state.firebase_last_ok_ts
    return HealthResponse(
        mongo=db.is_mongo_connected(),
        firebase_last_ok_s=round(time.time() - last_ok, 1) if last_ok else None,
        network_errors=poller_state.network_errors,
        invalid_readings=poller_state.invalid_readings,
    )


@app.get("/api/status", response_model=StatusResponse)
def status() -> StatusResponse:
    """Dernière mesure, âge des données, capteur hors ligne ?, alerte ouverte."""
    reading: Optional[Dict[str, Any]] = poller_state.latest_reading
    open_alert: Optional[Dict[str, Any]] = None
    try:
        if reading is None:                      # API redémarrée : on reprend la dernière mesure stockée
            reading = db.get_latest_reading()
        open_alert = db.get_latest_open_alert()
    except PyMongoError:
        pass                                     # /api/status reste utilisable sans MongoDB

    age = _age_seconds(reading["ts"]) if reading else None
    # Une alerte « ouverte » dont la dernière mesure est ancienne est un reste d'un ancien lancement
    if open_alert and (_age_seconds(open_alert.get("last_ts")) or 0) > settings.STALE_SECONDS:
        open_alert = None

    return StatusResponse(
        latest_reading=reading,
        data_age_s=age,
        sensor_offline=age is None or age > settings.STALE_SECONDS,
        open_alert=open_alert,
        range=RangeInfo(min=settings.TEMP_MIN, max=settings.TEMP_MAX),
    )


@app.get("/api/readings")
def readings(limit: int = Query(100, ge=1, le=1000), since_ts: int = Query(0, ge=0)) -> List[Dict[str, Any]]:
    """Historique des mesures (plus récentes d'abord)."""
    return _from_mongo(db.get_readings_history, limit, since_ts)


@app.get("/api/alerts")
def alerts(limit: int = Query(50, ge=1, le=500)) -> List[Dict[str, Any]]:
    """Historique des alertes (plus récentes d'abord)."""
    return _from_mongo(db.get_alerts_history, limit)


@app.get("/api/risk")
def risk_prediction() -> Dict[str, Any]:
    """Risque (IA) que la température sorte de la plage dans la prochaine minute."""
    readings: List[Dict[str, Any]] = list(poller_state.recent_readings)
    if len(readings) < 3:                         # API redémarrée : reprendre l'historique MongoDB
        try:
            readings = list(reversed(db.get_readings_history(10, 0)))
        except PyMongoError:
            pass
    result = risk.predict_risk(readings, settings.TEMP_MIN, settings.TEMP_MAX)
    # Données trop anciennes : la prédiction n'aurait pas de sens
    if readings and (_age_seconds(readings[-1].get("ts")) or 0) > settings.STALE_SECONDS:
        return {"level": "unknown", "probability": None, "eta_s": None, "slope_c_min": None,
                "reason": "Capteur hors ligne : aucune mesure récente."}
    return result


@app.get("/api/stats", response_model=StatsResponse)
def stats() -> Dict[str, Any]:
    """Statistiques globales : nombre de mesures, min / moyenne / max, % hors plage, alertes."""
    return _from_mongo(db.get_stats)
