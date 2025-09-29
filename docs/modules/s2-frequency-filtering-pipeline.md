# S2 Frequency Filtering Pipeline

This document specifies the frequency-based consolidation that filters `Candidate` inputs using occurrence and support thresholds.

## Scope

- `src/taxonomy/pipeline/s2_frequency_filtering/processor.py`
- `src/taxonomy/pipeline/s2_frequency_filtering/main.py`
- `src/taxonomy/pipeline/s2_frequency_filtering/aggregator.py`

## Components

- Frequency aggregator: groups candidates, computes counts, and institution support metrics.
- Filtering processor: applies thresholds per level and emits filtered candidates and stats.

## Data Flow

`Candidate` → aggregate frequency/support → apply thresholds → filtered `Candidate`

## Thresholds & Policies

- Level-specific minimum count.
- Optional institution-based weighting to prefer broadly supported tokens.

## Checkpointing

- Phase-level checkpoint after filtering completes; includes summary stats and drop reasons.

## CLI

- `pipeline generate --step S2 --level <0..3>`
- Entry: `filter_by_frequency()` in `main.py`.

## Example

```json
{
  "token": "python",
  "level": 1,
  "count": 3,
  "institutions": ["A", "B"]
}
```
→ kept when `count >= min_count[level]` and support is sufficient; otherwise dropped with reason.

