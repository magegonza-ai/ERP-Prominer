# Registro de Decisiones de Implementación

Anexo al **documento de análisis (Pasos 1–21)** aprobado del Sistema Web de Gestión,
Valorización y Trazabilidad de Cilindros de Gas para AGAS.

Las decisiones **D1–D15** (requisitos, alcance, stack, catálogos y reglas) se documentaron
durante el análisis y fueron aprobadas en su totalidad. Este anexo registra las decisiones
tomadas durante la **implementación** que ajustan o precisan lo definido en el análisis.

---

## D16 — Versión de Python de desarrollo

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Resuelta / Aprobada por el usuario |
| **Fecha** | 2026-10-08 |
| **Contexto** | El stack definido en el análisis indicaba **Python 3.12**. Al preparar el entorno local se detectó que la única versión instalada en la máquina de desarrollo es **Python 3.14.5**. |
| **Decisión** | Se continúa con **Python 3.14.5**. Motivos: (1) todas las dependencias críticas tienen soporte y wheels para 3.14 (FastAPI 0.142, SQLAlchemy 2.1.4 + greenlet, asyncpg 0.32, bcrypt 5, Alembic 1.20); (2) el backend completo se validó en 3.14 (44 tablas, migraciones Alembic online/offline, ruff, arranque uvicorn); (3) soporte de seguridad hasta 2031 vs. 2028 de 3.12; (4) el código usa características compatibles con ambas versiones. |
| **Impacto** | `pyproject.toml`: `requires-python >= 3.13`; ruff `target-version = py314`; mypy `python_version = 3.14`. El `Dockerfile`/CI fijarán la versión de producción (imagen `python:3.14-slim`). Sin impacto funcional en el resto del stack aprobado. |
| **Alternativas descartadas** | Instalar Python 3.12 solo por fidelidad al análisis: requería re-crear `.venv` y revalidar todo sin beneficio funcional. |

---

## D17 — Driver síncrono para Alembic

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada (técnica, documentada para gobernanza) |
| **Fecha** | 2026-10-08 |
| **Contexto** | El entorno `alembic/env.py` ejecuta migraciones online con un driver síncrono; `asyncpg` es asíncrono. |
| **Decisión** | Se agregó **`psycopg[binary]>=3.1`** como dependencia base, exclusivamente para Alembic (la aplicación en runtime sigue usando `asyncpg`). |

---

## D18 — Hashing de contraseñas

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada (técnica, documentada para gobernanza) |
| **Fecha** | 2026-10-08 |
| **Contexto** | `passlib 1.7.4` (sin mantenimiento) es incompatible con `bcrypt >= 4.1` (error `bcrypt.__about__`). El pip actual instaló `bcrypt 5.0`. |
| **Decisión** | Se eliminó `passlib` y se usa **`bcrypt` directamente** en `app/core/security.py` (rounds = 12 configurable). Se mantiene la política de contraseña y se agrega límite de 72 bytes (bcrypt). |

---

## D19 — Entorno Docker local (WSL2 pendiente de reinicio)

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada (instalación); ⏳ **pendiente reinicio de Windows** para activar WSL2 |
| **Fecha** | 2026-10-08 |
| **Contexto** | Docker no estaba instalado. Se instaló **Docker Desktop 4.94.0** (winget) y se habilitó **WSL2 / Plataforma de Máquina Virtual** (`wsl --install --no-distribution`). Las características de Windows exigen **reiniciar el sistema** para activarse. |
| **Decisión** | Documentar que la **prueba real de `docker compose up`** (Postgres 16 + Redis + MinIO + API) quedó pendiente del reinicio. La infraestructura Docker (Dockerfile, 3 compose, nginx) ya está versionada y validada estáticamente (YAML OK, llaves JWT generadas y verificadas). |
| **Pasos post-reinicio** | 1) Abrir Docker Desktop y aceptar el acuerdo. 2) `docker --version` y `docker info`. 3) `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build`. |
| **Impacto** | Sin impacto en código. Habilita el entorno de ejecución local reproduciendo infraestructura de producción. |

---

