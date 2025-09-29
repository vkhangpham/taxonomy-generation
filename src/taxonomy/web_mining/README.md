# Web Mining — README (Developer Quick Reference)

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
- Detailed spec: `docs/modules/web-mining.md`.
- Related: `src/taxonomy/pipeline/s0_raw_extraction`, `src/taxonomy/observability`, `taxonomy.config`.

Maintenance
- Extend parsers/processors with tests in `tests/test_web_mining.py` and integration checks for policies.

