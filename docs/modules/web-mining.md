# Web Mining — Logic Spec

Purpose
- Acquire institutional content safely and efficiently, producing normalized page snapshots for downstream S0 segmentation.

Core Tech
- Firecrawl v2.0 (SDK/API) as the unified fetch/render/crawl layer; no custom scrapers or browser automation.
- Built-in JS rendering for client-side apps; configurable timeouts and concurrency.
- Snapshot caching with TTL and checksum-based dedup to minimize re-fetching.

Scope
- Institutional domains only (and explicitly whitelisted subdomains). No custom scrapers or browser automation; use a unified fetch layer (e.g., Firecrawl-equivalent) that handles JS rendering.

Inputs/Outputs (semantic)
- Input: Seed configuration per institution: {institution_id, seed_urls[], allowed_domains[], disallowed_paths[], max_pages, max_depth, ttl_days}.
- Output: PageSnapshot[] with fields: {institution, url, canonical_url, fetched_at, http_status, content_type, html?, text, lang, checksum, meta{rendered:boolean, robots_blocked?:boolean, redirects?:[...], source:"provider"}}.

Rules & Invariants
- Robots and ethics: respect robots.txt and no-login/no-paywall constraints; abort on disallow.
- Politeness: rate limits, concurrency caps, exponential backoff on errors.
- Budgets: enforce per-institution caps (pages, depth, time, content size); stop cleanly when exceeded.
- Canonicalization: prefer canonical_url from <link rel="canonical">; normalize querystrings; consolidate trailing slashes.
- Deduplication: collapse snapshots with identical checksums across URLs; keep first seen; record alias_urls.
- Rendering: enable JS rendering only when needed (heuristics: empty body, heavy client-side apps).
- PDF/Docs: optionally extract text from PDFs when linked from allowed domains; record content_type and text origin; skip large binaries by size limit.

Core Logic
- Discovery
  - Initialize queue from seed_urls and/or sitemap.xml if available.
  - BFS by default with depth limit; prioritize URLs matching include patterns (e.g., "/departments", "/research").
  - Skip disallowed_paths and external domains unless explicitly whitelisted.
- Content Processing
  - Extract main text (readability heuristics) while keeping simple list structure markers.
  - Detect language; drop non-target languages unless specifically allowed for that institution.
  - Compute checksum over normalized text; store small excerpt for debugging.
- Dedup & Caching
  - Before fetch: consult cache by URL and TTL; short-circuit if fresh.
  - After fetch: check checksum-based dedup to avoid downstream duplication.

Failure Handling
- HTTP errors/timeouts → retry with backoff up to N attempts; record last error.
- robots.txt blocks → do not fetch; mark robots_blocked and continue.
- Excessive redirects or content size → abort fetch, record reason, skip URL.

Observability
- Counters: urls_queued, urls_fetched, robots_blocked, errors, rendered, deduped, pdf_extracted.
- Per-institution budgets: pages_used, depth_max_seen, time_spent.
- Sampling: store N example snapshots per institution for spot checks.

Acceptance Tests
- Given seeds for three institutions, crawler stops at max_pages and max_depth while respecting robots.txt.
- Duplicate content under different URLs collapses to one snapshot with alias_urls recorded.
- Client-side page with empty initial HTML triggers rendered=true with non-empty text.

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
    "meta": {"rendered": false, "source": "provider"}
  }
  ```

- Example C: Dedup across URLs
  - URLs: `/engineering/departments` and `/engineering/departments?ref=home` → same checksum → keep first; record alias_urls in meta.

Open Questions
- PDF policy: always extract text for allowed domains or only when no HTML alternative exists?
- Subdomain policy: do `labs.u1.edu` and `cs.u1.edu` count as allowed by default, or require explicit inclusion?
- Dynamic sites: when to give up on rendering due to heavy client-side hydration times?
