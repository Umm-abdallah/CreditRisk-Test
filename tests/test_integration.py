"""Tests d'intégration : validation -> prétraitement -> modèle -> API.

Scénario principal INT01 à INT06, scénarios complémentaires INT07 à INT14.
Les défaillances internes sont simulées par monkeypatch sur un client isolé.
"""

from __future__ import annotations

import json
import shutil

import joblib
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import creer_app
from app.prediction import sha256_fichier
from app.preprocessing import VARIABLES_MODELE, transformer
from tests.conftest import MODELE_CANDIDAT, verifier_erreur_propre

# ---------- Scénario principal ----------


def test_int01_a_06_pipeline_bout_en_bout(client_frais, demande_valide, monkeypatch):
    appels = {}
    transformer_reel = main_module.transformer

    def espion_transformer(donnees):
        appels["entree"] = dict(donnees)
        appels["sortie"] = transformer_reel(donnees)
        return appels["sortie"]

    monkeypatch.setattr(main_module, "transformer", espion_transformer)
    response = client_frais.post("/predict", json=demande_valide)

    # INT01 : la requête valide est acceptée
    assert response.status_code == 200
    # INT02 : la validation a transmis des données typées et complètes
    assert appels["entree"] == {
        k: float(v) if k in ("revenu_mensuel", "montant_credit", "anciennete_activite") else v
        for k, v in demande_valide.items()
    }
    # INT03 : la transformation produit le vecteur attendu
    X = appels["sortie"]
    assert X.shape == (1, len(VARIABLES_MODELE))
    assert X[0, VARIABLES_MODELE.index("taux_effort")] == pytest.approx(1_000_000 / 12 / 250_000)
    # INT04 : la prédiction de l'API est celle du modèle sur ce vecteur
    modele = joblib.load(MODELE_CANDIDAT)
    attendu = float(modele.predict_proba(X)[0, 1])
    assert response.json()["probabilite_defaut"] == pytest.approx(attendu, abs=1e-6)
    # INT05 : structure de la réponse
    corps = response.json()
    assert corps["version_modele"] and isinstance(corps["alertes"], list)
    # INT06 : métadonnées cohérentes avec le fichier réellement chargé
    info = client_frais.get("/model-info").json()
    assert info["sha256"] == sha256_fichier(MODELE_CANDIDAT)
    assert info["variables"] == list(VARIABLES_MODELE)
    assert info["version"] == corps["version_modele"]
    assert modele.n_features_in_ == len(info["variables"])


def test_int01_classe_de_risque_coherente_avec_probabilite(client, demande_valide):
    seuils = [("faible", 0.0, 0.30), ("modere", 0.30, 0.60), ("eleve", 0.60, 1.0001)]
    for montant in (100_000, 1_000_000, 3_000_000, 6_000_000):
        demande_valide["montant_credit"] = montant
        r = client.post("/predict", json=demande_valide).json()
        bornes = {c: (a, b) for c, a, b in seuils}[r["classe_risque"]]
        assert bornes[0] <= r["probabilite_defaut"] < bornes[1]


# ---------- Scénarios complémentaires ----------


# INT07 : le modèle ne peut pas être chargé (absent, corrompu, empreinte falsifiée)
def _client_avec_modele(chemin):
    return TestClient(creer_app(str(chemin)), raise_server_exceptions=False)


def test_int07_modele_absent(tmp_path, demande_valide):
    with _client_avec_modele(tmp_path / "inexistant.joblib") as c:
        verifier_erreur_propre(c.post("/predict", json=demande_valide), 503, "MODELE_INDISPONIBLE")


def test_int07_modele_corrompu(tmp_path, demande_valide):
    chemin = tmp_path / "model.joblib"
    chemin.write_bytes(b"ceci n'est pas un modele")
    meta = json.loads(MODELE_CANDIDAT.with_suffix(".json").read_text())
    meta.pop("sha256")
    chemin.with_suffix(".json").write_text(json.dumps(meta))
    with _client_avec_modele(chemin) as c:
        verifier_erreur_propre(c.get("/health"), 503, "MODELE_INDISPONIBLE")
        verifier_erreur_propre(c.post("/predict", json=demande_valide), 503, "MODELE_INDISPONIBLE")


def test_int07_empreinte_invalide(tmp_path, demande_valide):
    chemin = tmp_path / "model.joblib"
    shutil.copy(MODELE_CANDIDAT, chemin)
    meta = json.loads(MODELE_CANDIDAT.with_suffix(".json").read_text())
    meta["sha256"] = "0" * 64
    chemin.with_suffix(".json").write_text(json.dumps(meta))
    with _client_avec_modele(chemin) as c:
        verifier_erreur_propre(c.post("/predict", json=demande_valide), 503, "MODELE_INDISPONIBLE")


