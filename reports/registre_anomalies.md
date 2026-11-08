# Registre des anomalies

Pour la gravité, j'ai utilisé trois niveaux. Critique quand l'anomalie peut fausser beaucoup de décisions de crédit ou bloquer l'usage métier, majeure quand le contrat n'est pas respecté ou que la décision est fausse sur quelques cas, mineure quand l'écart n'a pas d'effet direct sur la décision.

Les sorties des tests sont dans `reports/preuves/` : `robustesse_avant_corrections.txt` (12 échecs) et `robustesse_apres_corrections.txt` (plus aucun échec, 2 anomalies connues marquées `xfail`).

| ID | Gravité | Test qui l'a révélée | Risque visé | Comportement attendu | Résultat observé | Correction | Statut |
|---|---|---|---|---|---|---|---|
| ANO-01 | Majeure | ROB03 `entier_demesure[5000]`, ROB03 `json_profondement_imbrique`, ROB06 `erreurs_http_au_format_du_contrat` | Client incapable d'interpréter l'erreur | 400, 404 et 405 au format `{erreur, id_requete}` | Format FastAPI par défaut `{"detail": "There was an error parsing the body"}`, sans code ni identifiant | Gestionnaire `StarletteHTTPException` qui applique le contrat d'erreur | Corrigée et vérifiée |
| ANO-02 | Critique | ROB08 `revenu_dans_le_domaine`, ROB08 `revenu_hors_domaine` | Refus injustifié de demandeurs à revenu élevé | Risque décroissant quand le revenu augmente | Modèle 1.0.0 : risque 0,316 à 500 000 FCFA, 0,454 à 1,8 M FCFA (dans le domaine), 0,99 à 10 M FCFA (classe « élevé ») | Atténuation applicative (ANO-04) ; modèle 1.3.0 à contraintes de monotonie | Ouverte sur 1.0.0 (test `xfail` strict) ; corrigée dans le candidat 1.3.0 |
| ANO-03 | Majeure | ROB04 `limite_invalide[montant 9 999,99]` | Scoring d'un montant absurde | Montant minimal métier | 0,0001 FCFA accepté, probabilité 0,96, classe « élevé » (extrapolation du logarithme du montant) | Borne `montant_credit >= 10 000 FCFA` | Corrigée et vérifiée |
| ANO-04 | Majeure | ROB05 (5 cas) | Décision automatique sur une prédiction extrapolée | Alerte et orientation vers une analyse manuelle | Alerte émise mais décision suggérée inchangée | Décision `analyse_manuelle_hors_domaine` dès qu'une variable sort du domaine d'entraînement | Corrigée et vérifiée |
| ANO-05 | Critique (métier) | Analyse par segment (`scripts/compare_versions.py`) | Défauts non détectés sur les crédits longs | Taux de faux négatifs homogène entre segments | FNR 5,4 % sous 12 mois, 51,6 % de 12 à 23 mois, 83,0 % à partir de 24 mois (global 24,7 %) | Seuils par segment, variables complémentaires, revue métier ; non corrigée par 1.3.0 (79,5 %) | Ouverte, bloquante pour un usage décisionnel |
| ANO-06 | Majeure | REG01 `rappel` | Hausse des défauts non détectés | Baisse du rappel au plus 0,03 | Candidat 1.2.0 : rappel 0,607 contre 0,753 (baisse de 0,146) alors que le F1 progresse (0,702 contre 0,694) | Candidat rejeté ; cause : pondération des classes supprimée | Détectée, candidat bloqué |
| ANO-07 | Mineure | REG03 `predictions_jeu_or` | Changement de comportement non expliqué | Écart de probabilité au plus 0,15 | Candidat 1.1.0 : écart maximal 0,212, métriques globales conformes | Investigation avant toute promotion | Détectée, candidat bloqué |
| ANO-08 | Mineure | Exploration ROB08 | Incohérence locale | Risque croissant avec le montant | Modèle 1.0.0 : 0,294 à 100 000 FCFA, 0,283 à 300 000 FCFA (baisse de 0,011, sous la tolérance de 0,02) | Couverte par la contrainte de monotonie de 1.3.0 | Observée, acceptée |

## Bilan

J'ai relevé 8 anomalies : 2 critiques, 4 majeures et 2 mineures. J'en ai corrigé 3 dans le code (ANO-01, ANO-03, ANO-04), et la non-régression a bloqué 2 versions candidates (ANO-06, ANO-07). Deux restent ouvertes sur la version 1.0.0 : ANO-02, que la version 1.3.0 corrige, et ANO-05, qu'aucune version ne corrige pour l'instant.
