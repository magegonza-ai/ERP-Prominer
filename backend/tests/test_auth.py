"""
Tests de autenticación (ETAPA 2): login, refresh con rotación, /me,
bloqueo por intentos fallidos, 2FA (TOTP) y autorización RBAC.

Los usuarios de prueba usan nombres únicos (uuid) y permanecen en la base
`agas_cilindros_test` (base desechable); cada test los consulta siempre por
su propio id/username. El esquema lo garantiza el fixture compartido
`db_engine` (ver conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from app.api.deps import RequirePermission
from app.config import settings
from app.core.exceptions import PermissionDenied
from app.core.permissions import get_user_permissions, has_permission, require_permission
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    generate_session_token_hash,
    generate_totp_secret,
    hash_password,
)
from app.main import app
from app.models import (
    Area,
    Empleado,
    EmpleadoTarea,
    Permiso,
    Sesion,
    Tarea,
    TareaPermiso,
    Usuario,
)

pytestmark = pytest.mark.asyncio

CLAVE = "Admin2026!"  # política: mayúscula, minúscula, dígito y especial


@pytest.fixture(autouse=True)
def _hash_rapido(monkeypatch):
    """Bcrypt con rondas mínimas: la lógica es la misma, la suite más veloz."""
    monkeypatch.setattr(settings, "PASSWORD_HASH_ROUNDS", 4)


# ============================================================
# HELPERS
# ============================================================


def _prefijo() -> str:
    return uuid.uuid4().hex[:12]


def _cabecera(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _codigo(resp) -> str:
    return resp.json()["detail"]["code"]


async def _crear_usuario(session_factory, *, estado: str = "ACTIVO", **extras) -> tuple[Usuario, str]:
    p = _prefijo()
    user = Usuario(
        username=f"usr_{p}",
        email=f"usr_{p}@agas.test",
        password_hash=hash_password(CLAVE),
        estado=estado,
        requiere_cambio_password=False,
        **extras,
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user, CLAVE


async def _crear_cadena_permisos(session_factory) -> tuple[Usuario, str]:
    """
    Crea la cadena completa usuario → empleado → tarea (VIGENTE) → permiso
    y devuelve (usuario, codigo_permiso).
    """
    p = _prefijo()
    codigo_permiso = f"PRUEBA_{p[:10]}"
    async with session_factory() as session:
        area = Area(codigo=f"A{p[:8]}", nombre="Área de pruebas")
        session.add(area)
        await session.flush()

        empleado = Empleado(
            rut=f"9{p[:8]}",
            nombres="Ana",
            apellidos="Prueba",
            cargo="Operador",
            area_id=area.id,
            correo=f"emp_{p}@agas.test",
            fecha_ingreso=date(2026, 1, 1),
        )
        session.add(empleado)
        await session.flush()

        tarea = Tarea(codigo=f"T{p[:8]}", nombre="Tarea de pruebas", categoria="OPERATIVO")
        permiso = Permiso(codigo=codigo_permiso, nombre="Permiso de pruebas")
        session.add_all([tarea, permiso])
        await session.flush()
        session.add(TareaPermiso(tarea_id=tarea.id, permiso_id=permiso.id, concedido=True))

        user = Usuario(
            username=f"usr_{p}",
            email=f"usr_{p}@agas.test",
            password_hash=hash_password(CLAVE),
            estado="ACTIVO",
            requiere_cambio_password=False,
            empleado_id=empleado.id,
        )
        session.add(user)
        await session.flush()

        session.add(
            EmpleadoTarea(
                empleado_id=empleado.id,
                tarea_id=tarea.id,
                usuario_asigno_id=user.id,
            )
        )
        await session.commit()
        await session.refresh(user)
    return user, codigo_permiso


def _login(client: TestClient, username: str, password: str, totp_code: str | None = None):
    payload = {"username": username, "password": password}
    if totp_code is not None:
        payload["totp_code"] = totp_code
    return client.post("/api/v1/auth/login", json=payload)


# ============================================================
# LOGIN
# ============================================================


async def test_login_emite_tokens_y_registra_sesion(session_factory) -> None:
    user, clave = await _crear_usuario(session_factory, intentos_fallidos=3)

    with TestClient(app) as client:
        resp = _login(client, user.username, clave)

    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60

    payload = decode_access_token(body["access_token"])
    assert payload["sub"] == str(user.id)
    assert payload["username"] == user.username
    assert payload["type"] == "access"

    refresf = decode_refresh_token(body["refresh_token"])
    assert refresf["type"] == "refresh"
    session_id = uuid.UUID(refresf["session_id"])

    async with session_factory() as s:
        sesion = await s.get(Sesion, session_id)
        assert sesion is not None
        assert sesion.usuario_id == user.id
        assert sesion.token_hash == generate_session_token_hash(body["refresh_token"])
        assert sesion.expira_en > datetime.now(UTC)
        assert sesion.revocada is False

        actual = await s.get(Usuario, user.id)
        assert actual.intentos_fallidos == 0
        assert actual.bloqueado_hasta is None
        assert actual.ultimo_acceso is not None


async def test_login_password_incorrecta_incrementa_intentos(session_factory) -> None:
    user, _ = await _crear_usuario(session_factory)

    with TestClient(app) as client:
        resp = _login(client, user.username, "Pass Incorrecta 7!")

    assert resp.status_code == 401
    detalle = resp.json()["detail"]
    assert detalle["code"] == "INVALID_CREDENTIALS"
    assert set(detalle) >= {"code", "message"}

    async with session_factory() as s:
        actual = await s.get(Usuario, user.id)
        assert actual.intentos_fallidos == 1
        assert actual.bloqueado_hasta is None


async def test_login_no_revela_si_el_usuario_existe(session_factory) -> None:
    user, _ = await _crear_usuario(session_factory)

    with TestClient(app) as client:
        r_usuario = _login(client, user.username, "Pass Incorrecta 7!")
        r_fantasma = _login(client, "usuario_que_no_existe", "Pass Incorrecta 7!")

    assert r_usuario.status_code == 401
    assert r_fantasma.status_code == 401
    # Respuesta idéntica: no se puede adivinar si el username existe.
    assert r_usuario.json() == r_fantasma.json()


@pytest.mark.parametrize(
    ("estado", "codigo_esperado"),
    [
        ("BLOQUEADO", "ACCOUNT_BLOCKED"),
        ("PENDIENTE_ACTIVACION", "ACCOUNT_PENDING_ACTIVATION"),
        ("EXPIRADO", "ACCOUNT_EXPIRED"),
    ],
)
async def test_login_rechaza_cuentas_no_activas(session_factory, estado, codigo_esperado) -> None:
    user, clave = await _crear_usuario(session_factory, estado=estado)

    with TestClient(app) as client:
        resp = _login(client, user.username, clave)

    assert resp.status_code == 401
    assert _codigo(resp) == codigo_esperado


async def test_login_bloquea_tras_intentos_maximos(session_factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "MAX_FAILED_LOGIN_ATTEMPTS", 2)
    user, clave = await _crear_usuario(session_factory)

    with TestClient(app) as client:
        assert _login(client, user.username, "Mala!234567").status_code == 401
        assert _login(client, user.username, "Mala!234567").status_code == 401
        # Se alcanzó el máximo: hasta la contraseña correcta queda rechazada.
        resp = _login(client, user.username, clave)

    assert resp.status_code == 401
    assert _codigo(resp) == "ACCOUNT_LOCKED"

    async with session_factory() as s:
        actual = await s.get(Usuario, user.id)
        assert actual.bloqueado_hasta is not None
        assert actual.bloqueado_hasta > datetime.now(UTC)


async def test_login_totp_requerido_sin_codigo(session_factory) -> None:
    secreto = generate_totp_secret()
    user, clave = await _crear_usuario(session_factory, totp_activado=True, totp_secret=secreto)

    with TestClient(app) as client:
        resp = _login(client, user.username, clave)

    assert resp.status_code == 401
    assert _codigo(resp) == "TOTP_INVALID"


async def test_login_totp_codigo_correcto_emite_tokens(session_factory) -> None:
    secreto = generate_totp_secret()
    user, clave = await _crear_usuario(session_factory, totp_activado=True, totp_secret=secreto)
    codigo = pyotp.TOTP(secreto, digits=settings.TOTP_DIGITS, interval=settings.TOTP_INTERVAL).now()

    with TestClient(app) as client:
        resp = _login(client, user.username, clave, totp_code=codigo)

    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_login_totp_codigo_incorrecto(session_factory) -> None:
    secreto = generate_totp_secret()
    user, clave = await _crear_usuario(session_factory, totp_activado=True, totp_secret=secreto)
    real = pyotp.TOTP(secreto, digits=settings.TOTP_DIGITS, interval=settings.TOTP_INTERVAL).now()
    falso = f"{(int(real) + 1) % 1_000_000:06d}"  # garantizadamente distinto del actual

    with TestClient(app) as client:
        resp = _login(client, user.username, clave, totp_code=falso)

    assert resp.status_code == 401
    assert _codigo(resp) == "TOTP_INVALID"


# ============================================================
# REFRESH
# ============================================================


async def test_refresh_rota_tokens(session_factory) -> None:
    user, clave = await _crear_usuario(session_factory)

    with TestClient(app) as client:
        login = _login(client, user.username, clave).json()
        refrescado = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})

    assert refrescado.status_code == 200
    body = refrescado.json()
    assert body["refresh_token"] != login["refresh_token"]
    assert body["access_token"] != login["access_token"]
    assert body["expires_in"] == settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60

    session_id = uuid.UUID(decode_refresh_token(login["refresh_token"])["session_id"])
    async with session_factory() as s:
        sesion = await s.get(Sesion, session_id)
        assert sesion.token_hash == generate_session_token_hash(body["refresh_token"])
        assert sesion.ultima_actividad >= sesion.iniciada_en


async def test_refresh_reuso_de_token_antiguo_revoca_sesion(session_factory) -> None:
    user, clave = await _crear_usuario(session_factory)

    with TestClient(app) as client:
        login = _login(client, user.username, clave).json()
        viejo = login["refresh_token"]
        rotado = client.post("/api/v1/auth/refresh", json={"refresh_token": viejo})
        assert rotado.status_code == 200

        # Reuso del token ya rotado (posible robo) → revoca la sesión...
        resp_reuso = client.post("/api/v1/auth/refresh", json={"refresh_token": viejo})
        # ...y el token vigente también queda invalidado.
        resp_vigente = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": rotado.json()["refresh_token"]}
        )

    assert resp_reuso.status_code == 401
    assert _codigo(resp_reuso) == "TOKEN_INVALID"
    assert resp_vigente.status_code == 401

    session_id = uuid.UUID(decode_refresh_token(viejo)["session_id"])
    async with session_factory() as s:
        sesion = await s.get(Sesion, session_id)
        assert sesion.revocada is True
        assert sesion.revocada_en is not None


async def test_refresh_rechaza_access_token(session_factory) -> None:
    user, clave = await _crear_usuario(session_factory)

    with TestClient(app) as client:
        login = _login(client, user.username, clave).json()
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": login["access_token"]})

    assert resp.status_code == 401
    assert _codigo(resp) == "TOKEN_INVALID"


async def test_refresh_token_basura() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "esto-no-es-un-jwt"})

    assert resp.status_code == 401
    assert _codigo(resp) == "TOKEN_INVALID"


async def test_refresh_sesion_inexistente(session_factory) -> None:
    user, _ = await _crear_usuario(session_factory)
    token = create_refresh_token(user.id, uuid.uuid4())

    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token})

    assert resp.status_code == 401
    assert _codigo(resp) == "TOKEN_INVALID"


async def test_refresh_sesion_expirada(session_factory) -> None:
    user, clave = await _crear_usuario(session_factory)

    with TestClient(app) as client:
        login = _login(client, user.username, clave).json()
        session_id = uuid.UUID(decode_refresh_token(login["refresh_token"])["session_id"])
        async with session_factory() as s:
            sesion = await s.get(Sesion, session_id)
            sesion.expira_en = datetime.now(UTC) - timedelta(minutes=1)
            await s.commit()

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})

    assert resp.status_code == 401
    assert _codigo(resp) == "TOKEN_EXPIRED"


async def test_refresh_sesion_revocada(session_factory) -> None:
    user, clave = await _crear_usuario(session_factory)

    with TestClient(app) as client:
        login = _login(client, user.username, clave).json()
        session_id = uuid.UUID(decode_refresh_token(login["refresh_token"])["session_id"])
        async with session_factory() as s:
            sesion = await s.get(Sesion, session_id)
            sesion.revocada = True
            await s.commit()

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})

    assert resp.status_code == 401
    assert _codigo(resp) == "TOKEN_INVALID"


async def test_refresh_usuario_bloqueado(session_factory) -> None:
    user, clave = await _crear_usuario(session_factory)

    with TestClient(app) as client:
        login = _login(client, user.username, clave).json()
        async with session_factory() as s:
            actual = await s.get(Usuario, user.id)
            actual.estado = "BLOQUEADO"
            await s.commit()

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})

    assert resp.status_code == 401
    assert _codigo(resp) == "ACCOUNT_BLOCKED"


# ============================================================
# /me
# ============================================================


async def test_me_sin_autorizacion() -> None:
    with TestClient(app) as client:
        resp_sin = client.get("/api/v1/auth/me")
        resp_basic = client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"})

    assert resp_sin.status_code == 401
    assert _codigo(resp_sin) == "UNAUTHORIZED"
    assert resp_basic.status_code == 401
    assert _codigo(resp_basic) == "UNAUTHORIZED"


async def test_me_token_basura_y_expirado(session_factory) -> None:
    user, _ = await _crear_usuario(session_factory)

    with TestClient(app) as client:
        basura = client.get("/api/v1/auth/me", headers=_cabecera("esto-no-es-un-jwt"))
        expirado = client.get(
            "/api/v1/auth/me",
            headers=_cabecera(create_access_token(user.id, user.username, expires_minutes=-1)),
        )

    assert basura.status_code == 401
    assert _codigo(basura) == "TOKEN_INVALID"
    assert expirado.status_code == 401
    assert _codigo(expirado) == "TOKEN_EXPIRED"


async def test_me_rechaza_token_de_otro_algoritmo(session_factory) -> None:
    user, _ = await _crear_usuario(session_factory)
    ahora = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "type": "access",
        "iat": ahora,
        "exp": ahora + 300,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    # Firmado con HS256 y un secreto compartido: el endpoint exige RS256.
    token = jose_jwt.encode(payload, "secreto-compartido", algorithm="HS256")

    with TestClient(app) as client:
        resp = client.get("/api/v1/auth/me", headers=_cabecera(token))

    assert resp.status_code == 401
    assert _codigo(resp) == "TOKEN_INVALID"


async def test_me_devuelve_usuario_sin_permisos(session_factory) -> None:
    user, _ = await _crear_usuario(session_factory)
    token = create_access_token(user.id, user.username)

    with TestClient(app) as client:
        resp = client.get("/api/v1/auth/me", headers=_cabecera(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(user.id)
    assert body["username"] == user.username
    assert body["email"] == user.email
    assert body["estado"] == "ACTIVO"
    assert body["empleado_id"] is None
    assert body["requiere_cambio_password"] is False
    assert body["totp_activado"] is False
    assert body["ultimo_acceso"] is None  # nunca inició sesión
    assert body["permisos"] == []  # sin cadena empleado→tareas→permisos


@pytest.mark.parametrize(
    ("estado", "codigo_esperado"),
    [
        ("BLOQUEADO", "ACCOUNT_BLOCKED"),
        ("PENDIENTE_ACTIVACION", "ACCOUNT_PENDING_ACTIVATION"),
        ("EXPIRADO", "ACCOUNT_EXPIRED"),
    ],
)
async def test_me_rechaza_cuentas_no_activas(session_factory, estado, codigo_esperado) -> None:
    user, _ = await _crear_usuario(session_factory, estado=estado)
    token = create_access_token(user.id, user.username)

    with TestClient(app) as client:
        resp = client.get("/api/v1/auth/me", headers=_cabecera(token))

    assert resp.status_code == 401
    assert _codigo(resp) == codigo_esperado


async def test_me_incluye_permisos_rbac(session_factory) -> None:
    user, codigo = await _crear_cadena_permisos(session_factory)
    token = create_access_token(user.id, user.username)

    with TestClient(app) as client:
        resp = client.get("/api/v1/auth/me", headers=_cabecera(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["empleado_id"] is not None
    assert body["permisos"] == [codigo]


# ============================================================
# PERMISOS (unidad sobre app.core.permissions y la dependencia)
# ============================================================


async def test_get_user_permissions_y_has_permission(session_factory) -> None:
    user, codigo = await _crear_cadena_permisos(session_factory)
    user_sin, _ = await _crear_usuario(session_factory)

    async with session_factory() as s:
        assert await get_user_permissions(s, user.id) == [codigo]
        assert await has_permission(s, user.id, codigo) is True
        assert await has_permission(s, user.id, "PERMISO_QUE_NO_TIENE") is False
        assert await get_user_permissions(s, user_sin.id) == []


async def test_require_permission_lanza_si_falta(session_factory) -> None:
    user, codigo = await _crear_cadena_permisos(session_factory)
    user_sin, _ = await _crear_usuario(session_factory)

    async with session_factory() as s:
        assert await require_permission(s, user.id, codigo) is None  # no lanza
        with pytest.raises(PermissionDenied, match=codigo):
            await require_permission(s, user_sin.id, codigo)


async def test_dependencia_require_permission_factory(session_factory) -> None:
    user, codigo = await _crear_cadena_permisos(session_factory)
    user_sin, _ = await _crear_usuario(session_factory)
    dep = RequirePermission(codigo)

    async with session_factory() as s:
        resultado = await dep(user, s)
        assert resultado.id == user.id
        with pytest.raises(PermissionDenied, match=codigo):
            await dep(user_sin, s)


# ============================================================
# DEFENSAS DE TOKENS
# ============================================================


def _firmar_rs256(payload: dict) -> str:
    with open(settings.JWT_PRIVATE_KEY_PATH) as f:
        clave_privada = f.read()
    return jose_jwt.encode(payload, clave_privada, algorithm=settings.JWT_ALGORITHM)


async def test_me_token_sin_claim_sub(session_factory) -> None:
    user, _ = await _crear_usuario(session_factory)
    ahora = int(datetime.now(UTC).timestamp())
    token = _firmar_rs256(
        {
            "username": user.username,
            "type": "access",
            "iat": ahora,
            "exp": ahora + 300,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        }
    )

    with TestClient(app) as client:
        resp = client.get("/api/v1/auth/me", headers=_cabecera(token))

    assert resp.status_code == 401
    assert _codigo(resp) == "TOKEN_INVALID"


async def test_me_token_de_usuario_eliminado(session_factory) -> None:
    user, _ = await _crear_usuario(session_factory)
    token = create_access_token(user.id, user.username)

    async with session_factory() as s:
        actual = await s.get(Usuario, user.id)
        await s.delete(actual)
        await s.commit()

    with TestClient(app) as client:
        resp = client.get("/api/v1/auth/me", headers=_cabecera(token))

    assert resp.status_code == 401
    assert _codigo(resp) == "TOKEN_INVALID"


async def test_refresh_jwt_expirado(session_factory) -> None:
    user, _ = await _crear_usuario(session_factory)
    token = create_refresh_token(user.id, uuid.uuid4(), expires_days=-1)

    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token})

    assert resp.status_code == 401
    assert _codigo(resp) == "TOKEN_EXPIRED"


async def test_refresh_token_sin_session_id(session_factory) -> None:
    user, _ = await _crear_usuario(session_factory)
    ahora = int(datetime.now(UTC).timestamp())
    token = _firmar_rs256(
        {
            "sub": str(user.id),
            "type": "refresh",
            "iat": ahora,
            "exp": ahora + 3600,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        }
    )

    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token})

    assert resp.status_code == 401
    assert _codigo(resp) == "TOKEN_INVALID"
