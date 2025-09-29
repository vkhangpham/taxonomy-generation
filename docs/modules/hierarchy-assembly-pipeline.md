# Hierarchy Assembly Pipeline

This document specifies how verified concepts are assembled into a coherent, validated hierarchy.

## Scope

- `src/taxonomy/pipeline/hierarchy_assembly/assembler.py`
- `src/taxonomy/pipeline/hierarchy_assembly/main.py`
- `src/taxonomy/pipeline/hierarchy_assembly/graph.py`

## Components

- `HierarchyAssembler`: constructs the hierarchy and resolves parent-child links.
- `HierarchyGraph`: graph utilities for construction and traversal.
- `GraphValidator`: checks invariants (acyclic, connectivity, orphans).

## Data Flow

`Concept` → graph construction → parent resolution → placeholder/orphan handling → validation → `HierarchyAssemblyResult`

## Strategies

- Orphans: attach to nearest valid ancestor or quarantine based on policy.
- Placeholders: created when a referenced parent is missing but policy allows deferral.

## Outputs

- Final hierarchy index, validation report, and manifest with counts and invariants.

## Integration

- Invoked during orchestration finalization; emits artifacts referenced by the run manifest.

