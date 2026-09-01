import logging
import platform

from PySide6.QtWidgets import QFrame

from core.vlc_bootstrap import ensure_vlc_path

ensure_vlc_path()

import vlc  # noqa: E402  (doit suivre ensure_vlc_path)

logger = logging.getLogger(__name__)

_instance = None


def get_vlc_instance() -> "vlc.Instance":
    """Instance libVLC partagée par le processus.

    libVLC tient un état global initialisé au premier `Instance()` : en créer et
    en libérer plusieurs dans un même processus provoque des violations d'accès.
    L'application n'a de toute façon qu'un seul lecteur.
    """
    global _instance
    if _instance is None:
        _instance = vlc.Instance()
    return _instance


class VideoWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: black;")
        self.instance = get_vlc_instance()
        self.player = self.instance.media_player_new()
        self._released = False

    def is_released(self) -> bool:
        """Après release(), toucher au lecteur libVLC fait planter le processus."""
        return self._released

    def attach_surface(self):
        if self._released:
            return
        self._set_surface(int(self.winId()))

    def detach_surface(self):
        """Rend la fenêtre à Qt avant d'arrêter VLC.

        Tant que la sortie Direct3D possède le HWND, elle a besoin de la boucle de
        messages du thread graphique pour se démonter — or c'est ce même thread qui
        appelle stop(). Détacher d'abord casse cette dépendance circulaire.
        """
        if self._released:
            return
        self._set_surface(0)

    def _set_surface(self, handle: int):
        try:
            system = platform.system()
            if system == "Windows":
                self.player.set_hwnd(handle)
            elif system == "Linux":
                self.player.set_xwindow(handle)
            elif system == "Darwin":
                self.player.set_nsobject(handle)
        except Exception as e:
            logger.error(f"Could not set the video surface to {handle}: {e}")

    def release(self):
        """Libère le lecteur libVLC. À appeler avant la destruction du widget.

        Sans cela, il était détruit par le ramasse-miettes dans un ordre
        indéterminé, après la fenêtre qui l'héberge. L'instance partagée, elle,
        reste en place jusqu'à la fin du processus.
        """
        if self._released:
            return
        self._released = True
        try:
            self.player.release()
        except Exception as e:
            logger.warning(f"Could not release the VLC player: {e}")

    def showEvent(self, event):
        self.attach_surface()
        super().showEvent(event)
