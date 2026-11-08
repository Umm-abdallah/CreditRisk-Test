"""Tests de robustesse : entrées limites, invalides, inhabituelles et propriétés du modèle.

Deux familles sont distinguées :
* entrées INVALIDES : elles doivent être rejetées avec une erreur contrôlée ;
* entrées INHABITUELLES MAIS VALIDES : elles sont traitées, avec une alerte
  et une orientation vers une analyse manuelle.
Chaque cas porte un identifiant ROBxx repris dans le registre des anomalies
(reports/registre_anomalies.md).
"""

from __future__ import annotations

import json
import math

import joblib
import numpy as np
import pytest

from app.preprocessing import transformer
from tests.conftest import DEMANDE_VALIDE, MODELE_CANDIDAT, verifier_erreur_propre

ENTETE_JSON = {"Content-Type": "application/json"}


def corps_brut(champ: str, litteral: str) -> str:
    """Construit un JSON brut où ``champ`` prend la valeur littérale fournie."""
    d = dict(DEMANDE_VALIDE)
    d[champ] = "__X__"
    return json.dumps(d).replace('"__X__"', litteral)


def contrat_probabilite(resultat: dict) -> None:
    p = resultat["probabilite_defaut"]
    assert math.isfinite(p)
    assert 0.0 <= p <= 1.0


# ------------------------------------------------------------------ ROB01 valeurs manquantes
@pytest.mark.parametrize("champ", list(DEMANDE_VALIDE))
def test_rob01_valeur_null(client, champ):
    r = client.post("/predict", content=corps_brut(champ, "null"), headers=ENTETE_JSON)
    corps = verifier_erreur_propre(r, 422, "DONNEES_INVALIDES")
    assert corps["erreur"]["details"][0]["champ"] == champ


def test_rob01_objet_vide(client):
    corps = verifier_erreur_propre(client.post("/predict", json={}), 422, "DONNEES_INVALIDES")
    assert len(corps["erreur"]["details"]) == 5


# ------------------------------------------------------------------ ROB02 valeurs non numériques
@pytest.mark.parametrize("litteral", ['"abc"', '""', "true", "[35]", '{"v": 35}', '"35"', '"٣٥"'])
@pytest.mark.parametrize("champ", ["age", "revenu_mensuel", "duree_mois"])
def test_rob02_non_numerique(client, champ, litteral):
    r = client.post("/predict", content=corps_brut(champ, litteral), headers=ENTETE_JSON)
    verifier_erreur_propre(r, 422, "DONNEES_INVALIDES")


