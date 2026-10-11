"""
Modèles Pydantic v2 pour la validation des données et les réponses de l'API.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class Reading(BaseModel):
    """
    Modèle de validation pour une mesure de télémétrie du camion frigorifique.
    """
    temperature: float = Field(
        ...,
        ge=-60.0,
        le=100.0,
        description="Température mesurée par la sonde (°C)",
    )
    lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Latitude GPS",
    )
    lon: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Longitude GPS",
    )
    speed: float = Field(
        ...,
        ge=0.0,
        le=250.0,
        description="Vitesse du camion (km/h)",
    )
    ts: int = Field(
        ...,
        gt=0,
        description="Horodatage Unix en millisecondes",
    )
    out_of_range: Optional[bool] = Field(
        default=None,
        description="Indicateur d'anomalie thermique (recalculé côté serveur)",
    )


class Alert(BaseModel):
    """
    Modèle représentant un événement d'alerte de rupture de la chaîne du froid.
    """
    id: str = Field(..., description="Identifiant unique (str du started_ts)")
    status: str = Field(..., description="Statut de l'alerte ('open' ou 'closed')")
    kind: str = Field(..., description="Nature de l'anomalie ('hot' ou 'cold')")
    peak: float = Field(..., description="Température extrême atteinte pendant l'anomalie")
    readings: int = Field(..., ge=1, description="Nombre de mesures consécutives hors plage")
    started_ts: int = Field(..., gt=0, description="Horodatage de la 1ère mesure hors plage")
    last_ts: int = Field(..., gt=0, description="Horodatage de la dernière mesure hors plage")
    duration_s: int = Field(..., ge=0, description="Durée de l'anomalie en secondes")
    lat: float = Field(..., description="Dernière latitude enregistrée")
    lon: float = Field(..., description="Dernière longitude enregistrée")


class HealthResponse(BaseModel):
    """
    Réponse du point de terminaison /health.
    """
    api: str = "ok"
    mongo: bool
    firebase_last_ok_s: Optional[float] = None
    network_errors: int = 0
    invalid_readings: int = 0


class RangeInfo(BaseModel):
    """
    Seuils réglementaires de température configurés.
    """
    min: float
    max: float


class StatusResponse(BaseModel):
    """
    Réponse du point de terminaison /api/status.
    """
    latest_reading: Optional[Dict[str, Any]] = None
    data_age_s: Optional[float] = None
    sensor_offline: bool
    open_alert: Optional[Dict[str, Any]] = None
    range: RangeInfo


class StatsResponse(BaseModel):
    """
    Réponse du point de terminaison /api/stats (agrégation globale).
    """
    readings: int = 0
    temp_min: Optional[float] = None
    temp_avg: Optional[float] = None
    temp_max: Optional[float] = None
    pct_out_of_range: float = 0.0
    alerts: int = 0
