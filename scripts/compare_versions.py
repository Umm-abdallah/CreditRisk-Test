"""Rapport de non-régression : compare des versions candidates à la référence 1.0.0.

    python scripts/compare_versions.py 1.1.0 1.2.0 1.3.0
Produit reports/rapport_non_regression.md et reports/non_regression.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app.prediction import classer_risque  # noqa: E402
from app.preprocessing import transformer  # noqa: E402
from scripts.train_model import CHEMIN_DONNEES, SEUIL, evaluer, matrice_variables  # noqa: E402

REF = json.loads((RACINE / "reference" / "reference_v1.0.0.json").read_text(encoding="utf-8"))
TOL = json.loads((RACINE / "reference" / "tolerances.json").read_text(encoding="utf-8"))
JEU_OR = pd.read_csv(RACINE / "reference" / "jeu_or.csv")
BASE = {"age": 35, "revenu_mensuel": 250000, "montant_credit": 1000000, "duree_mois": 12, "anciennete_activite": 4}


def fnr_par_duree(modele, test: pd.DataFrame) -> dict:
    proba = modele.predict_proba(matrice_variables(test))[:, 1]
    pred = proba >= SEUIL
    res = {}
    for nom, lo, hi in (("moins_12_mois", 0, 12), ("12_23_mois", 12, 24), ("24_mois_et_plus", 24, 999)):
        masque = (test["duree_mois"].between(lo, hi - 1)) & (test["defaut"] == 1)
        res[nom] = round(float(1 - pred[masque.to_numpy()].mean()), 3)
    return res


def monotonie_revenu(modele) -> bool:
    valeurs = [
        float(modele.predict_proba(transformer({**BASE, "revenu_mensuel": r}))[0, 1])
        for r in (30_000, 250_000, 500_000, 1_000_000, 1_800_000, 3_000_000, 10_000_000)
    ]
    return all(b <= a + 0.02 for a, b in zip(valeurs, valeurs[1:], strict=False))


def comparer(version: str, test: pd.DataFrame) -> dict:
    modele = joblib.load(RACINE / "models" / f"model_v{version}.joblib")
    m = evaluer(modele, matrice_variables(test), test["defaut"].to_numpy())
    r = REF["metriques_test"]
    proba = modele.predict_proba(matrice_variables(JEU_OR))[:, 1]
    ref_p = np.array(REF["probabilites_jeu_or"])
    chg = float(np.mean([classer_risque(a)[0] != classer_risque(b)[0] for a, b in zip(ref_p, proba, strict=True)]))
    controles = {
        "rappel": r["rappel"] - m["rappel"] <= TOL["baisse_max_rappel"],
        "f1": r["f1"] - m["f1"] <= TOL["baisse_max_f1"],
        "auc": r["auc"] - m["auc"] <= TOL["baisse_max_auc"],
        "ecart_proba": float(np.abs(proba - ref_p).max()) <= TOL["ecart_max_proba_nouvelle_version"],
        "changement_classe": chg <= TOL["part_max_changement_classe_risque"],
    }
    return {
        "version": version,
        "metriques": m,
        "ecart_proba_max": round(float(np.abs(proba - ref_p).max()), 4),
        "ecart_proba_moyen": round(float(np.abs(proba - ref_p).mean()), 4),
        "part_changement_classe": round(chg, 3),
        "controles": controles,
        "verdict": "CONFORME" if all(controles.values()) else "NON CONFORME",
        "fnr_par_duree": fnr_par_duree(modele, test),
        "monotonie_revenu": monotonie_revenu(modele),
    }


def main(versions: list[str]) -> None:
    df = pd.read_csv(CHEMIN_DONNEES)
    test = df[df["jeu"] == "test"]
    ref_modele = joblib.load(RACINE / "models" / "model_v1.0.0.joblib")
    reference = {
        "version": "1.0.0",
        "metriques": REF["metriques_test"],
        "fnr_par_duree": fnr_par_duree(ref_modele, test),
        "monotonie_revenu": monotonie_revenu(ref_modele),
    }
    resultats = [comparer(v, test) for v in versions]
    (RACINE / "reports" / "non_regression.json").write_text(
        json.dumps({"reference": reference, "tolerances": TOL, "candidats": resultats}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    ok = lambda b: "OK" if b else "ÉCHEC"  # noqa: E731
    lignes = [
        "# Rapport de non-régression",
        "",
        "Je compare chaque version au modèle de référence 1.0.0 (StandardScaler et LogisticRegression), sur les 1 800 dossiers du jeu de test synthétique, avec un seuil de décision de 0,5.",
        "J'ai fixé les tolérances avant la comparaison, dans `reference/tolerances.json` : le rappel et le F1 ne doivent pas baisser de plus de 0,03, "
        "l'AUC de plus de 0,02, la probabilité d'un dossier du jeu « or » ne doit pas bouger de plus de 0,15, et au plus 20 % des dossiers peuvent changer de classe de risque.",
        "",
        "## Métriques",
        "",
        "| Version | Rappel | Précision | F1 | AUC | Taux de faux négatifs |",
        "|---|---|---|---|---|---|",
        f"| 1.0.0 (référence) | {REF['metriques_test']['rappel']} | {REF['metriques_test']['precision']} | {REF['metriques_test']['f1']} | {REF['metriques_test']['auc']} | {REF['metriques_test']['taux_faux_negatifs']} |",
    ]
    for c in resultats:
        m = c["metriques"]
        lignes.append(
            f"| {c['version']} | {m['rappel']} | {m['precision']} | {m['f1']} | {m['auc']} | {m['taux_faux_negatifs']} |"
        )
    lignes += [
        "",
        "## Contrôles",
        "",
        "| Version | Rappel | F1 | AUC | Écart proba max | Changements de classe | Verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in resultats:
        k = c["controles"]
        lignes.append(
            f"| {c['version']} | {ok(k['rappel'])} | {ok(k['f1'])} | {ok(k['auc'])} | "
            f"{ok(k['ecart_proba'])} ({c['ecart_proba_max']}) | {ok(k['changement_classe'])} ({c['part_changement_classe']:.0%}) | {c['verdict']} |"
        )
    lignes += [
        "",
        "## Contrôles en plus (non bloquants)",
        "",
        "| Version | FNR < 12 mois | FNR 12 à 23 mois | FNR 24 mois et plus | Risque décroissant avec le revenu |",
        "|---|---|---|---|---|",
    ]
    for c in [reference] + resultats:
        f = c["fnr_par_duree"]
        lignes.append(
            f"| {c['version']} | {f['moins_12_mois']} | {f['12_23_mois']} | {f['24_mois_et_plus']} | {'oui' if c['monotonie_revenu'] else 'non (ANO-02)'} |"
        )
    (RACINE / "reports" / "rapport_non_regression.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    print("\n".join(lignes))


if __name__ == "__main__":
    main(sys.argv[1:] or ["1.1.0", "1.2.0", "1.3.0"])
