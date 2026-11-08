# Rapport de non-régression

Je compare chaque version au modèle de référence 1.0.0 (StandardScaler et LogisticRegression), sur les 1 800 dossiers du jeu de test synthétique, avec un seuil de décision de 0,5.
J'ai fixé les tolérances avant la comparaison, dans `reference/tolerances.json` : le rappel et le F1 ne doivent pas baisser de plus de 0,03, l'AUC de plus de 0,02, la probabilité d'un dossier du jeu « or » ne doit pas bouger de plus de 0,15, et au plus 20 % des dossiers peuvent changer de classe de risque.

## Métriques

| Version | Rappel | Précision | F1 | AUC | Taux de faux négatifs |
|---|---|---|---|---|---|
| 1.0.0 (référence) | 0.753 | 0.6436 | 0.694 | 0.8841 | 0.247 |
| 1.1.0 | 0.7411 | 0.6367 | 0.6849 | 0.8758 | 0.2589 |
| 1.2.0 | 0.6067 | 0.832 | 0.7017 | 0.8842 | 0.3933 |
| 1.3.0 | 0.749 | 0.6285 | 0.6835 | 0.8791 | 0.251 |

## Contrôles

| Version | Rappel | F1 | AUC | Écart proba max | Changements de classe | Verdict |
|---|---|---|---|---|---|---|
| 1.1.0 | OK | OK | OK | ÉCHEC (0.2124) | OK (17%) | NON CONFORME |
| 1.2.0 | ÉCHEC | OK | OK | ÉCHEC (0.2312) | OK (15%) | NON CONFORME |
| 1.3.0 | OK | OK | OK | OK (0.1436) | OK (12%) | CONFORME |

## Contrôles en plus (non bloquants)

| Version | FNR < 12 mois | FNR 12 à 23 mois | FNR 24 mois et plus | Risque décroissant avec le revenu |
|---|---|---|---|---|
| 1.0.0 | 0.054 | 0.516 | 0.83 | non (ANO-02) |
| 1.1.0 | 0.065 | 0.547 | 0.83 | non (ANO-02) |
| 1.2.0 | 0.164 | 0.844 | 0.989 | non (ANO-02) |
| 1.3.0 | 0.071 | 0.5 | 0.795 | oui |
