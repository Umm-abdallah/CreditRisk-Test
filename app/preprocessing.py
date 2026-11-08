"""Module de prétraitement : construction du vecteur de variables du modèle.

Variables produites (ordre figé, versionné dans les métadonnées du modèle) :
    age, revenu_mensuel, montant_credit, duree_mois, anciennete_activite,
    taux_effort (mensualité / revenu), log_revenu, log_montant
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np

VARIABLES_BRUTES = (
    "age",
    "revenu_mensuel",
    "montant_credit",
    "duree_mois",
    "anciennete_activite",
)
VARIABLES_MODELE = VARIABLES_BRUTES + ("taux_effort", "log_revenu", "log_montant")


class PreprocessingError(Exception):
    """Erreur contrôlée du prétraitement."""


def construire_variables(donnees: Mapping[str, float]) -> dict[str, float]:
    """Calcule les variables dérivées à partir des variables brutes."""
    manquantes = [v for v in VARIABLES_BRUTES if v not in donnees]
    if manquantes:
        raise PreprocessingError(f"Variables manquantes : {', '.join(manquantes)}")
    try:
        brutes = {v: float(donnees[v]) for v in VARIABLES_BRUTES}
    except (TypeError, ValueError) as exc:
        raise PreprocessingError("Variable non numérique") from exc

    if brutes["revenu_mensuel"] <= 0 or brutes["montant_credit"] <= 0 or brutes["duree_mois"] <= 0:
        raise PreprocessingError("revenu, montant et durée doivent être strictement positifs")

    mensualite = brutes["montant_credit"] / brutes["duree_mois"]
    variables = dict(brutes)
    variables["taux_effort"] = mensualite / brutes["revenu_mensuel"]
    variables["log_revenu"] = math.log(brutes["revenu_mensuel"])
    variables["log_montant"] = math.log(brutes["montant_credit"])

    if not all(math.isfinite(x) for x in variables.values()):
        raise PreprocessingError("Valeur non finie produite par le prétraitement")
    return variables


def transformer(donnees: Mapping[str, float]) -> np.ndarray:
    """Retourne une matrice (1, n_variables) dans l'ordre attendu par le modèle."""
    variables = construire_variables(donnees)
    return np.array([[variables[v] for v in VARIABLES_MODELE]], dtype=float)
