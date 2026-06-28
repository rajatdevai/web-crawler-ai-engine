import pytest
from httpx import AsyncClient, ASGITransport
from app.api.router import app
from app.core.config import Settings, get_settings, AppSettings, DatabaseSettings, RedisSettings, LLMSettings
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.models import Base
from app.core.dependencies import get_db_session

# Test DB URL
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def test_settings():
    return Settings(
        app=AppSettings(env="testing"),
        db=DatabaseSettings(url=TEST_DATABASE_URL),
        redis=RedisSettings(url="redis://localhost:6379/1"),
        llm=LLMSettings(api_key="mock_key_testing")
    )

import pytest_asyncio

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def test_session(test_engine):
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

@pytest.fixture
def app_with_overrides(test_settings, test_session):
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_db_session] = lambda: test_session
    yield app
    app.dependency_overrides.clear()

@pytest_asyncio.fixture
async def async_client(app_with_overrides):
    async with AsyncClient(transport=ASGITransport(app=app_with_overrides), base_url="http://test") as client:
        yield client

# Mock Redis Client for testing unit logic without hitting Redis server
@pytest.fixture
def mock_redis(monkeypatch):
    class MockRedis:
        def __init__(self):
            self.store = {}
            self.lists = {}
            self.sets = {}

        async def get(self, key):
            return self.store.get(key)

        async def set(self, key, value, *args, **kwargs):
            self.store[key] = value
            return True

        async def set_with_ttl(self, key, value, ttl):
            self.store[key] = value
            return True

        async def delete(self, *keys):
            for k in keys:
                self.store.pop(k, None)
                self.lists.pop(k, None)
                self.sets.pop(k, None)
            return True

        async def push_to_queue(self, key, value):
            self.lists.setdefault(key, []).append(value)
            return True

        async def pop_from_queue(self, key, timeout=0):
            l = self.lists.get(key, [])
            if l:
                return l.pop(0)
            return None

        async def get_list_length(self, key):
            return len(self.lists.get(key, []))

        async def sadd(self, key, value):
            s = self.sets.setdefault(key, set())
            if value in s:
                return 0
            s.add(value)
            return 1

        async def zadd(self, key, mapping, *args, **kwargs):
            s = self.store.setdefault(key, {})
            s.update(mapping)
            return len(mapping)

        async def sismember(self, key, value):
            return value in self.sets.get(key, set())

        async def srem(self, key, value):
            s = self.sets.get(key, set())
            if value in s:
                s.remove(value)
                return 1
            return 0

        async def smembers(self, key):
            return self.sets.get(key, set())

        async def rpush(self, key, value):
            self.lists.setdefault(key, []).append(value)
            return len(self.lists[key])

        async def expire(self, key, seconds):
            return True

        async def lrange(self, key, start, stop):
            return self.lists.get(key, [])

    mock_client = MockRedis()
    from app.database.redis_client import redis_client
    monkeypatch.setattr(redis_client, "client", mock_client, raising=False)
    monkeypatch.setattr(redis_client, "get", mock_client.get, raising=False)
    monkeypatch.setattr(redis_client, "set", mock_client.set, raising=False)
    monkeypatch.setattr(redis_client, "set_with_ttl", mock_client.set_with_ttl, raising=False)
    monkeypatch.setattr(redis_client, "delete", mock_client.delete, raising=False)
    monkeypatch.setattr(redis_client, "push_to_queue", mock_client.push_to_queue, raising=False)
    monkeypatch.setattr(redis_client, "pop_from_queue", mock_client.pop_from_queue, raising=False)
    monkeypatch.setattr(redis_client, "get_list_length", mock_client.get_list_length, raising=False)
    return mock_client
