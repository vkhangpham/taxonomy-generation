# Pipeline Data Flow

This document traces artifacts across S0–S3 and assembly, defining the semantic contracts and example JSON payloads for each type.

## Scope

- Entities: `src/taxonomy/entities/core.py`
- Reference: `docs/logic-spec.md`

## Artifact Types

- `PageSnapshot` (input): raw page content and metadata.
- `SourceRecord` (S0 output): segmented, filtered text units with provenance.
- `Candidate` (S1 output): normalized tokens with counts and optional parents.
- `Concept` (S3 output): verified candidates with confidence and reasons.
- `Hierarchy` (final): assembled, validated graph with manifest.

## Example Payloads

```json
// PageSnapshot
{"snapshot_id":"s1","url":"https://ex.org","content":"...","lang":"en"}

// SourceRecord
{"record_id":"s1-0","text":"Intro...","metadata":{"lang":"en","snapshot_id":"s1"}}

// Candidate
{"token":"python","level":1,"count":3,"parents":["programming-language"]}

// Concept
{"token":"python","level":1,"confidence":0.94,"reasons":["passes-rules","llm-positive"]}

// Hierarchy (simplified)
{"nodes":[{"id":"programming-language"},{"id":"python","parent":"programming-language"}]}
```

## Serialization & Layout

- JSONL for streaming artifacts, parquet where configured for analytics.
- File naming: phase- and level-scoped prefixes; deterministic sharding for large outputs.

## Contracts

- Required fields must be present at each handoff; optional metadata is preserved when available.
- Canonical forms (ASCII, casing) are maintained after S1 normalization.

## Related

- S0–S3 and assembly module docs under `docs/modules/*`.

