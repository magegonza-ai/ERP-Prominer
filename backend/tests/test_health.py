"""
Tests de los endpoints de salud y de los handlers de error globales (ETAPA 1).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_root_devuelve_info_de_aplicacion() -> None:
    with TestClient(app) as client:
        resp = client.get("/")

    assert resp.status_code == 200
    body = resp.json()
    assert body["app"] == "AGAS Cilindros API"
    assert body["version"] == "1.0.0"
    assert body["api"] == "/api/v1"


def test_health_liveness_responde_ok() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "AGAS Cilindros API"
    assert body["environment"] in {"test", "development", "staging", "production"}


def test_health_detail_informa_estado_de_bd() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/health/detail")

    # 200 con BD disponible; 503 "degraded" si no está (aceptable en CI/local).
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert isinstance(body["database"]["connected"], bool)


def test_404_tiene_formato_consistente() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/no-existe")

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["code"] == "NOT_FOUND"
    assert "message" in detail


def test_405_tiene_formato_consistente() -> None:
    with TestClient(app) as client:
        resp = client.put("/api/v1/health")

    assert resp.status_code == 405
    detail = resp.json()["detail"]
    assert detail["code"] == "METHOD_NOT_ALLOWED"
    assert "message" in detail
