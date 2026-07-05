"""
Links de los 3 portales por empresa (multi-tenant por slug).
El slug en la URL permite que cada frontend cargue la paleta/logo de la
empresa ANTES del login (branding pre-autenticación).
"""

import os
from typing import Optional

ADMIN_ORIGIN = os.environ.get("ADMIN_ORIGIN", "https://admin-neurobaeza.vercel.app")
PORTAL_ORIGIN = os.environ.get("PORTAL_ORIGIN", "https://portal-neurobaeza.vercel.app")
REPOGEMIN_ORIGIN = os.environ.get("REPOGEMIN_ORIGIN", "https://repogemin.vercel.app")


def links_de_company(slug: Optional[str]) -> dict:
    """Devuelve los links de los 3 portales para una empresa. Sin slug → links genéricos."""
    if not slug:
        return {
            "admin": ADMIN_ORIGIN,
            "portal": PORTAL_ORIGIN,
            "repogemin": REPOGEMIN_ORIGIN,
        }
    return {
        "admin": f"{ADMIN_ORIGIN}/login?empresa={slug}",
        "portal": f"{PORTAL_ORIGIN}/?empresa={slug}",
        "repogemin": f"{REPOGEMIN_ORIGIN}/?empresa={slug}",
    }
