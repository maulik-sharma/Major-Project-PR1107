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
