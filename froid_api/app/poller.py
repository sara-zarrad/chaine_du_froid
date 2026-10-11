"""
Module de scrutation en arrière-plan (Poller démon).
Exécute périodiquement la synchronisation entre Firebase Realtime Database,
MongoDB et le moteur de détection d'alertes thermiques (BreachTracker).
"""

import logging
import threading
import time
from collections import deque
from typing import Any, Dict, Optional
import requests
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from app.config import settings
from app.detection import BreachTracker, is_out_of_range
from app.firebase import get_current_reading, put_alert
from app.models import Reading
from app.db import save_reading, save_alert

logger = logging.getLogger("froid_api.poller")


class PollerState:
    """
    État en mémoire du poller pour le suivi de la télémétrie et des compteurs de pannes.
    """

    def __init__(self) -> None:
        self.network_errors: int = 0
        self.invalid_readings: int = 0
        self.firebase_last_ok_ts: Optional[float] = None
        self.last_processed_ts: Optional[int] = None
        self.latest_reading: Optional[Dict[str, Any]] = None
        self.recent_readings: deque = deque(maxlen=20)   # dernières mesures, pour la prédiction de risque
        self.mongo_ok: bool = False


# Instance unique d'état partagée avec l'API
poller_state = PollerState()


def poller_worker(
    tracker: BreachTracker,
    state: PollerState,
    stop_event: threading.Event,
) -> None:
    """
    Fonction exécutée en continu par le thread démon.

    :param tracker: Instance du détecteur d'anomalies BreachTracker.
    :param state: Conteneur de métriques et d'état.
    :param stop_event: Signal d'arrêt pour l'extinction propre du serveur.
    """
    logger.info(f"[Poller] Démarrage du thread d'interrogation (période : {settings.POLL_SECONDS}s).")

    while not stop_event.is_set():
        try:
            # 1. GET {FIREBASE_URL}/transport/current.json (timeout 8s)
            raw_data = None
            try:
                raw_data = get_current_reading(settings.FIREBASE_URL, timeout=8.0)
                state.firebase_last_ok_ts = time.time()
            except requests.RequestException as req_err:
                state.network_errors += 1
                logger.warning(f"[Poller] Erreur réseau / Firebase injoignable : {req_err}")
                stop_event.wait(settings.POLL_SECONDS)
                continue

            # Si Firebase ne contient pas encore de données ou renvoie null
            if raw_data is None:
                logger.debug("[Poller] Aucune mesure active dans Firebase (/transport/current est null).")
                stop_event.wait(settings.POLL_SECONDS)
                continue

            # 2. Validation avec le modèle Pydantic v2 Reading
            try:
                validated_reading = Reading.model_validate(raw_data)
            except (ValidationError, ValueError, TypeError) as val_err:
                state.invalid_readings += 1
                logger.warning(f"[Poller] Mesure invalide ignorée : {val_err}")
                stop_event.wait(settings.POLL_SECONDS)
                continue

            # 3. Ignore la mesure si son ts est identique au précédent
            if state.last_processed_ts is not None and validated_reading.ts == state.last_processed_ts:
                logger.debug(f"[Poller] Mesure ts={validated_reading.ts} déjà traitée, cycle ignoré.")
                stop_event.wait(settings.POLL_SECONDS)
                continue

            state.last_processed_ts = validated_reading.ts

            # 4. Recalcule out_of_range côté serveur avec les seuils de config
            server_out_of_range = is_out_of_range(
                validated_reading.temperature,
                settings.TEMP_MIN,
                settings.TEMP_MAX,
            )
            validated_reading.out_of_range = server_out_of_range
            reading_dict = validated_reading.model_dump()

            # Mise à jour de la dernière mesure en mémoire pour accès instantané
            state.latest_reading = reading_dict
            state.recent_readings.append(reading_dict)

            # 5. Enregistre la mesure dans MongoDB (readings, index unique sur ts)
            try:
                save_reading(reading_dict)
                state.mongo_ok = True
            except PyMongoError as db_err:
                state.mongo_ok = False
                logger.warning(f"[Poller] MongoDB indisponible lors de l'enregistrement de la mesure : {db_err}")

            # 6. Passe la mesure au BreachTracker
            alert_event = tracker.feed(reading_dict)

            # 7. Si le tracker retourne un événement d'alerte
            if alert_event is not None:
                logger.info(
                    f"[Poller] Événement d'alerte détecté : id={alert_event['id']} "
                    f"status={alert_event['status']} kind={alert_event['kind']} peak={alert_event['peak']}°C"
                )

                # 7a. Upsert dans la collection alerts
                try:
                    save_alert(alert_event)
                    state.mongo_ok = True
                except PyMongoError as db_err:
                    state.mongo_ok = False
                    logger.warning(f"[Poller] MongoDB indisponible lors de l'upsert de l'alerte : {db_err}")

                # 7b. PUT {FIREBASE_URL}/transport/alerts/{id}.json
                try:
                    put_alert(settings.FIREBASE_URL, alert_event["id"], alert_event, timeout=8.0)
                    logger.info(f"[Poller] Alerte synchronisée avec succès sur Firebase : {alert_event['id']}")
                except requests.RequestException as req_err:
                    state.network_errors += 1
                    logger.warning(f"[Poller] Échec de l'envoi de l'alerte vers Firebase : {req_err}")

        except Exception as exc:
            # Gestion des pannes génériques : trace complète et poursuite de la boucle
            logger.exception(f"[Poller] Exception inattendue dans la boucle du poller : {exc}")

        stop_event.wait(settings.POLL_SECONDS)

    logger.info("[Poller] Arrêt du thread d'interrogation.")


class PollerService:
    """
    Gestionnaire du cycle de vie du thread poller.
    """

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.tracker = BreachTracker(
            tmin=settings.TEMP_MIN,
            tmax=settings.TEMP_MAX,
            min_readings=settings.ALERT_MIN_READINGS,
        )

    def start(self) -> None:
        """Démarre le thread d'arrière-plan en mode démon."""
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=poller_worker,
            args=(self.tracker, poller_state, self.stop_event),
            daemon=True,
            name="ColdChainPollerThread",
        )
        self.thread.start()

    def stop(self) -> None:
        """Arrête proprement le thread d'arrière-plan."""
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=3.0)
