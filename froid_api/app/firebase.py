"""
Module d'intégration avec Firebase Realtime Database.
Utilise l'API REST via la bibliothèque requests avec un timeout configurable.
Aucun compte de service ni clé d'authentification n'est requis (règles ouvertes en TP).
"""

from typing import Any, Dict, Optional
import requests


def get_current_reading(firebase_url: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    """
    Récupère la mesure courante depuis Firebase : GET {FIREBASE_URL}/transport/current.json.

    :param firebase_url: URL de base de la base Realtime Database (sans slash final).
    :param timeout: Délai d'attente maximal en secondes (défaut 8s).
    :return: Dictionnaire des données JSON, ou None si la clé est vide/nulle.
    :raises requests.RequestException: En cas d'erreur de communication réseau.
    """
    url = f"{firebase_url}/transport/current.json"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()

    data = response.json()
    if data is None or not isinstance(data, dict):
        return None
    return data


def put_alert(firebase_url: str, alert_id: str, alert_doc: Dict[str, Any], timeout: float = 8.0) -> bool:
    """
    Publie un événement d'alerte sur Firebase : PUT {FIREBASE_URL}/transport/alerts/{alert_id}.json.

    :param firebase_url: URL de base de la base Realtime Database.
    :param alert_id: Identifiant de l'alerte (started_ts en str).
    :param alert_doc: Document complet de l'alerte.
    :param timeout: Délai d'attente maximal en secondes (défaut 8s).
    :return: True si la publication a réussi.
    :raises requests.RequestException: En cas d'erreur de communication réseau.
    """
    url = f"{firebase_url}/transport/alerts/{alert_id}.json"
    response = requests.put(url, json=alert_doc, timeout=timeout)
    response.raise_for_status()
    return True
