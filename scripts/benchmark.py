"""Mesures de performance : latence d'inférence, latence API, P95, débit, charge progressive.

    python scripts/benchmark.py            # lance un serveur uvicorn local sur le port 8765
Produit reports/performance.json et reports/rapport_performance.md
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import joblib
import numpy as np

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app.preprocessing import transformer  # noqa: E402
from app.validation import DemandeCredit  # noqa: E402

PORT = 8765
URL = f"http://127.0.0.1:{PORT}"
DEMANDE = {"age": 35, "revenu_mensuel": 250000, "montant_credit": 1000000, "duree_mois": 12, "anciennete_activite": 4}

# Objectifs fixés AVANT la mesure (justification dans le rapport)
OBJECTIF_P95_MS = 200.0
OBJECTIF_DEBIT = 50.0  # requêtes par seconde
CONCURRENCE_CIBLE = 20


def stats_ms(durees_s: list[float]) -> dict:
    ms = np.array(durees_s) * 1000
    return {
        "n": int(len(ms)),
        "moyenne": round(float(ms.mean()), 3),
        "p50": round(float(np.percentile(ms, 50)), 3),
        "p95": round(float(np.percentile(ms, 95)), 3),
        "p99": round(float(np.percentile(ms, 99)), 3),
        "max": round(float(ms.max()), 3),
    }


def mesurer_inference(n: int = 3000) -> dict:
    modele = joblib.load(RACINE / "models" / "model_v1.0.0.joblib")
    X = transformer(DEMANDE)
    for _ in range(100):
        modele.predict_proba(X)
    inf, pipe = [], []
    for _ in range(n):
        t = time.perf_counter()
        modele.predict_proba(X)
        inf.append(time.perf_counter() - t)
    for _ in range(n):
        t = time.perf_counter()
        d = DemandeCredit(**DEMANDE)
        modele.predict_proba(transformer(d.model_dump()))
        pipe.append(time.perf_counter() - t)
    return {"inference_modele": stats_ms(inf), "validation_pretraitement_inference": stats_ms(pipe)}


def requete(client: httpx.Client) -> tuple[float, int]:
    t = time.perf_counter()
    r = client.post(f"{URL}/predict", json=DEMANDE)
    return time.perf_counter() - t, r.status_code


def charge(concurrence: int, total: int) -> dict:
    def travail(nb):
        res = []
        with httpx.Client(timeout=10) as c:
            for _ in range(nb):
                res.append(requete(c))
        return res

    parts = [total // concurrence] * concurrence
    debut = time.perf_counter()
    with ThreadPoolExecutor(concurrence) as ex:
        resultats = [r for lot in ex.map(travail, parts) for r in lot]
    duree = time.perf_counter() - debut
    durees = [d for d, _ in resultats]
    erreurs = sum(1 for _, s in resultats if s != 200)
    return {
        "concurrence": concurrence,
        **stats_ms(durees),
        "debit_req_s": round(len(resultats) / duree, 1),
        "taux_erreur": erreurs / len(resultats),
    }


def environnement() -> dict:
    cpu = "inconnu"
    try:
        for ligne in Path("/proc/cpuinfo").read_text().splitlines():
            if ligne.startswith("model name"):
                cpu = ligne.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    mem = "inconnue"
    try:
        kb = int(Path("/proc/meminfo").read_text().split()[1])
        mem = f"{kb / 1024 / 1024:.1f} Go"
    except (OSError, ValueError, IndexError):
        pass
    import fastapi
    import sklearn

    return {
        "systeme": platform.platform(),
        "processeur": cpu,
        "coeurs_logiques": os.cpu_count(),
        "memoire": mem,
        "python": platform.python_version(),
        "fastapi": fastapi.__version__,
        "scikit_learn": sklearn.__version__,
        "serveur": "uvicorn, 1 worker, local (127.0.0.1)",
        "client": "httpx, threads (ThreadPoolExecutor), même machine",
    }


def main() -> None:
    serveur = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=RACINE,
    )
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{URL}/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        with httpx.Client() as c:
            for _ in range(50):
                requete(c)
            sequentiel = [requete(c)[0] for _ in range(500)]
        progressive = [charge(n, 400 if n < 10 else 1000) for n in (1, 5, 10, 20, 50)]
    finally:
        serveur.terminate()
        serveur.wait()

    resultats = {
        "environnement": environnement(),
        "objectifs": {"p95_ms": OBJECTIF_P95_MS, "debit_req_s": OBJECTIF_DEBIT, "concurrence": CONCURRENCE_CIBLE},
        "inference": mesurer_inference(),
        "api_sequentielle": stats_ms(sequentiel),
        "charge_progressive": progressive,
    }
    cible = next(p for p in progressive if p["concurrence"] == CONCURRENCE_CIBLE)
    resultats["objectif_atteint"] = (
        cible["p95"] <= OBJECTIF_P95_MS and cible["debit_req_s"] >= OBJECTIF_DEBIT and cible["taux_erreur"] == 0
    )
    (RACINE / "reports" / "performance.json").write_text(json.dumps(resultats, indent=2, ensure_ascii=False))
    print(json.dumps(resultats, indent=2, ensure_ascii=False))
    _ = statistics  # module conservé pour d'éventuels calculs complémentaires


if __name__ == "__main__":
    main()
