"""Test de charge léger avec Locust.

uvicorn app.main:app --port 8000
locust -f locustfile.py --headless -u 50 -r 5 -t 30s --host http://127.0.0.1:8000 --csv reports/locust
"""

import random

from locust import HttpUser, between, task


class AgentDeCredit(HttpUser):
    wait_time = between(0.05, 0.2)

    @task(8)
    def predire(self):
        age = random.randint(18, 75)
        self.client.post(
            "/predict",
            json={
                "age": age,
                "revenu_mensuel": random.randint(30_000, 1_500_000),
                "montant_credit": random.randint(50_000, 10_000_000),
                "duree_mois": random.choice([3, 6, 12, 18, 24, 36]),
                "anciennete_activite": round(random.uniform(0, min(30, age - 14)), 1),
            },
            name="/predict",
        )

    @task(1)
    def requete_invalide(self):
        with self.client.post("/predict", json={"age": -5}, name="/predict [invalide]", catch_response=True) as r:
            if r.status_code == 422:
                r.success()

    @task(1)
    def sante(self):
        self.client.get("/health")
