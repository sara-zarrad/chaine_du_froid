"""
Entraînement du modèle de risque de rupture (régression logistique, scikit-learn).

Usage (depuis le dossier froid_api) :
    py -m pip install -r requirements-ml.txt
    py ml/train_risk_model.py

Les données sont SIMULÉES (camion frigorifique : bruit de capteur, ouvertures de porte,
panne de compresseur, sur-refroidissement). Le script écrit `app/risk_model.json`
et `ml/metrics.json`.
"""
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_fscore_support, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.risk import compute_features  # noqa: E402  (mêmes variables qu'à l'exécution)

TMIN, TMAX = 2.0, 8.0
WINDOW = 6            # nombre de mesures utilisées
HORIZON_S = 60        # on prédit une sortie de plage dans les 60 prochaines secondes
FEATURES = ["margin", "approach", "std", "margin_proj", "log_ttb"]   # symétriques haut / bas
SEED = 42


def simulate_sequence(rng: random.Random, duration_s: int = 1500):
    """Température simulée à 1 point par seconde + bruit capteur. Retourne (liste des mesures bruitées)."""
    setpoint = rng.uniform(3.2, 6.8)
    noise = rng.uniform(0.05, 0.25)
    temp = setpoint + rng.uniform(-1.0, 1.0)
    events = []
    t = rng.uniform(30, 200)
    while t < duration_s:
        kind = rng.choices(["door", "small_door", "compressor", "overcool"], weights=[2, 2, 1.5, 3.5])[0]
        if kind == "door":
            events.append(("up", t, rng.uniform(40, 300), rng.uniform(0.5, 4.0)))
        elif kind == "small_door":
            events.append(("up", t, rng.uniform(15, 80), rng.uniform(0.1, 1.0)))
        elif kind == "compressor":
            events.append(("up", t, rng.uniform(200, 700), rng.uniform(0.08, 0.8)))
        else:
            events.append(("down", t, rng.uniform(60, 400), rng.uniform(0.15, 1.5)))
        t += rng.uniform(90, 300)
    series = []
    for s in range(duration_s):
        drift = 0.0
        for direction, start, dur, rate_per_min in events:
            if start <= s < start + dur:
                drift += (1 if direction == "up" else -1) * rate_per_min / 60.0
        temp += drift + 0.03 * (setpoint - temp) + rng.gauss(0, 0.02)     # retour progressif vers la consigne
        series.append(temp + rng.gauss(0, noise))
    return series


def build_dataset(n_sequences: int, rng: random.Random):
    X, y, groups = [], [], []
    for g in range(n_sequences):
        series = simulate_sequence(rng)
        # instants de mesure irréguliers (5 à 23 s, comme les envois réels de l'ESP32)
        times, t = [], 0
        while t < len(series) - HORIZON_S - 1:
            times.append(t)
            t += rng.randint(5, 23)
        for i in range(WINDOW, len(times)):
            window = [{"temperature": series[times[j]], "ts": 1_700_000_000_000 + times[j] * 1000}
                      for j in range(i - WINDOW + 1, i + 1)]
            now = times[i]
            if not (TMIN <= series[now] <= TMAX):
                continue                       # déjà en rupture : rien à prédire
            feats = compute_features(window, TMIN, TMAX, HORIZON_S, WINDOW)
            future = series[now + 1: now + 1 + HORIZON_S]
            label = int(any(v < TMIN or v > TMAX for v in future))
            X.append([feats[f] for f in FEATURES])
            y.append(label)
            groups.append(g)
    return np.array(X), np.array(y), np.array(groups)


def main():
    rng = random.Random(SEED)
    X, y, groups = build_dataset(1200, rng)
    train = groups < 900                                   # séparation par séquence (pas de fuite)
    Xtr, ytr, Xte, yte = X[train], y[train], X[~train], y[~train]
    print(f"Échantillons : {len(y)} (rupture à venir : {y.mean():.1%}) | train={len(ytr)} test={len(yte)}")

    scaler = StandardScaler().fit(Xtr)
    clf = LogisticRegression(max_iter=1000, C=1.0).fit(scaler.transform(Xtr), ytr)
    proba = clf.predict_proba(scaler.transform(Xte))[:, 1]

    # Référence simple : « la température est proche d'une limite »
    baseline_score = -Xte[:, FEATURES.index("margin")]
    baseline_proj = -Xte[:, FEATURES.index("margin_proj")]      # règle « extrapolation linéaire »
    thresholds = {"medium": 0.30, "high": 0.60}

    def report(pred):
        p, r, f, _ = precision_recall_fscore_support(yte, pred, average="binary", zero_division=0)
        return {"precision": round(float(p), 3), "recall": round(float(r), 3), "f1": round(float(f), 3)}

    metrics = {
        "samples_total": int(len(y)),
        "positive_rate": round(float(y.mean()), 3),
        "horizon_s": HORIZON_S,
        "window": WINDOW,
        "roc_auc": round(float(roc_auc_score(yte, proba)), 3),
        "average_precision": round(float(average_precision_score(yte, proba)), 3),
        "roc_auc_baseline_margin_only": round(float(roc_auc_score(yte, baseline_score)), 3),
        "roc_auc_baseline_linear_projection": round(float(roc_auc_score(yte, baseline_proj)), 3),
        "average_precision_baseline_margin_only": round(float(average_precision_score(yte, baseline_score)), 3),
        "average_precision_baseline_linear_projection": round(float(average_precision_score(yte, baseline_proj)), 3),
        "at_threshold_medium_0.30": report((proba >= thresholds["medium"]).astype(int)),
        "at_threshold_high_0.60": report((proba >= thresholds["high"]).astype(int)),
    }
    print(json.dumps(metrics, indent=2, ensure_ascii=False))

    model = {
        "type": "logistic_regression",
        "trained_on": "données simulées (voir ml/train_risk_model.py)",
        "temp_min": TMIN, "temp_max": TMAX,
        "window": WINDOW, "horizon_s": HORIZON_S,
        "features": FEATURES,
        "mean": [float(v) for v in scaler.mean_],
        "scale": [float(v) for v in scaler.scale_],
        "coef": [float(v) for v in clf.coef_[0]],
        "intercept": float(clf.intercept_[0]),
        "thresholds": thresholds,
    }
    (ROOT / "app" / "risk_model.json").write_text(json.dumps(model, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "ml" / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Écrit : app/risk_model.json, ml/metrics.json")


if __name__ == "__main__":
    main()
