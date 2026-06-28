# 🕷️ AI Website Page Categorizer Automation Engine

An enterprise-grade, distributed website crawler and intelligent categorization platform powered by **Python**, **FastAPI**, **Playwright**, **PostgreSQL (with pgvector)**, **Redis**, and **OpenAI**. 

This system dynamically crawls websites, extracts structured content, generates vector embeddings, and classifies pages into business-relevant categories using a multi-stage deterministic, semantic, and generative AI hierarchy.

---

## 📖 Table of Contents
1. [System Overview & Key Features](#system-overview--key-features)
2. [Deep-Dive Architecture of Each Component](#deep-dive-architecture-of-each-component)
   - [FastAPI Web Server Gateway](#1-fastapi-web-server-gateway)
   - [Database Schema & Models (PostgreSQL + pgvector)](#2-database-schema--models-postgresql--pgvector)
   - [Distributed Queueing & Broker Architecture (Redis)](#3-distributed-queueing--broker-architecture-redis)
   - [Distributed Background Workers](#4-distributed-background-workers)
   - [Real-time Events & Log Streaming](#5-real-time-events--log-streaming)
3. [Crawling Fundamentals & Execution Pipeline](#-crawling-fundamentals--execution-pipeline)
4. [The Multi-Stage Classification Engine](#-the-multi-stage-classification-engine)
5. [Approach, Planning & Implementation Lifecycle](#-approach-planning--implementation-lifecycle)
6. [Prerequisites & Environment Variables](#-prerequisites--environment-variables)
7. [Installation & Local Setup](#-installation--local-setup)
8. [API Reference & Usage Examples](#-api-reference--usage-examples)
9. [Performance, Scalability & Hardening](#-performance-scalability--hardening)

---

## 🌟 System Overview & Key Features

The **AI Website Page Categorizer** is designed to automatically map and organize crawled pages of large web portals under coherent classifications (e.g. mapping Gummies, Capsules, Softgels, Blogs, or Regulatory pages under their respective categories for a manufacturer).

### Core Features:
* **Hybrid Crawling Engine**: Supports fast static HTML extraction alongside an on-demand Playwright headless browser rendering fallback to execute JavaScript.
* **Smart Section Filters**: Constrains crawls to specific path prefixes (e.g., `/private-label`) to optimize crawls and avoid indexing irrelevant pages.
* **Three-Tier Classification Pipeline**: Employs keyword matching (Deterministic), Vector similarity search (Semantic), and LLM classification (Generative GPT-4o-mini) fallback.
* **High-Performance Vector Pipeline**: Utilizes OpenAI `text-embedding-3-small` and PostgreSQL `pgvector` index queries to perform ultra-fast category matching.
* **Real-time Log Streaming**: Uses Redis PubSub to stream backend worker events directly to the client dashboard.
* **Rich Glassmorphic Dashboard**: A premium, responsive interface featuring dynamic job creation, crawl metrics, real-time logging, and interactive classification reasoning popups.

---

## 🏗️ Deep-Dive Architecture of Each Component

The application is structured around a decoupled, event-driven, service-oriented architecture:

```mermaid
graph TD
    Client[REST API & Dashboard] -->|HTTP / WebSocket| API[FastAPI Gateway]
    API -->|Read/Write Jobs & Pages| DB[(Neon PostgreSQL + pgvector)]
    API -->|Publish Events / Queue Tasks| Redis[(Upstash Redis Cache & Broker)]
    
    subgraph Background Workers (Managed by WorkerDaemonManager)
        CrawlWorker[Crawl Worker] -->|Fetch & Extract Links| Frontier[Redis: Crawl Frontier]
        CrawlWorker -->|Push Extracted Text| DB
        CrawlWorker -->|Trigger Embedding| EmbedQueue[Redis: Embedding Queue]
        
        EmbedWorker[Embedding Worker] -->|Pop Pointer| EmbedQueue
        EmbedWorker -->|Call OpenAI API| OpenAIEmbed[text-embedding-3-small]
        EmbedWorker -->|Store Embedding Vector| DB
        EmbedWorker -->|Trigger Classification| CatQueue[Redis: Categorization Queue]
        
        CatWorker[Categorizer Worker] -->|Pop Pointer| CatQueue
        CatWorker -->|Deterministic Rule Match| DB
        CatWorker -->|Semantic DB Vector Query| DB
        CatWorker -->|Fallback LLM Generation| OpenAILLM[gpt-4o-mini]
        CatWorker -->|Commit Classified Status| DB
    end
    
    CrawlWorker -.->|Publish Logs| Redis
    EmbedWorker -.->|Publish Logs| Redis
    CatWorker -.->|Publish Logs| Redis
    Redis -.->|Stream Logs| API
```

### 1. FastAPI Web Server Gateway
Located in `app/api/router.py` and `app/api/v1/jobs.py`, the API Gateway handles request routing, inputs validation, job spawning, and dashboard status querying.
* **Job Submission (`POST /api/v1/crawl`)**: Validates the seed URL, inserts a pending `CrawlJob` in the DB, and pushes a startup task to Redis.
* **Job Progress Tracker (`GET /api/v1/jobs/{id}`)**: Returns live metrics (pages discovered, crawled, failed, progress percentage, active worker count, ETA, elapsed time).
* **Classified Pages List (`GET /api/v1/jobs/{id}/pages`)**: Retrieves pages filtered by classification status. Now enhanced to serialize `classification_method` and `reasoning`.
* **Event Stream (`GET /api/v1/jobs/{id}/logs`)**: Long-polls/streams the latest log entries published to Redis PubSub.

### 2. Database Schema & Models (PostgreSQL + pgvector)
Defined in `app/models/`, using SQLAlchemy ORM to manage three main schemas:
* **`CrawlJob` (`app/models/job.py`)**: Stores metadata about a run (current status, seed URL, path prefixes, total count counters, configuration limits, start/end timestamps, error summaries).
* **`Page` (`app/models/page.py`)**: Represents a crawled webpage. Tracks depth, HTTP response code, render method (static vs. browser), content hash, the full raw text in JSONB, and a `classification_result` JSONB column storing details like `final_category`, `final_confidence`, `classification_method`, and `reasoning`.
* **`Category` (`app/models/category.py`)**: Defines categories configured for the system or custom-injected per job, mapping them to predefined vector centroids.

### 3. Distributed Queueing & Broker Architecture (Redis)
We use Redis (supporting both local instances and Upstash cloud) as an asynchronous message queue, locking service, and pub/sub broker:
* **Crawl Frontier**: Managed in `app/crawler/frontier.py` using Redis sorted sets (ZSET) to implement breadth-first search (BFS) queues. It tracks visited URLs and handles loop detection, robots.txt exclusions, and domain scopes.
* **Workers Pipelines**: Backed by list structures acting as FIFO queues (`embedding_queue:{job_id}`, `categorization_queue:{job_id}`).
* **PubSub Broker**: Receives real-time log lines from background workers and pushes them to the FastAPI SSE/polling log tracker.

### 4. Distributed Background Workers
The background processing lifecycle is orchestrated by `app/workers/manager.py` (the **WorkerDaemonManager**), which boots and monitors the lifecycles of three asynchronous worker loops:
* **Crawl Worker (`app/workers/crawl_worker.py`)**:
  * Extracts URLs matching domain and prefix restrictions.
  * Discovers pages and feeds links back to the frontier queue.
  * Captures inner text from HTML nodes, saves it, and pushes the page ID to the embedding worker's queue.
* **Embedding Worker (`app/workers/embedding_worker.py`)**:
  * Chunks text content to fit token constraints.
  * Interacts with OpenAI's `text-embedding-3-small` API to get a 1536-dimensional vector.
  * Commits the embedding vector to the database and queues the page ID for categorization.
* **Categorization Worker (`app/workers/categorizer_worker.py`)**:
  * Pulls the page ID and applies the categorization hierarchy to determine the best label.
  * Persists the categorization results in the database and updates job metrics.

### 5. Real-time Events & Log Streaming
Workers issue standard structural logs that are interceptable. They publish these entries to a Redis channel named `job_logs:{job_id}`. The client-side dashboard subscribes to this channel using a polling query loop on `/logs`, capturing a live scrolling terminal feed of the crawl's internal process.

---

## 🕸️ Crawling Fundamentals & Execution Pipeline

The crawler module is designed based on production crawling standards, incorporating automated path optimization, dynamic rendering fallbacks, and real-time execution statistics.

### 1. Traditional Crawling Loop vs. Our Implementation
Every standard web crawler follows a basic four-step processing cycle:
```
Download HTML ──> Parse DOM ──> Extract Links & Text ──> Enqueue & Repeat
```
The platform uses **Breadth-First Search (BFS)** to traverse the site structure level-by-level (e.g. `Home` -> `Products/Blog/About` -> `Individual Category Pages` -> `Leaf Nodes`). This structure represents site navigation hierarchies much better than Depth-First Search (DFS).

### 2. Robots.txt and Sitemap Parsing
To respect target websites and accelerate URL discovery:
* **robots.txt**: The crawler first queries `https://website.com/robots.txt` to respect disallowed paths (such as `/admin` or `/checkout`) and parse the host crawler delay policies.
* **sitemap.xml**: If a sitemap URL is listed in robots.txt or found at standard routes, the crawler parses it to instantly seed the BFS queue, avoiding redundant page discovery loops.

### 3. Static Parsing vs. JavaScript Rendering (Hybrid Engine)
Traditional crawlers (like `requests` or `httpx` with `BeautifulSoup`) only download static HTML. However, modern Single Page Applications (SPAs) built with React, Vue, or Angular return empty root templates (e.g., `<div id="root">Loading...</div>`), loading content asynchronously via API requests.
* **Static Content**: Checked first. If the page is server-side rendered (SSR), it is parsed quickly via BeautifulSoup.
* **Dynamic Content**: If the HTML lacks content, the crawler hands the URL to a pooled **Playwright** browser context. Playwright loads the page, executes scripts, and captures the fully rendered DOM tree.

### 4. Dynamic UI Progress & Section Filters
To ensure the UI is fully dynamic and never appears stuck, we implement:
* **Section Filter Config**: Users can filter crawls by path prefix (e.g. `/private-label`). The crawler drops any link outside this path, preventing crawls from extending infinitely.
* **ETA Progress Bar**: The backend measures crawl rate (pages/sec) and remaining pages to output a dynamic progress percentage ($\min(100, (\text{crawled}/\text{discovered}) \times 100)$) and rate-based estimated time of completion (ETA).
* **Actionable Logging**: Terminal screens stream clean logs focusing on milestone actions (e.g. `Discovered URL`, `Categorized [Gummies] (llm)`) instead of raw technical trace dumps.

---

## 🧠 The Multi-Stage Classification Engine

Categorizing web pages reliably at scale requires balancing cost, speed, and accuracy. The Categorizer Worker (`app/categorizer/`) solves this using a **3-stage fallback architecture**:

```
[Page Content]
      │
      ▼
┌──────────────┐      Match?      ┌──────────────────────┐
│  Stage 1:   ├─────────────────>│ Categorized!         │
│Deterministic │                  │ Method: Deterministic│
└──────┬───────n                  └──────────────────────┘
       │ No match
       ▼
┌──────────────┐      Match?      ┌──────────────────────┐
│  Stage 2:   ├─────────────────>│ Categorized!         │
│  Semantic    │   (Confidence   │ Method: Embedding    │
│  Similarity  │     > 0.85)      └──────────────────────┘
└──────┬───────┘
       │ No match
       ▼
┌──────────────┐                  ┌──────────────────────┐
│  Stage 3:   ├─────────────────>│ Categorized!         │
│ Generative   │                  │ Method: LLM          │
│  LLM (GPT)   │                  └──────────────────────┘
└──────────────┘
```

1. **Stage 1: Deterministic Signals** (`app/categorizer/deterministic.py`)
   * Scrapes metadata (URL slug, Title, Header tags) for exact keyword matches.
   * Highly accurate for distinct paths (e.g. `/blog/` -> Blog, `/private-label/` -> Services).
   * Negligible latency and zero cost.
2. **Stage 2: Semantic Similarity** (`app/categorizer/embedding.py`)
   * Projects the page text into high-dimensional vector space.
   * Performs a Cosine Distance lookup in PostgreSQL against the average embedding vector (centroid) of target categories.
   * Matches pages that share thematic language patterns even if spelling differs. If similarity exceeds a threshold (e.g., `0.85`), the category is committed immediately.
3. **Stage 3: Generative LLM Fallback** (`app/categorizer/llm_classifier.py`)
   * For complex, ambiguous, or multi-topic pages, content is passed to `gpt-4o-mini`.
   * Prompts instruct the LLM to output a strictly structured JSON response containing:
     * `final_category`: Selected category.
     * `final_confidence`: Probability float.
     * `reasoning`: Bulleted explanation justifying the decision.
     * `needs_human_review`: Boolean indicating low confidence or ambiguity.

---

## 🚀 Approach, Planning & Implementation Lifecycle

The engine was developed using a rigorous pair-programming iteration methodology divided into key technical phases:

### Phase 1: Local Setup & SQLite Core
* Initialized the Python structure using **Poetry** to manage dependency locks.
* Bootstrapped a prototype with SQLite/JSON1 extensions to store raw pages and job states locally.
* Created deterministic and simple crawl filters.

### Phase 2: Distributed Upgrades (Postgres + Redis)
* Migrated from SQLite to a robust **PostgreSql** Neon instance. Included `pgvector` extension capabilities.
* Integrated **Alembic** migrations to manage schema transitions (`alembic upgrade head`).
* Replaced local async queues with a robust distributed Redis layout, solving concurrency and resource constraints.

### Phase 3: Crawl Optimization & Resiliency
* Configured proper `User-Agent` spoofing and headers.
* Overcame local queue conflicts by implementing a robust process manager daemon (`WorkerDaemonManager`) that starts and stops loops safely.
* Programmed zombie process cleanups to release connections on restart.

### Phase 4: UI Refinement & API Enhancements (The Frontend Fix)
* **API Extension**: Added serialization for `classification_method` and `reasoning` inside the `/pages` route to fetch live categorization reasons.
* **Dynamic Modals**: Designed custom glassmorphic modals on the dashboard frontend. When a user clicks `View Reason`, the exact AI reasoning from the LLM classification stage is loaded.
* **Method Badge Colors**: Assigned colors for each classification method (`LLM` in purple, `Deterministic` in blue, `Embedding` in green) to make inspection visually simple.

---

## 🛠️ Prerequisites & Environment Variables

### Requirements:
* **Python**: `^3.11`
* **Redis Server**: Standard local instance or Upstash cloud URL.
* **PostgreSQL Database**: Postgres v12+ with `pgvector` support.
* **OpenAI API Key**: Required for embeddings generation and LLM classifications.

### Environment Setup (`.env`):
Create a file named `.env` in `ai_website_categorizer/`:
```ini
APP_ENV=development
DATABASE_URL=postgresql+asyncpg://neondb_owner:YOUR_PASS@YOUR_HOST/neondb
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=sk-proj-YOUR_API_KEY
MAX_PAGES=120
MAX_DEPTH=3
RESPECT_ROBOTS_TXT=True
```

---

## 🚀 Installation & Local Setup

1. **Clone & Enter Directory**:
   ```bash
   cd ai_website_categorizer
   ```

2. **Install Dependencies via Poetry**:
   ```bash
   poetry install
   ```

3. **Install Playwright Browsers**:
   ```bash
   poetry run playwright install chromium
   ```

4. **Run Database Migrations**:
   ```bash
   poetry run alembic upgrade head
   ```

5. **Start Web Server (FastAPI)**:
   ```bash
   poetry run uvicorn app.api.router:app --port 8000
   ```

6. **Start Workers Daemon Manager**:
   Open a separate shell and run:
   ```bash
   poetry run python -m app.workers.manager
   ```

7. **Access Dashboard**:
   Open your browser and navigate to: `http://localhost:8000/`

---

## 📡 API Reference & Usage Examples

### 1. Submit a New Crawl Job
Start a website crawl and classification session:
* **URL**: `/api/v1/crawl`
* **Method**: `POST`
* **Payload**:
```json
{
  "url": "https://www.makersnutrition.com/",
  "max_pages": 40,
  "max_depth": 2,
  "respect_robots_txt": true,
  "allowed_path_prefix": "/private-label"
}
```
* **Example curl**:
```bash
curl -X POST http://localhost:8000/api/v1/crawl \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.makersnutrition.com/","max_pages":40}'
```

### 2. Query Job Status
* **URL**: `/api/v1/jobs/{job_id}`
* **Method**: `GET`
* **Response**:
```json
{
  "job_id": "eb2f2801-7cab-493c-a426-553c2b4a0779",
  "status": "COMPLETED",
  "url": "https://www.makersnutrition.com/",
  "pages_discovered": 41,
  "pages_crawled": 41,
  "pages_classified": 41,
  "progress_pct": 100
}
```

### 3. Fetch Classified Results
Retrieves the list of classified pages for a job:
* **URL**: `/api/v1/jobs/{job_id}/pages?status=CLASSIFIED&page_size=100`
* **Method**: `GET`
* **Response Snippet**:
```json
{
  "total_count": 41,
  "page": 1,
  "page_size": 100,
  "pages": [
    {
      "url": "https://www.makersnutrition.com/private-label/gummies",
      "category": "Gummies",
      "confidence": 0.95,
      "classification_method": "deterministic",
      "reasoning": "Matched deterministic signal in path prefix /private-label/gummies."
    },
    {
      "url": "https://www.makersnutrition.com/press/trends",
      "category": "Blog",
      "confidence": 0.90,
      "classification_method": "llm",
      "reasoning": "The content discusses trends in the supplement industry, which aligns with typical blog topics."
    }
  ]
}
```

---

## 🛡️ Performance, Scalability & Hardening

* **Process Isolation**: The Workers Daemon Manager launches the crawler, embedder, and classifier loop in dedicated sub-processes. Memory leaks or loop blockages in Playwright do not impact API routing responsiveness.
* **Prompt Injection Shield**: `app/categorizer/llm_classifier.py` runs defensive regular expression checks against input texts to filter out prompts containing injection strings (such as instructions to ignore previous instructions) before sending them to the OpenAI API.
* **Token Pruning**: Text content is dynamically token-counted using tiktoken and truncated to ensure compatibility with LLM context windows, keeping prompt costs low.
* **SQL Injection Prevention**: All queries to Postgres databases are fully parameterized using SQLAlchemy’s modern query model.
