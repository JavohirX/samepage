"""Tests for OpenAPI 3.0 schema generation and Swagger UI (S11)."""

import pytest
from django.core.management import call_command

from conftest import needs_db

pytestmark = [needs_db, pytest.mark.django_db]


import json

def test_openapi_schema_endpoint(client):
    """Verify /openapi.json and /api/v1/openapi.json return valid OpenAPI 3.0 specs."""
    resp1 = client.get("/openapi.json")
    assert resp1.status_code == 200
    data1 = json.loads(resp1.content.decode("utf-8"))
    assert data1["openapi"].startswith("3.0")
    assert "info" in data1
    assert data1["info"]["title"] == "Samepage API"
    assert "paths" in data1
    assert len(data1["paths"]) > 10

    resp2 = client.get("/api/v1/openapi.json")
    assert resp2.status_code == 200
    data2 = json.loads(resp2.content.decode("utf-8"))
    assert data2["openapi"].startswith("3.0")


def test_swagger_ui_docs_endpoint(client):
    """Verify /docs serves Swagger UI HTML documentation."""
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "swagger-ui" in resp.content.decode("utf-8").lower()


def test_drf_spectacular_validation():
    """Verify drf-spectacular schema validation passes cleanly."""
    call_command("spectacular", "--validate")
