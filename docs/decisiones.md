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

---

## D24 — Subetapa 2.1: CRUD con matriz RBAC tarea × permiso

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada y validada (2026-10-08) |
| **Fecha** | 2026-10-08 |
| **Contexto** | Tras el núcleo de autenticación (D23) faltaba el CRUD operativo de usuarios, empleados, tareas, permisos, sesiones y bitácora de auditoría bajo autorización. `has_permission` es **agregado**: consulta los permisos de *todas* las tareas vigentes del usuario. Exigir solo el permiso permitiría que un administrador de catálogos (TAREA_29) creara usuarios si la matriz global concedía el mismo código en su dominio, y exigir solo la tarea no distingue acciones (leer vs. eliminar). |
| **Decisión** | **(a)** Guard **`RequireTaskPermission(tarea, permiso)`** = tarea VIGENTE del empleado (**dominio**) **Y** permiso agregado (**acción**); instancias `_LEER/_CREAR/_MODIFICAR/_ANULAR/_ASIGNAR/_REVOCAR` por endpoint. Matriz: **TAREA_28** usuarios/empleados/sesiones (7 acciones, incluye PERM_09/10 asignar/reasignar), **TAREA_29** catálogos tareas/permisos (5), **TAREA_30** auditoría (solo lectura/anulación). **(b)** `DELETE /usuarios/{id}` = **anulación lógica** (estado := `BLOQUEADO` + revocación de sesiones; `ck_usuario_estado` no admite ANULADO) y `DELETE /empleados/{id}` = **baja** (`RETIRADO`, único estado de salida que permite el CK); toda transición ≠ `ACTIVO` revoca sesiones vivas; transición al mismo estado → `409 INVALID_STATE_TRANSITION`. **(c)** Catálogos con historial (tareas/permisos): `DELETE` físico solo con cero referencias, si no → `409 HAS_HISTORY` (alternativa: inactivar); estado de tarea `ACTIVA/INACTIVA` validado en código (sin CK). **(d)** Estados cerrados con `Literal` en esquemas → `422` con el formato del proyecto; `verificar_unico(..., exclude_id)` para PATCH sin colisión propia; `ip_a_cadena()` normaliza columnas `INET`; listados paginados con `Pagina[T]` (genéricos PEP 695). **(e)** **`null` en PATCH = sin cambio** (contrato de los esquemas `*Update`): los nulos se filtran antes de validar y un PATCH solo de nulos → `400`; antes producían `setattr(None)` → error 500 en columnas NOT NULL. **(f)** `scripts/create_superadmin.py` asigna (o reactiva) **TAREA_28/29/30** al empleado del superadmin en el alta *y* en re-ejecuciones idempotentes: sin tareas el RBAC devuelve 403 en todos los módulos (decisión del usuario). |
| **Validación** | **126 tests** (51 nuevos en `test_usuarios`, `test_empleados`, `test_tareas_permisos`, `test_sesiones`, `test_auditoria`): guards 401/403 cross-dominio y unitarios de `RequireTaskPermission`, CRUD completo, 404/409/422, transiciones + revocación de sesiones, anulación → `401 ACCOUNT_BLOCKED`, matiz `null`, bitácora solo-lectura. Ruff limpio, cobertura **95%** (los 6 módulos de endpoints al 100%). E2E dev: smoke HTTP **39/39** + ambas rutas de `create_superadmin` verificadas. |
| **Impacto** | Endpoints y esquemas nuevos (6 módulos), `app/api/deps.py` (`RequireTaskPermission`, `obtener_o_404`, `verificar_unico`, `ip_a_cadena`), `router.py`, `tests/factories.py` + fixture global de bcrypt rápido, `scripts/create_superadmin.py`. |

