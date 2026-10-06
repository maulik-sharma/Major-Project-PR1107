# Architectural Design Patterns

## Core Patterns
1. **Adapter / Provider Pattern**: Encapsulate vendor-specific API variations behind a unified interface (`ChatAdapter`).
2. **Strategy / Router Pattern**: Dynamically evaluate incoming queries against cost, latency, or quality policies.
3. **Repository / Storage Abstraction**: Decouple domain entities from persistence engines (SQLite, Postgres, memory).
4. **Progressive Disclosure**: Load high-level catalogs in system prompts; load detailed instruction modules on demand.
