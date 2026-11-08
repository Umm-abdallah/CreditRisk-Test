# Résultats des tests fonctionnels de l'API

J'ai lancé `pytest tests/test_api.py -v` avec le modèle 1.0.0 (sortie complète dans `reports/preuves/tests_api_detail.txt`). Les 40 cas passent.

| ID | Scénario | Cas | Code attendu | Code observé | Contenu vérifié | Statut |
|---|---|---|---|---|---|---|
| API01 | Requête valide | 1 | 200 | 200 | 7 champs, probabilité 0,354463 finie dans [0, 1], classe « modere », aucune alerte | Réussi |
| API02 | Champ obligatoire absent | 5 | 422 | 422 | `DONNEES_INVALIDES`, champ et type `missing` | Réussi |
| API03 | Âge négatif | 1 | 422 | 422 | Détail sur `age` | Réussi |
| API04 | Revenu sous forme de texte | 3 | 422 | 422 | `float_type`, aucune conversion de "250000" | Réussi |
| API05 | Montant nul ou négatif | 3 | 422 | 422 | Détail sur `montant_credit` | Réussi |
| API06 | Durée non entière | 3 | 422 | 422 | `int_type` pour 12.5, 12.0 et "12" | Réussi |
| API07 | Champ supplémentaire | 1 | 422 | 422 | `extra_forbidden` sur `sexe` | Réussi |
| API08 | Valeurs extrêmement élevées | 5 | 422 / 200 | 422 / 200 | Rejet au delà des bornes ; valeurs élevées valides acceptées avec alerte | Réussi |
| API09 | Modèle indisponible | 3 | 503 | 503 | `MODELE_INDISPONIBLE` sur `/predict`, `/health`, `/model-info` | Réussi |
| API10 | Requête mal formée | 8 | 400 / 422 | 400 / 422 | JSON illisible en 400 ; liste, texte, nombre, `null`, corps vide en 422 | Réussi |
| API11 | Disponibilité | 1 | 200 | 200 | `statut = ok`, version 1.0.0 | Réussi |
| API12 | Métadonnées du modèle | 1 | 200 | 200 | 8 variables, seuil 0,5, métriques, SHA-256 | Réussi |
| API13 | Méthode et route invalides | 2 | 405 / 404 | 405 / 404 | Codes HTTP corrects | Réussi |
| API14 | Traçabilité | 2 | 200 / 422 | 200 / 422 | `X-Request-ID` renvoyé dans l'en-tête et le corps | Réussi |
| API15 | Cohérence des versions | 1 | 200 | 200 | Même version sur `/health` et `/model-info` | Réussi |

Pour chaque réponse d'erreur, ma fonction `verifier_erreur_propre` vérifie aussi la structure `{erreur, id_requete}` et qu'aucune trace technique n'apparaît (`Traceback`, chemin de fichier, `site-packages`, nom d'exception, extension `.py`).