## D20 — Sustitución de MinIO por SeaweedFS (almacén de objetos)

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada y validada (2026-10-08) |
| **Fecha** | 2026-10-08 |
| **Contexto** | El stack aprobado contemplaba **MinIO** como almacén de objetos S3. El fabricante **archivó el proyecto open-source de MinIO Server** (aviso oficial en `dl.min.io`: *"The open-source MinIO Server, MinIO Client (mc) and MinIO KES projects are archived and no longer maintained"*). Consecuencias verificadas: Docker Hub `minio/minio` → 404; Quay `quay.io/minio/minio` → requiere autenticación (repo migrado a **AIStor**); la nueva imagen `quay.io/minio/aistor/minio` **requiere licencia comercial** (free tier con registro manual); `dl.min.io` ya no sirve binarios (HTTP 410) y GitHub Releases no publica binarios Linux. |
| **Decisión** | Sustituir MinIO por **SeaweedFS** como servidor S3-compatible. Motivos: (1) licencia **Apache-2.0** (sin fricción de licencias en dev/CI); (2) proyecto **activo** con imagen oficial en Docker Hub (`chrislusf/seaweedfs`, validada v4.48); (3) **S3-compatible** → la configuración del backend (`MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET`) permanece sin cambios de código; (4) un solo contenedor y arranque simple (`weed server -s3`). Se descartó Garage (exige archivo de config + pasos de *layout* adicionales) y AIStor (licenciado). |
| **Detalles técnicos** | El gateway S3 de SeaweedFS escucha en el puerto **8333** interno (el flag `-s3.port` no aplica dentro de `weed server`); el host lo expone como **9000** (`9000:8333`). Interfaz web Filer/Status en **8888**. Servicio compose renombrado a `seaweedfs`; `MINIO_ENDPOINT=seaweedfs:8333` en el API. Volumen `s3data`. En dev se aceptan credenciales arbitrarias (default de SeaweedFS); en **producción** debe montarse un archivo `-s3.config` con usuarios/recurso S3 reales (pendiente cuando se construyan los módulos de adjuntos). |
| **Impacto** | Infraestructura: sustituye la imagen MinIO. Código backend: ninguno (config S3 genérica). Documentación y compose actualizados. |

---

## D21 — Puerto 5433 para PostgreSQL desde el host

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada y validada (2026-10-08) |
| **Fecha** | 2026-10-08 |
| **Contexto** | En la máquina de desarrollo existe un **PostgreSQL 18 local** (servicio Windows `postgresql-x64-18`) escuchando en `0.0.0.0:5432`, en paralelo con `com.docker.backend` que publica el puerto 5432 del contenedor. Dos listeners en el mismo puerto provocaban que las conexiones desde el host a `localhost:5432` fallaran de forma intermitente con `asyncpg: connection was closed in the middle of operation` (la conexión terminaba en el PostgreSQL local, que no tiene la base/usuario del proyecto). Esto impedía ejecutar los tests y scripts locales contra la base de desarrollo. |
| **Decisión** | Publicar el Postgres del proyecto en el **puerto 5433** del host (`5433:5432` en `docker-compose.yml`), conservando el 5432 **interno** (la API sigue conectándose a `postgres:5432` en la red Docker). `backend/.env` y `backend/.env.example` pasan a `DATABASE_PORT=5433` (solo aplica a procesos del host: tests y scripts locales). README actualizado. |
| **Alternativas descartadas** | (1) Detener el servicio `postgresql-x64-18` local: invasivo, puede pertenecer a otros proyectos. (2) Cambiar el puerto interno del contenedor: rompería la configuración de la red Docker y de producción sin necesidad. |
| **Impacto** | `docker-compose.yml` (mapeo host), `.env`/`.env.example`, README. Producción no se ve afectada (`docker-compose.prod.yml` no publica puerto de PostgreSQL). |

---