def test_int07_metadonnees_absentes(tmp_path, demande_valide):
    chemin = tmp_path / "model.joblib"
    shutil.copy(MODELE_CANDIDAT, chemin)
    with _client_avec_modele(chemin) as c:
        verifier_erreur_propre(c.get("/health"), 503, "MODELE_INDISPONIBLE")


def test_int07_objet_sans_predict_proba(tmp_path):
    chemin = tmp_path / "model.joblib"
    joblib.dump({"pas": "un modele"}, chemin)
    chemin.with_suffix(".json").write_text(json.dumps({"version": "x"}))
    with _client_avec_modele(chemin) as c:
        verifier_erreur_propre(c.get("/health"), 503, "MODELE_INDISPONIBLE")


# INT08 : une variable attendue est absente au niveau du prétraitement
def test_int08_variable_absente_dans_pipeline(client_frais, demande_valide, monkeypatch):
    transformer_reel = main_module.transformer

    def transformer_amputé(donnees):
        d = dict(donnees)
        d.pop("anciennete_activite")
        return transformer_reel(d)

    monkeypatch.setattr(main_module, "transformer", transformer_amputé)
    verifier_erreur_propre(client_frais.post("/predict", json=demande_valide), 422, "PRETRAITEMENT_IMPOSSIBLE")


# INT09 : le prétraitement retourne une erreur
def test_int09_erreur_pretraitement(client_frais, demande_valide, monkeypatch):
    from app.preprocessing import PreprocessingError

    def en_echec(_):
        raise PreprocessingError("division par zéro dans /home/app/preprocessing.py")

    monkeypatch.setattr(main_module, "transformer", en_echec)
    verifier_erreur_propre(client_frais.post("/predict", json=demande_valide), 422, "PRETRAITEMENT_IMPOSSIBLE")


# INT10 : dimensions incompatibles avec le modèle
@pytest.mark.parametrize("forme", [(1, 5), (1, 9), (2, 8), (8,)])
def test_int10_dimensions_incompatibles(client_frais, demande_valide, monkeypatch, forme):
    monkeypatch.setattr(main_module, "transformer", lambda _: np.ones(forme))
    verifier_erreur_propre(client_frais.post("/predict", json=demande_valide), 500, "ERREUR_PREDICTION")


# INT11 : erreur interne pendant la prédiction
class ModeleDefaillant:
    n_features_in_ = 8

    def predict_proba(self, X):
        raise RuntimeError("Traceback secret : /home/serveur/model.py ligne 42")


class ModeleSortieInvalide:
    n_features_in_ = 8

    def __init__(self, valeur):
        self.valeur = valeur

    def predict_proba(self, X):
        return np.array([[0.0, self.valeur]])


def test_int11_exception_dans_le_modele(client_frais, demande_valide):
    client_frais.app.state.service.modele = ModeleDefaillant()
    corps = verifier_erreur_propre(client_frais.post("/predict", json=demande_valide), 500, "ERREUR_PREDICTION")
    assert "secret" not in json.dumps(corps)


@pytest.mark.parametrize("valeur", [float("nan"), float("inf"), 1.5, -0.2])
def test_int11_sortie_du_modele_invalide(client_frais, demande_valide, valeur):
    client_frais.app.state.service.modele = ModeleSortieInvalide(valeur)
    verifier_erreur_propre(client_frais.post("/predict", json=demande_valide), 500, "ERREUR_PREDICTION")


# INT12 : erreur imprévue dans la couche applicative
def test_int12_erreur_imprevue_couche_applicative(client_frais, demande_valide, monkeypatch):
    def bogue(_):
        raise KeyError("cle_interne_confidentielle")

    monkeypatch.setattr(main_module, "classer_risque", bogue)
    corps = verifier_erreur_propre(client_frais.post("/predict", json=demande_valide), 500, "ERREUR_INTERNE")
    assert "confidentielle" not in json.dumps(corps)


def test_int12_erreur_imprevue_avec_remontee_serveur(demande_valide, monkeypatch):
    """Même avec raise_server_exceptions=True, l'exception ne doit pas sortir du service."""
    monkeypatch.setattr(main_module, "classer_risque", lambda _: 1 / 0)
    with TestClient(creer_app(str(MODELE_CANDIDAT))) as c:
        verifier_erreur_propre(c.post("/predict", json=demande_valide), 500, "ERREUR_INTERNE")


# INT13 : le service se rétablit après la panne simulée
def test_int13_service_inchange_apres_erreur(client, demande_valide):
    r1 = client.post("/predict", json={"age": "x"})
    r2 = client.post("/predict", json=demande_valide)
    assert r1.status_code == 422 and r2.status_code == 200


# INT14 : prétraitement identique entre entraînement et service (pas de « training/serving skew »)
def test_int14_meme_pretraitement_entrainement_et_service(demande_valide):
    import pandas as pd

    from scripts.train_model import matrice_variables

    X_service = transformer(demande_valide)
    X_entrainement = matrice_variables(pd.DataFrame([demande_valide]))
    assert np.allclose(X_service, X_entrainement)
