# Modèle d'IA : risque de rupture de la chaîne du froid

**Question posée au modèle :** d'après les 6 dernières mesures, la température va-t-elle sortir de la
plage 2 à 8 °C dans la **prochaine minute** ? Le but est d'alerter *avant* la rupture, alors que
`detection.py` ne réagit qu'après 3 mesures hors plage.

## Méthode
- **Modèle :** régression logistique (scikit-learn), simple, rapide et explicable.
- **Variables (calculées sur les 6 dernières mesures) :**
  `margin` (distance à la borne la plus proche), `approach` (vitesse d'approche de cette borne en °C/min),
  `std` (variabilité), `margin_proj` (marge prévue dans 60 s si la tendance continue),
  `log_ttb` (temps estimé avant la borne, en échelle logarithmique).
  Elles sont **symétriques** : un réchauffement vers 8 °C et un refroidissement vers 2 °C sont traités pareil.
- **Données :** simulées (bruit du capteur, ouvertures de porte, panne de compresseur,
  sur-refroidissement), 1 200 trajectoires, séparation entraînement / test **par trajectoire**.
- **Utilisation :** les coefficients sont dans `app/risk_model.json`. `app/risk.py` calcule la
  prédiction avec la bibliothèque standard seulement (scikit-learn n'est nécessaire que pour réentraîner).
  Le dashboard refait le même calcul en JavaScript.

## Résultats (jeu de test simulé, `metrics.json`)
| Mesure | Modèle | Règle « proche d'une limite » | Règle « extrapolation linéaire » |
| :--- | :---: | :---: | :---: |
| ROC AUC | 0,956 | 0,956 | 0,934 |
| Précision moyenne | 0,541 | 0,538 | 0,359 |

Au seuil « risque modéré » (30 %) : précision 0,53, rappel 0,58. Au seuil « risque élevé » (60 %) : précision 0,78, rappel 0,30.

## Limites (à écrire dans le rapport)
- Entraîné sur des **données simulées**, pas sur de vraies mesures de camion.
- Face à une règle simple fondée sur la distance à la limite, le gain est **faible** : le modèle est
  surtout meilleur que l'extrapolation linéaire. Dans la simulation, beaucoup de sorties de plage
  viennent du bruit du capteur près de la limite, que la tendance ne prédit pas.
- Les mesures de l'ESP32 arrivent toutes les 13 à 23 s : la prédiction à 60 s repose sur peu de points.

## Réentraîner
```
py -m pip install -r requirements-ml.txt
py ml/train_risk_model.py
```
