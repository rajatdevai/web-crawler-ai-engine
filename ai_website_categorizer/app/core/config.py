from functools import lru_cache
from typing import Dict, Any
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class AppSettings(BaseModel):
    name: str = Field(default="AI Website Categorizer", description="Name of the application")
    env: str = Field(default="development", description="Environment (development | staging | production)")
    debug: bool = Field(default=True, description="Enable debug mode")

class DatabaseSettings(BaseModel):
    url: str = Field(..., description="PostgreSQL async database URL")

class RedisSettings(BaseModel):
    url: str = Field(..., description="Redis connection URL")

class CrawlerSettings(BaseModel):
    max_concurrent_workers: int = Field(default=5, description="Maximum concurrent crawler workers")
    request_timeout: int = Field(default=30, description="HTTP request timeout in seconds")
    crawl_delay: float = Field(default=1.0, description="Global delay between requests in seconds")
    max_retries: int = Field(default=3, description="Maximum retry attempts for failed requests")
    max_depth: int = Field(default=10, description="Maximum crawl depth from seed URL")
    max_pages: int = Field(default=5000, description="Maximum pages to crawl per job")
    respect_robots_txt: bool = Field(default=True, description="Whether to respect robots.txt rules")
    user_agent: str = Field(default="AI Categorizer Crawler Bot 1.0", description="User agent string for HTTP requests")
    domain_rate_limits: Dict[str, float] = Field(
        default_factory=dict, 
        description="Domain-specific rate limits (requests per second) mapped by normalized eTLD+1"
    )

class PlaywrightSettings(BaseModel):
    headless: bool = Field(default=True, description="Run Playwright in headless mode")
    timeout: int = Field(default=30000, description="Playwright navigation timeout in ms")

class LLMSettings(BaseModel):
    provider: str = Field(default="openai", description="LLM provider name")
    api_key: str = Field(..., description="LLM API Key")
    model: str = Field(default="gpt-4o-mini", description="LLM model identifier")
    max_tokens: int = Field(default=500, description="Maximum tokens for LLM generation")
    temperature: float = Field(default=0.1, description="Temperature for LLM generation")
    budget_limit_usd: float = Field(default=5.0, description="Budget limit for LLM calls per job")

class EmbeddingSettings(BaseModel):
    model: str = Field(default="text-embedding-3-small", description="Embedding model identifier")
    batch_size: int = Field(default=50, description="Batch size for generating embeddings")

class ClassificationSettings(BaseModel):
    embedding_similarity_threshold: float = Field(default=0.85, description="Threshold for embedding classification")
    deterministic_confidence_threshold: float = Field(default=0.90, description="Threshold for deterministic classification")

class SecuritySettings(BaseModel):
    max_payload_size_mb: int = Field(default=5, description="Maximum payload size limit in MB")

class Settings(BaseSettings):
    app: AppSettings = AppSettings()
    db: DatabaseSettings
    redis: RedisSettings
    crawler: CrawlerSettings = CrawlerSettings()
    playwright: PlaywrightSettings = PlaywrightSettings()
    llm: LLMSettings
    embedding: EmbeddingSettings = EmbeddingSettings()
    classification: ClassificationSettings = ClassificationSettings()
    security: SecuritySettings = SecuritySettings()

    def __init__(self, **values):
        import os
        from dotenv import load_dotenv
        load_dotenv(override=True)
        
        def get_env_bool(key: str, default: bool) -> bool:
            val = os.getenv(key)
            if val is None:
                return default
            return val.lower() in ("true", "1", "yes")

        # 1. AppSettings
        if "app" not in values:
            values["app"] = AppSettings(
                name=os.getenv("APP_NAME", "AI Website Categorizer"),
                env=os.getenv("APP_ENV", "development"),
                debug=get_env_bool("DEBUG", True)
            )

        # 2. DatabaseSettings
        if "db" not in values:
            url = os.getenv("DATABASE_URL") or "postgresql+asyncpg://user:password@localhost:5432/ai_crawler"
            values["db"] = DatabaseSettings(url=url)

        # 3. RedisSettings
        if "redis" not in values:
            url = os.getenv("REDIS_URL") or "redis://localhost:6379/0"
            values["redis"] = RedisSettings(url=url)

        # 4. CrawlerSettings
        if "crawler" not in values:
            values["crawler"] = CrawlerSettings(
                max_concurrent_workers=int(os.getenv("MAX_CONCURRENT_WORKERS", 5)),
                request_timeout=int(os.getenv("REQUEST_TIMEOUT", 30)),
                crawl_delay=float(os.getenv("CRAWL_DELAY", 1.0)),
                max_retries=int(os.getenv("MAX_RETRIES", 3)),
                max_depth=int(os.getenv("MAX_DEPTH", 10)),
                max_pages=int(os.getenv("MAX_PAGES", 5000)),
                respect_robots_txt=get_env_bool("RESPECT_ROBOTS_TXT", True),
                user_agent=os.getenv("USER_AGENT", "AI Categorizer Crawler Bot 1.0")
            )

        # 5. PlaywrightSettings
        if "playwright" not in values:
            values["playwright"] = PlaywrightSettings(
                headless=get_env_bool("PLAYWRIGHT_HEADLESS", True),
                timeout=int(os.getenv("PLAYWRIGHT_TIMEOUT", 30000))
            )

        # 6. LLMSettings
        if "llm" not in values:
            values["llm"] = LLMSettings(
                provider=os.getenv("LLM_PROVIDER", "openai"),
                api_key=os.getenv("OPENAI_API_KEY") or "mock_key_if_missing",
                model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", 500)),
                temperature=float(os.getenv("LLM_TEMPERATURE", 0.1)),
                budget_limit_usd=float(os.getenv("LLM_BUDGET_LIMIT_USD", 5.0))
            )

        # 7. EmbeddingSettings
        if "embedding" not in values:
            values["embedding"] = EmbeddingSettings(
                model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
                batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", 50))
            )

        # 8. ClassificationSettings
        if "classification" not in values:
            values["classification"] = ClassificationSettings(
                embedding_similarity_threshold=float(os.getenv("EMBEDDING_SIMILARITY_THRESHOLD", 0.85)),
                deterministic_confidence_threshold=float(os.getenv("DETERMINISTIC_CONFIDENCE_THRESHOLD", 0.90))
            )

        # 9. SecuritySettings
        if "security" not in values:
            values["security"] = SecuritySettings(
                max_payload_size_mb=int(os.getenv("MAX_PAYLOAD_SIZE_MB", 5))
            )

        super().__init__(**values)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__"
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()
