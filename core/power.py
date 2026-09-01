"""Inhibition de la mise en veille pendant la lecture.

Sans cela l'écran s'éteint au beau milieu d'un film : le seul signal d'activité
que connaisse le système est le clavier et la souris, or un spectateur n'y touche
pas pendant deux heures. Chaque plateforme a son mécanisme ; l'objet reste le même
pour les trois et devient inerte là où aucun n'est disponible — au pire on retombe
sur le comportement d'avant, jamais sur une erreur.
"""

import ctypes
import logging
import platform
import subprocess
import time

logger = logging.getLogger(__name__)

# Drapeaux de SetThreadExecutionState (Windows).
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002

# ES_CONTINUOUS pose un état censé survivre à l'appel, mais Windows le perd dans
# plusieurs cas courants (session verrouillée puis reprise, changement de mode
# d'alimentation). On le repose donc périodiquement au lieu d'une fois pour toutes.
_REASSERT_AFTER = 30.0

# Sur Unix l'inhibition est portée par un processus annexe : elle dure tant qu'il
# vit, et disparaît avec lui — y compris si l'application meurt brutalement.
_HELPERS = {
    "Darwin": ["caffeinate", "-d", "-i"],
    "Linux": [
        "systemd-inhibit",
        "--what=idle",
        "--who=EpiKodi",
        "--why=Lecture en cours",
        "--mode=block",
        "sleep",
        "infinity",
    ],
}


class KeepAwake:
    """Empêche l'écran de s'éteindre entre `acquire()` et `release()`.

    Les deux appels sont idempotents et sans effet de bord : réacquérir un état
    déjà actif ne fait rien (hors rafraîchissement périodique), relâcher sans
    avoir acquis non plus. On peut donc les appeler depuis n'importe quel chemin
    du lecteur sans tenir de compteur.

    Sous Windows, `SetThreadExecutionState` ne vaut que pour le thread appelant :
    acquérir et relâcher depuis le thread graphique, seul à vivre aussi longtemps
    que la lecture.
    """

    def __init__(self):
        self._active = False
        self._last_assert = 0.0
        self._helper = None
        self._unavailable = False

    def is_active(self) -> bool:
        return self._active

    def acquire(self):
        """Interdit la veille. Appelable en boucle : l'état est reposé toutes les 30 s."""
        if self._unavailable:
            return
        now = time.monotonic()
        if self._active and now - self._last_assert < _REASSERT_AFTER:
            return
        if self._start():
            self._active = True
            self._last_assert = now

    def release(self):
        """Rend la main au système. Sans effet si la veille n'était pas inhibée."""
        if not self._active:
            return
        self._active = False
        self._stop()

    def set_active(self, active: bool):
        """Aligne l'inhibition sur l'état de lecture."""
        if active:
            self.acquire()
        else:
            self.release()

    # =================================================================
    # Implémentations par plateforme
    # =================================================================

    def _start(self) -> bool:
        if platform.system() == "Windows":
            return self._set_execution_state(
                _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
            )
        return self._spawn_helper()

    def _stop(self):
        if platform.system() == "Windows":
            self._set_execution_state(_ES_CONTINUOUS)
        else:
            self._kill_helper()

    def _set_execution_state(self, flags: int) -> bool:
        try:
            previous = ctypes.windll.kernel32.SetThreadExecutionState(
                ctypes.c_uint(flags)
            )
        except (AttributeError, OSError) as e:
            logger.warning(f"Screen sleep left untouched, API unavailable: {e}")
            self._unavailable = True
            return False
        if not previous:
            logger.warning(f"SetThreadExecutionState refused flags 0x{flags:08X}")
            return False
        return True

    def _spawn_helper(self) -> bool:
        if self._helper is not None and self._helper.poll() is None:
            return True

        command = _HELPERS.get(platform.system())
        if not command:
            self._unavailable = True
            return False

        try:
            self._helper = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            # Binaire absent : rien à inhiber, on ne réessaiera pas.
            logger.warning(f"Screen sleep left untouched, {command[0]} unavailable: {e}")
            self._unavailable = True
            return False
        return True

    def _kill_helper(self):
        if self._helper is None:
            return
        try:
            if self._helper.poll() is None:
                self._helper.terminate()
        except OSError as e:
            logger.error(f"Could not stop the keep-awake helper: {e}")
        finally:
            self._helper = None