## D25 — Subetapa 3.1: catálogos simples (áreas, categorías, tipos de gas, formas de pago, tipos de documento)

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada y validada (2026-10-08) |
| **Fecha** | 2026-10-08 |
| **Contexto** | ETAPA 3 = datos maestros, dividida por el usuario en **3.1** (5 catálogos simples) y **3.2** (parámetros del sistema y tasas de impuesto, pendiente). Todo el dominio funcional depende de estos catálogos (`tipo_gas` de cilindros, `categoria` de productos, `forma_pago` de pagos, `tipo_documento` de documentos comerciales) y el patrón CRUD + RBAC de la D24 estaba probado. |
| **Decisión** | **(a)** 5 módulos uniformes — `/areas`, `/categorias`, `/tipos-gas`, `/formas-pago`, `/tipos-documento` — con `GET` (paginado + `q`/`estado`; además `tipo` y `padre_id` en categorías), `GET /{id}`, `POST`, `PATCH /{id}`, `PATCH /{id}/estado` y `DELETE /{id}`, todos bajo **TAREA_29** × `PERM_01/02/03/07` (matriz ya sembrada en la ETAPA 1: sin cambios de seed). **(b)** `codigo` único e **inmutable** (ausente de los esquemas `*Update` → un PATCH solo con `codigo` → `400`). **(c)** Estados con el género del default del modelo aprobado en ETAPA 1: `ACTIVA/INACTIVA` (área, categoría, forma de pago) y `ACTIVO/INACTIVO` (tipo de gas, tipo de documento), validados con `Literal` → `422`; transición al mismo estado → `409 INVALID_STATE_TRANSITION` con `allowed_states`. **(d)** `DELETE` físico solo con **cero referencias** (área ← empleado/orden de trabajo; categoría ← hijas/productos/servicios; tipo de gas ← cilindros/órdenes/detalles; forma de pago ← pagos/documentos; tipo de documento ← documentos comerciales); con historial → `409 HAS_HISTORY` (alternativa: inactivar vía `PATCH /{id}/estado`). **(e)** Jerarquía de categorías: `padre_id` debe existir (`404`), no puede ser la propia categoría ni crear ciclos — se sube por la cadena de madres — (`400 VALIDATION_ERROR`, igual que el matiz `null` de la D24; el `422` queda para la validación de esquema). **(f)** `color_etiqueta` con patrón `#RRGGBB` → `422`; `orden_visual ≥ 0` → `422`; `null` en PATCH = sin cambio (mismo contrato de 2.1). **(g)** Esquemas agrupados en `app/schemas/catalogos.py` (5 `*Create/*Update/*EstadoUpdate/*Response`) y un endpoint por módulo, replicando el formato de `tareas.py`. |
| **Validación** | **176 tests** (50 nuevos en `test_catalogos.py`, parametrizados por módulo): guards 401/403 cross-dominio, CRUD completo, unicidad e intransigibilidad de `codigo`, transiciones, semántica `null`, 404/422, jerarquía a 3 niveles con anti-ciclos, delete con/sin historial, defaults del modelo, paginación. Ruff limpio, cobertura **96%** (`areas`, `categorias` y `schemas/catalogos.py` al 100%). E2E dev: smoke HTTP **32/32**. |
| **Impacto** | 5 endpoints + `app/schemas/catalogos.py` + `router.py` (prefijos nuevos), `tests/test_catalogos.py`, `master_data.py` (ver D26). |

## D26 — Deriva modelo ↔ base de datos y migración `0003_drift_fix`

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada y validada (2026-10-08) |
| **Fecha** | 2026-10-08 |
| **Contexto** | El E2E de la subetapa 3.1 falló con `500` en `DELETE /formas-pago`: el chequeo de referencias consultaba `documento_comercial.saldo_pendiente`, columna que **existe en el modelo pero no en la BD dev** construida con `alembic upgrade head`. `alembic check` reveló la deriva completa: **(a)** falta `documento_comercial.saldo_pendiente` (+ su índice parcial `idx_documento_estado_saldo`); **(b)** `orden_trabajo` arrastra 2 columnas huérfanas que el modelo ya no tiene (`estado_registro`, `fecha_creacion_registro`); **(c)** `tasa_impuesto.valor` era `Numeric(5,2)` en BD pero `float` en el modelo; **(d)** ~200 comentarios de columna de la 0001 nunca sincronizados. Los tests no lo habían detectado porque la BD de pruebas (`agas_cilindros_test`) se construye con `create_all` (fiel al modelo), no con alembic. |
| **Decisión** | **(a)** (aprobada por el usuario) **Alinear el modelo a la BD desplegada**: `tasa_impuesto.valor` → `Decimal` con `Numeric(5,2)` (exacto para tasas; evita el redondeo de `float` y evita migrar datos). **(b)** Migración **`0003_drift_fix`** autogenerada con `alembic revision --autogenerate` (dentro del contenedor, en `/tmp`, porque `docker-compose.dev.yml` monta `alembic/` en solo-lectura) y revisada a mano: `add_column saldo_pendiente`, reconstrucción de `idx_documento_estado_saldo` (`(estado, saldo_pendiente) WHERE saldo_pendiente > 0`), `drop_column` de las 2 huérfanas de `orden_trabajo` (tablas vacías: seguro) y `COMMENT ON` de todos los campos para cerrar también la deriva cosmética. **(c)** **`alembic check` como guarda de deriva**: ahora devuelve *No new upgrade operations detected* (exit 0); candidato a paso de CI en una etapa futura (requiere Postgres en el job de lint). **(d)** Nota de proceso: crear columnas nuevas en un modelo **exige** una migración en la misma entrega; la BD de pruebas por `create_all` no la sustituye. |
| **Validación** | `alembic upgrade head` → `downgrade 0002` → `upgrade head` (ciclo completo OK) y `alembic check` = 0 tras cada paso; E2E dev 32/32 (el `DELETE /formas-pago` que daba 500 ahora → 204); **176 tests** y ruff limpios. |
| **Impacto** | `app/models/master_data.py` (`Decimal`/`Numeric(5,2)`), `backend/alembic/versions/0003_drift_fix.py`. |

