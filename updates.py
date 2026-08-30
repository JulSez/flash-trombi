from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple

from version import APP_VERSION

LATEST_RELEASE_API = "https://api.github.com/repos/JulSez/flash-trombi/releases/latest"
RELEASES_URL = "https://github.com/JulSez/flash-trombi/releases"


def _version_tuple(value: str) -> Tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+){0,3})", value or "")
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def check_for_update(timeout: float = 4.0) -> Dict[str, Optional[str]]:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"User-Agent": f"FlashTrombi/{APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "available": False,
                "current": APP_VERSION,
                "latest": None,
                "url": RELEASES_URL,
                "message": "Aucune version Windows publiée pour le moment.",
            }
        return {
            "available": False,
            "current": APP_VERSION,
            "latest": None,
            "url": RELEASES_URL,
            "message": "Impossible de vérifier les mises à jour maintenant.",
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {
            "available": False,
            "current": APP_VERSION,
            "latest": None,
            "url": RELEASES_URL,
            "message": "Pas de connexion à GitHub. Réessaie plus tard.",
        }

    tag = str(payload.get("tag_name", ""))
    url = str(payload.get("html_url") or RELEASES_URL)
    available = _version_tuple(tag) > _version_tuple(APP_VERSION)
    return {
        "available": available,
        "current": APP_VERSION,
        "latest": tag or None,
        "url": url,
        "message": (
            f"Une nouvelle version ({tag}) est disponible."
            if available
            else "Flash Trombi est à jour."
        ),
    }