## D22 — Triggers de auditoría en bases migradas y política de `server_default`

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada y validada (2026-10-08) |
| **Fecha** | 2026-10-08 |
| **Contexto** | La primera suite de tests (pytest + PostgreSQL real) reveló tres defectos que la validación estática (`alembic --sql`, importación de mappers) no podía detectar: **(1)** `0001_initial` creaba las tablas pero **no los triggers de auditoría** → una base migrada tenía **0 triggers** (vs. 36 creados por `create_all`), es decir, **sin trazabilidad de auditoría**; **(2)** `create_all` no aplicaba `server_default` en `auditoria.id` → el trigger fallaba con `NOT NULL violation` al registrar el INSERT; **(3)** `env.py` usaba `compare_server_default=True` mientras los `server_default` existían solo en la migración → un futuro `alembic revision --autogenerate` propondría **borrar** todos los defaults de la BD. |
| **Decisión** | **(a)** Alinear el modelo con la migración: `server_default=gen_random_uuid()` en `BaseModel.id` y `Auditoria.id`, `server_default=now()` en `TimestampMixin.fecha_creacion` y `Auditoria.fecha_hora` (los defaults uniformes; los defaults puntuales por tabla —`estado`, escalares— se mantienen exclusivamente en las migraciones). **(b)** Nueva migración **`0002_audit_triggers`** que crea las 36 funciones + triggers a partir de `app.models.base.generate_audit_trigger` (misma fuente que usa `create_all`), una sentencia por `op.execute` (asyncpg/psycopg no aceptan múltiples comandos en una sentencia preparada). **(c)** `base.py` expone `AUDITED_TABLES` (registro único de tablas auditadas, usado por la migración). **(d)** `env.py`: `compare_server_default=False` — la autoridad de los defaults de BD son las migraciones; los modelos expresan defaults en Python. |
| **Validación** | `alembic upgrade head` en BD dev → 36 triggers + `alembic_version=0002_audit_triggers`; tests: `test_triggers_de_auditoria_creados` y `test_trigger_auditoria_registra_insert_y_delete` (INSERT/DELETE auditados end-to-end) ✅. |
| **Impacto** | Modelos (`base.py`, `audit.py`), migración 0002, `env.py`, tests. Cubre todo entorno desplegado con Alembic (dev, CI, producción). |

---

## D23 — Autenticación JWT: claim `jti`, rotación de refresh y bloqueo por intentos

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada y validada (2026-10-08) |
| **Fecha** | 2026-10-08 |
| **Contexto** | Al implementar `POST /auth/refresh` con rotación de tokens, los tests de la ETAPA 2 demostraron que **dos JWT emitidos dentro del mismo segundo eran byte-idénticos**: `iat` tiene resolución de segundos y el resto del payload (sub, type, iss, aud, exp) era igual → el "nuevo" refresh token era idéntico al anterior, `sesion.token_hash` no cambiaba y el **reuso del token viejo no se detectaba** (rotación inútil). |
| **Decisión** | **(a)** Claim **`jti`** (UUID v4) en access y refresh tokens → cada emisión es única aunque ocurra en el mismo segundo; la rotación invalida materialmente el token anterior. **(b)** Cada refresh rota el par: `sesion.token_hash = sha256(refresh)` por uso; el **reuso** de un token ya rotado revoca la sesión completa (detección de robo) y además invalida el token vigente. **(c)** Cadena de validación del access token en `get_current_user`: Bearer → firma RS256 + `iss`/`aud` → `type=access` → `sub` → usuario existe → estado de cuenta (`BLOQUEADO`/`PENDIENTE_ACTIVACION`/`EXPIRADO` → 401 con código propio). **(d)** Anti-abuso de login: contador `intentos_fallidos` con `MAX_FAILED_LOGIN_ATTEMPTS=5` → `bloqueado_hasta` (+`ACCOUNT_LOCKOUT_DURATION_MINUTES=30`) → `401 ACCOUNT_LOCKED` incluso con contraseña correcta; login exitoso limpia contadores y marca `ultimo_acceso`. Respuesta idéntica para usuario inexistente y contraseña incorrecta (sin enumeración). |
| **Validación** | 33 tests de `tests/test_auth.py` (login, rotación, reuso/revocación, estados, TOTP, permisos RBAC, defensas de claims) + E2E contra el stack dev: login → `/me` → refresh → reuso del viejo refresh → `401 TOKEN_INVALID` ✅. |
| **Impacto** | `app/core/security.py` (claim `jti` adicional, compatible con decodificadores que lo ignoran), `app/api/deps.py`, `app/api/v1/endpoints/auth.py`, `app/schemas/auth.py`, tests. |