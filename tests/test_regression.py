"""Tests de non-régression du logiciel et du modèle.

Référence : version 1.0.0 (reference/reference_v1.0.0.json, reference/jeu_or.csv).
Modèle évalué : variable d'environnement MODELE_CANDIDAT (par défaut la référence).
Les tolérances sont lues dans reference/tolerances.json, fixé avant comparaison.

    MODELE_CANDIDAT=models/model_v1.3.0.joblib pytest tests/test_regression.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import joblib
import numpy as np
import pandas as pd
import pytest

from app.prediction import ModelService, classer_risque, sha256_fichier
from scripts.train_model import CHEMIN_DONNEES, evaluer, matrice_variables
from tests.conftest import MODELE_CANDIDAT, MODELE_REFERENCE, RACINE

REFERENCE = json.loads((RACINE / "reference" / "reference_v1.0.0.json").read_text(encoding="utf-8"))
TOL = json.loads((RACINE / "reference" / "tolerances.json").read_text(encoding="utf-8"))
JEU_OR = pd.read_csv(RACINE / "reference" / "jeu_or.csv")
MEME_VERSION = MODELE_CANDIDAT.resolve() == MODELE_REFERENCE.resolve()


@pytest.fixture(scope="module")
def candidat():
    return joblib.load(MODELE_CANDIDAT)


@pytest.fixture(scope="module")
def jeu_test():
    df = pd.read_csv(CHEMIN_DONNEES)
    test = df[df["jeu"] == "test"]
    return matrice_variables(test), test["defaut"].to_numpy()


@pytest.fixture(scope="module")
def metriques_candidat(candidat, jeu_test):
    return evaluer(candidat, *jeu_test)


# REG01 : les métriques ne baissent pas au delà des tolérances
@pytest.mark.parametrize(
    "metrique,cle_tol",
    [("rappel", "baisse_max_rappel"), ("f1", "baisse_max_f1"), ("auc", "baisse_max_auc")],
)
def test_reg01_pas_de_baisse_excessive(metriques_candidat, metrique, cle_tol):
    ref = REFERENCE["metriques_test"][metrique]
    obs = metriques_candidat[metrique]
    assert obs >= ref - TOL[cle_tol], (
        f"Régression sur {metrique} : {obs:.4f} contre {ref:.4f} en référence "
        f"(baisse {ref - obs:.4f} > tolérance {TOL[cle_tol]})"
    )


# REG02 : les métriques déclarées dans les métadonnées sont celles réellement mesurées
def test_reg02_metadonnees_conformes_aux_mesures(metriques_candidat):
    declarees = json.loads(MODELE_CANDIDAT.with_suffix(".json").read_text())["metriques_test"]
    assert declarees == metriques_candidat


# REG03 : prédictions du jeu « or » stables
def test_reg03_predictions_jeu_or(candidat):
    proba = candidat.predict_proba(matrice_variables(JEU_OR))[:, 1]
    ref = np.array(REFERENCE["probabilites_jeu_or"])
    ecart = np.abs(proba - ref)
    if MEME_VERSION:
        assert ecart.max() <= TOL["ecart_max_proba_meme_version"]
    else:
        assert ecart.max() <= TOL["ecart_max_proba_nouvelle_version"], f"écart max {ecart.max():.3f}"
        classes_ref = [classer_risque(p)[0] for p in ref]
        classes_obs = [classer_risque(p)[0] for p in proba]
        part = np.mean([a != b for a, b in zip(classes_ref, classes_obs, strict=True)])
        assert part <= TOL["part_max_changement_classe_risque"], f"{part:.0%} de changements de classe"


# REG04 : sauvegarde puis rechargement sans aucune différence
def test_reg04_sauvegarde_rechargement(candidat, tmp_path):
    chemin = tmp_path / "copie.joblib"
    joblib.dump(candidat, chemin)
    recharge = joblib.load(chemin)
    X = matrice_variables(JEU_OR)
    assert np.array_equal(candidat.predict_proba(X), recharge.predict_proba(X))


# REG05 : intégrité de l'artefact versionné
def test_reg05_empreinte_artefact():
    meta = json.loads(MODELE_CANDIDAT.with_suffix(".json").read_text())
    assert sha256_fichier(MODELE_CANDIDAT) == meta["sha256"]


def test_reg05_chargement_par_le_service():
    service = ModelService()
    service.charger(MODELE_CANDIDAT)
    assert service.pret and service.metadonnees["version"]


# REG06 : réentraînement reproductible (même graine, mêmes données => même modèle)
@pytest.mark.skipif(not MEME_VERSION, reason="Vérifié sur la version de référence")
def test_reg06_reentrainement_reproductible(tmp_path):
    subprocess.run(
        [
            sys.executable,
            str(RACINE / "scripts" / "train_model.py"),
            "--version",
            "1.0.0",
            "--algo",
            "logreg",
            "--sortie",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        cwd=RACINE,
    )
    nouveau = joblib.load(tmp_path / "model_v1.0.0.joblib")
    X = matrice_variables(JEU_OR)
    assert np.allclose(nouveau.predict_proba(X)[:, 1], REFERENCE["probabilites_jeu_or"], atol=1e-9)


# REG07 : les sorties du pipeline restent conformes au contrat sur tout le jeu « or »
def test_reg07_contrat_api_sur_jeu_or(client):
    for demande in JEU_OR.to_dict("records"):
        demande["age"] = int(demande["age"])
        demande["duree_mois"] = int(demande["duree_mois"])
        r = client.post("/predict", json=demande)
        assert r.status_code == 200, r.text
        corps = r.json()
        assert 0.0 <= corps["probabilite_defaut"] <= 1.0
        assert corps["classe_risque"] in {"faible", "modere", "eleve"}


# REG08 : le contrôle détecte bien une régression connue (test du test)
def test_reg08_le_controle_detecte_la_version_degradee(jeu_test):
    degrade = RACINE / "models" / "model_v1.2.0.joblib"
    if not degrade.exists():
        pytest.skip("modèle dégradé de démonstration absent")
    m = evaluer(joblib.load(degrade), *jeu_test)
    assert m["rappel"] < REFERENCE["metriques_test"]["rappel"] - TOL["baisse_max_rappel"]


def test_reg09_copie_modele_independante(tmp_path):
    """Un artefact copié garde la même empreinte (pas de dépendance au chemin)."""
    copie = tmp_path / MODELE_CANDIDAT.name
    shutil.copy(MODELE_CANDIDAT, copie)
    assert sha256_fichier(copie) == sha256_fichier(MODELE_CANDIDAT)
