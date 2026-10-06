---
trigger: always_on
---

# ModelMesh Workspace Rules

These rules apply to all agent interactions in this repository.

1. **Layering is law.** `core/` must never import PyQt. `ui/` may import `core/`, never the reverse. Provider-specific code lives **only** in `core/providers/`. Nothing outside an adapter may mention a provider by name.
2. **PyQt6 only.** Fully qualified enums (e.g. `Qt.AlignmentFlag.AlignCenter`). Use `pyqtSignal`/`pyqtSlot`.
3. **The UI thread never does I/O.** Workers run on `QThread` and talk to UI only via Qt signals carrying plain data (dicts/dataclasses).
4. **No asyncio, no qasync.** Threads (`QThread`) plus synchronous SDK streaming.
5. **Adding a model or OpenAI-compatible provider must require zero code changes.** Handle deviations with per-model quirks in config.
6. **Never hardcode model names, base URLs, prices, or API keys in source.** Models, URLs, and prices live in YAML config; keys live only in `.env`.
7. **Do not invent APIs.** Follow exact SDK specs.
8. **Scope discipline.** Edit only files relevant to the specific task.
9. **Tests pass and small commits.** Every task ends with `pytest` passing and clean verification.
10. **Files stay small** (aim under ~300 lines). Type hints everywhere, docstrings on public members, `pathlib`, UTF-8 encoding.
11. **Errors are normalized.** Use `ProviderError` with category and retryable flag.
12. **Candidate-based architecture.** Operations work on `Candidate` (Model + Endpoint) objects.
13. **A model is not a provider.** Model has endpoints; provider-specific data lives on the endpoint.
14. **A decision model is not a chat model.** Clef-flash never goes in `models:` in `providers.yaml`. It lives in `routing.yaml` and `core/routing/smart/decision/`.
15. **Scores are data, not config.** Never hardcode benchmark numbers in source or YAML. Everything comes from SQLite score snapshots.
16. **External-data hygiene.** AA snapshots stay in SQLite; synthetic fixtures in tests; attribution "Model scores: Artificial Analysis" displayed.
17. **Smart strategy never fails turn on decision failure.** Fall back to heuristic decision provider with `decision_source=heuristic_fallback`.
18. **Routing math is pure.** `scoring.py` and `selector.py` do no I/O; network happens in `DecisionService`.
19. **Privacy switch.** Never send user text if `send_prompt_text` is false. Truncate according to `max_state_tokens`.
20. **Do not guess API shapes.** Use response fixtures from Phase 0.
