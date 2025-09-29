# Web Mining — README (Developer Quick Reference)

## Quick Reference

Purpose
- Crawl and process web content to produce normalized page snapshots for raw extraction; supports caching, robots.txt compliance, and optional JS rendering.

Key APIs
- Classes: `WebMiner` — orchestrates crawl queue, fetching, rendering, and processing.
- Classes: `CacheManager` — de-duplicates and persists fetched content with TTL.
- Classes: `ContentProcessor` — extracts text, detects language, normalizes metadata.
- Classes: `RobotsChecker` — enforces robots and rate limits.
- Functions: `build_web_miner(settings)` — factory configured from policies and paths.

Data Contracts
- Inputs: crawl configuration per institution `{institution_id, seed_urls[], allowed_domains[], disallowed_paths[], max_pages, max_depth, ttl_days}`.
- Outputs: PageSnapshot `{institution, url, canonical_url, fetched_at, http_status, content_type, text?, lang, checksum, meta{rendered?:bool, robots_blocked?:bool, redirects?:[...]}}`.

Quick Start
- Construct and run
  - `from taxonomy.web_mining.client import build_web_miner`
  - `wm = build_web_miner(settings)`
  - `snapshots = wm.crawl(institution_cfg)`

Configuration
- Policies govern budgets, timeouts, rendering enablement, and language thresholds; see `docs/policies.md` and `src/taxonomy/config/settings.py`.

Observability
- Counters for fetch attempts, cache hits, rendered fetches, robots blocks, and snapshot totals; stored in manifests.

Determinism
- Stable queueing with seeded ordering; cache keys and checksums ensure idempotent re-runs within TTL.

See Also
- Detailed spec: this README.
- Related: `src/taxonomy/pipeline/s0_raw_extraction`, `src/taxonomy/observability`, `taxonomy.config`.

Maintenance
- Extend parsers/processors with tests in `tests/test_web_mining.py` and integration checks for policies.

## Detailed Specification

### Web Mining — Logic Spec

Purpose
- Acquire institutional content safely and efficiently, producing normalized page snapshots for downstream S0 segmentation.

Core Tech
- Firecrawl v2 `scrape` API as the unified fetch/render/crawl layer; no custom scrapers or browser automation.
- Adaptive JS rendering fallback: perform a lightweight fetch first, then re-fetch with rendering when HTML is empty/client-side; mark snapshots as `meta.rendered=true`.
- Snapshot caching with TTL and checksum-based dedup to minimize re-fetching.

Scope
- Institutional domains only (and explicitly whitelisted subdomains). No custom scrapers or browser automation; use a unified fetch layer (e.g., Firecrawl-equivalent) that handles JS rendering.

Inputs/Outputs (semantic)
- Input: Seed configuration per institution: {institution_id, seed_urls[], allowed_domains[], disallowed_paths[], max_pages, max_depth, ttl_days}.
- Output: PageSnapshot[] with fields: {institution, url, canonical_url, fetched_at, http_status, content_type, html?, text, lang, checksum, meta{rendered:boolean, robots_blocked?:boolean, redirects?:[...], source:"provider"}}.

Rules & Invariants
- Robots and ethics: respect robots.txt and no-login/no-paywall constraints; abort on disallow.
- Politeness: rate limits, concurrency caps, and optional crawl-delay compliance (respect robots delay only when `respect_crawl_delay` is true).
- Budgets: enforce per-institution caps (pages, depth, time, content size); stop cleanly when exceeded.
- Canonicalization: prefer canonical_url from <link rel="canonical">; normalize querystrings; consolidate trailing slashes.
- Deduplication: collapse snapshots with identical checksums across URLs; keep first seen; persist `meta.alias_urls` with every alias.
- Rendering: enable JS rendering only when needed (heuristics: empty body, heavy client-side apps) and mark `meta.rendered=true` on rendered snapshots.
- PDF/Docs: optionally extract text from PDFs; enforce `pdf_size_limit_mb` before parsing to avoid oversized payloads.
- Content Policy: enforce `min_text_length` and language allowlists (with confidence thresholds); violations raise `content_policy` crawl errors and skip the page.

