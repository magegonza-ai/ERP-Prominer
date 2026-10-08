"""
Dependencias compartidas de la API (ETAPA 2).

- SessionDep: sesión de SQLAlchemy inyectada por `app.database.get_db`.
- get_current_user / CurrentUser: resuelve el usuario del token Bearer
  y valida su estado de cuenta antes de entrar a cualquier endpoint.
- RequirePermission: factoría de dependencias para exigir un permiso RBAC
  (catálogo sembrado en `scripts/seed_data.py`, motor en
  `app.core.permissions`).
- RequireTaskPermission: exige tarea (dominio) + permiso (acción) juntos.
- obtener_o_404 / verificar_unico: utilidades CRUD compartidas por los
  endpoints (404 NOT_FOUND y 409 DUPLICATE_VALUE consistentes).

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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicateValue,
    NotFound,
    PermissionDenied,
    TokenExpired,
    TokenInvalid,
    Unauthorized,
)
from app.core.permissions import has_permission, has_task
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


class RequireTaskPermission:
    """
    Dependencia de endpoint: exige una tarea RBAC vigente (dominio) Y un
    permiso de acción (matriz agregada).

    El RBAC del sistema separa **dominio** (tarea: TAREA_28 administrar
    usuarios, TAREA_29 catálogos, TAREA_30 auditoría) de **acción**
    (PERM_01 consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular,
    PERM_09 asignar, PERM_10 reasignar). Un usuario sin la tarea del dominio
    no pasa aunque agregue el permiso por otra tarea.

    Uso:
        @router.post("/usuarios")
        async def crear(user=Depends(RequireTaskPermission("TAREA_28", "PERM_02"))):
            ...

    Sin la tarea → 403 (mención a la tarea); sin el permiso → 403 (mención
    al permiso). Ambos con código PERMISSION_DENIED.
    """

    def __init__(self, tarea: str, permiso: str) -> None:
        self.tarea = tarea
        self.permiso = permiso

    async def __call__(self, user: CurrentUser, session: SessionDep) -> Usuario:
        if not await has_task(session, user.id, self.tarea):
            raise PermissionDenied(action=f"la operación requerida (tarea '{self.tarea}')")
        if not await has_permission(session, user.id, self.permiso):
            raise PermissionDenied(action=f"la operación requerida (permiso '{self.permiso}')")
        return user


# ============================================================
# HELPERS DE ENTIDADES (usados por todos los endpoints CRUD)
# ============================================================


async def obtener_o_404(
    session: AsyncSession,
    model,
    identifier: uuid.UUID,
    entidad: str = "Registro",
):
    """Carga por PK o lanza 404 NOT_FOUND con el nombre de la entidad."""
    obj = await session.get(model, identifier)
    if obj is None:
        raise NotFound(entidad, identifier)
    return obj


async def verificar_unico(
    session: AsyncSession,
    model,
    campo: str,
    valor,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Lanza 409 DUPLICATE_VALUE si `valor` ya existe en `model.campo`.

    `exclude_id` excluye un registro propio (necesario en actualizaciones
    para no chocar contra el mismo registro).
    """
    if valor is None:
        return
    # PK genérica: `id` en la mayoría de modelos, `clave` en `parametro`.
    pk = model.__mapper__.primary_key[0]
    stmt = select(pk).where(getattr(model, campo) == valor)
    if exclude_id is not None:
        stmt = stmt.where(pk != exclude_id)
    if (await session.execute(stmt.limit(1))).scalar_one_or_none() is not None:
        raise DuplicateValue(campo, str(valor))


def ip_a_cadena(valor) -> str | None:
    """Normaliza valores INET del driver (str o ipaddress) a `str` para las
    respuestas JSON de sesiones/auditoría. `None` se propaga."""
    return None if valor is None else str(valor)
