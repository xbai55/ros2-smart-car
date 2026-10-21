import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.db.base import Base
from app.main import app
from app.seed import seed_session

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session")
def seeded_db():
    session = TestingSessionLocal()
    try:
        seed_session(session)
        # Test-only business fixtures. Production initialization has no samples.
        from app.models import Robot, MapModel, Route
        for i, name in enumerate(("Patrol-01", "Patrol-02", "Carrier-01"), 1):
            session.add(Robot(id=f"fixture-robot-{i}", name=name, serial=f"TEST-{i}"))
        session.add(MapModel(id="fixture-map", name="Test map"))
        session.add(Route(id="fixture-route", name="Test route", map_id="fixture-map", points="[]"))
        session.commit()
        return session
    finally:
        session.close()


@pytest.fixture(scope="session")
def client(seeded_db):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def login(client):
    def _login(username: str, password: str) -> str:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    return _login