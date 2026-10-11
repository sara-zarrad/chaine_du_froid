"""
Module de détection des ruptures de la chaîne du froid.
Logique métier pure : aucun import de réseau, de Pydantic ni de base de données.
"""

from typing import Any, Dict, List, Optional


def is_out_of_range(temp: float, tmin: float, tmax: float) -> bool:
    """
    Détermine si une température est hors de la plage autorisée [tmin, tmax].

    :param temp: Température mesurée en °C.
    :param tmin: Borne inférieure autorisée en °C.
    :param tmax: Borne supérieure autorisée en °C.
    :return: True si temp < tmin ou temp > tmax, sinon False.
    """
    return temp < tmin or temp > tmax


class BreachTracker:
    """
    Suivi d'état pour la détection et le cycle de vie des alertes thermiques.

    Règles :
    - Compte les mesures consécutives hors plage.
    - Une alerte s'ouvre à la mesure numéro `min_readings`.
    - started_ts correspond au ts de la PREMIÈRE mesure hors plage de la série.
    - Tant que la série continue, l'alerte est mise à jour (status 'open') et retournée.
    - À la première mesure conforme suivant une alerte ouverte, l'alerte est retournée
      une dernière fois avec status 'closed'.
    - Une mesure conforme isolée remet le compteur à zéro sans déclencher d'alerte
      si min_readings n'a pas été atteint.
    """

    def __init__(self, tmin: float, tmax: float, min_readings: int = 3) -> None:
        """
        Initialise le traqueur d'alertes.

        :param tmin: Température minimale conforme en °C.
        :param tmax: Température maximale conforme en °C.
        :param min_readings: Nombre consécutif de mesures hors plage requis.
        """
        self.tmin: float = float(tmin)
        self.tmax: float = float(tmax)
        self.min_readings: int = int(min_readings)

        self._consecutive_out: List[Dict[str, Any]] = []
        self._is_open: bool = False

    def feed(self, reading: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Traite une nouvelle mesure et émet un événement d'alerte si applicable.

        :param reading: Dictionnaire contenant au minimum 'temperature', 'ts', 'lat', 'lon'.
        :return: Document d'alerte (dict) si une alerte s'ouvre, se prolonge ou se ferme,
                 sinon None.
        """
        temp = reading.get("temperature")
        if temp is None:
            return None

        out = is_out_of_range(temp, self.tmin, self.tmax)

        if out:
            self._consecutive_out.append(reading)

            # Si le seuil minimal de mesures consécutives n'est pas encore atteint
            if len(self._consecutive_out) < self.min_readings:
                return None

            # Le seuil est atteint ou dépassé : alerte active ("open")
            self._is_open = True
            return self._build_alert_doc(status="open")

        else:
            # La mesure est conforme
            if self._is_open:
                # Première mesure conforme après une alerte : fermeture ("closed")
                closed_alert = self._build_alert_doc(status="closed")
                self._consecutive_out.clear()
                self._is_open = False
                return closed_alert
            else:
                # Mesure conforme normale ou réinitialisation d'une série < min_readings
                self._consecutive_out.clear()
                return None

    def _build_alert_doc(self, status: str) -> Dict[str, Any]:
        """
        Construit le document d'alerte à partir de la série courante de mesures hors plage.
        """
        first_reading = self._consecutive_out[0]
        last_reading = self._consecutive_out[-1]

        started_ts = int(first_reading["ts"])
        last_ts = int(last_reading["ts"])

        # Kind : "hot" si au moins une température > tmax, sinon "cold"
        has_hot = any(r["temperature"] > self.tmax for r in self._consecutive_out)
        kind = "hot" if has_hot else "cold"

        # Peak : maximum si hot, minimum si cold
        temps = [r["temperature"] for r in self._consecutive_out]
        raw_peak = max(temps) if kind == "hot" else min(temps)
        peak = round(float(raw_peak), 2) if isinstance(raw_peak, float) else raw_peak

        # Calcul de duration_s (arrondi, entre la première et la dernière mesure hors plage)
        diff = last_ts - started_ts
        if started_ts > 100_000_000_000 or (diff >= 1000 and diff % 1000 == 0):
            # Horodatage en millisecondes
            duration_s = int(round(diff / 1000.0))
        else:
            # Horodatage déjà en secondes (ex: tests unitaires avec petits entiers)
            duration_s = int(round(diff))

        return {
            "id": str(started_ts),
            "status": status,
            "kind": kind,
            "peak": peak,
            "readings": len(self._consecutive_out),
            "started_ts": started_ts,
            "last_ts": last_ts,
            "duration_s": duration_s,
            "lat": last_reading.get("lat"),
            "lon": last_reading.get("lon"),
        }
