"""Tests for liveness + readiness endpoints."""

import pytest


@pytest.mark.anyio
async def test_health_liveness_always_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_readiness_passes_when_db_and_uploads_ok(client):
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["uploads_writable"]["ok"] is True
    # API key is informational, not a readiness gate
    assert body["checks"]["anthropic_key"]["configured"] is False
