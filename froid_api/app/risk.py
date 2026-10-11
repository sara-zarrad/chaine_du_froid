"""
Prédiction du risque de rupture de la chaîne du froid (phase IA).

Le modèle est une régression logistique entraînée par `ml/train_risk_model.py`.
Ses coefficients sont stockés dans `app/risk_model.json` : cette partie « inférence »
n'utilise donc que la bibliothèque standard (aucune dépendance scikit-learn à l'exécution).

Question posée au modèle : « d'après les dernières mesures, la température va-t-elle sortir
de la plage [TEMP_MIN, TEMP_MAX] dans les `horizon_s` prochaines secondes ? »
"""
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

MODEL_PATH = Path(__file__).resolve().parent / "risk_model.json"

_model_cache: Optional[Dict[str, Any]] = None


def load_model(path: Path = MODEL_PATH) -> Dict[str, Any]:
    """Charge (une fois) les coefficients du modèle."""
    global _model_cache
    if _model_cache is None or path != MODEL_PATH:
        with open(path, "r", encoding="utf-8") as f:
            model = json.load(f)
        if path != MODEL_PATH:
            return model
        _model_cache = model
    return _model_cache


def compute_features(
    readings: Sequence[Dict[str, Any]], tmin: float, tmax: float, horizon_s: float, window: int
) -> Optional[Dict[str, float]]:
    """
    Calcule les variables d'entrée à partir des `window` dernières mesures (ordre chronologique).
    Retourne None s'il y a moins de 3 mesures exploitables.
    """
    pts = [r for r in readings if isinstance(r.get("temperature"), (int, float)) and r.get("ts")]
    pts = sorted(pts, key=lambda r: r["ts"])[-window:]
    if len(pts) < 3:
        return None

    t0 = pts[-1]["ts"]
    xs = [(p["ts"] - t0) / 60000.0 for p in pts]       # minutes, 0 = dernière mesure
    ys = [float(p["temperature"]) for p in pts]
    n = len(pts)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x < 1e-12:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / var_x   # °C / minute
    std = math.sqrt(sum((y - mean_y) ** 2 for y in ys) / n)

    temp = ys[-1]
    projected = temp + slope * (horizon_s / 60.0)
    margin = min(tmax - temp, temp - tmin)                          # distance à la borne la plus proche
    margin_proj = min(tmax - projected, projected - tmin)
    # Vitesse d'approche de la borne la plus proche (>0 = on s'en rapproche) : le modèle reste
    # symétrique, il traite pareil un réchauffement vers 8 °C et un refroidissement vers 2 °C.
    approach = slope if (tmax - temp) <= (temp - tmin) else -slope
    # Temps estimé avant la borne (secondes, plafonné à 10 min), en échelle logarithmique
    ttb = 600.0 if approach <= 1e-6 else min(600.0, max(margin, 0.0) / approach * 60.0)
    return {
        "temp": temp,
        "slope": slope,
        "std": std,
        "margin": margin,
        "margin_proj": margin_proj,
        "approach": approach,
        "log_ttb": math.log1p(ttb),
    }


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def predict_risk(
    readings: Sequence[Dict[str, Any]],
    tmin: float = 2.0,
    tmax: float = 8.0,
    model: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Retourne un dictionnaire :
      level        : 'unknown' | 'low' | 'medium' | 'high' | 'breach'
      probability  : probabilité (0 à 1) de sortie de plage dans l'horizon, None si inconnu
      eta_s        : secondes estimées avant la sortie de plage (None si pas de tendance vers une borne)
      slope_c_min  : tendance en °C par minute
      reason       : phrase d'explication
    """
    model = model or load_model()
    horizon_s = float(model["horizon_s"])
    feats = compute_features(readings, tmin, tmax, horizon_s, int(model["window"]))
    if feats is None:
        return {"level": "unknown", "probability": None, "eta_s": None, "slope_c_min": None,
                "reason": "Pas assez de mesures (3 minimum) pour estimer le risque."}

    slope = feats["slope"]
    if feats["margin"] < 0:
        return {"level": "breach", "probability": 1.0, "eta_s": 0, "slope_c_min": round(slope, 3),
                "reason": "La température est déjà hors de la plage autorisée."}

    z = model["intercept"]
    for name, mean, scale, coef in zip(model["features"], model["mean"], model["scale"], model["coef"]):
        z += coef * (feats[name] - mean) / scale
    proba = _sigmoid(z)

    # Temps estimé avant la borne atteinte par la tendance actuelle
    eta: Optional[float] = None
    temp = feats["temp"]
    if slope > 1e-6:
        eta = (tmax - temp) / slope * 60.0
    elif slope < -1e-6:
        eta = (temp - tmin) / -slope * 60.0
    if eta is not None and eta > 3600:
        eta = None

    th = model["thresholds"]
    level = "high" if proba >= th["high"] else "medium" if proba >= th["medium"] else "low"
    if level == "low":
        reason = "Température stable et loin des limites."
    else:
        bound = "8 °C" if slope > 0 else "2 °C"
        eta_txt = f" (environ {int(round(eta))} s)" if eta is not None else ""
        reason = f"Tendance de {slope:+.2f} °C/min vers {bound}{eta_txt}."
    return {
        "level": level,
        "probability": round(proba, 3),
        "eta_s": None if eta is None else int(round(eta)),
        "slope_c_min": round(slope, 3),
        "reason": reason,
    }
