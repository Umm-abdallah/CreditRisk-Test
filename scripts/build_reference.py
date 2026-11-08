"""Construit la version de référence pour les tests de non-régression.

Produit :
    reference/jeu_or.csv              60 demandeurs fixes (jeu « golden »)
    reference/reference_v1.0.0.json   métriques et prédictions de référence
Les tolérances sont définies à part, AVANT toute comparaison, dans
reference/tolerances.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import pandas as pd

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app.preprocessing import VARIABLES_BRUTES  # noqa: E402
from scripts.train_model import CHEMIN_DONNEES, evaluer, matrice_variables  # noqa: E402

VERSION_REFERENCE = "1.0.0"


def main() -> None:
    df = pd.read_csv(CHEMIN_DONNEES)
    test = df[df["jeu"] == "test"]
    jeu_or = test.sample(60, random_state=7)[list(VARIABLES_BRUTES)].reset_index(drop=True)
    dossier = RACINE / "reference"
    dossier.mkdir(exist_ok=True)
    jeu_or.to_csv(dossier / "jeu_or.csv", index=False)

    modele = joblib.load(RACINE / "models" / f"model_v{VERSION_REFERENCE}.joblib")
    proba_or = modele.predict_proba(matrice_variables(jeu_or))[:, 1]
    reference = {
        "version": VERSION_REFERENCE,
        "metriques_test": evaluer(modele, matrice_variables(test), test["defaut"].to_numpy()),
        "probabilites_jeu_or": [round(float(p), 12) for p in proba_or],
    }
    (dossier / f"reference_v{VERSION_REFERENCE}.json").write_text(
        json.dumps(reference, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("Référence écrite :", reference["metriques_test"])


if __name__ == "__main__":
    main()