# ------------------------------------------------------------------ ROB03 valeurs non finies
@pytest.mark.parametrize("litteral", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400"])
@pytest.mark.parametrize("champ", ["revenu_mensuel", "montant_credit", "anciennete_activite"])
def test_rob03_non_fini(client, champ, litteral):
    r = client.post("/predict", content=corps_brut(champ, litteral), headers=ENTETE_JSON)
    corps = verifier_erreur_propre(r, 422, "DONNEES_INVALIDES")
    assert corps["erreur"]["details"][0]["champ"] == champ


@pytest.mark.parametrize("chiffres", [400, 5000])
def test_rob03_entier_demesure(client, chiffres):
    """Entier JSON de plusieurs milliers de chiffres : rejet propre attendu (ANO-01)."""
    r = client.post("/predict", content=corps_brut("revenu_mensuel", "9" * chiffres), headers=ENTETE_JSON)
    assert r.status_code in (400, 422)
    verifier_erreur_propre(r, r.status_code, "REQUETE_MAL_FORMEE" if r.status_code == 400 else "DONNEES_INVALIDES")


def test_rob03_json_profondement_imbrique(client):
    """Imbrication extrême : rejet propre au format du contrat (ANO-01)."""
    r = client.post("/predict", content="[" * 50_000 + "]" * 50_000, headers=ENTETE_JSON)
    verifier_erreur_propre(r, 400, "REQUETE_MAL_FORMEE")


# ------------------------------------------------------------------ ROB04 valeurs aux limites
LIMITES_VALIDES = [
    {"age": 18, "anciennete_activite": 0},
    {"age": 75, "anciennete_activite": 60},
    {"duree_mois": 1},
    {"duree_mois": 60},
    {"revenu_mensuel": 100_000_000},
    {"montant_credit": 500_000_000},
    {"montant_credit": 10_000},
    {"revenu_mensuel": 0.01},
    {"age": 30, "anciennete_activite": 16},
]
LIMITES_INVALIDES = [
    {"age": 17, "anciennete_activite": 0},
    {"age": 76},
    {"duree_mois": 0},
    {"duree_mois": 61},
    {"revenu_mensuel": 0},
    {"revenu_mensuel": 100_000_000.01},
    {"montant_credit": 500_000_001},
    {"montant_credit": 9_999.99},
    {"anciennete_activite": -0.1},
    {"age": 30, "anciennete_activite": 16.1},
]


@pytest.mark.parametrize("modif", LIMITES_VALIDES, ids=lambda m: json.dumps(m))
def test_rob04_limite_valide(client, modif):
    r = client.post("/predict", json={**DEMANDE_VALIDE, **modif})
    assert r.status_code == 200, r.text
    contrat_probabilite(r.json())


@pytest.mark.parametrize("modif", LIMITES_INVALIDES, ids=lambda m: json.dumps(m))
def test_rob04_limite_invalide(client, modif):
    verifier_erreur_propre(client.post("/predict", json={**DEMANDE_VALIDE, **modif}), 422, "DONNEES_INVALIDES")


# ------------------------------------------------------------------ ROB05 hors domaine d'entraînement
HORS_DOMAINE = [
    ({"age": 75, "anciennete_activite": 50}, "age"),
    ({"revenu_mensuel": 10_000_000}, "revenu_mensuel"),
    ({"revenu_mensuel": 5_000}, "revenu_mensuel"),
    ({"montant_credit": 400_000_000, "duree_mois": 60}, "montant_credit"),
    ({"duree_mois": 60}, "duree_mois"),
]


@pytest.mark.parametrize("modif,champ", HORS_DOMAINE, ids=lambda x: json.dumps(x) if isinstance(x, dict) else x)
def test_rob05_hors_domaine_accepte_avec_alerte(client, modif, champ):
    r = client.post("/predict", json={**DEMANDE_VALIDE, **modif})
    assert r.status_code == 200
    corps = r.json()
    contrat_probabilite(corps)
    assert f"HORS_DOMAINE_ENTRAINEMENT:{champ}" in corps["alertes"]
    # ANO-02 : une prédiction extrapolée ne doit pas produire une décision automatique
    assert corps["decision_suggeree"] == "analyse_manuelle_hors_domaine"


# ------------------------------------------------------------------ ROB06 schéma incorrect
@pytest.mark.parametrize(
    "corps",
    [
        {"Age": 35, **{k: v for k, v in DEMANDE_VALIDE.items() if k != "age"}},
        {"demande": DEMANDE_VALIDE},
        {**DEMANDE_VALIDE, "age": {"valeur": 35}},
        [DEMANDE_VALIDE],
    ],
    ids=["casse_differente", "objet_imbrique", "champ_objet", "liste"],
)
def test_rob06_schema_incorrect(client, corps):
    verifier_erreur_propre(client.post("/predict", json=corps), 422, "DONNEES_INVALIDES")


def test_rob06_cle_dupliquee_derniere_valeur_validee(client):
    brut = (
        '{"age": 35, "age": 200, "revenu_mensuel": 250000, '
        '"montant_credit": 1000000, "duree_mois": 12, "anciennete_activite": 4}'
    )
    verifier_erreur_propre(client.post("/predict", content=brut, headers=ENTETE_JSON), 422, "DONNEES_INVALIDES")


def test_rob06_type_de_contenu_non_json(client):
    r = client.post("/predict", content=json.dumps(DEMANDE_VALIDE), headers={"Content-Type": "text/plain"})
    verifier_erreur_propre(r, 422, "DONNEES_INVALIDES")


@pytest.mark.parametrize("route,methode", [("/inexistant", "get"), ("/predict", "get"), ("/health", "post")])
def test_rob06_erreurs_http_au_format_du_contrat(client, route, methode):
    """404 et 405 doivent respecter le contrat d'erreur (ANO-01)."""
    r = getattr(client, methode)(route)
    assert r.status_code in (404, 405)
    assert set(r.json()) == {"erreur", "id_requete"}


# ------------------------------------------------------------------ ROB07 cohérence et reproductibilité
def test_rob07_determinisme(client):
    resultats = {client.post("/predict", json=DEMANDE_VALIDE).json()["probabilite_defaut"] for _ in range(20)}
    assert len(resultats) == 1


def test_rob07_ordre_des_champs_sans_effet(client):
    inverse = dict(reversed(list(DEMANDE_VALIDE.items())))
    a = client.post("/predict", json=DEMANDE_VALIDE).json()["probabilite_defaut"]
    b = client.post("/predict", json=inverse).json()["probabilite_defaut"]
    assert a == b


def test_rob07_fuzzing_contrat_probabilite(client):
    """500 demandeurs valides tirés aléatoirement (graine fixe) : contrat toujours respecté."""
    rng = np.random.default_rng(2026)
    for _ in range(500):
        age = int(rng.integers(18, 76))
        d = {
            "age": age,
            "revenu_mensuel": float(rng.uniform(0.01, 100_000_000)),
            "montant_credit": float(rng.uniform(10_000, 500_000_000)),
            "duree_mois": int(rng.integers(1, 61)),
            "anciennete_activite": float(rng.uniform(0, min(60, age - 14))),
        }
        r = client.post("/predict", json=d)
        assert r.status_code == 200, (d, r.text)
        contrat_probabilite(r.json())


# ------------------------------------------------------------------ ROB08 propriétés métier (tests métamorphiques)
@pytest.fixture(scope="module")
def proba():
    modele = joblib.load(MODELE_CANDIDAT)
    return lambda **m: float(modele.predict_proba(transformer({**DEMANDE_VALIDE, **m}))[0, 1])


TOLERANCE_MONOTONIE = 0.02  # baisse tolérée entre deux points successifs (définie avant mesure)


def _non_decroissante(valeurs, tol=TOLERANCE_MONOTONIE):
    return all(b >= a - tol for a, b in zip(valeurs, valeurs[1:], strict=False))


def test_rob08_risque_croissant_avec_montant_dans_le_domaine(proba):
    valeurs = [proba(montant_credit=m) for m in (60_000, 100_000, 300_000, 1e6, 3e6, 1e7)]
    assert _non_decroissante(valeurs), valeurs


EST_V100 = MODELE_CANDIDAT.name == "model_v1.0.0.joblib"


@pytest.mark.xfail(EST_V100, strict=True, reason="ANO-02 : v1.0.0 non monotone en revenu au delà de 500 000 FCFA")
def test_rob08_risque_decroissant_avec_revenu_dans_le_domaine(proba):
    valeurs = [proba(revenu_mensuel=r) for r in (30_000, 100_000, 250_000, 500_000, 1_000_000, 1_800_000)]
    assert _non_decroissante(valeurs[::-1]), valeurs


def test_rob08_risque_decroissant_avec_anciennete(proba):
    valeurs = [proba(age=60, anciennete_activite=a) for a in (0, 2, 5, 10, 20, 29)]
    assert _non_decroissante(valeurs[::-1]), valeurs


@pytest.mark.xfail(EST_V100, strict=True, reason="ANO-02 : extrapolation non monotone de v1.0.0 au delà du domaine")
def test_rob08_risque_decroissant_avec_revenu_hors_domaine(proba):
    valeurs = [proba(revenu_mensuel=r) for r in (1_000_000, 3_000_000, 10_000_000, 90_000_000)]
    assert _non_decroissante(valeurs[::-1]), valeurs