Core Logic
- Discovery
  - Initialize the crawl queue from `seed_urls`; augment with robots-advertised sitemaps (depth=1) when available and within configured budgets.
  - BFS by default with depth limit; URLs matching `include_patterns` are enqueued ahead of others to bias traversal toward high-value sections (e.g., "/departments", "/research").
  - Skip disallowed_paths and external domains unless explicitly whitelisted.
- Content Processing
  - Extract main text (readability heuristics) while keeping simple list structure markers and resolving canonical URLs relative to the page base.
  - Detect language; enforce allowlists using the configured confidence threshold, raising `content_policy` errors for violations.
  - Enforce minimum text length and PDF size limits; skip pages with insufficient content via `content_policy` errors.
  - Compute checksum over normalized text; store small excerpt for debugging.
- Dedup & Caching
  - Before fetch: consult cache by URL and TTL; each crawl threads `CrawlConfig.ttl_days` through the cache so entries respect per-run expiry, short-circuiting when snapshots are still fresh.
  - After fetch: check checksum-based dedup to avoid downstream duplication.

Failure Handling
- HTTP errors/timeouts → retry with backoff up to the configured attempt budget; classify crawl errors as retryable.
- robots.txt blocks → do not fetch; mark robots_blocked and continue.
- Excessive redirects or declared content size over budget → abort fetch early and record `content_policy` errors.
- Content policy violations (language, min text, PDF size) → raise `content_policy` crawl errors and continue without snapshot.

Observability
- Counters: urls_queued, urls_fetched, robots_blocked, errors, rendered; `deduped` increments when cache merges duplicate URLs and `pdf_extracted` tracks successful PDF processing.
- Per-institution budgets: pages_used, depth_max_seen, time_spent.
- Sampling: store N example snapshots per institution for spot checks.

Acceptance Tests
- Given seeds for three institutions, crawler stops at max_pages and max_depth while respecting robots.txt.
- Duplicate content under different URLs collapses to one snapshot with alias_urls recorded.
- Client-side page with empty initial HTML triggers rendered=true with non-empty text.
- Pages below `min_text_length` or in disallowed languages surface `content_policy` errors and are excluded from snapshots.
- When `respect_crawl_delay` is false, robots crawl-delay hints are ignored; when true, the crawler sleeps accordingly.

Examples
- Example A: Seed configuration
  ```json
  {
    "institution_id": "u1",
    "seed_urls": [
      "https://u1.edu/engineering/",
      "https://u1.edu/engineering/departments/"
    ],
    "allowed_domains": ["u1.edu"],
    "disallowed_paths": ["/login", "/search"],
    "max_pages": 300,
    "max_depth": 3,
    "ttl_days": 14
  }
  ```

- Example B: PageSnapshot (HTML → text)
  ```json
  {
    "institution": "u1",
    "url": "https://u1.edu/engineering/departments",
    "canonical_url": "https://u1.edu/engineering/departments",
    "http_status": 200,
    "content_type": "text/html",
    "fetched_at": "2025-09-27T10:00:00Z",
    "text": "Departments\nComputer Science\nElectrical & Computer Engineering",
    "lang": "en",
    "checksum": "sha256:abcd...",
    "meta": {"rendered": false, "source": "provider", "alias_urls": ["https://u1.edu/engineering/departments"]}
  }
  ```

- Example C: Dedup across URLs
  - URLs: `/engineering/departments` and `/engineering/departments?ref=home` → same checksum → keep first; record alias_urls in meta.

Open Questions
- PDF policy: always extract text for allowed domains or only when no HTML alternative exists?
- Subdomain policy: do `labs.u1.edu` and `cs.u1.edu` count as allowed by default, or require explicit inclusion?
- Dynamic sites: when to give up on rendering due to heavy client-side hydration times?

