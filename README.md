# ERP-Prominer — Sistema de Cilindros de Gas AGAS

Sistema Web de **Gestión, Valorización y Trazabilidad de Cilindros de Gas** para la empresa AGAS.

Aplicación empresarial responsiva en español que gestiona el ciclo de vida completo de los cilindros:
recepción, inspección, llenado, reparación, control de calidad, despacho, entregas, valorización
comercial, documentos tributarios y trazabilidad total con auditoría.

## Documentación

- **Análisis completo (Pasos 1–21)**: documento de análisis aprobado que define módulos, tablas,
  reglas de negocio, casos de prueba y etapas (documento de referencia en la conversación del proyecto).
- **Registro de decisiones de implementación**: [`docs/decisiones.md`](docs/decisiones.md).
- **Etapas 1, 2 y 3** (Arquitectura y Base de Datos; Autenticación y seguridad; Datos
  maestros) y **ETAPA 4** (clientes, propietarios e inventario de cilindros): completadas y
  aprobadas. **ETAPA 5 (Operaciones)** en curso: subetapas **5.1** (recepción de cilindros),
  **5.2** (inspección de cilindros), **5.3.a** (órdenes de trabajo: cabecera, detalles y ciclo de
  vida), **5.3.b** (tareas asignadas de la orden y reasignación), **5.4** (control de calidad de
  cilindros), **5.5** (despacho y entregas) y **5.6** (devoluciones de cilindros) aprobadas.

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | Python 3.14, FastAPI, SQLAlchemy 2.0 (async), Alembic |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS (pendiente ETAPA 3+) |
| Base de datos | PostgreSQL 16 |
| Cache / colas | Redis, Celery |
| Almacenamiento | SeaweedFS S3 (adjuntos y backups; D20) |
| Autenticación | JWT RS256 + TOTP 2FA, RBAC por tareas/permisos |
| Infraestructura | Docker Compose, GitHub Actions (CI/CD) |

## Estructura del repositorio

```
ERP-Prominer/
├── backend/
│   ├── alembic/            # Migraciones Alembic (0001_initial: 44 tablas)
│   ├── app/
│   │   ├── api/v1/         # Endpoints REST (por etapas)
│   │   ├── core/           # Seguridad, permisos, auditoría, excepciones
│   │   ├── models/         # 46 modelos SQLAlchemy 2.0
│   │   ├── config.py       # Settings (Pydantic)
│   │   ├── database.py     # Engine async + session factory
│   │   └── main.py         # Aplicación FastAPI
│   ├── scripts/            # seed_data, create_superadmin, generar_llaves_jwt
│   ├── requirements/       # base / dev / prod
│   ├── Dockerfile          # Imagen multi-etapa (python:3.14-slim)
│   ├── .env.example        # Plantilla de configuración
│   └── pyproject.toml      # Lint (ruff), tipado (mypy), pytest
├── deploy/
│   └── nginx/              # Reverse proxy de producción
├── docker-compose.yml      # Postgres 16 + Redis + SeaweedFS + API
├── docker-compose.dev.yml  # Override desarrollo (reload)
├── docker-compose.prod.yml # Override producción (+ nginx)
├── docs/                   # Documentación del proyecto (anexo decisiones)
└── .gitignore
```

## Requisitos

- Python 3.14 (`py -0` para comprobar; usar `py -3.14` si hay varias versiones)
- PostgreSQL 16 (local o vía Docker)
- Docker + Docker Compose v2 (**recomendado**, para levantar el stack completo)
- (Futuro) Node.js 20+ para frontend

## Configuración local (backend)

```powershell
cd backend

# Crear entorno virtual e instalar dependencias (solo la primera vez)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt

# Configuración
Copy-Item .env.example .env
# ... completar SECRET_KEY, DATABASE_PASSWORD, MINIO_ACCESS_KEY, MINIO_SECRET_KEY en .env

# Base de datos (con PostgreSQL corriendo)
.\.venv\Scripts\python.exe -m alembic upgrade head

# Datos semilla y superadmin
.\.venv\Scripts\python.exe -m scripts.seed_data
.\.venv\Scripts\python.exe -m scripts.create_superadmin

# Llaves JWT (RS256) - solo la primera vez
.\.venv\Scripts\python.exe -m scripts.generar_llaves_jwt

# Ejecutar API (desarrollo)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# Swagger: http://localhost:8000/docs
```

## Ejecución con Docker

Requiere **Docker (con Docker Compose v2)**. Levanta PostgreSQL 16, Redis, SeaweedFS y la API.

