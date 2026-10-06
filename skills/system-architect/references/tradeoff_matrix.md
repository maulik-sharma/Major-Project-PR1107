# Architecture Trade-off Matrix

## Common Trade-off Vectors

| Paradigm | Primary Benefit | Primary Cost / Risk | Mitigation Strategy |
|---|---|---|---|
| Monolith | Simplicity, single deploy | Coupling over time | Strict internal module boundaries |
| Microservices | Independent scaling | Distributed failure modes | Strong observability, circuit breaking |
| Event-Driven | Decoupled asynchronous flow | Eventual consistency debugging | Idempotency keys, dead letter queues |
| In-Memory Cache | Sub-millisecond latency | Cache invalidation complexity | TTL expiration, write-through caching |
