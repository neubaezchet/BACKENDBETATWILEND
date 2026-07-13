"""
Aislamiento multi-tenant para endpoints de datos (reportes, validador).
Si el request trae el JWT de un usuario de empresa (tenant), el filtro
"empresa" se FUERZA a la suya, sin importar qué pida el frontend.
Los admins globales (sin company_id) y las llamadas sin token conservan
el comportamiento actual.
"""

import logging

logger = logging.getLogger(__name__)


def empresa_scope(request, db, empresa_solicitada):
    """
    Devuelve el filtro de empresa efectivo:
    - Usuario tenant autenticado (JWT con company_id) → SIEMPRE el nombre de su empresa.
    - Admin global o sin token válido → lo que haya pedido ('all', nombre o None).
    """
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return empresa_solicitada
    try:
        from jose import jwt as _jwt
        from app.routes.admin import SECRET_KEY, ALGORITHM
        from app.database import AdminUser, Company
        payload = _jwt.decode(auth.split(" ", 1)[1], SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            return empresa_solicitada
        user = db.query(AdminUser).filter(AdminUser.username == username).first()
        if user and user.company_id:
            company = db.query(Company).filter(Company.id == user.company_id).first()
            if company:
                if empresa_solicitada not in ("all", company.nombre, None, "", "undefined"):
                    logger.warning(
                        f"🛑 Scoping multi-tenant: '{username}' pidió empresa "
                        f"'{empresa_solicitada}' pero pertenece a '{company.nombre}' — forzado"
                    )
                return company.nombre
    except Exception:
        # Token inválido/expirado → tratar como anónimo (comportamiento actual)
        pass
    return empresa_solicitada
