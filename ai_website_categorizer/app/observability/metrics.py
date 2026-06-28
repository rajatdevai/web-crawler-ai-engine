from prometheus_fastapi_instrumentator import Instrumentator, metrics
from prometheus_client import Counter, Histogram, Gauge

# Custom Counters
pages_discovered_total = Counter(
    "pages_discovered_total", 
    "Total number of pages discovered", 
    ["job_id"]
)

pages_crawled_total = Counter(
    "pages_crawled_total", 
    "Total number of pages successfully crawled", 
    ["job_id", "worker_id"]
)

pages_failed_total = Counter(
    "pages_failed_total", 
    "Total number of pages failed to crawl", 
    ["job_id", "worker_id"]
)

pages_classified_total = Counter(
    "pages_classified_total",
    "Total number of pages successfully classified",
    ["job_id", "method", "category"]
)

llm_calls_total = Counter(
    "llm_calls_total",
    "Total LLM categorization calls made",
    ["job_id"]
)

llm_tokens_used_total = Counter(
    "llm_tokens_used_total",
    "Total tokens consumed by LLM",
    ["job_id", "model"]
)

llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Total estimated cost in USD for LLM API",
    ["job_id"]
)

cache_hits_total = Counter(
    "cache_hits_total",
    "Total cache hits (e.g. content hash deduplication)",
    ["job_id"]
)

cache_misses_total = Counter(
    "cache_misses_total",
    "Total cache misses",
    ["job_id"]
)

# Custom Histograms
crawl_duration_seconds = Histogram(
    "crawl_duration_seconds",
    "Time taken to fetch a page",
    ["job_id", "domain"]
)

extraction_duration_seconds = Histogram(
    "extraction_duration_seconds",
    "Time taken to extract and clean content from HTML",
    ["job_id"]
)

embedding_duration_seconds = Histogram(
    "embedding_duration_seconds",
    "Time taken to generate embeddings",
    ["job_id"]
)

# Custom Gauges
queue_depth_gauge = Gauge(
    "queue_depth_gauge",
    "Current depth of the crawl queue",
    ["job_id", "queue_type"] # queue_type: main, retry, dead_letter
)

worker_active_gauge = Gauge(
    "worker_active_gauge",
    "Number of currently active workers",
    ["worker_id"]
)

def setup_metrics(app):
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics", "/health", "/health/ready"],
        env_var_name="ENABLE_METRICS"
    )
    # Expose custom metrics alongside fastapi default metrics
    instrumentator.instrument(app).expose(app, include_in_schema=False, should_gzip=True)
