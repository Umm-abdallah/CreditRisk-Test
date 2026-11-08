"""Fixtures partagées par les suites de tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app.main import creer_app  # noqa: E402

MODELE_REFERENCE = RACINE / "models" / "model_v1.0.0.joblib"
# Modèle évalué : la version en production par défaut, ou un candidat passé en variable d'environnement
MODELE_CANDIDAT = Path(os.getenv("MODELE_CANDIDAT", str(MODELE_REFERENCE)))
if not MODELE_CANDIDAT.is_absolute():
    MODELE_CANDIDAT = RACINE / MODELE_CANDIDAT

DEMANDE_VALIDE = {
    "age": 35,
    "revenu_mensuel": 250000,
    "montant_credit": 1000000,
    "duree_mois": 12,
    "anciennete_activite": 4,
}


@pytest.fixture
def demande_valide() -> dict:
    return dict(DEMANDE_VALIDE)


@pytest.fixture(scope="module")
def client():
    with TestClient(creer_app(str(MODELE_CANDIDAT))) as c:
        yield c


@pytest.fixture
def client_sans_modele(tmp_path):
    with TestClient(creer_app(str(tmp_path / "absent.joblib"))) as c:
        yield c


@pytest.fixture
def client_frais():
    """Client isolé, utilisable avec monkeypatch sans effet sur les autres tests."""
    with TestClient(creer_app(str(MODELE_CANDIDAT)), raise_server_exceptions=False) as c:
        yield c


def verifier_erreur_propre(response, statut: int, code: str) -> dict:
    """Vérifie le contrat d'erreur et l'absence de fuite technique."""
    assert response.status_code == statut, response.text
    corps = response.json()
    assert set(corps) == {"erreur", "id_requete"}
    assert corps["erreur"]["code"] == code
    assert isinstance(corps["erreur"]["message"], str) and corps["erreur"]["message"]
    texte = response.text.lower()
    for fuite in ("traceback", 'file "', "/home/", "site-packages", "exception", ".py"):
        assert fuite not in texte, f"Fuite technique détectée : {fuite}"
    return corps
