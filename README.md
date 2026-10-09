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
  maestros): completadas y aprobadas (ver hitos). ETAPA 4 completada y aprobada.

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
│   │   ├── models/         # 44 modelos SQLAlchemy 2.0
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
- [ ] **ETAPAS 5–12** (pendientes)

## Decisiones

- **D16 — Versión de Python**: se usa **Python 3.14.5** (única disponible en el entorno de desarrollo;
  el stack original indicaba 3.12). Todo el backend está validado en 3.14. En producción la versión
  la fija la imagen del contenedor. Ver [docs/decisiones.md](docs/decisiones.md).