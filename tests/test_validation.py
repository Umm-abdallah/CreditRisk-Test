"""Tests unitaires : module de validation et module de prétraitement.

Exigences couvertes : EX01, EX02, EX03, EX06, EX08, EX09, EX11.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from app.preprocessing import (
    VARIABLES_MODELE,
    PreprocessingError,
    construire_variables,
    transformer,
)
from app.validation import CHAMPS_ATTENDUS, DemandeCredit, detecter_alertes

BASE = {
    "age": 35,
    "revenu_mensuel": 250000,
    "montant_credit": 1000000,
    "duree_mois": 12,
    "anciennete_activite": 4,
}


def avec(**modifs):
    d = dict(BASE)
    d.update(modifs)
    return d


def types_erreur(exc: ValidationError) -> set[str]:
    return {e["type"] for e in exc.errors()}


def test_demande_valide_acceptee():
    d = DemandeCredit(**BASE)
    assert d.age == 35 and d.revenu_mensuel == 250000.0


# EX01 : âge dans l'intervalle [18, 75] (analyse des valeurs limites)
@pytest.mark.parametrize("age", [18, 19, 74, 75])
def test_ex01_age_limites_valides(age):
    assert DemandeCredit(**avec(age=age, anciennete_activite=0)).age == age


@pytest.mark.parametrize("age", [-1, 0, 17, 76, 150])
def test_ex01_age_hors_limites_rejete(age):
    with pytest.raises(ValidationError):
        DemandeCredit(**avec(age=age, anciennete_activite=0))


# EX02 : revenu numérique et strictement positif
@pytest.mark.parametrize("revenu", [0, -1, -250000, "250000", "abc", True, None])
def test_ex02_revenu_invalide_rejete(revenu):
    with pytest.raises(ValidationError):
        DemandeCredit(**avec(revenu_mensuel=revenu))


@pytest.mark.parametrize("revenu", [float("inf"), float("-inf"), float("nan")])
def test_ex02_revenu_non_fini_rejete(revenu):
    with pytest.raises(ValidationError):
        DemandeCredit(**avec(revenu_mensuel=revenu))


def test_ex02_revenu_entier_accepte_comme_nombre():
    assert DemandeCredit(**avec(revenu_mensuel=1)).revenu_mensuel == 1.0


# EX03 : durée entière dans [1, 60]
@pytest.mark.parametrize("duree", [1, 12, 60])
def test_ex03_duree_valide(duree):
    assert DemandeCredit(**avec(duree_mois=duree)).duree_mois == duree


@pytest.mark.parametrize("duree", [0, -12, 61, 12.5, 12.0, "12", True])
def test_ex03_duree_invalide_rejetee(duree):
    with pytest.raises(ValidationError):
        DemandeCredit(**avec(duree_mois=duree))


# EX06 : champ obligatoire absent
@pytest.mark.parametrize("champ", CHAMPS_ATTENDUS)
def test_ex06_champ_manquant(champ):
    d = dict(BASE)
    d.pop(champ)
    with pytest.raises(ValidationError) as exc:
        DemandeCredit(**d)
    assert "missing" in types_erreur(exc.value)


# EX08 : champs supplémentaires refusés
def test_ex08_champ_supplementaire_refuse():
    with pytest.raises(ValidationError) as exc:
        DemandeCredit(**avec(score_interne=900))
    assert "extra_forbidden" in types_erreur(exc.value)


# EX09 : cohérence ancienneté / âge
def test_ex09_anciennete_incoherente_rejetee():
    with pytest.raises(ValidationError):
        DemandeCredit(**avec(age=20, anciennete_activite=10))


def test_ex09_anciennete_limite_acceptee():
    assert DemandeCredit(**avec(age=20, anciennete_activite=6)).anciennete_activite == 6


@pytest.mark.parametrize("valeur", [-0.5, 61])
def test_ex09_anciennete_hors_bornes(valeur):
    with pytest.raises(ValidationError):
        DemandeCredit(**avec(age=75, anciennete_activite=valeur))


# EX11 : alertes pour entrées valides mais inhabituelles
def test_ex11_alerte_hors_domaine():
    domaine = {"revenu_mensuel": [30000, 1_822_000]}
    alertes = detecter_alertes(DemandeCredit(**avec(revenu_mensuel=50_000_000)), domaine)
    assert "HORS_DOMAINE_ENTRAINEMENT:revenu_mensuel" in alertes


def test_ex11_alerte_mensualite_superieure_revenu():
    d = DemandeCredit(**avec(revenu_mensuel=50000, montant_credit=1_200_000, duree_mois=6))
    assert "MENSUALITE_SUPERIEURE_AU_REVENU" in detecter_alertes(d, None)


def test_ex11_pas_d_alerte_cas_nominal():
    domaine = {c: [0, 1e12] for c in CHAMPS_ATTENDUS}
    assert detecter_alertes(DemandeCredit(**BASE), domaine) == []


# Prétraitement
def test_pretraitement_variables_derivees():
    v = construire_variables(BASE)
    assert v["taux_effort"] == pytest.approx((1_000_000 / 12) / 250_000)
    assert v["log_revenu"] == pytest.approx(math.log(250_000))
    assert v["log_montant"] == pytest.approx(math.log(1_000_000))


def test_pretraitement_ordre_et_dimension():
    X = transformer(BASE)
    assert X.shape == (1, len(VARIABLES_MODELE)) and X.dtype == np.float64
    assert X[0, VARIABLES_MODELE.index("age")] == 35
    assert np.all(np.isfinite(X))


def test_pretraitement_variable_absente():
    d = dict(BASE)
    d.pop("duree_mois")
    with pytest.raises(PreprocessingError, match="duree_mois"):
        transformer(d)


@pytest.mark.parametrize("modif", [{"duree_mois": 0}, {"revenu_mensuel": 0}, {"age": "x"}])
def test_pretraitement_valeur_inexploitable(modif):
    with pytest.raises(PreprocessingError):
        transformer(avec(**modif))


def test_pretraitement_valeur_non_finie():
    with pytest.raises(PreprocessingError):
        transformer(avec(montant_credit=float("inf")))


def test_pretraitement_deterministe():
    assert np.array_equal(transformer(BASE), transformer(dict(reversed(list(BASE.items())))))
