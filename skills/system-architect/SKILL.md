---
name: system-architect
description: Architectural patterns, distributed systems trade-offs, modular domain design, and API contracts.
---

# System Architecture Specialist

Guides high-level system design, boundary separation, scalability patterns, and data consistency models.

## Architectural Principles
1. **Separation of Concerns**: Enforce strict layering (UI -> Domain/Engine -> Providers/Adapters).
2. **Defensive Boundaries**: Validate all incoming payloads at boundary edges.
3. **Resilience & Fault Tolerance**: Design for graceful degradation, circuit breaking, and retry budgets.

## References
- See [Design Patterns](references/design_patterns.md) for adapter, factory, router, and event bus patterns.
- See [Architecture Trade-off Matrix](references/tradeoff_matrix.md) for consistency vs availability trade-offs.
