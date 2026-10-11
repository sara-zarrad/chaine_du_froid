"""
Module d'accès à la base de données MongoDB via PyMongo.
Gère la persistance des mesures (collection readings) et des alertes (collection alerts),
ainsi que les requêtes et agrégations statistiques.
"""

import logging
from typing import Any, Dict, List, Optional
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.config import settings

logger = logging.getLogger("froid_api.db")

# Initialisation du client PyMongo avec timeout court pour éviter les blocages
client: MongoClient = MongoClient(
    settings.MONGO_URL,
    serverSelectionTimeoutMS=settings.MONGO_TIMEOUT_MS,
    connectTimeoutMS=settings.MONGO_TIMEOUT_MS,
    socketTimeoutMS=settings.MONGO_TIMEOUT_MS,
)

db: Database = client[settings.MONGO_DB]
readings_collection: Collection = db["readings"]
alerts_collection: Collection = db["alerts"]


def init_db() -> bool:
    """
    Initialise les index de la base de données MongoDB.
    Ne lève pas d'exception si MongoDB est hors ligne lors du démarrage.
    """
    try:
        readings_collection.create_index("ts", unique=True)
        alerts_collection.create_index("id", unique=True)
        alerts_collection.create_index("started_ts")
        logger.info("[MongoDB] Index créés avec succès sur 'readings' (ts unique) et 'alerts' (id unique).")
        return True
    except PyMongoError as err:
        logger.warning(f"[MongoDB] Impossible d'initialiser les index (base probablement hors ligne) : {err}")
        return False


def is_mongo_connected() -> bool:
    """
    Vérifie la disponibilité actuelle du serveur MongoDB via une commande ping.
    """
    try:
        client.admin.command("ping")
        return True
    except PyMongoError:
        return False


def save_reading(reading_doc: Dict[str, Any]) -> bool:
    """
    Insère une mesure dans la collection 'readings'.
    Un doublon sur 'ts' est ignoré sans lever d'erreur.

    :param reading_doc: Données de la mesure validée.
    :return: True si inséré ou doublon ignoré, False en cas d'erreur PyMongo.
    """
    try:
        # Créer une copie superficielle pour ne pas altérer le document original
        doc = dict(reading_doc)
        readings_collection.insert_one(doc)
        return True
    except DuplicateKeyError:
        # Doublon détecté via l'index unique sur ts : ignoré sans erreur
        logger.debug(f"[MongoDB] Mesure ts={reading_doc.get('ts')} déjà présente, doublon ignoré.")
        return True
    except PyMongoError as err:
        logger.warning(f"[MongoDB] Erreur lors de l'insertion de la mesure : {err}")
        raise err


def save_alert(alert_doc: Dict[str, Any]) -> bool:
    """
    Met à jour ou insère une alerte dans la collection 'alerts' (clé 'id').

    :param alert_doc: Données de l'événement d'alerte.
    :return: True en cas de succès.
    """
    try:
        doc = dict(alert_doc)
        alerts_collection.replace_one({"id": doc["id"]}, doc, upsert=True)
        return True
    except PyMongoError as err:
        logger.warning(f"[MongoDB] Erreur lors de l'upsert de l'alerte {alert_doc.get('id')} : {err}")
        raise err


def get_latest_reading() -> Optional[Dict[str, Any]]:
    """
    Récupère la dernière mesure enregistrée dans MongoDB (tri par ts décroissant).
    """
    doc = readings_collection.find_one(sort=[("ts", -1)], projection={"_id": False})
    return doc


def get_latest_open_alert() -> Optional[Dict[str, Any]]:
    """
    Récupère l'alerte actuellement ouverte la plus récente, ou None.
    """
    doc = alerts_collection.find_one({"status": "open"}, sort=[("started_ts", -1)], projection={"_id": False})
    return doc


def get_readings_history(limit: int = 100, since_ts: int = 0) -> List[Dict[str, Any]]:
    """
    Récupère l'historique des mesures depuis MongoDB, plus récent d'abord.
    Exclut le champ interne '_id'.

    :param limit: Nombre maximal de mesures à retourner (1 à 1000).
    :param since_ts: Horodatage minimal en millisecondes.
    """
    query: Dict[str, Any] = {}
    if since_ts > 0:
        query["ts"] = {"$gte": since_ts}

    cursor = readings_collection.find(query, projection={"_id": False}).sort("ts", -1).limit(limit)
    return list(cursor)


def get_alerts_history(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Récupère l'historique des alertes depuis MongoDB, plus récentes d'abord.
    Exclut le champ interne '_id'.

    :param limit: Nombre maximal d'alertes à retourner (1 à 500).
    """
    cursor = alerts_collection.find({}, projection={"_id": False}).sort("started_ts", -1).limit(limit)
    return list(cursor)


def get_stats() -> Dict[str, Any]:
    """
    Calcule les statistiques globales sur la collection 'readings' via une agrégation MongoDB.
    Retourne : readings, temp_min, temp_avg, temp_max, pct_out_of_range, alerts.
    """
    pipeline = [
        {
            "$group": {
                "_id": None,
                "readings": {"$sum": 1},
                "temp_min": {"$min": "$temperature"},
                "temp_max": {"$max": "$temperature"},
                "temp_avg": {"$avg": "$temperature"},
                "out_of_range_count": {
                    "$sum": {"$cond": [{"$eq": ["$out_of_range", True]}, 1, 0]}
                },
            }
        }
    ]

    results = list(readings_collection.aggregate(pipeline))
    alert_count = alerts_collection.count_documents({})

    if not results:
        return {
            "readings": 0,
            "temp_min": None,
            "temp_avg": None,
            "temp_max": None,
            "pct_out_of_range": 0.0,
            "alerts": alert_count,
        }

    data = results[0]
    total_readings = int(data.get("readings", 0))
    oor_count = int(data.get("out_of_range_count", 0))

    pct = round((oor_count / total_readings) * 100.0, 2) if total_readings > 0 else 0.0
    t_min = round(float(data["temp_min"]), 2) if data.get("temp_min") is not None else None
    t_max = round(float(data["temp_max"]), 2) if data.get("temp_max") is not None else None
    t_avg = round(float(data["temp_avg"]), 2) if data.get("temp_avg") is not None else None

    return {
        "readings": total_readings,
        "temp_min": t_min,
        "temp_avg": t_avg,
        "temp_max": t_max,
        "pct_out_of_range": pct,
        "alerts": alert_count,
    }
