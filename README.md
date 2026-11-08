# CreditRisk-Test

Projet de test et d'assurance qualité d'un système qui estime le risque de défaut de remboursement pour une institution de microfinance. Le dépôt contient l'API FastAPI, les modèles scikit-learn versionnés, mes suites de tests Pytest (validation, API, intégration, robustesse, non-régression), les mesures de performance et le workflow GitHub Actions.

Remarque sur les données : le fichier `data/credit_synthetique.csv` est un jeu synthétique que je génère avec `scripts/train_model.py` (graine 42). Il me sert à tester le système, il ne permet pas de juger la performance réelle d'un modèle de crédit.

## Architecture

```
CreditRisk-Test/
├── app/
│   ├── main.py            API : /health, /predict, /model-info, contrat d'erreur
│   ├── validation.py      schéma strict, bornes métier, cohérence, alertes
│   ├── preprocessing.py   variables dérivées (taux d'effort, logarithmes)
│   └── prediction.py      chargement contrôlé (SHA-256), inférence, classes de risque
├── models/                artefacts versionnés 1.0.0 (référence), 1.1.0, 1.2.0, 1.3.0 + métadonnées
├── reference/             jeu « or », prédictions de référence, tolérances
├── tests/                 test_validation, test_api, test_integration, test_robustness, test_regression
├── scripts/               train_model, build_reference, compare_versions, benchmark
├── docs/plan_de_test.md   stratégie, priorisation, matrice de traçabilité
├── reports/               résultats API, anomalies, non-régression, performance, preuves
├── locustfile.py          test de charge
└── .github/workflows/tests.yml
```

## Contrat de l'API

`POST /predict`

```json
{"age": 35, "revenu_mensuel": 250000, "montant_credit": 1000000, "duree_mois": 12, "anciennete_activite": 4}
```

Réponse 200 :

```json
{"probabilite_defaut": 0.354463, "classe_risque": "modere", "decision_suggeree": "analyse_complementaire",
 "alertes": [], "version_modele": "1.0.0", "id_requete": "...", "avertissement": "Aide à la décision : ..."}
```

| Règle | Valeur |
|---|---|
| `age` | entier, 18 à 75 |
| `revenu_mensuel` | nombre fini, strictement positif, au plus 100 000 000 FCFA |
| `montant_credit` | nombre fini, 10 000 à 500 000 000 FCFA |
| `duree_mois` | entier, 1 à 60 |
| `anciennete_activite` | nombre fini, 0 à 60, au plus âge moins 14 |
| Champs supplémentaires | refusés |
| Classes de risque | faible (moins de 0,30), modéré (0,30 à 0,60), élevé (0,60 et plus) |
| Hors domaine d'entraînement | alerte et décision `analyse_manuelle_hors_domaine` |

Toutes les erreurs ont le même format `{"erreur": {"code", "message", "details"}, "id_requete"}`, avec les codes 400 `REQUETE_MAL_FORMEE`, 404, 405, 422 `DONNEES_INVALIDES` ou `PRETRAITEMENT_IMPOSSIBLE`, 500 `ERREUR_PREDICTION` ou `ERREUR_INTERNE`, 503 `MODELE_INDISPONIBLE`. L'API ne renvoie jamais de trace technique au client.

## Exécution locale

```bash
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt

# Qualité du code
ruff check . && ruff format --check .

# Tous les tests avec couverture (modèle de référence 1.0.0)
pytest --cov=app --cov-report=term-missing --cov-report=html

# Une suite précise
pytest tests/test_robustness.py -v

# Non-régression d'un modèle candidat
MODELE_CANDIDAT=models/model_v1.3.0.joblib pytest tests/test_regression.py -v
python scripts/compare_versions.py 1.1.0 1.2.0 1.3.0

# Preuve qu'un test défaillant fait échouer la suite
FORCER_ECHEC=1 pytest tests/test_echec_volontaire.py

# Lancer l'API puis la documentation interactive sur http://127.0.0.1:8000/docs
uvicorn app.main:app --reload

# Performance
python scripts/benchmark.py
locust -f locustfile.py --headless -u 50 -r 5 -t 30s --host http://127.0.0.1:8000 --csv reports/locust

# Régénérer données, modèles et référence (déterministe)
python scripts/train_model.py --version 1.0.0 --algo logreg
python scripts/train_model.py --version 1.1.0 --algo hgb
python scripts/train_model.py --version 1.2.0 --algo logreg --sans-equilibrage
python scripts/train_model.py --version 1.3.0 --algo hgb --monotone
python scripts/build_reference.py
```

## Intégration continue

Le workflow `.github/workflows/tests.yml` se lance à chaque push sur `main`, à chaque Pull Request, et on peut le lancer à la main. Il a trois jobs :

1. **Qualité** : `ruff check` et `ruff format --check`.
2. **Tests** : contrôle d'intégrité SHA-256 des modèles, suite complète avec `pytest-cov` (seuil de couverture 90 %), rapport JUnit et HTML publiés en artefacts.
3. **Non-régression** : rapport comparatif des versions dans le résumé du job, puis contrôle bloquant du modèle candidat (1.3.0 par défaut).

Pour vérifier qu'un test en échec bloque bien le workflow : onglet Actions, workflow « Tests et qualification », Run workflow, puis cocher `forcer_echec`. Le job de tests échoue alors sur `test_echec_volontaire`. On peut aussi mettre `models/model_v1.2.0.joblib` comme modèle candidat pour voir la non-régression bloquer.

## Résultats

Le rapport de qualification complet est dans `reports/rapport_qualification.pdf`. Les autres rapports sont aussi en PDF dans `reports/`, et le plan de test dans `docs/plan_de_test.pdf`.

| Élément | Résultat |
|---|---|
| Tests | 209 réussis, 1 ignoré (échec volontaire désactivé), 2 anomalies connues en `xfail` strict |
| Couverture de `app/` | 98 % (lignes et branches) |
| Anomalies | 8 (2 critiques, 4 majeures, 2 mineures), voir `reports/registre_anomalies.md` |
| Non-régression | 1.1.0 et 1.2.0 non conformes, 1.3.0 conforme (`reports/rapport_non_regression.md`) |
| Performance | P95 de 40,6 ms à 20 requêtes simultanées, 557 req/s, 0 erreur (`reports/rapport_performance.md`) |