```powershell
# 1) Llaves JWT (primera vez)
cd backend
.\scripts\generar_llaves_jwt.ps1       # o: .\.venv\Scripts\python.exe -m scripts.generar_llaves_jwt

# 2) Levantar el stack base (desarrollo)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Servicios expuestos
#   API      → http://localhost:8000   (Swagger /docs en DEBUG)
#   Postgres → localhost:5433         (agas_user / agas_cilindros)
#   Redis    → localhost:6379
#   SeaweedFS → http://localhost:9000  (API S3; interfaz: http://localhost:8888)

# Logs y estado
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f api
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps

# Detener
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

Cambios en `backend/app` se reflejan en caliente (`uvicorn --reload`).

### Producción

```powershell
# Requiere definir MINIO_ROOT_USER y MINIO_ROOT_PASSWORD en el entorno
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# nginx publica en http://localhost (proxy hacia la API)
```

Las llaves JWT de producción se montan como volumen docker `jwt_secrets` (copiar
los `.pem` generados a mano o vía secreto del orquestador).

## Validación (herramientas)

```powershell
cd backend
.\.venv\Scripts\python.exe -m ruff check app scripts alembic
.\.venv\Scripts\python.exe -m ruff format --check app scripts alembic
.\.venv\Scripts\python.exe -m alembic upgrade head --sql     # valida SQL sin BD
.\.venv\Scripts\python.exe -m pytest                          # (tests por etapa)
```

## Hitos

- [x] **ETAPA 1 — Arquitectura y Base de Datos** *(completada)*: análisis aprobado (Pasos 1–21),
      44 tablas y migración validada, core de seguridad/permisos/auditoría, API v1 con health,
      scripts seed/superadmin, lint limpio, suite de tests con CI (GitHub Actions) en verde.
- [x] **ETAPA 2 — Autenticación y seguridad** *(completada y aprobada)*: `POST /auth/login`
      (bcrypt + 2FA TOTP + bloqueo por intentos), `POST /auth/refresh`
      (rotación con revocación por reuso), `GET /auth/me` (usuario + permisos RBAC), dependencias
      `get_current_user`/`RequirePermission`/`RequireTaskPermission`; CRUD completo de **usuarios**,
      **empleados** (con asignación de tareas), **tareas** y **permisos** (matriz `tarea_permiso`),
      **sesiones** (listado/revocación) y **auditoría** (solo lectura con filtros), todo bajo la
      matriz RBAC dominio×acción (TAREA_28/29/30) — 126 tests, cobertura 95%, E2E dev 39/39.
- [x] **ETAPA 3 — Datos maestros** *(completada y aprobada)*: catálogos simples `/areas`,
      `/categorias` (jerárquica con anti-ciclos), `/tipos-gas`, `/formas-pago` y
      `/tipos-documento` (guard TAREA_29, `codigo` único e inmutable, estados por `Literal`,
      `DELETE` solo sin referencias → 409); y **3.2** `/parametros` (PK `clave`, coacción de
      `valor` al `tipo` declarado, `editable=false` → 409 `READONLY`) + `/tasas-impuesto`
      (vigencias con `cerrar_vigencia`, `valor` 0–100, un solo `es_default` global) —
      204 tests, cobertura 96%, E2E dev 32/32 y 28/28, migración `0003_drift_fix` que alinea
      modelo↔BD (`alembic check` limpio) — decisiones D25, D26 y D27.
- [x] **ETAPA 4 — Clientes, propietarios e inventario de cilindros** *(completada y
      aprobada)*: **4.1** `/clientes` (rut único e
      inmutable, estados `ACTIVO/INACTIVO/BLOQUEADO`, DELETE solo con cero referencias →
      409) + receptores autorizados anidados (acotados al cliente, `autorizado_por`,
      `vigente_hasta` ≥ fecha de autorización) y `/propietarios` (tipo/rut inmutables,
      unicidad parcial `(rut, tipo)`, vínculo `cliente_id` obligatorio solo en tipo CLIENTE)
      — 228 tests, cobertura 96%, E2E dev 45/45, decisión D28; **4.2** `/ubicaciones`
      (catálogo: `codigo` único e inmutable, `tipo` mutable, estados `ACTIVA/INACTIVA`,
      DELETE solo sin referencias → 409), `/cilindros` (identidad única e inmutable, nacen
      `REGISTRADO`, FKs → 404, campos no editables, DELETE solo sin historial en 8 tablas →
      409 `HAS_HISTORY`) y `/movimientos` (solo `POST`+`GET`, guard OR TAREA_15/16,
      atómico con origen/`estado_anterior` derivados del servidor, no-op → 400, reglas de la
      ubicación solo con cambio real de ubicación) — 264 tests, cobertura 97%, E2E dev
      59/59, decisión D29.
- [ ] **ETAPA 5 — Operaciones** *(en curso; 5.1, 5.2, 5.3.a, 5.3.b, 5.4, 5.5 y 5.6 aprobadas)*:
      **5.1** `/recepciones` (guard TAREA_04): cabecera con `numero` del servidor
      (`REC-<AÑO>-######`), `fecha_hora`/`usuario_responsable_id` derivados, FKs → 404,
      estados `COMPLETADA ⇄ ANULADA` (misma transición → 409 con `allowed_states`) y
      `DELETE` no expuesto (405: se anula por estado); detalles anidados donde cada
      cilindro recibido emite un `Movimiento` **atómico** (nace `RECIBIDO`, o
      `PENDIENTE_INSPECCION` si `motivo_servicio = INSPECCION`), cilindro repetido en la
      misma recepción → 409 `DUPLICATE_VALUE`, detalle acotado a su recepción → 404 y el
      borrado del detalle no revierte la traza — 291 tests, cobertura 97%, E2E dev 53/53,
      decisiones D30 y D31; **5.2** `/inspecciones` (guard TAREA_05, **append-only**:
      PATCH/DELETE → 405): checklist opcional y `resultado` validados (`Literal`/`bool` →
      422), `usuario_id`/`fecha_hora` derivados, `cilindro_id` (404) y `recepcion_id`
      (vínculo informativo, 404); cada alta emite un `Movimiento` **atómico** que mapea el
      resultado al estado del cilindro (`APTO_LLENADO`→`APTO_LLENADO`, `REQUIERE_REPARACION`
      →`APTO_REPARACION`, `REQUIERE_INSPECCION_TECNICA`→`PENDIENTE_INSPECCION`,
      `RECHAZADO`→`RECHAZADO`, `FUERA_SERVICIO`→`FUERA_SERVICIO`) — 312 tests, cobertura
      97%, E2E dev 44/44, decisión D33; **5.3.a** `/ordenes-trabajo` (colección única de
      llenado/reparación con RBAC **condicionado por `tipo`**, decisión D32): numeración
      del servidor `OTL`/`OTR-<AÑO>-######`, alta **atómica** con cilindros `inline` (≥ 1;
      repetido → 409; elegible `APTO_LLENADO`/`APTO_REPARACION` → si no, 400), ciclo
      `PENDIENTE → EN_PROCESO → FINALIZADA → PENDIENTE_CALIDAD` (+`CANCELADA` desde
      `PENDIENTE`) donde cada transición emite un `Movimiento` **atómico** por cilindro
      (`EN_PROCESO_LLENADO`/`EN_REPARACION` → `FINALIZADO_LLENADO`/`REPARADO` →
      `PENDIENTE_CONTROL_CALIDAD`), transición inválida o misma → 409 `allowed_states`,
      sub-recurso de detalles con resultados de ejecución (solo `EN_PROCESO`/`FINALIZADA`)
      y sin `DELETE` de cabecera (405) — 340 tests, cobertura 97%, E2E dev 57/57; **5.3.b**
      `/ordenes-trabajo/{id}/tareas` (tareas asignadas, decisión D34): alta que valida orden
      (no `CANCELADA`), tarea `ACTIVA`, empleado `ACTIVO` y cilindro **perteneciente a la
      orden** (asignar = `TAREA_28` + `PERM_09`), avance
      `ASIGNADA → EN_PROCESO → COMPLETADA` (+`EN_PAUSA`/`CANCELADA`; misma/inválida → 409
      `allowed_states`) reservado a `TAREA_28`/`TAREA_08`/`TAREA_12` + `PERM_03`, reasignación
      con **traza** vía `POST /{tareas}/{id}/reasignar` (`TAREA_28` + `PERM_10`: la original
      pasa a `REASIGNADA` y nace un reemplazo con `reasignada_desde_id`/`usuario_reasigno_id`
      /`motivo`), listado con filtros (`estado`/`responsable_id`/`tarea_id`), `DELETE` → 405 —
      351 tests, cobertura 97%, E2E dev 52/52, decisión D34; **5.4** `/controles-calidad`
       (guard TAREA_14, **append-only**: PATCH/DELETE → 405): el control se registra sobre un
       cilindro **de la orden** vinculada (`orden_relacionada_id` obligatoria) cuando la orden
       está `PENDIENTE_CALIDAD` y el cilindro `PENDIENTE_CONTROL_CALIDAD` (si no → 400); además
       de PERM_02, `resultado` exige PERM_04 (aprobar) o PERM_05 (rechazar); cada control emite
       un `Movimiento` **atómico** que mapea el resultado al estado del cilindro
       (`APROBADO`→`APROBADO` o `LISTO_PARA_ENTREGAR` si `autoriza_entrega`,
       `APROBADO_OBSERVACIONES`→`APROBADO_OBSERVACIONES`,
       `REQUIERE_NUEVA_REPARACION`→`APTO_REPARACION`, `RECHAZADO`→`RECHAZADO`,
       `PENDIENTE_REVISION`→sin cambio, permite re-control); se aplica la **segregación de
       funciones RN28** (quien ejecutó el trabajo —TAREA_08/12 completada— no puede aprobar su
       propio control → 403 `SEPARATION_OF_DUTIES`) y la orden **cierra en la misma transacción**
       cuando todos sus cilindros quedan controlados y ninguno en `PENDIENTE_REVISION`
       (`RECHAZADA` › `REQUIERE_NUEVA_REPARACION` › `APROBADA`) — 370 tests, cobertura 97%,
       E2E dev 42/42, decisión D35; **5.5** `/entregas` (dominios TAREA_17 «Preparar
        entregas» / TAREA_18 «Entregar cilindros», decisión D36): colección única de despacho
        con cabecera y cilindros anidados, numeración del servidor `ENT-<AÑO>-######` y
        `cantidad` fija =1 con montos calculados; ciclo `BORRADOR → PENDIENTE → CONFIRMADA →
        ENTREGADA` (+`CANCELADA` terminal desde `BORRADOR`/`PENDIENTE`) con RBAC por acción
        (leer TAREA_17∨18 + PERM_01; crear/reemplazar TAREA_17 + PERM_02/03; →`CONFIRMADA`
        TAREA_17 + PERM_06; **entregar solo TAREA_18** × PERM_06 — quien prepara no entrega —
        y anular TAREA_17 × PERM_03, pues la matriz no otorga PERM_07), `DELETE` no expuesto
        (405: se anula por estado) y `PUT` fuera de `BORRADOR` → 400; **RN13**: cilindro
        `APROBADO` o `LISTO_PARA_ENTREGAR` (si no → 422 `CylinderNotApprovedForDelivery`), del
        propietario de la cabecera, sin repetirse en la misma cabecera y sin estar en otra
        entrega activa (409 `DUPLICATE_VALUE`); al pasar a `ENTREGADA` cada cilindro emite un
        `Movimiento` **atómico** (D31) `→ ENTREGADO` sin cambio de ubicación y con
        firma/observaciones opcionales; `CANCELADA` no toca el cilindro y lo libera para otra
        entrega — 396 tests, cobertura 98%, E2E dev 12/12, decisión D36; **5.6**
        `/devoluciones` (guard TAREA_19 «Registrar devoluciones», matriz sembrada
        `[0,1,2,7]` = PERM_01/02/03/07, decisión D37): retorno de cilindros `ENTREGADO` a
        AGAS con cabecera y cilindros anidados inline (`DevolucionDetalle`, ≥ 1; repetido o
        en otra devolución activa → 409 `DUPLICATE_VALUE`; no `ENTREGADO` → 400; cliente
        404 / `INACTIVO` 400; `entrega_id` y `ubicacion_destino_id` opcionales → 404),
        numeración del servidor `DEV-<AÑO>-######`, `motivo`
        `DEVOLUCION_CLIENTE|DANO_EN_TRANSITO|ERROR_ENTREGA|GARANTIA|OTRO` y `estado_fisico`
        `BUENO|REGULAR|MALO|CRITICO`; ciclo `REGISTRADA → ANULADA` (terminal; misma/inválida
        → 409 con `allowed_states`) donde **anular exige PERM_07** y **no revierte la traza**
        (el cilindro ya regresó físicamente como `RECIBIDO`), edición de campos descriptivos
        solo en `REGISTRADA` (sin tocar detalles ni `ubicacion_destino_id`, ya materializados
        en el alta) y `DELETE` no expuesto (405: se anula por estado); al registrar se emite un
        `Movimiento` **atómico** por cilindro (D31) `ENTREGADO → RECIBIDO` con
        `usuario_recibe_id` y cambio de ubicación si se indica destino — 422 tests, cobertura
        98%, E2E dev 16/16, decisión D37.
- [ ] **ETAPAS 5.7–12** (pendientes)

## Decisiones

- **D16 — Versión de Python**: se usa **Python 3.14.5** (única disponible en el entorno de desarrollo;
  el stack original indicaba 3.12). Todo el backend está validado en 3.14. En producción la versión
  la fija la imagen del contenedor. Ver [docs/decisiones.md](docs/decisiones.md).