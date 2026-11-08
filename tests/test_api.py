"""Tests fonctionnels de l'API (contrat HTTP).

Chaque test porte l'identifiant du scénario (API01 à API15) repris dans le
tableau des résultats (reports/resultats_tests_api.md).
"""

from __future__ import annotations

import math

import pytest

from tests.conftest import verifier_erreur_propre

CHAMPS_REPONSE = {
    "probabilite_defaut",
    "classe_risque",
    "decision_suggeree",
    "alertes",
    "version_modele",
    "id_requete",
    "avertissement",
}


# API01 : requête valide (EX04)
def test_api01_requete_valide(client, demande_valide):
    response = client.post("/predict", json=demande_valide)
    assert response.status_code == 200
    resultat = response.json()
    assert set(resultat) == CHAMPS_REPONSE
    p = resultat["probabilite_defaut"]
    assert isinstance(p, float) and math.isfinite(p) and 0.0 <= p <= 1.0
    assert resultat["classe_risque"] in {"faible", "modere", "eleve"}
    assert resultat["alertes"] == []
    assert response.headers["content-type"].startswith("application/json")


# API02 : champ obligatoire absent (EX06)
@pytest.mark.parametrize("champ", ["age", "revenu_mensuel", "montant_credit", "duree_mois", "anciennete_activite"])
def test_api02_champ_obligatoire_absent(client, demande_valide, champ):
    demande_valide.pop(champ)
    corps = verifier_erreur_propre(client.post("/predict", json=demande_valide), 422, "DONNEES_INVALIDES")
    assert {"champ": champ, "type": "missing"}.items() <= corps["erreur"]["details"][0].items()


# API03 : âge négatif (EX01)
def test_api03_age_negatif(client, demande_valide):
    demande_valide["age"] = -5
    corps = verifier_erreur_propre(client.post("/predict", json=demande_valide), 422, "DONNEES_INVALIDES")
    assert corps["erreur"]["details"][0]["champ"] == "age"


# API04 : revenu sous forme de texte (EX02)
@pytest.mark.parametrize("valeur", ["250000", "deux cent mille", ""])
def test_api04_revenu_texte(client, demande_valide, valeur):
    demande_valide["revenu_mensuel"] = valeur
    corps = verifier_erreur_propre(client.post("/predict", json=demande_valide), 422, "DONNEES_INVALIDES")
    assert corps["erreur"]["details"][0] == {
        "champ": "revenu_mensuel",
        "type": "float_type",
        "message": "Doit être un nombre",
    }


# API05 : montant nul ou négatif (EX10)
@pytest.mark.parametrize("montant", [0, -1, -1_000_000])
def test_api05_montant_nul_ou_negatif(client, demande_valide, montant):
    demande_valide["montant_credit"] = montant
    corps = verifier_erreur_propre(client.post("/predict", json=demande_valide), 422, "DONNEES_INVALIDES")
    assert corps["erreur"]["details"][0]["champ"] == "montant_credit"


# API06 : durée non entière (EX03)
@pytest.mark.parametrize("duree", [12.5, 12.0, "12"])
def test_api06_duree_non_entiere(client, demande_valide, duree):
    demande_valide["duree_mois"] = duree
    corps = verifier_erreur_propre(client.post("/predict", json=demande_valide), 422, "DONNEES_INVALIDES")
    assert corps["erreur"]["details"][0]["type"] == "int_type"


# API07 : champs supplémentaires non autorisés (EX08)
def test_api07_champ_supplementaire(client, demande_valide):
    demande_valide["sexe"] = "F"
    corps = verifier_erreur_propre(client.post("/predict", json=demande_valide), 422, "DONNEES_INVALIDES")
    assert corps["erreur"]["details"][0] == {
        "champ": "sexe",
        "type": "extra_forbidden",
        "message": "Champ non autorisé",
    }


