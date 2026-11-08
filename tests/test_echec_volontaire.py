"""Test volontairement défaillant : prouve que le workflow échoue quand un test échoue.

Désactivé par défaut. Activé par FORCER_ECHEC=1 (déclenchement manuel du workflow
avec l'option « forcer_echec », ou en local).
"""

import os

import pytest


@pytest.mark.skipif(os.getenv("FORCER_ECHEC") != "1", reason="démonstration activée par FORCER_ECHEC=1")
def test_echec_volontaire():
    probabilite = 1.7
    assert 0.0 <= probabilite <= 1.0, "Échec volontaire : le pipeline CI doit être bloqué"
