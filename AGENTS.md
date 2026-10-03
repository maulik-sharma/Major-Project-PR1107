# ModelMesh Standing Rules for AI Agents

1. **Layering is law.** `core/` must never import PyQt. `ui/` may import `core/`, never the reverse. Provider-specific code (OpenAI-format vs Anthropic-format) lives **only** in `core/providers/`. Nothing outside an adapter may mention a provider by name.
2. **PyQt6 only.** Never mix in PyQt5 idioms. Use fully qualified enums (e.g. `Qt.AlignmentFlag.AlignCenter`, not `Qt.AlignCenter`). Use `pyqtSignal`/`pyqtSlot`.
3. **The UI thread never does I/O.** No network, disk-heavy work, or tool execution on the main thread. Workers talk to the UI only through Qt signals carrying plain data (dicts or dataclasses). Never touch a widget from a worker thread.
4. **No asyncio, no qasync.** Use threads (`QThread`) plus synchronous SDK streaming. The only exception is the optional MCP client (isolated in its own thread with its own event loop).
5. **Adding a model or an OpenAI-compatible provider must require zero code changes.** If a task seems to need an `if provider == ...` branch, it belongs in config (`quirks`) or in an adapter. Stop and report instead of adding the branch.
6. **Never hardcode model names, base URLs, prices, or API keys in source.** Models, URLs, and prices live in YAML config; keys live only in the git-ignored `.env` file. Never log, print, commit, or quote the contents of `.env`, and never open or read it unless the task is specifically about key handling. Scrub keys from error messages.
7. **Do not invent APIs.** If unsure about a provider's request or response shape, read its official docs or ask. Do not guess parameter names.
8. **Scope discipline.** Implement only the task you were given. List the files you intend to touch before editing. Do not refactor unrelated files, add dependencies, or rename things without asking.
9. **Every task ends with:** tests passing (`pytest`), a short note of what changed, and a git commit. Small commits, one per task.
10. **Files stay small** (aim under about 300 lines). Type hints everywhere. Docstrings on every public class and function. Use `pathlib`, explicit `utf-8`, and `QStandardPaths` for app data locations (Windows-safe).
11. **Errors are normalized.** Adapters convert every provider failure into a `ProviderError` with a category (`auth`, `rate_limit`, `context_length`, `bad_request`, `network`, `server`, `unknown`) and a `retryable` flag. UI shows friendly messages, never raw tracebacks.
12. **Every new feature gets a capability flag or registry entry,** not a special case in the chat engine.
13. **A model is not a provider.** A logical **Model** (identity, tier, default capabilities) can have several **Endpoints** (one per provider that serves it, each with its own `api_model` string, price, and limits). Provider-specific data (`api_model`, prices, quirks, region) lives on the endpoint, never on the model. The router, engine, and adapters operate on **Candidates** (a model plus one endpoint), never on bare models.