## D27 — Subetapa 3.2: parámetros del sistema y tasas de impuesto

| Campo | Descripción |
|-------|-------------|
| **Estado** | ✅ Aplicada y validada (2026-10-08) |
| **Fecha** | 2026-10-08 |
| **Contexto** | Segunda y última subetapa de la ETAPA 3 (diseño aprobado por el usuario): los datos maestros que condicionan el resto del ERP — configuración global *key-value* (`parametro`, con PK natural `clave`, no es una tabla `BaseModel`) y tasas de impuesto con vigencias que referencian productos y servicios. Ambos ya tenían seed en la ETAPA 1 (sin cambios de seed). |
| **Decisión** | **(a)** `/parametros` bajo TAREA_29 × PERM_01/02/03/07 con la PK natural en la ruta (`/parametros/{clave}`); `clave` y `tipo` inmutables (ausentes del esquema `Update` → `400` si es lo único que se manda); el `valor` debe **coaccionar al `tipo` declarado** — `STRING/INTEGER/DECIMAL/BOOLEAN/JSON/DATE` (CK real) — con `400 VALIDATION_ERROR` si no corresponde: `DECIMAL` exige número finito (`Infinity`/`NaN` rechazados), `BOOLEAN` acepta `true/false/1/0` sin distinción de mayúsculas, `JSON` debe parsear y `DATE` es ISO `YYYY-MM-DD`; PATCH registra `actualizada_por` = usuario autenticado. **(b)** `editable=false` → **cualquier** PATCH o DELETE → **409 `READONLY`** (código de error **nuevo**, `ReadOnlyError(Conflict)`): conflicto por estado del registro; el parámetro solo cambia por seed/migración y se protege con los mismos guards (PERM_03/PERM_07). DELETE es físico (`parametro` no tiene FKs entrantes). **(c)** `/tasas-impuesto` como CRUD estándar de la serie: estados `ACTIVA/INACTIVA` con las mismas transiciones (misma → `409 INVALID_STATE_TRANSITION`, fuera de `Literal` → `422`), `codigo` único e inmutable, `valor` acotado **0–100** (`422`, `Numeric(5,2)` ya alineado en la D26), `vigencia_desde <= vigencia_hasta` cuando hay cierre (`400`, re-validado en PATCH con los **valores efectivos** tras aplicar el cuerpo), máximo **una** tasa `es_default` global — al marcarla se revoca en la misma transacción la de las demás — y **`cerrar_vigencia: bool`** como interruptor del cierre (`true` = hoy, `false` = sin cierre) para poder mantener el contrato de la ETAPA 2.1 "`null` = sin cambio" en `vigencia_hasta` (ambos campos a la vez → `400`). **(d)** DELETE físico solo con cero referencias (`producto`, `servicio`); con historial → `409 HAS_HISTORY` indicando inactivar con `PATCH /{id}/estado`. **(e)** `verificar_unico` se generalizó para leer la PK real del modelo (`model.__mapper__.primary_key[0]`) porque `parametro` no tiene `id` — misma conducta para todos los modelos existentes. |
| **Validación** | **204 tests** (28 nuevos en `test_parametros_tasas.py`): coacción de valor por tipo parametrizada (8 casos), `READONLY` en PATCH y DELETE, inmutabilidad de `clave`/`tipo`/`codigo`, semántica `null`, unicidad de `es_default` con auto-revocación (alta y PATCH), vigencias invertidas en alta y actualización, `cerrar_vigencia` (cerrar/abrir/combinación inválida), producto que referencia la tasa → `409 HAS_HISTORY` y borrado `204` tras retirar la referencia, guards 401/403 cross-dominio. Ruff limpio, cobertura **96%** (`parametros.py`, `tasas_impuesto.py` y `schemas/catalogos.py` al **100%**). E2E dev: smoke **28/28** (incluye restauración del `es_default` sembrado). |
| **Impacto** | `app/core/exceptions.py` (`ReadOnlyError` → `READONLY`), `app/api/deps.py` (`verificar_unico` con PK genérica), `app/schemas/catalogos.py` (secciones 3.2), `app/api/v1/endpoints/parametros.py`, `app/api/v1/endpoints/tasas_impuesto.py`, `router.py`, `tests/test_parametros_tasas.py`. |