# API08 : valeurs extrêmement élevées (EX01, EX02, EX10)
@pytest.mark.parametrize(
    "champ,valeur",
    [("revenu_mensuel", 10**12), ("montant_credit", 10**15), ("age", 10**6), ("duree_mois", 10**4)],
)
def test_api08_valeurs_extremes_rejetees(client, demande_valide, champ, valeur):
    demande_valide[champ] = valeur
    corps = verifier_erreur_propre(client.post("/predict", json=demande_valide), 422, "DONNEES_INVALIDES")
    assert corps["erreur"]["details"][0]["type"] == "less_than_equal"


def test_api08_valeurs_elevees_mais_valides_avec_alerte(client, demande_valide):
    demande_valide.update(revenu_mensuel=90_000_000, montant_credit=400_000_000, duree_mois=60)
    response = client.post("/predict", json=demande_valide)
    assert response.status_code == 200
    assert "HORS_DOMAINE_ENTRAINEMENT:revenu_mensuel" in response.json()["alertes"]


# API09 : modèle indisponible ou non chargé (EX05)
def test_api09_modele_indisponible_predict(client_sans_modele, demande_valide):
    verifier_erreur_propre(client_sans_modele.post("/predict", json=demande_valide), 503, "MODELE_INDISPONIBLE")


def test_api09_modele_indisponible_health(client_sans_modele):
    verifier_erreur_propre(client_sans_modele.get("/health"), 503, "MODELE_INDISPONIBLE")


def test_api09_modele_indisponible_model_info(client_sans_modele):
    verifier_erreur_propre(client_sans_modele.get("/model-info"), 503, "MODELE_INDISPONIBLE")


# API10 : requête mal formée (EX12)
@pytest.mark.parametrize("corps", ['{"age": 35,', "pas du json", '{"age": 35 "duree_mois": 12}'])
def test_api10_json_mal_forme(client, corps):
    response = client.post("/predict", content=corps, headers={"Content-Type": "application/json"})
    verifier_erreur_propre(response, 400, "REQUETE_MAL_FORMEE")


@pytest.mark.parametrize("corps", ["[1, 2, 3]", '"texte"', "42", "null"])
def test_api10_corps_qui_n_est_pas_un_objet(client, corps):
    response = client.post("/predict", content=corps, headers={"Content-Type": "application/json"})
    verifier_erreur_propre(response, 422, "DONNEES_INVALIDES")


def test_api10_corps_vide(client):
    response = client.post("/predict", content="", headers={"Content-Type": "application/json"})
    verifier_erreur_propre(response, 422, "DONNEES_INVALIDES")


# API11 : disponibilité du service (EX05)
def test_api11_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    corps = response.json()
    assert corps["statut"] == "ok" and corps["modele_charge"] is True
    assert corps["version_modele"]


# API12 : métadonnées du modèle (EX13)
def test_api12_model_info(client):
    response = client.get("/model-info")
    assert response.status_code == 200
    info = response.json()
    for cle in ("version", "algorithme", "variables", "seuil_decision", "metriques_test", "sha256"):
        assert info[cle] is not None
    assert len(info["variables"]) == 8
    assert 0 < info["seuil_decision"] < 1


# API13 : méthode non autorisée et route inconnue
def test_api13_methode_non_autorisee(client):
    assert client.get("/predict").status_code == 405


def test_api13_route_inconnue(client):
    assert client.get("/predire").status_code == 404


# API14 : traçabilité de la requête (EX14)
def test_api14_identifiant_de_requete(client, demande_valide):
    response = client.post("/predict", json=demande_valide, headers={"X-Request-ID": "test-123"})
    assert response.headers["X-Request-ID"] == "test-123"
    assert response.json()["id_requete"] == "test-123"
    assert float(response.headers["X-Process-Time-ms"]) >= 0


def test_api14_identifiant_present_dans_les_erreurs(client):
    response = client.post("/predict", json={}, headers={"X-Request-ID": "err-1"})
    assert response.json()["id_requete"] == "err-1"


# API15 : cohérence entre /health et /model-info
def test_api15_version_coherente(client):
    assert client.get("/health").json()["version_modele"] == client.get("/model-info").json()["version"]
