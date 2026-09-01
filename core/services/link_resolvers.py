"""Passage d'un lien de page à un lien de fichier.

Certains hébergeurs ne servent pas le fichier à l'adresse qu'on se partage : cette
adresse est une page HTML, et le lien réel s'obtient auprès de leur API avec les
identifiants du compte. Ce module ne connaît que des hébergeurs — il reçoit une URL
et en renvoie une autre — et ne cherche jamais de contenu.
"""

import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

ONEFICHIER_API = "https://api.1fichier.com/v1"
RESOLVE_TIMEOUT = 30


class ResolverError(Exception):
    """Message destiné à l'utilisateur, affiché sur la ligne du téléchargement."""


def resolve(url: str) -> str:
    """Adresse réellement téléchargeable pour `url`.

    Renvoie l'URL inchangée quand l'hébergeur n'a rien à résoudre — c'est le cas
    général. À rappeler à chaque tentative : les liens rendus par les API sont à
    usage unique ou expirent au bout de quelques minutes.
    """
    if _is_onefichier_page(url):
        return _resolve_onefichier(url)
    return url


def _is_onefichier_page(url: str) -> bool:
    """Seul le domaine nu porte des pages.

    Les liens directs rendus par l'API vivent sur des sous-domaines (`sX.1fichier.com`)
    et ne doivent surtout pas être résolus une seconde fois.
    """
    host = urlparse(url).netloc.lower().split(":")[0]
    return host in ("1fichier.com", "www.1fichier.com")


def _normalise_onefichier_url(url: str) -> str:
    """Ne garde que l'identifiant du fichier.

    Les liens qui circulent traînent souvent un paramètre d'affiliation
    (« ?abc123&af=5010551 ») : le navigateur s'en accommode, l'API répond
    « Resource not found » parce qu'elle ne reconnaît plus la ressource.
    L'identifiant est le seul segment sans « = ».
    """
    parsed = urlparse(url)
    identifier = next(
        (part for part in parsed.query.split("&") if part and "=" not in part), ""
    )
    return f"https://1fichier.com/?{identifier}" if identifier else url


def _resolve_onefichier(url: str) -> str:
    from core.config import get_onefichier_api_key

    if urlparse(url).path.startswith("/dir/"):
        raise ResolverError(
            "Lien de dossier 1fichier : seuls les liens de fichier peuvent être "
            "téléchargés. Ouvrez le dossier et copiez le lien d'un fichier."
        )

    api_key = get_onefichier_api_key()
    if not api_key:
        raise ResolverError(
            "Lien 1fichier : renseignez votre clé API dans "
            "Paramètres → Téléchargements."
        )

    try:
        response = requests.post(
            f"{ONEFICHIER_API}/download/get_token.cgi",
            json={"url": _normalise_onefichier_url(url), "single": 1},
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=RESOLVE_TIMEOUT,
        )
    except requests.RequestException as e:
        raise ResolverError(f"1fichier injoignable : {e}") from e

    # Le corps est du JSON même sur un code d'erreur, et c'est lui qui porte le
    # motif exact — 401 « Not authenticated » pour une clé refusée, 404 pour un
    # lien mort. Lever sur le seul code HTTP perdrait cette distinction.
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if payload.get("status") == "OK" and payload.get("url"):
        logger.info("Resolved a 1fichier link to a direct one")
        return payload["url"]

    message = payload.get("message")
    if message:
        raise ResolverError(f"1fichier : {message} (HTTP {response.status_code})")
    raise ResolverError(
        f"1fichier a refusé le lien (HTTP {response.status_code}, réponse illisible)."
    )
