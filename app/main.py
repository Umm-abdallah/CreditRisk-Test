"""API de prédiction du risque de défaut (FastAPI).

Endpoints :
    GET  /health      disponibilité du service et du modèle
    POST /predict     estimation du risque pour un demandeur
    GET  /model-info  métadonnées de la version du modèle

Contrat d'erreur (toutes les erreurs) :
    {"erreur": {"code": str, "message": str, "details": [...]}, "id_requete": str}
Aucune trace technique n'est renvoyée au client ; le détail est journalisé.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.prediction import (
    MODELE_PAR_DEFAUT,
    ModelLoadError,
    ModelNotLoadedError,
    ModelService,
    PredictionError,
    classer_risque,
)
from app.preprocessing import PreprocessingError, transformer
from app.validation import DemandeCredit, detecter_alertes

logger = logging.getLogger("creditrisk")
API_VERSION = "1.0.0"

MESSAGES_FR = {
    "missing": "Champ obligatoire manquant",
    "extra_forbidden": "Champ non autorisé",
    "int_type": "Doit être un entier",
    "float_type": "Doit être un nombre",
    "greater_than": "Valeur trop faible",
    "greater_than_equal": "Valeur trop faible",
    "less_than_equal": "Valeur trop élevée",
    "finite_number": "Doit être un nombre fini",
    "model_type": "Le corps de la requête doit être un objet JSON",
    "model_attributes_type": "Le corps de la requête doit être un objet JSON",
}


class ReponsePrediction(BaseModel):
    probabilite_defaut: float
    classe_risque: str
    decision_suggeree: str
    alertes: list[str]
    version_modele: str
    id_requete: str
    avertissement: str = "Aide à la décision : la décision finale relève de l'agent de crédit."


def _erreur(statut: int, code: str, message: str, request: Request, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=statut,
        content={
            "erreur": {"code": code, "message": message, "details": details or []},
            "id_requete": getattr(request.state, "id_requete", ""),
        },
    )


def creer_app(chemin_modele: str | None = None) -> FastAPI:
    chemin = chemin_modele or os.getenv("MODEL_PATH", str(MODELE_PAR_DEFAUT))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service = ModelService()
        try:
            service.charger(chemin)
            logger.info("Modèle chargé : %s", service.metadonnees.get("version"))
        except ModelLoadError as exc:
            logger.error("Chargement du modèle impossible : %s", exc)
        app.state.service = service
        yield

    app = FastAPI(title="CreditRisk API", version=API_VERSION, lifespan=lifespan)
    app.state.service = ModelService()

    @app.middleware("http")
    async def identifiant_et_duree(request: Request, call_next):
        request.state.id_requete = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        debut = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # filet de sécurité : jamais de trace au client
            logger.exception("Erreur non gérée (id=%s)", request.state.id_requete)
            response = _erreur(500, "ERREUR_INTERNE", "Erreur interne du service", request)
        response.headers["X-Request-ID"] = request.state.id_requete
        response.headers["X-Process-Time-ms"] = f"{(time.perf_counter() - debut) * 1000:.3f}"
        return response

    @app.exception_handler(RequestValidationError)
    async def erreur_validation(request: Request, exc: RequestValidationError):
        erreurs = exc.errors()
        if any(e.get("type") == "json_invalid" for e in erreurs):
            return _erreur(400, "REQUETE_MAL_FORMEE", "Le corps n'est pas un JSON valide", request)
        details = []
        for e in erreurs:
            loc = [str(x) for x in e.get("loc", []) if x != "body"]
            details.append(
                {
                    "champ": ".".join(loc) or None,
                    "type": e.get("type"),
                    "message": MESSAGES_FR.get(e.get("type"), e.get("msg", "Valeur invalide")),
                }
            )
        return _erreur(422, "DONNEES_INVALIDES", "Données du demandeur invalides", request, details)

    @app.exception_handler(StarletteHTTPException)
    async def erreur_http(request: Request, exc: StarletteHTTPException):
        # ANO-01 : les erreurs HTTP du framework respectent aussi le contrat d'erreur
        codes = {
            400: ("REQUETE_MAL_FORMEE", "Le corps de la requête ne peut pas être lu"),
            404: ("RESSOURCE_INTROUVABLE", "Ressource introuvable"),
            405: ("METHODE_NON_AUTORISEE", "Méthode non autorisée sur cette ressource"),
        }
        code, message = codes.get(exc.status_code, (f"HTTP_{exc.status_code}", "Requête refusée"))
        reponse = _erreur(exc.status_code, code, message, request)
        if exc.headers:
            reponse.headers.update(exc.headers)
        return reponse

    @app.exception_handler(Exception)
    async def erreur_generique(request: Request, exc: Exception):
        logger.exception("Erreur non gérée (id=%s)", getattr(request.state, "id_requete", ""))
        return _erreur(500, "ERREUR_INTERNE", "Erreur interne du service", request)

    def service_courant(request: Request) -> ModelService:
        return request.app.state.service

    @app.get("/health")
    def health(request: Request, service: ModelService = Depends(service_courant)):
        if not service.pret:
            return _erreur(503, "MODELE_INDISPONIBLE", "Le modèle n'est pas chargé", request)
        return {
            "statut": "ok",
            "modele_charge": True,
            "version_modele": service.metadonnees.get("version"),
            "version_api": API_VERSION,
        }

    @app.get("/model-info")
    def model_info(request: Request, service: ModelService = Depends(service_courant)):
        if not service.pret:
            return _erreur(503, "MODELE_INDISPONIBLE", "Le modèle n'est pas chargé", request)
        m = service.metadonnees
        cles = (
            "version",
            "algorithme",
            "date_entrainement",
            "variables",
            "seuil_decision",
            "metriques_test",
            "domaine_entrainement",
            "sklearn_version",
            "sha256",
            "donnees",
        )
        return {k: m.get(k) for k in cles}

    @app.post("/predict", response_model=ReponsePrediction)
    def predict(
        demande: DemandeCredit,
        request: Request,
        service: ModelService = Depends(service_courant),
    ):
        if not service.pret:
            return _erreur(503, "MODELE_INDISPONIBLE", "Le modèle n'est pas chargé", request)
        try:
            X = transformer(demande.model_dump())
            proba = service.predire(X)
        except PreprocessingError:
            logger.exception("Erreur de prétraitement (id=%s)", request.state.id_requete)
            return _erreur(422, "PRETRAITEMENT_IMPOSSIBLE", "Données non exploitables", request)
        except ModelNotLoadedError:
            return _erreur(503, "MODELE_INDISPONIBLE", "Le modèle n'est pas chargé", request)
        except PredictionError:
            logger.exception("Erreur de prédiction (id=%s)", request.state.id_requete)
            return _erreur(500, "ERREUR_PREDICTION", "La prédiction n'a pas pu être calculée", request)

        classe, decision = classer_risque(proba)
        alertes = detecter_alertes(demande, service.metadonnees.get("domaine_entrainement"))
        if any(a.startswith("HORS_DOMAINE_ENTRAINEMENT") for a in alertes):
            # ANO-02 : une prédiction extrapolée n'oriente pas automatiquement la décision
            decision = "analyse_manuelle_hors_domaine"
        return ReponsePrediction(
            probabilite_defaut=round(proba, 6),
            classe_risque=classe,
            decision_suggeree=decision,
            alertes=alertes,
            version_modele=service.metadonnees.get("version", "inconnue"),
            id_requete=request.state.id_requete,
        )

    return app


app = creer_app()
