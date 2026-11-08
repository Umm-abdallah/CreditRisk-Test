"""Génère le jeu de données synthétique et entraîne une version de modèle.

AVERTISSEMENT : les données sont synthétiques. Elles servent uniquement à
tester le système (contrats, robustesse, non-régression, performance) et ne
permettent PAS de démontrer la performance réelle d'un modèle de crédit.

Usage :
    python scripts/train_model.py --version 1.0.0 --algo logreg
    python scripts/train_model.py --version 1.1.0 --algo hgb
    python scripts/train_model.py --version 1.2.0 --algo logreg --sans-equilibrage
    python scripts/train_model.py --version 1.3.0 --algo hgb --monotone
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app.prediction import sha256_fichier  # noqa: E402
from app.preprocessing import VARIABLES_BRUTES, VARIABLES_MODELE, construire_variables  # noqa: E402

GRAINE = 42
SEUIL = 0.5
DATE_FIGEE = "2026-11-08"  # date figée pour la reproductibilité des métadonnées
CHEMIN_DONNEES = RACINE / "data" / "credit_synthetique.csv"


def generer_donnees(n: int = 6000, graine: int = GRAINE) -> pd.DataFrame:
    rng = np.random.default_rng(graine)
    age = rng.integers(18, 71, n)
    plafond_anc = np.minimum(age - 14, 30)
    anciennete = np.round(plafond_anc * rng.beta(1.6, 3.0, n), 1)
    revenu = np.clip(rng.lognormal(np.log(200_000), 0.6, n), 30_000, 3_000_000).round(-3)
    montant = np.clip(revenu * rng.uniform(1, 15, n), 50_000, 20_000_000).round(-4)
    duree = rng.choice([3, 6, 9, 12, 18, 24, 36, 48], n)
    taux_effort = montant / duree / revenu
    logit = (
        -1.9
        + 2.6 * (taux_effort - 0.3)
        - 0.035 * (age - 35)
        - 0.16 * (anciennete - 4)
        + 0.012 * (duree - 12)
        + rng.normal(0, 0.8, n)
    )
    defaut = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    return pd.DataFrame(
        {
            "age": age,
            "revenu_mensuel": revenu,
            "montant_credit": montant,
            "duree_mois": duree,
            "anciennete_activite": anciennete,
            "defaut": defaut,
        }
    )


def matrice_variables(df: pd.DataFrame) -> np.ndarray:
    lignes = [construire_variables(r) for r in df[list(VARIABLES_BRUTES)].to_dict("records")]
    return np.array([[ligne[v] for v in VARIABLES_MODELE] for ligne in lignes], dtype=float)


# Sens de variation imposé (ordre de VARIABLES_MODELE) : -1 décroissant, +1 croissant
CONTRAINTES_MONOTONES = [-1, -1, 1, 1, -1, 1, -1, 1]


def construire_modele(algo: str, equilibrage: bool = True, monotone: bool = False):
    poids = "balanced" if equilibrage else None
    if algo == "logreg":
        return Pipeline(
            [
                ("normalisation", StandardScaler()),
                ("classifieur", LogisticRegression(class_weight=poids, max_iter=2000)),
            ]
        )
    if algo == "hgb":
        return HistGradientBoostingClassifier(
            max_depth=3,
            learning_rate=0.08,
            max_iter=200,
            class_weight=poids,
            random_state=GRAINE,
            monotonic_cst=CONTRAINTES_MONOTONES if monotone else None,
        )
    raise ValueError(f"Algorithme inconnu : {algo}")


def evaluer(modele, X: np.ndarray, y: np.ndarray, seuil: float = SEUIL) -> dict:
    proba = modele.predict_proba(X)[:, 1]
    pred = (proba >= seuil).astype(int)
    return {
        "rappel": round(float(recall_score(y, pred)), 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred)), 4),
        "auc": round(float(roc_auc_score(y, proba)), 4),
        "taux_faux_negatifs": round(float(1 - recall_score(y, pred)), 4),
        "n_test": int(len(y)),
        "taux_defaut_test": round(float(y.mean()), 4),
    }


def charger_ou_generer() -> pd.DataFrame:
    if CHEMIN_DONNEES.exists():
        return pd.read_csv(CHEMIN_DONNEES)
    df = generer_donnees()
    idx_train, _ = train_test_split(df.index, test_size=0.3, stratify=df["defaut"], random_state=GRAINE)
    df["jeu"] = np.where(df.index.isin(idx_train), "entrainement", "test")
    CHEMIN_DONNEES.parent.mkdir(exist_ok=True)
    df.to_csv(CHEMIN_DONNEES, index=False)
    return df


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--version", required=True)
    p.add_argument("--algo", choices=["logreg", "hgb"], default="logreg")
    p.add_argument(
        "--bruit-etiquettes",
        type=float,
        default=0.0,
        help="Part des défauts d'entraînement réétiquetés à 0 (simulation de régression)",
    )
    p.add_argument(
        "--sans-equilibrage",
        action="store_true",
        help="Désactive la pondération des classes (simulation d'une régression de code)",
    )
    p.add_argument(
        "--monotone",
        action="store_true",
        help="Impose des contraintes de monotonie métier (hgb uniquement, correction ANO-02)",
    )
    p.add_argument("--sortie", default=str(RACINE / "models"))
    args = p.parse_args()

    df = charger_ou_generer()
    train, test = df[df["jeu"] == "entrainement"], df[df["jeu"] == "test"]
    X_train, y_train = matrice_variables(train), train["defaut"].to_numpy().copy()
    X_test, y_test = matrice_variables(test), test["defaut"].to_numpy()

    if args.bruit_etiquettes > 0:
        rng = np.random.default_rng(GRAINE)
        positifs = np.flatnonzero(y_train == 1)
        flips = rng.choice(positifs, int(len(positifs) * args.bruit_etiquettes), replace=False)
        y_train[flips] = 0

    modele = construire_modele(args.algo, not args.sans_equilibrage, args.monotone).fit(X_train, y_train)

    sortie = Path(args.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    chemin = sortie / f"model_v{args.version}.joblib"
    joblib.dump(modele, chemin)

    metadonnees = {
        "version": args.version,
        "algorithme": (
            "HistGradientBoostingClassifier" + (" (monotone)" if args.monotone else "")
            if args.algo == "hgb"
            else "StandardScaler+LogisticRegression"
        ),
        "date_entrainement": DATE_FIGEE,
        "graine": GRAINE,
        "donnees": "synthetiques (scripts/train_model.py) : test du système uniquement",
        "bruit_etiquettes": args.bruit_etiquettes,
        "equilibrage_classes": not args.sans_equilibrage,
        "contraintes_monotones": args.monotone,
        "variables": list(VARIABLES_MODELE),
        "seuil_decision": SEUIL,
        "metriques_test": evaluer(modele, X_test, y_test),
        "domaine_entrainement": {v: [float(train[v].min()), float(train[v].max())] for v in VARIABLES_BRUTES},
        "sklearn_version": sklearn.__version__,
        "sha256": sha256_fichier(chemin),
    }
    chemin.with_suffix(".json").write_text(json.dumps(metadonnees, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"version": args.version, **metadonnees["metriques_test"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
