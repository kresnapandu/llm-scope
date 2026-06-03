"""
Integration tests for llm-scope backend API.
Uses in-memory SQLite for testing (via aiosqlite).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models import Base, Trace

# Use SQLite for tests (no Postgres required)
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_llmscope.db"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionFactory = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    async with TestSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client():
    return TestClient(app)


def make_trace(**kwargs) -> Trace:
    defaults = {
        "id": uuid.uuid4(),
        "trace_id": "abc123def456789" + "0" * 17,
        "span_id": "span12345678",
        "name": "llm.openai.chat",
        "service_name": "test-service",
        "start_time": datetime.now(timezone.utc),
        "end_time": datetime.now(timezone.utc),
        "duration_ms": 150,
        "status": "OK",
        "attributes": {
            "gen_ai.system": "openai",
            "gen_ai.request.model": "gpt-4o-mini",
            "gen_ai.usage.input_tokens": 50,
            "gen_ai.usage.output_tokens": 100,
            "llmscope.cost_usd": 0.000075,
            "llmscope.latency_ms": 150,
        },
    }
    defaults.update(kwargs)
    return Trace(**defaults)


class TestHealthCheck:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestTracesAPI:
    @pytest.mark.asyncio
    async def test_list_traces_empty(self, client):
        response = client.get("/api/traces")
        assert response.status_code == 200
        data = response.json()
        assert data["traces"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_traces_with_data(self):
        async with TestSessionFactory() as session:
            trace = make_trace()
            session.add(trace)
            await session.commit()

        async with AsyncClient(app=app, base_url="http://test") as ac:
            response = await ac.get("/api/traces")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["traces"]) == 1

    @pytest.mark.asyncio
    async def test_filter_by_status(self):
        async with TestSessionFactory() as session:
            ok_trace = make_trace(status="OK")
            err_trace = make_trace(
                id=uuid.uuid4(),
                span_id="span99999999",
                status="ERROR",
            )
            session.add_all([ok_trace, err_trace])
            await session.commit()

        async with AsyncClient(app=app, base_url="http://test") as ac:
            response = await ac.get("/api/traces?status=ERROR")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["traces"][0]["status"] == "ERROR"

    @pytest.mark.asyncio
    async def test_get_trace_not_found(self):
        async with AsyncClient(app=app, base_url="http://test") as ac:
            response = await ac.get("/api/traces/nonexistent_trace")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_trace(self):
        trace_id = "deadbeef" * 4
        async with TestSessionFactory() as session:
            trace = make_trace(trace_id=trace_id)
            session.add(trace)
            await session.commit()

        async with AsyncClient(app=app, base_url="http://test") as ac:
            response = await ac.delete(f"/api/traces/{trace_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 1


class TestAlertsAPI:
    @pytest.mark.asyncio
    async def test_create_alert(self):
        async with AsyncClient(app=app, base_url="http://test") as ac:
            response = await ac.post(
                "/api/alerts",
                json={
                    "name": "High Error Rate",
                    "type": "error_rate",
                    "threshold": 0.1,
                    "window_minutes": 60,
                },
            )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "High Error Rate"
        assert data["type"] == "error_rate"

    @pytest.mark.asyncio
    async def test_list_alerts_empty(self):
        async with AsyncClient(app=app, base_url="http://test") as ac:
            response = await ac.get("/api/alerts")
        assert response.status_code == 200
        assert response.json()["rules"] == []


class TestJudgeAPI:
    def test_judge_short_completion(self, client):
        response = client.post(
            "/api/judge",
            json={
                "context": "Paris is the capital of France.",
                "completion": "Hi",
                "span_id": "span001",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["score"] == 0.0
        assert data["method"] == "deterministic"

    def test_judge_faithful_completion(self, client):
        response = client.post(
            "/api/judge",
            json={
                "context": "The Python programming language was created by Guido van Rossum.",
                "completion": "Python was created by Guido van Rossum and is a programming language.",
                "span_id": "span002",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["score"] < 0.5  # Should be low (faithful)
        assert "span_id" in data
