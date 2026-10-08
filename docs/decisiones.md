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