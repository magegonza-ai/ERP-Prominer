"""
Endpoints de autenticación (ETAPA 2).

POST /auth/login   → valida credenciales (bcrypt + 2FA opcional) y emite
                     access/refresh tokens, registrando la sesión en la
                     tabla `sesion`.
POST /auth/refresh → rota el refresh token (uno nuevo por uso) y emite un
                     nuevo access token; el reuso de un token ya rotado
                     revoca la sesión completa (detección de robo).
GET  /auth/me      → usuario autenticado con sus permisos RBAC efectivos.

Anti-abuso en login (config `MAX_FAILED_LOGIN_ATTEMPTS` /
`ACCOUNT_LOCKOUT_DURATION_MINUTES`):
- contraseña incorrecta → incrementa `intentos_fallidos`;
- al alcanzar el máximo → `bloqueado_hasta` en el futuro y 401 ACCOUNT_LOCKED;
- login exitoso → `intentos_fallidos = 0`, `bloqueado_hasta = None` y
  `ultimo_acceso = ahora`.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from jose.exceptions import ExpiredSignatureError, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# noqa en TC001: FastAPI resuelve estas anotaciones en runtime al registrar
# las rutas (Depends/Annotated), no pueden vivir en TYPE_CHECKING.
from app.api.deps import CurrentUser, SessionDep  # noqa: TC001
from app.config import settings
from app.core.exceptions import (
    AccountLocked,
    InvalidCredentials,
    TokenExpired,
    TokenInvalid,
    TOTPInvalid,
    Unauthorized,
)
from app.core.permissions import get_user_permissions
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    generate_session_token_hash,
    verify_password,
    verify_totp,
)
from app.models import Sesion, Usuario
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UsuarioActualResponse

router = APIRouter(tags=["Autenticación"])


# ============================================================
# UTILIDADES
# ============================================================


def _ip_limpia(ip: str | None) -> str | None:
    """Normaliza la IP para las columnas INET; descarta valores no válidos
    (por ejemplo el host sintético del TestClient: 'testclient')."""
    if not ip:
        return None
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def _ip_cliente(request: Request) -> str | None:
    return _ip_limpia(request.client.host if request.client else None)


def _validar_estado_cuenta(user: Usuario) -> None:
    """401 según el estado de la cuenta (siempre tras validar la contraseña,
    para no revelar el estado de una cuenta a un desconocido)."""
    if user.estado == "BLOQUEADO":
        raise Unauthorized("Cuenta bloqueada por el administrador", code="ACCOUNT_BLOCKED")
    if user.estado == "PENDIENTE_ACTIVACION":
        raise Unauthorized("Cuenta pendiente de activación", code="ACCOUNT_PENDING_ACTIVATION")
    if user.estado == "EXPIRADO":
        raise Unauthorized("Cuenta expirada. Contacte al administrador.", code="ACCOUNT_EXPIRED")


async def _emitir_tokens(session: AsyncSession, request: Request, user: Usuario) -> TokenResponse:
    """Marca el login exitoso, crea la sesión (refresh token hasheado) y
    devuelve el par de tokens."""
    user.intentos_fallidos = 0
    user.bloqueado_hasta = None
    user.ultimo_acceso = datetime.now(UTC)

    session_id = uuid.uuid4()
    refresh_token = create_refresh_token(user.id, session_id)
    access_token = create_access_token(user.id, user.username, user.empleado_id)

    ip = _ip_cliente(request)
    sesion = Sesion(
        id=session_id,
        usuario_id=user.id,
        token_hash=generate_session_token_hash(refresh_token),
        user_agent=request.headers.get("user-agent"),
        ip_inicio=ip,
        ip_ultima=ip,
        expira_en=datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    session.add(sesion)
    await session.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ============================================================
# ENDPOINTS
# ============================================================


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Inicio de sesión",
    description=(
        "Valida credenciales (bcrypt) y, si la cuenta lo requiere, un código "
        "TOTP. Devuelve access token (15 min) y refresh token (7 días)."
    ),
)
async def login(body: LoginRequest, request: Request, session: SessionDep) -> TokenResponse:
    result = await session.execute(select(Usuario).where(Usuario.username == body.username))
    user = result.scalar_one_or_none()

    # Usuario inexistente y contraseña incorrecta producen la MISMA respuesta
    # (evita enumeración de usuarios).
    if user is None:
        raise InvalidCredentials

    ahora = datetime.now(UTC)
    if user.bloqueado_hasta is not None and user.bloqueado_hasta > ahora:
        restantes = int((user.bloqueado_hasta - ahora).total_seconds() // 60) + 1
        raise AccountLocked(minutes=restantes)

    if not verify_password(body.password, user.password_hash):
        user.intentos_fallidos = (user.intentos_fallidos or 0) + 1
        if user.intentos_fallidos >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            user.bloqueado_hasta = ahora + timedelta(minutes=settings.ACCOUNT_LOCKOUT_DURATION_MINUTES)
        await session.commit()
        raise InvalidCredentials

    _validar_estado_cuenta(user)

    if user.totp_activado:
        if not body.totp_code:
            raise TOTPInvalid("Su cuenta requiere código de verificación (2FA)")
        if not verify_totp(user.totp_secret or "", body.totp_code):
            raise TOTPInvalid

    return await _emitir_tokens(session, request, user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Renovar tokens",
    description=(
        "Intercambia un refresh token válido por un nuevo par de tokens "
        "(rotación). El reuso de un refresh token ya rotado revoca la sesión."
    ),
)
async def refresh(body: RefreshRequest, request: Request, session: SessionDep) -> TokenResponse:
    try:
        payload = decode_refresh_token(body.refresh_token)
    except ExpiredSignatureError as exc:
        raise TokenExpired("Refresh token expirado. Inicie sesión nuevamente.") from exc
    except JWTError as exc:
        raise TokenInvalid from exc

    try:
        user_id = uuid.UUID(payload["sub"])
        session_id = uuid.UUID(payload["session_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenInvalid("Refresh token sin claims requeridos") from exc

    sesion = await session.get(Sesion, session_id)
    if sesion is None or sesion.usuario_id != user_id:
        raise TokenInvalid("Sesión inválida")
    if sesion.revocada:
        raise TokenInvalid("Sesión revocada. Inicie sesión nuevamente.")
    if sesion.expira_en is not None and sesion.expira_en < datetime.now(UTC):
        raise TokenExpired("Sesión expirada. Inicie sesión nuevamente.")
    if sesion.token_hash != generate_session_token_hash(body.refresh_token):
        # Reuso de un refresh token ya rotado: posible robo → revocar la
        # sesión completa (todos los tokens dejan de servir).
        sesion.revocada = True
        sesion.revocada_en = datetime.now(UTC)
        await session.commit()
        raise TokenInvalid("Refresh token ya utilizado; la sesión fue revocada")

    user = await session.get(Usuario, user_id)
    if user is None:
        raise TokenInvalid("Usuario de la sesión inexistente")
    _validar_estado_cuenta(user)

    # Rotación: nuevo refresh token con el mismo session_id.
    refresh_token = create_refresh_token(user.id, session_id)
    sesion.token_hash = generate_session_token_hash(refresh_token)
    sesion.ultima_actividad = datetime.now(UTC)
    sesion.ip_ultima = _ip_cliente(request)

    access_token = create_access_token(user.id, user.username, user.empleado_id)
    await session.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get(
    "/me",
    response_model=UsuarioActualResponse,
    summary="Usuario autenticado",
    description="Devuelve el usuario del token Bearer con sus permisos RBAC efectivos.",
)
async def me(user: CurrentUser, session: SessionDep) -> UsuarioActualResponse:
    permisos = await get_user_permissions(session, user.id)
    return UsuarioActualResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        estado=user.estado,
        empleado_id=user.empleado_id,
        requiere_cambio_password=user.requiere_cambio_password,
        totp_activado=user.totp_activado,
        ultimo_acceso=user.ultimo_acceso,
        permisos=permisos,
    )
