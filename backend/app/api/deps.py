"""
Dependencias compartidas de la API (ETAPA 2).

- SessionDep: sesión de SQLAlchemy inyectada por `app.database.get_db`.
- get_current_user / CurrentUser: resuelve el usuario del token Bearer
  y valida su estado de cuenta antes de entrar a cualquier endpoint.
- RequirePermission: factoría de dependencias para exigir un permiso RBAC
  (catálogo sembrado en `scripts/seed_data.py`, motor en
  `app.core.permissions`).

Los 401/403 usan las excepciones de `app.core.exceptions`, de modo que
todas las respuestas conservan el formato
`{"detail": {"code": ..., "message": ...}}` definido en `app.main`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose.exceptions import ExpiredSignatureError, JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PermissionDenied,
    TokenExpired,
    TokenInvalid,
    Unauthorized,
)
from app.core.permissions import has_permission
from app.core.security import decode_access_token
from app.database import get_db
from app.models import Usuario

# auto_error=False: la ausencia de token la reportamos nosotros con el
# formato AppException del proyecto (y no el formato por defecto de FastAPI).
_bearer_scheme = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: SessionDep,
) -> Usuario:
    """
    Extrae y valida el access token del encabezado `Authorization: Bearer`.

    Lanza 401 si el token es inexistente, expirado, firmado por otro, de tipo
    incorrecto, o si la cuenta asociada no está ACTIVA.
    """
    if credentials is None:
        raise Unauthorized("Falta el token de autorización (envíe 'Authorization: Bearer <token>')")

    try:
        payload = decode_access_token(credentials.credentials)
    except ExpiredSignatureError as exc:
        raise TokenExpired from exc
    except JWTError as exc:
        raise TokenInvalid from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenInvalid("Token sin sujeto ('sub') válido") from exc

    user = await session.get(Usuario, user_id)
    if user is None:
        raise TokenInvalid("Usuario del token inexistente")

    if user.estado == "BLOQUEADO":
        raise Unauthorized("Cuenta bloqueada por el administrador", code="ACCOUNT_BLOCKED")
    if user.estado == "PENDIENTE_ACTIVACION":
        raise Unauthorized("Cuenta pendiente de activación", code="ACCOUNT_PENDING_ACTIVATION")
    if user.estado == "EXPIRADO":
        raise Unauthorized("Cuenta expirada. Contacte al administrador.", code="ACCOUNT_EXPIRED")

    return user


CurrentUser = Annotated[Usuario, Depends(get_current_user)]


class RequirePermission:
    """
    Dependencia de endpoint: exige un permiso RBAC específico.

    Uso:
        @router.get("/clientes")
        async def listar(user: CurrentUser = Depends(RequirePermission("CLIENTES_VER"))):
            ...

    El permiso se evalúa contra la BD (usuario → empleado → tareas VIGENTES
    → permisos concedidos). Sin permiso → 403 PERMISSION_DENIED.
    """

    def __init__(self, codigo: str) -> None:
        self.codigo = codigo

    async def __call__(self, user: CurrentUser, session: SessionDep) -> Usuario:
        if not await has_permission(session, user.id, self.codigo):
            raise PermissionDenied(action=f"la operación requerida (permiso '{self.codigo}')")
        return user
