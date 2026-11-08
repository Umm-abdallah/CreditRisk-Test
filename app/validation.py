"""Module de validation des données du demandeur.

Responsabilités :
* vérifier le type, la présence et les bornes de chaque variable ;
* refuser les champs non prévus par le contrat ;
* contrôler la cohérence entre variables (ancienneté et âge) ;
* produire des alertes pour les entrées valides mais inhabituelles.

Le schéma est en mode strict : aucune conversion implicite n'est faite
(une chaîne "250000" n'est pas acceptée comme revenu, 12.0 n'est pas
accepté comme durée entière, un booléen n'est pas accepté comme nombre).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bornes métier du contrat (documentées dans docs/plan_de_test.md)
AGE_MIN, AGE_MAX = 18, 75
REVENU_MAX = 100_000_000  # FCFA par mois
MONTANT_MIN = 10_000  # FCFA (ANO-03 : plus de montant quasi nul)
MONTANT_MAX = 500_000_000  # FCFA
DUREE_MIN, DUREE_MAX = 1, 60  # mois
ANCIENNETE_MAX = 60  # années
AGE_DEBUT_ACTIVITE = 14  # ancienneté maximale = âge - 14 ans

CHAMPS_ATTENDUS = (
    "age",
    "revenu_mensuel",
    "montant_credit",
    "duree_mois",
    "anciennete_activite",
)


class DemandeCredit(BaseModel):
    """Contrat d'entrée de l'endpoint POST /predict."""

    model_config = ConfigDict(strict=True, extra="forbid")

    age: int = Field(ge=AGE_MIN, le=AGE_MAX, description="Âge du demandeur en années")
    revenu_mensuel: float = Field(gt=0, le=REVENU_MAX, allow_inf_nan=False, description="Revenu mensuel en FCFA")
    montant_credit: float = Field(
        ge=MONTANT_MIN, le=MONTANT_MAX, allow_inf_nan=False, description="Montant demandé en FCFA"
    )
    duree_mois: int = Field(ge=DUREE_MIN, le=DUREE_MAX, description="Durée du crédit en mois")
    anciennete_activite: float = Field(ge=0, le=ANCIENNETE_MAX, allow_inf_nan=False, description="Ancienneté en années")

    @model_validator(mode="after")
    def verifier_coherence(self) -> DemandeCredit:
        if self.anciennete_activite > self.age - AGE_DEBUT_ACTIVITE:
            raise ValueError(
                "anciennete_activite incohérente avec l'âge "
                f"(maximum {self.age - AGE_DEBUT_ACTIVITE} ans pour {self.age} ans)"
            )
        return self


def detecter_alertes(demande: DemandeCredit, domaine: dict[str, list[float]] | None) -> list[str]:
    """Signale les entrées valides mais inhabituelles.

    ``domaine`` contient, pour chaque variable, l'intervalle [min, max]
    observé à l'entraînement (métadonnées du modèle). Une valeur hors de
    cet intervalle reste acceptée mais la prédiction est moins fiable.
    """
    alertes: list[str] = []
    if domaine:
        for champ in CHAMPS_ATTENDUS:
            bornes = domaine.get(champ)
            if not bornes:
                continue
            valeur = getattr(demande, champ)
            if valeur < bornes[0] or valeur > bornes[1]:
                alertes.append(f"HORS_DOMAINE_ENTRAINEMENT:{champ}")
    mensualite = demande.montant_credit / demande.duree_mois
    if mensualite > demande.revenu_mensuel:
        alertes.append("MENSUALITE_SUPERIEURE_AU_REVENU")
    return alertes
