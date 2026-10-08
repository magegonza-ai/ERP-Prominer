# ==============================================================
# AGAS Cilindros - Backend API
# Imagen multi-etapa basada en Python 3.14 (decisión D16)
# ==============================================================

# ---------- Base ----------
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---------- Dependencias ----------
FROM base AS deps

COPY requirements/base.txt requirements/prod.txt ./requirements/

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements/prod.txt

# ---------- Runtime ----------
FROM base AS runtime

# Copia el venv con las dependencias
COPY --from=deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Código de la aplicación
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# Usuario no-root
RUN addgroup --system agas \
    && adduser --system --ingroup agas --uid 1001 agas \
    && mkdir -p /app/secrets \
    && chown -R agas:agas /app

USER agas

EXPOSE 8000

# Migraciones + arranque del API
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]