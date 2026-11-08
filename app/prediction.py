"""Module de prédiction : chargement du modèle versionné et inférence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np

RACINE = Path(__file__).resolve().parent.parent
MODELE_PAR_DEFAUT = RACINE / "models" / "model_v1.0.0.joblib"

# Seuils de restitution métier (couche applicative)
SEUIL_RISQUE_MODERE = 0.30
SEUIL_RISQUE_ELEVE = 0.60


class ModelNotLoadedError(Exception):
    """Le modèle n'est pas chargé ou n'a pas pu l'être."""


class ModelLoadError(Exception):
    """Échec du chargement (fichier absent, corrompu, empreinte invalide)."""


class PredictionError(Exception):
    """Erreur pendant l'inférence (dimensions, sortie invalide, exception interne)."""


def sha256_fichier(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(65536), b""):
            h.update(bloc)
    return h.hexdigest()


def metadonnees_pour(chemin_modele: Path) -> Path:
    return chemin_modele.with_suffix(".json")


@dataclass
class ModelService:
    """Encapsule le modèle et ses métadonnées."""

    modele: object | None = None
    metadonnees: dict = field(default_factory=dict)
    erreur_chargement: str | None = None

    @property
    def pret(self) -> bool:
        return self.modele is not None

    def charger(self, chemin: str | Path) -> None:
        chemin = Path(chemin)
        self.modele, self.metadonnees, self.erreur_chargement = None, {}, None
        try:
            if not chemin.exists():
                raise ModelLoadError(f"Fichier modèle introuvable : {chemin.name}")
            meta_path = metadonnees_pour(chemin)
            if not meta_path.exists():
                raise ModelLoadError("Métadonnées du modèle introuvables")
            metadonnees = json.loads(meta_path.read_text(encoding="utf-8"))
            attendu = metadonnees.get("sha256")
            if attendu and sha256_fichier(chemin) != attendu:
                raise ModelLoadError("Empreinte SHA-256 du modèle invalide")
            modele = joblib.load(chemin)
            if not hasattr(modele, "predict_proba"):
                raise ModelLoadError("L'objet chargé n'expose pas predict_proba")
        except ModelLoadError as exc:
            self.erreur_chargement = str(exc)
            raise
        except Exception as exc:  # fichier corrompu, version incompatible...
            self.erreur_chargement = "Modèle illisible"
            raise ModelLoadError("Modèle illisible") from exc
        self.modele, self.metadonnees = modele, metadonnees

    def predire(self, X: np.ndarray) -> float:
        if not self.pret:
            raise ModelNotLoadedError("Modèle non chargé")
        attendu = getattr(self.modele, "n_features_in_", None)
        if X.ndim != 2 or X.shape[0] != 1 or (attendu is not None and X.shape[1] != attendu):
            raise PredictionError(f"Dimensions incompatibles : reçu {X.shape}, attendu (1, {attendu})")
        try:
            proba = float(self.modele.predict_proba(X)[0, 1])
        except Exception as exc:
            raise PredictionError("Échec de l'inférence") from exc
        if not math.isfinite(proba) or not 0.0 <= proba <= 1.0:
            raise PredictionError("Probabilité invalide produite par le modèle")
        return proba


def classer_risque(probabilite: float) -> tuple[str, str]:
    """Traduit la probabilité en classe de risque et en suggestion pour l'agent."""
    if probabilite >= SEUIL_RISQUE_ELEVE:
        return "eleve", "dossier_a_risque_eleve_avis_comite"
    if probabilite >= SEUIL_RISQUE_MODERE:
        return "modere", "analyse_complementaire"
    return "faible", "avis_favorable_sous_reserve"
