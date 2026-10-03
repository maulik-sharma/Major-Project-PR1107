# ModelMesh Desktop Client: Midterm Build Plan

> Audience: the developer and any AI coding agent working in this repo.
> Scope: a 4-day build for the midterm evaluation. No code is included here on purpose; this is the specification the code must follow.
> How to use: put **Part A** into `AGENTS.md` at the repo root (copy to `CLAUDE.md` / `.cursor/rules` if your IDE needs it). Keep the rest as `docs/PLAN.md`. When prompting an agent, point it at one task ID (Part N) and the sections it references. Do not paste the whole file into every prompt.

---

## Part A. Standing rules for AI agents (copy into AGENTS.md)

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
13. **A model is not a provider.** A logical **Model** (identity, tier, default capabilities) can have several **Endpoints** (one per provider that serves it, each with its own `api_model` string, price, and limits). Provider-specific data (`api_model`, prices, quirks, region) lives on the endpoint, never on the model. The router, engine, and adapters operate on **Candidates** (a model plus one endpoint), never on bare models. See Part 6.

---

## Part 1. Context and goal

**Full project (from the synopsis):** a multi-tenant LLM router platform: one platform-issued private key, a pool of subscribed models, a query-difficulty classifier with threshold routing, a prompt cache, an OpenAI-compatible gateway, and evaluation against baselines.

**Midterm deliverable (this plan):** a **desktop chat client plus a UI-independent router core** that:
- connects to many LLM providers through a config-driven model registry,
- offers a modern chat experience (streaming, markdown, attachments, tool use, and more),
- implements the three mandatory baseline routers: **random, cheapest-first, expensive-first**,
- logs every routing decision with tokens, cost, and latency (this log becomes the evaluation dataset later).

**Why this lines up with the synopsis:** Methodology step 1 (model pool plus the three baselines) and the logging layer are exactly this. The classifier, semantic cache, multi-tenant key issuing, and OpenAI-compatible gateway come after the midterm. Because `core/` has no UI dependency, the later gateway is a thin FastAPI wrapper around the same code, so nothing built now is throwaway. Be upfront with evaluators: in this version the user supplies provider keys locally, standing in for the "platform-held subscriptions".

**Honest framing of the baselines:** random, always-cheap, and always-expensive are non-adaptive on purpose. They are the reference lines the future classifier must beat on the cost-quality curve. Quality will not be preserved by them; that is expected.

---

## Part 2. Technology decisions (already made)

| Area | Decision | Why |
|---|---|---|
| Language | Python 3.11 or newer | You know it; agents are strongest in it |
| GUI | **PyQt6** | Good choice. Real threads, rich widgets, QSS styling. Main risks are threading and chat rendering, both mitigated below. (PySide6 is near-identical; pick one and never mix.) |
| Chat transcript rendering | **QWebEngineView** with bundled `marked`, `highlight.js`, `DOMPurify` (KaTeX optional). All other UI uses native Qt widgets | Native per-message widgets with auto-height, markdown, code blocks, and streaming are a time sink. HTML/CSS gives a ChatGPT-like look quickly and agents are very good at it. Requires the `PyQt6-WebEngine` package |
| Fallback renderer | `QTextBrowser` plus the `markdown` and `pygments` packages | Use only if WebEngine causes problems. Time-box WebEngine setup to 2 hours on Day 2 |
| HTTP/LLM clients | Official `openai` SDK (with `base_url` override) for all OpenAI-compatible providers; official `anthropic` SDK for Claude; `boto3` (optional, only if you build the AWS Bedrock adapter). Synchronous streaming in worker threads | SDKs handle SSE parsing and retries, so less hand-written streaming code to get wrong |
| Concurrency | Threads plus Qt signals | Mixing asyncio with Qt (qasync) is a classic source of agent-generated bugs |
| Config | YAML (`pyyaml`), validated with `pydantic` v2 | Human-editable, and the Settings UI can write it |
| Secrets | `python-dotenv`: keys in a git-ignored `.env` file, referenced from YAML by variable name (`auth_env` list on each provider). No keyring | Simple during development, and the same pattern a server-side gateway would use later. Keys never touch YAML, the DB, or git |
| Storage | stdlib `sqlite3`, no ORM | Simple, inspectable, one file |
| Tests | `pytest`, plus `respx` for mocked HTTP | Offline and deterministic |
| Env | venv plus pinned `requirements.txt` | Reproducible for agents |

**Explicitly rejected:** LangChain (abstraction hides bugs; the routing and provider layer is *your* project), LiteLLM (it would do the core of your project for you and weaken the evaluation story; keep it only as an emergency escape hatch), Electron or web UI (new stack, new bugs), ORMs, packaging with PyInstaller before the midterm (run from source).

**Is PyQt the right call?** Yes. The only credible alternative is a local web UI (FastAPI plus browser), which would look polished faster but forces a JS toolchain you would have to debug. Stay with PyQt6.

---

## Part 3. Architecture

```
┌──────────────────────────── ui/ (PyQt6) ────────────────────────────┐
│ MainWindow · Sidebar · ChatView (WebEngine) · Composer · Settings    │
│ Dialogs · Usage view · Router Lab                                     │
└───────────────▲───────── Qt signals / slots (plain data) ───┬────────┘
                │                                              ▼
        ┌───────┴──────────── ui/workers.py (QThread) ─────────────┐
        │ runs ChatEngine.run_turn() off the UI thread, forwards    │
        │ each yielded event as a signal; owns the cancel Event     │
        └───────────────────────────┬───────────────────────────────┘
┌──────────────────────────── core/ (NO Qt imports) ───────────────────┐
│ ChatEngine ─► Router ─► ProviderAdapter ─► openai SDK / anthropic SDK │
│     │            ▲            ▲                                        │
│     ▼            │            │                                        │
│ ToolRegistry   Registry     Mock adapter (tests + offline demo)        │
│ SkillLoader    (YAML)       Cache (stretch)                            │
│ Storage (SQLite) · CostMeter · RoutingLog                              │
└────────────────────────────────────────────────────────────────────────┘
```

**Dependency rule:** `ui → core`. `ChatEngine` is a plain Python generator that yields events, so the full chat flow can be tested with no GUI. Router strategies are **pure functions** of (request features, candidate list), so they are trivially testable and reusable by the Router Lab and the future gateway.

### Repo layout

```
modelmesh/
  AGENTS.md
  docs/PLAN.md
  requirements.txt
  .gitignore              # MUST list .env, config/providers.yaml, *.db; create BEFORE the first commit
  .env                    # real API keys (git-ignored, never committed)
  .env.example            # committed; variable names with empty values
  config/
    providers.yaml        # user's providers + models (git-ignored; ship providers.example.yaml)
    presets.yaml          # provider presets: OpenAI, Gemini, Groq, OpenRouter, Ollama, Anthropic, Custom
    mcp_servers.yaml      # optional, stretch
  skills/                 # each skill is a folder containing SKILL.md
  src/modelmesh/
    core/
      types.py            # canonical dataclasses (Part 4) + registry types Model/Endpoint/Candidate (Part 6)
      errors.py           # ProviderError and categories
      registry.py         # load/validate/save models + providers; capability queries
      keys.py             # loads .env; reads/writes provider keys (see Part 6)
      cost.py             # token estimate + cost calculation
      engine.py           # ChatEngine: the turn lifecycle (Part 9)
      providers/
        base.py           # ProviderAdapter ABC + protocol registry
        openai_compat.py
        anthropic.py
        bedrock.py        # optional: AWS Bedrock (Converse API via boto3)
        mock.py
      routing/
        base.py           # Strategy ABC, RoutingDecision, strategy registry
        features.py       # request feature extraction + eligibility filter
        random_.py  cheapest.py  expensive.py  manual.py
        heuristic.py      # stretch
      tools/
        registry.py       # decorator-based registration, JSON-schema validation
        builtin.py        # datetime, calculator, read_text_file, fetch_url, web_search
        mcp_client.py     # stretch
      skills.py
      attachments.py      # image resize, text/PDF extraction
      cache.py            # exact-match cache (stretch)
      storage.py          # SQLite schema + queries
    ui/
      main_window.py  sidebar.py  composer.py  chat_view.py  workers.py
      settings/ (providers_tab.py models_tab.py routing_tab.py tools_tab.py ...)
      usage_view.py  router_lab.py  theme.py
      web/ (chat.html chat.js chat.css vendor/marked.min.js highlight.min.js purify.min.js)
    cli.py                # headless test harness for the engine
    app.py                # entry point
  tests/
```

---

## Part 4. Canonical data model (provider-neutral)

All code outside adapters speaks **only** these types. They are modeled loosely on the OpenAI chat format because it is the de facto standard, so the OpenAI-compatible adapter is nearly pass-through and the Anthropic adapter does the translating.

- **Message:** `role` (system, user, assistant, tool), `parts[]`, `tool_calls[]` (assistant only), `tool_call_id` (tool role only), `meta` (model_id, usage, routing_decision_id, status).
- **Parts:** `TextPart`, `ImagePart` (media_type plus base64 data). Documents are converted to text at attach time (Part 10).
- **ToolSpec:** name, description, JSON-Schema parameters. **ToolCall:** id, name, arguments (parsed dict).
- **ChatRequest:** messages, system prompt, tools, params (temperature, max_tokens, and so on), plus *derived* `required_capabilities`.
- **StreamEvent** (what adapters yield): `text_delta`, `reasoning_delta`, `tool_call` (emitted **complete**, after the adapter has assembled the streamed fragments), `usage` (input, output, cached, reasoning tokens), `done` (finish_reason), plus engine-level events `routed`, `fallback`, `tool_start`, `tool_result`, `error`.
- **Model, Endpoint, Candidate** (registry types, defined in Part 6): a **Model** is the logical LLM; an **Endpoint** is one provider's way of serving it; a **Candidate** is a (Model, Endpoint) pair with *effective* (resolved) properties: price, context window, capabilities, quirks. Endpoint values override the model's defaults.
- **RoutingDecision:** chosen candidate (model_id **and** endpoint_id **and** provider_id), ordered fallback list of candidates, strategy name, human-readable reason, eligible candidates with their scores, request features, seed (for random).
- **Usage and cost:** tokens in/out, cost in USD (**notional**; see Part 6).

---

## Part 5. Provider layer (the "add any LLM easily" core)

### 5.1 Correcting an assumption: "all APIs are similar"

Mostly true, but not fully.

| Protocol id | Covers | Notes |
|---|---|---|
| `openai_compat` | OpenAI, Google Gemini (via its OpenAI-compatible endpoint), Groq, OpenRouter, Together, Mistral, DeepSeek, xAI, Fireworks, and local servers: Ollama, LM Studio, vLLM, llama.cpp | One adapter covers most of the market. Use the **Chat Completions** shape, since that is what compatible providers implement |
| `anthropic` | Claude (native Messages API) | Genuinely different: system prompt is a separate field; content is typed blocks; tool calls are `tool_use` blocks and results are `tool_result` blocks inside *user* messages; `max_tokens` is required; streaming events differ; images use a different block format. Anthropic offers an OpenAI-SDK compatibility layer, but it is documented as a testing aid with feature gaps, so use the native adapter for full tool, vision, and thinking support |
| `bedrock` (optional) | Models hosted on AWS Bedrock, including Claude | Different again: AWS-signed requests through `boto3` instead of a bearer key, a region setting, and its own unified Converse / ConverseStream request and event shapes (verify against current AWS docs). The same Claude model can therefore be reached through **two different protocols** (`anthropic` and `bedrock`); this is exactly why a model must support several endpoints (Part 6) |

Other hosts you may meet later (for example Claude or Gemini through Google Vertex AI, or OpenAI models through Azure) would each be a new protocol added via path 5.3-B.

Even "compatible" providers deviate in small ways: which parameters they accept, the name of the reasoning field in streamed deltas, whether streamed usage is available, tool-calling reliability, and model listing. Handle these with per-model **`quirks` in config**, never with provider-name branches in code.

Preset base URLs to prefill (verify each against provider docs before relying on it): OpenAI `https://api.openai.com/v1`, Gemini `https://generativelanguage.googleapis.com/v1beta/openai/`, Groq `https://api.groq.com/openai/v1`, OpenRouter `https://openrouter.ai/api/v1`, DeepSeek `https://api.deepseek.com`, Ollama `http://localhost:11434/v1` (any non-empty key string).

### 5.2 Adapter contract (`ProviderAdapter`)

Each adapter implements:
1. `stream_chat(request, candidate, cancel_event)`: a generator of normalized `StreamEvent`s. The `candidate` carries the provider config (base URL, credentials, options such as region) and the endpoint's `api_model` string. Checks `cancel_event` between chunks and closes the stream when set.
2. `list_models(provider)`: optional; powers "Fetch models" in Settings (for OpenAI-compatible, this is `GET /models`).
3. `test_connection(provider)`: a cheap authenticated call; returns ok or a friendly error.

Rules:
- Translate canonical messages to the provider format **on every call** (history is stored canonically, which is what makes mid-conversation model switching possible).
- Strip `reasoning` content before sending history to *any* provider.
- Accumulate streamed tool-call fragments (they arrive as partial JSON strings keyed by index or block) and emit one complete `tool_call` event; parse JSON only at the end and report a clean error if it is invalid.
- Always request streamed usage where the provider supports it (for example OpenAI's `stream_options` include_usage); if usage is absent, emit an estimated usage flagged `estimated=true`.
- Apply the candidate's effective `quirks` (for example the name of the max-tokens parameter, whether temperature is allowed). Quirks can differ between endpoints of the same model.
- Never leak provider exceptions: map to `ProviderError`.

### 5.3 Two ways to add a provider

**A. OpenAI-compatible (zero code):** Settings → Providers → Add → pick a preset (or "Custom") → paste key (written to `.env`) → **Test** → **Fetch models** → tick models → for each ticked model choose **"Create new model"** or **"Add as an endpoint of an existing model"** (dropdown of current models) → fill price, tier, capabilities → Save. The same result is achievable by editing `providers.yaml`. Adding a local Ollama model must work this way too (this satisfies the synopsis's "one local open-weight model" requirement).

**B. New protocol (one file):** create `core/providers/<name>.py`, subclass `ProviderAdapter`, implement the three methods, register with the protocol decorator, and make it pass the shared **adapter conformance tests** (plain text, streaming, tool call, image, usage, error mapping, cancellation).

### 5.4 Mock adapter

A deterministic offline adapter (`protocol: mock`) that streams canned text, can emit tool calls, and can simulate errors and delays. Uses: unit tests, UI development without spending tokens, and **a demo safety net** if Wi-Fi dies.

---

## Part 6. Model registry and configuration

The registry has three levels. Keep them separate; this is what lets one model be served by several providers.

| Level | Meaning | Holds |
|---|---|---|
| **Provider** | A place you can call (a company's API, a cloud, or a local server) | id, `protocol`, `base_url` (if applicable), `auth_env` (list of environment variable names, see below), `options` (non-secret settings such as `region`), timeouts (connect about 10 s; read about 120 s, longer for local models), extra headers |
| **Model** (logical) | The LLM itself, independent of who hosts it | id, display name, **tier** (cheap, mid, premium), default `context_window`, `max_output`, **capabilities** (`streaming`, `tools`, `vision`, `reasoning`, `json_mode`), `local` (bool), `enabled`, `endpoint_policy`, and a list of **endpoints** (at least one) |
| **Endpoint** | One provider's way of serving that model | id, `provider` (must exist), `api_model` (the exact string *that provider* expects), `price_in_per_mtok`, `price_out_per_mtok`, `priority` (lower = preferred), `enabled`, and *optional overrides* of the model's context window, max output, capabilities, and `quirks` |

A **Candidate** is a (Model, Endpoint) pair with effective values: anything the endpoint overrides wins, otherwise the model default applies. Prices exist **only** on endpoints, because the same model costs different amounts on different providers. The router, engine, adapters, and logs all work with candidates.

`endpoint_policy` (per model) decides how that model's endpoints are ordered when the strategy has already picked the model: `priority` (default; follow the `priority` numbers), `cheapest` (lowest estimated request cost), or `fastest` (lowest observed median latency from the routing log; stretch).

Illustrative shape (values are placeholders; real model strings, regions, and prices come from provider docs on the day you configure them). One model, two endpoints on two different protocols, plus a second model with a single endpoint:

```yaml
providers:
  - id: anthropic
    protocol: anthropic
    auth_env: [ANTHROPIC_API_KEY]
  - id: bedrock
    protocol: bedrock
    auth_env: [AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY]   # plus AWS_SESSION_TOKEN if you use temporary credentials
    options: { region: "<your-region>" }
  - id: groq
    protocol: openai_compat
    base_url: https://api.groq.com/openai/v1
    auth_env: [GROQ_API_KEY]
models:
  - id: claude-mid
    display_name: "Claude (mid tier)"
    tier: mid
    context_window: 200000
    max_output: 8192
    capabilities: [streaming, tools, vision]
    endpoint_policy: priority
    endpoints:
      - id: claude-mid@anthropic
        provider: anthropic
        api_model: "<exact model string from Anthropic docs>"
        price_in_per_mtok: 3.0
        price_out_per_mtok: 15.0
        priority: 1
      - id: claude-mid@bedrock
        provider: bedrock
        api_model: "<exact Bedrock model id or inference profile from AWS docs>"
        price_in_per_mtok: 3.0
        price_out_per_mtok: 15.0
        priority: 2
  - id: llama-fast
    display_name: "Fast open model"
    tier: cheap
    context_window: 131072
    max_output: 8192
    capabilities: [streaming, tools]
    endpoints:
      - id: llama-fast@groq
        provider: groq
        api_model: "<exact model string from provider docs>"
        price_in_per_mtok: 0.05
        price_out_per_mtok: 0.08
        quirks: { max_tokens_param: max_tokens, supports_temperature: true }
```

Registry validation rules (fail loudly with a readable message): every endpoint's `provider` exists; every model has at least one endpoint; endpoint ids are unique; `api_model` is present on every endpoint; a model whose endpoints are all disabled is treated as unavailable. The registry exposes `models()`, `endpoints_for(model_id)`, and `candidates()` (the flattened, resolved list), and the Settings UI writes the same YAML.

**Demoing multi-provider without Bedrock or any extra adapter:** an open-weight model is usually hosted by several OpenAI-compatible providers (for example one hosted API plus an aggregator such as OpenRouter, plus a local Ollama copy). Give that model two or three endpoints, all on the `openai_compat` protocol. No new code is needed, and you still demonstrate cross-provider failover and price differences. Build the Bedrock adapter only if you have AWS access and time.

Key points:
- **Capabilities drive behavior everywhere.** The UI hides or disables the attach-image control for non-vision models; the router filters candidates by what the request needs (Part 7); tools are only offered to tool-capable models.
- **Prices are notional.** Many keys will be free-tier. Enter the real list price anyway so the cost comparisons are meaningful, and label costs in the UI as "est. cost". Prices change, so they are config, never code.
- **Pool target:** 3 to 6 models, at least two tiers, at least one local model, ideally two providers (as the synopsis requires), and **at least one model with two endpoints on different providers** to show multi-provider routing. Suggested starting pool: one free or cheap fast model, one mid model, one premium model, one local Ollama model, and (if you have a key) one Claude model to prove the native adapter. Check which free tiers currently exist before assuming.
- **Keys (`.env` approach):**
  - Each provider's `auth_env` lists the variable names it needs (one for most providers, for example `GROQ_API_KEY`; several for AWS-style credentials). The values live in a `.env` file in the project root (path configurable), loaded at startup with `python-dotenv`. Real environment variables, if set, take precedence over `.env`. SDKs that read standard variables themselves (such as `boto3` with the AWS variable names) pick them up from the process environment automatically.
  - Because several providers can serve one model, a key belongs to the **provider**, never to the model or endpoint. Add a key once and every endpoint on that provider can use it.
  - The Settings "paste key" form shows one masked field per variable in `auth_env` and writes each to `.env` (updating or adding only that variable without disturbing the others), then updates the running process's environment, so no restart is needed. Keys are masked in the UI after saving.
  - `.env.example` is committed with the variable names and empty values. Local models (Ollama) need no real key.
  - Keys never appear in YAML, SQLite, logs, exceptions, or the routing log.
  - **Safety checklist:** (1) create `.gitignore` with `.env` **before the first commit**, because adding it later does not remove a file git already tracks, and a committed key stays in history; (2) run `git status` before the first push to confirm `.env` is not listed; (3) AI IDE agents can read workspace files and may send their contents to a model provider, so add `.env` to your IDE's ignore mechanism (for example `.cursorignore`) where one exists; (4) use free-tier or spend-capped keys for development; (5) if a key ever lands on GitHub, revoke it immediately rather than just deleting the commit, since scrapers find leaked keys within minutes.
  - Keyring support is a possible later hardening step (it matters if the app is ever distributed to other people), not part of this build.

---

## Part 7. Routing

### 7.1 Pipeline (runs once per user turn)

1. **Extract features:** has image, tools enabled, estimated input tokens (a characters/4 heuristic is fine, labeled estimate), attachment types, prompt length.
2. **Eligibility filter, applied per candidate (endpoint level):** model and endpoint enabled; provider credentials present (or local); *effective* capabilities ⊇ required; *effective* context window ≥ estimated tokens plus margin; endpoint not currently marked unhealthy (7.5). Filtering per endpoint matters because two endpoints of the same model can differ (for example one provider offers a smaller context window or lacks a feature). If nothing is eligible, tell the user *why* (for example "no enabled endpoint supports images"), not a generic error.
3. **Strategy ranks** the eligible candidates in two stages: **(a)** order the *models*, **(b)** within each model order its eligible endpoints using that model's `endpoint_policy`. Flatten the result into one ordered list. The first item is the choice; the rest form the **fallback chain** (7.3).
4. Produce a **RoutingDecision**, emit a `routed` event (the UI shows the badge immediately, including the provider), and write it to the routing log.

### 7.2 Strategies (Strategy ABC plus registry; the UI dropdown auto-populates from the registry)

| Strategy | Behavior |
|---|---|
| `manual` | User picks a model, and optionally pins a **specific endpoint** ("Claude via Bedrock"). If no endpoint is pinned, the model's `endpoint_policy` orders its endpoints. Optional fallback chain |
| `random` | Pick a **model** uniformly at random, *then* pick its endpoint by `endpoint_policy`. Do **not** sample over flattened candidates, or a model with three providers would be three times as likely to be chosen and the baseline would be biased. Remaining models are shuffled as the fallback chain. Accepts a seed, and the seed is recorded in the decision so benchmark runs are reproducible |
| `cheapest_first` | Rank **models** ascending by the *estimated request cost of their cheapest eligible endpoint* (est. input × price_in plus an expected-output default × price_out); ties broken by latency then name. Within the chosen model, endpoints are ordered cheapest first regardless of `endpoint_policy` (the strategy's goal overrides it). Fallback chain is the next cheapest, i.e. escalation |
| `expensive_first` | Rank models descending by the cost of their **cheapest** eligible endpoint (so a model's rank does not depend on which of its providers happens to be pricey), then order endpoints within the chosen model by `endpoint_policy`. Mirror of the above for model ordering |

Extension points (not for the midterm, but the interface must not block them): `threshold_classifier` (a scorer returns P(strong model wins); at or above τ → strongest, else cheapest; this is the synopsis's RouteLLM-style policy), and `semantic_similarity` router.

**Stretch for Day 4:** a `heuristic_difficulty` strategy with a transparent score (length, code fences, math symbols, words like "prove", "derive", "analyze", multi-part questions) plus a threshold. Label it honestly as a stand-in that demonstrates the interface until the learned classifier exists.

### 7.3 Behavior rules
- **Sticky per turn:** route once per user message and reuse that **candidate (model and endpoint)** for every iteration of the tool loop. The next user message routes again, unless the user enabled "pin model for this conversation".
- **Fallback chain order = same model on other providers first, then other models.** If the chosen model has more endpoints, they come next in the chain (ordered by the model's `endpoint_policy`), followed by the next model's endpoints, and so on. Rationale: a provider outage or rate limit says nothing about answer quality, so failing over to the *same model* elsewhere preserves behavior and quality, while switching models changes the answer and the cost profile.
- **Which errors skip the remaining endpoints of the same model:** provider-level errors (`auth`, `rate_limit`, `network`, `server`) move to the next endpoint of the same model. Model-level errors (`context_length`, or a `bad_request` that is about the content itself) skip that model's other endpoints, since they will fail the same way, unless the eligibility filter already showed an endpoint with a larger effective context window.
- **Fallback only before output starts.** If a retryable error happens and nothing has streamed yet, move to the next candidate (emit `fallback` so the UI shows "Claude via Anthropic failed (rate limit) → trying Claude via Bedrock"). If it fails mid-stream, keep the partial text, show an error, and offer "Retry with next provider/model". Never silently splice two outputs together, even from the same model on different providers.
- **Rate limits:** retry once on the same endpoint if the wait is short (about 3 s or less), otherwise fall back.
- **Switching models or endpoints mid-conversation is normal** under routing. Canonical storage and per-call translation make it work, even when the same model moves between protocols (for example `anthropic` to `bedrock`). Beware of tool-call id formats and reasoning blocks (rule in 5.2); never resend reasoning content to another endpoint.

### 7.4 Routing log (one row per model call)
timestamp, conversation, message, strategy, chosen model, **chosen endpoint, provider**, fallback chain (as endpoint ids), candidates with scores, features, reason, cache status, time-to-first-token, total latency, tokens in/out, estimated cost (using the **chosen endpoint's** prices), error category. This table *is* the future evaluation dataset; design it now. Because latency and cost are logged per endpoint, the same table later feeds the `fastest` endpoint policy.

### 7.5 Endpoint health (small, in-memory)
Keep a per-endpoint counter of consecutive retryable failures. After 3 in a row, mark the endpoint **unhealthy** for a cooldown (about 60 s). Unhealthy endpoints are excluded by the eligibility filter unless they are the only option, and a success resets the counter. Show a small status dot per endpoint in Settings. This is what makes multi-provider failover feel smart instead of retrying a dead provider on every message. Persisting health across restarts is not needed.

---

## Part 8. Persistence (SQLite)

Tables (versioned with `PRAGMA user_version`):
- `conversations`: id, title, created, updated, system_prompt, settings_json (params, routing mode, pinned model, pinned endpoint (optional), enabled tools)
- `messages`: id, conversation_id, role, content_json (parts, tool_calls), model_id, endpoint_id, provider_id, routing_log_id, tokens_in, tokens_out, cost, latency_ms, status (complete, stopped, error), created
- `routing_log`: as in 7.4
- `attachments`: id, message_id, name, mime, size, stored_path or content hash
- `tool_runs`: id, message_id, tool, args_json, result_text, ms, ok

Rules: **one SQLite connection per thread** (or a single lock-guarded connection); store DB and config under `QStandardPaths.AppDataLocation`; the conversation title is the first about 6 words of the first message (no API call needed).

---

## Part 9. Chat engine: turn lifecycle

`ChatEngine.run_turn(conversation, user_input, settings, cancel_event)` is a generator that yields events:

1. Build canonical history: system prompt, then the skills index (if enabled, Part 10.5), then prior messages, then the new user message (attachments already processed).
2. Router → `RoutingDecision` → yield `routed`.
3. (Stretch) cache lookup; on hit, yield cached text with `cache_status=hit`, cost 0.
4. Call the adapter; forward `text_delta` and `reasoning_delta`; collect `tool_call`s and `usage`.
5. If tool calls were produced: for each, validate arguments against the tool's JSON Schema, execute with a timeout and an output size cap, catch every exception and return it **to the model** as a tool result string (never crash the turn), append the assistant tool-call message and the tool result messages, and loop to step 4 with the same model. **Max 8 iterations**, then stop with a visible notice.
6. On completion: compute cost from usage, persist the message and the routing log row, yield `done`.
7. On `ProviderError`: apply the fallback rules in 7.3.
8. **Cancellation:** a `threading.Event` checked per chunk. Partial text is saved with status `stopped`.

Parameter panel (per conversation): temperature, max output tokens, system prompt. Only send parameters the chosen candidate's effective `quirks` allow.

---

## Part 10. Features, priorities, and acceptance criteria

**Rule: do not start a P1 item until every P0 acceptance check passes.** P0 alone is a complete, demo-able midterm.

### P0. Must ship
| Feature | Acceptance |
|---|---|
| Streaming chat with markdown, syntax-highlighted code blocks with copy button, tables | Tokens appear smoothly; a long answer does not freeze the window; partial markdown (an open code fence) does not break the page |
| Conversation sidebar | New, rename, delete, search; survives restart; grouped by Today / Yesterday / Older |
| Provider and model management | Add an OpenAI-compatible provider purely from Settings; Test and Fetch models work; a bad key gives a friendly message |
| Multiple providers per model | A model can have 2 or more endpoints on different providers (added in Settings or YAML with no code changes); each endpoint has its own `api_model` string and price; the registry resolves candidates correctly |
| Model selector with Auto strategies | Dropdown contains Auto: Random / Cheapest first / Expensive first, then each individual model. Each model has a submenu to choose **Provider: Auto (model's policy)** or a specific provider |
| Routing transparency | Each assistant message shows model chip, **provider chip**, strategy chip (tooltip = reason), tokens in/out, est. cost (from that endpoint's prices), latency |
| Stop and Regenerate | Stop ends the stream within about 1 s and keeps partial text; Regenerate re-routes and replaces the reply |
| Fallback | Break one key on purpose; the turn still succeeds and the UI says so. With a multi-endpoint model, the failover goes to **the same model on the other provider first**; with a single-endpoint model, it goes to the next model |
| Routing log | Every call recorded in SQLite; viewable in a basic table |

### P1. Strongly recommended
- **Attachments:** paperclip, drag-and-drop, and paste-image-from-clipboard, with removable chips above the input.
  - *Images:* png, jpg, webp, gif. Downscale to a max edge of about 1600 px and re-encode; send as `ImagePart`. Requires the `vision` capability; routing filters to vision models, and in manual mode warn if the chosen model or pinned endpoint lacks vision.
  - *Text and code:* txt, md, csv, json, source files. Read as UTF-8 with a size cap (about 200 KB) and inject as a delimited block that includes the filename.
  - *PDF:* extract text with `pypdf` or `pymupdf` with a page cap; if no text is found (scanned), tell the user. DOCX optional via `python-docx`.
  - Show an estimated-token warning if attachments approach the context window.
- **Tool use:** a registry where tools are declared once (name, description, JSON-Schema) and exposed to any tool-capable model through the adapters. Built-ins: `get_current_datetime`; `calculator` (parse with `ast`, never `eval`); `read_text_file` (restricted to a user-chosen workspace folder); `fetch_url` (timeout, size cap, text extraction); `web_search` (optional, via a no-key library or a keyed API). UI: a collapsible tool card in the transcript (name, arguments, result, duration, success/failure), a per-conversation tool toggle, and enabling tools makes the router filter to tool-capable models. No shell tool and no arbitrary file writes in this phase.
- **System prompt and parameters** per conversation.
- **Usage dashboard:** table aggregated from `routing_log` by model, by **provider/endpoint**, and by day: requests, tokens, est. cost, average latency. Seeing the same model split across providers is a good demo of multi-provider routing.
- **Light/dark theme** (QSS plus CSS variables in the web view).
- **Keyboard:** Enter sends, Shift+Enter newline, Ctrl+N new chat, Esc stops.

### P2. If time remains (in this order)
1. **Router Lab:** load 10 to 30 prompts (CSV or JSON), run them through each strategy. **Dry-run mode** computes routing decisions and estimated cost without calling any model, which is free and shows the cheapest vs. expensive vs. random cost gap clearly. *Live mode* runs real calls and records latency. (Quality scoring via LLM-as-judge is post-midterm.)
2. **Reasoning display:** if a stream carries reasoning deltas, show a collapsible "Thinking" block. Never resend it.
3. **Exact-match cache:** key = hash of the normalized prompt, the conversation context hash, and the tool-enabled flag. Only for turns without tools or attachments. Includes TTL. A hit shows a "cached" badge and zero cost. (Semantic cache is post-midterm.)
4. **Skills** (see below).
5. **Heuristic difficulty strategy** (7.2).
6. Export conversation as Markdown; edit-and-resend of a user message.
7. **MCP client** (only if everything above is done; most likely cut): use the official `mcp` Python SDK, configure stdio servers in `mcp_servers.yaml`, list their tools at startup, and register each in the ToolRegistry as `server__tool`. The SDK is async, so run it in a dedicated thread with its own loop and bridge via `run_coroutine_threadsafe`.

### 10.5 Skills (lightweight, in the spirit of Anthropic's Agent Skills)
- A skill is a folder under `skills/` containing `SKILL.md` with front matter (`name`, `description`) and a markdown body of instructions.
- At turn start, inject only the **names and descriptions** of enabled skills into the system prompt, and expose one tool, `load_skill(name)`, that returns the full body. The model pulls instructions on demand (progressive disclosure, so no wasted tokens).
- Skills are instructions only in this phase. No script execution.
- Ship two example skills for the demo (for example "meeting-notes formatter", "code-review checklist").

---

## Part 11. UI specification

**Style:** inspired by modern LLM chat apps (clean, calm, content-first), without copying any brand's assets or logos.

**Layout**
- **Sidebar (about 260 px):** New chat button, search box, conversation list, and at the bottom: Usage, Router Lab, Settings.
- **Top bar:** model/strategy dropdown (for example "Auto · Cheapest first ▾"; individual models show a provider submenu, for example "Claude (mid tier) ▸ Provider: Auto / Anthropic / Bedrock"), parameters popover, tools popover.
- **Transcript (web view):** centered column about 760 px wide; user messages in a subtle bubble; assistant messages as plain text without a bubble; footer on each assistant message with chips (model, strategy), tokens, est. cost, latency, and actions (copy, regenerate). Tool cards and thinking blocks are collapsible.
- **Composer:** auto-growing multiline input, attach button, attachment chips, Send button that turns into Stop while streaming, small caption with estimated tokens.
- **Status bar:** session est. cost.
- **Empty state:** short greeting, a few suggested prompts, and a "Set up a provider" button if none is configured (first-run flow). Handle every empty and error state explicitly.

**Settings dialog tabs:** Providers (list, add/edit/delete, Test), Models (a tree or expandable table: each model row expands to its **endpoints** table with provider, `api_model`, prices, priority, enabled, optional overrides, and a health dot; **Add endpoint** and **Move up/down** (priority) buttons; a model-level `endpoint_policy` selector), Routing (default strategy, expected output tokens, random seed, fallback on/off, max fallbacks), Tools and Skills (toggles, workspace folder, skills directory), Appearance, Data (DB path, export, clear).

**Web-view bridge (keep it tiny and safe)**
- Python → JS: a `ChatView` wrapper with methods such as `add_user_message`, `start_assistant_message`, `append_text`, `set_reasoning`, `add_tool_card`, `finish_message`, `set_error`. Build all JS calls with `json.dumps` for arguments (never string-format raw text into JS). Buffer token deltas and flush on a QTimer every about 40 ms to avoid flooding the page.
- JS → Python (QWebChannel): only whitelisted slots: `copy(text)`, `regenerate(message_id)`, `open_link(url)`, `edit_message(id)`.
- Security: model output is untrusted. Render markdown, then sanitize with DOMPurify. Intercept navigation so links open in the system browser. Load only bundled local assets (no CDN; the app must work offline).

**Threading in the UI**
- One worker per active turn, with its own cancel Event. Signals carry plain data. The main window routes signals to `ChatView` and to storage.
- Tools that need confirmation (none are destructive in this phase) would use a signal plus a blocking queue; skip unless needed.

---

## Part 12. Testing and verification

- **Unit:** each strategy with a fixed registry fixture (ordering, ties, seeding, capability filtering, empty-eligible case); **multi-endpoint cases**: effective-value resolution (endpoint override vs. model default), random picks models uniformly rather than endpoints (statistical check over many seeded draws), cheapest-first uses each model's cheapest endpoint, fallback chain puts the same model's other endpoints before other models, model-level errors skip sibling endpoints, an unhealthy endpoint is excluded, and a pinned endpoint is respected; cost calculator (uses the chosen endpoint's prices); attachment processing; tool argument validation.
- **Adapter conformance suite** (run against the mock adapter, and against mocked HTTP using `respx` for each real adapter): text stream, usage, tool-call assembly from fragments, image input, error mapping, cancellation.
- **Engine tests with the mock adapter:** tool loop (including iteration cap and a tool that raises), fallback before output, error mid-stream, cancellation, and persistence.
- **Live smoke tests** (marked `live`, skipped without keys): one tiny prompt per configured provider.
- **UI:** manual checklist before the demo (see Part 14 acceptance); no automated GUI tests.
- **`cli.py`:** headless harness (`prompt`, `--strategy`, `--model`) so the core can be exercised and debugged without the GUI.

---

## Part 13. Known traps (read before coding)

1. PyQt5 and PyQt6 code get mixed by agents constantly; enums and `exec_` vs `exec` differ. Pin PyQt6.
2. Streamed tool calls arrive as fragments; concatenate argument strings per call and parse JSON **once** at the end.
3. OpenAI-format streaming only reports usage if requested; some compatible providers do not support it, so fall back to estimates and flag them.
4. Anthropic needs `max_tokens` on every request, takes the system prompt separately, and wants `tool_result` blocks inside a user message. Message-role ordering rules are stricter.
5. Do not send reasoning/thinking blocks back to any model, and never to a different provider.
6. Assistant messages with tool calls can have empty or null text content; handle both.
7. Some reasoning models reject `temperature` or use a different max-tokens parameter name; that is what `quirks` is for.
8. Local models (Ollama): vision and tool support depends on the specific model, so set capability flags honestly. The first request is slow (model load), so use a generous read timeout.
9. Context-length errors look different on every provider; normalize them to `context_length` and suggest trimming or switching to a larger-context model.
10. Base64 images and big text attachments blow up payloads; enforce size limits.
11. SQLite connections are not thread-safe by default; do not share one across threads.
12. Agents hallucinate model names and parameters. Model strings live only in config; verify against live docs or the provider's `/models` endpoint.
13. Windows specifics: `pathlib`, explicit UTF-8, high-DPI scaling, and `.env` line endings (read and write it as UTF-8 and do not corrupt other variables when updating one key).
14. Redact secrets from every log line and error message.
15. **The same model is not identical everywhere.** Different providers can use different model strings, prices, context limits, rate limits, feature support (vision, tools, reasoning), and even different streaming event shapes. That is why these live on the endpoint, and why eligibility is checked per endpoint, not per model.
16. **Do not sample randomly over flattened candidates.** Pick the model first, then the endpoint, or the random baseline is biased toward models with many providers.
17. **Do not key prices, rate limits, or credentials by model.** Prices belong to endpoints; credentials belong to providers. Cost for a message must always come from the endpoint that actually served it (including after a fallback).
18. **Credentials can be multi-part** (for example access key, secret key, and region for AWS). Do not assume one API key string per provider; use the `auth_env` list.

---

## Part 14. Four-day schedule with exit criteria

Each task is a self-contained unit you can hand to an agent. Commit after each one.

### Day 1: Core, no UI
| ID | Task | Done when |
|---|---|---|
| T1 | Repo skeleton, venv, pinned deps, AGENTS.md, config dirs, pytest wired, **`.gitignore` and `.env.example` created before the first commit** | `pytest` runs (zero tests is fine); `git status` does not show `.env` |
| T2 | Canonical types and `ProviderError` | Types importable; round-trip serialization works |
| T3 | Registry with **providers, models, endpoints, and resolved candidates** (Part 6); validation; presets; `.env` key helper (load, read, write one variable per `auth_env` entry) | Example YAML with one two-endpoint model loads and `candidates()` shows resolved values; invalid YAML gives a readable error; writing a key updates only that line in `.env` |
| T4 | Mock adapter plus engine skeleton plus `cli.py` | `cli` streams a mock reply end to end |
| T5 | OpenAI-compatible adapter (text streaming, usage, error mapping, test connection, list models) | Live prompt works on at least two providers, one being local Ollama |
| T6 | Routing on **candidates**: features, per-endpoint eligibility filter, model-then-endpoint ranking, three strategies plus manual (with optional pinned endpoint), fallback chain ordering (7.3), decision object, endpoint health (7.5), unit tests | `cli --strategy cheapest/expensive/random` picks differently, logs model **and** provider with the reason, and a simulated failure falls over to the same model's other endpoint first |
| T7 | SQLite storage, routing log, cost meter | Every cli call writes a log row with tokens and cost |
| T8 | Anthropic adapter, text streaming only for now. Also configure **one open-weight model with two `openai_compat` endpoints** (two providers, or a hosted provider plus local Ollama) to exercise multi-provider routing | Anthropic works if you have a key, otherwise passes mocked-HTTP conformance tests; the two-endpoint model can be reached through each provider and fails over between them |

**Day 1 exit:** a headless run against 2 or more real providers with all three strategies and a populated routing log.

### Day 2: GUI
| ID | Task | Done when |
|---|---|---|
| T9 | `chat.html/js/css` plus `ChatView` bridge | Fake streaming appears with markdown and code highlighting; copy button works. If not working after about 2 h, switch to the fallback renderer |
| T10 | Main window: sidebar, top bar, composer (static, wired to nothing) | Layout matches Part 11 |
| T11 | Worker thread plus engine wiring, streaming, Stop | Real streaming chat; UI stays responsive; Stop works |
| T12 | Persistence wiring: conversations, reload, rename/delete/search | Restart keeps history |
| T13 | Settings: Providers and Models tabs, Test, Fetch models, key saving to `.env` | Add a provider through the UI only, then chat with it |
| T14 | Strategy dropdown with per-model provider submenu, model/provider/strategy/cost/latency chips, fallback notices (naming provider and model), regenerate | All P0 acceptance rows pass |

**Day 2 exit:** every P0 row in Part 10 passes. If it does not, Day 3 does not start.

### Day 3: Capabilities
| ID | Task | Done when |
|---|---|---|
| T15 | Attachments (images, text, PDF), chips, drag-and-drop, paste | A screenshot gets described by a vision model; a PDF can be summarized |
| T16 | Tool registry plus tool loop plus built-ins plus tool cards, including the Anthropic tool translation | A calculator or datetime question triggers a visible tool call on two different providers |
| T17 | Vision for the Anthropic adapter; reasoning display. **Optional: Bedrock adapter** (only if you have AWS access; use Converse streaming via `boto3`, pass the conformance suite) | Image works on Claude; thinking block collapses; if built, the same Claude model answers through both `anthropic` and `bedrock` endpoints |
| T18 | Usage dashboard; parameters and system prompt panel; theme | Table matches the SQLite totals |
| T19 | Skills (only if T15 to T18 are done) | `load_skill` fires in a demo chat |

### Day 4: Demo hardening
| ID | Task | Done when |
|---|---|---|
| T20 | Router Lab (dry-run first, then live) | Table shows cost per strategy for a 20-prompt set |
| T21 | Exact-match cache | Repeating a prompt shows a cached badge and zero cost |
| T22 | Optional: heuristic difficulty strategy | Appears in the dropdown and routes visibly differently |
| T23 | Polish: first-run flow, error states, README, screenshots, seeded demo data, mock-mode demo profile | Fresh clone plus README gets a working app |

**Feature freeze midday on Day 4.** Afternoon is bug-fixing only, then rehearse the demo twice and record a screen capture as a backup.

**Cut order if behind (cut first to last):** MCP → heuristic strategy → cache → skills → Router Lab live mode (keep dry-run) → reasoning display → usage dashboard. **Never cut:** streaming chat, the three strategies with visible routing info, provider config UI, routing log, cost display, fallback.

---

## Part 15. Demo script and likely questions

**Demo flow (about 6 to 8 minutes)**
1. Architecture slide: UI → engine → router → adapters; point out that the core has no UI dependency and that the classifier plugs into the Strategy interface.
2. Add a new provider live from Settings with no code (the local Ollama model is a safe choice). Test, fetch models, save.
3. Ask a question with a manual model.
4. Switch to Auto: Cheapest first, then Expensive first, then Random, on the same prompt. Show the routing chip, reason tooltip, tokens, and est. cost differences.
5. Show **multi-provider** routing: open Settings → Models and show one model with two endpoints (different providers, different prices). Chat with it pinned to provider A, then to provider B, then "Provider: Auto". Break provider A's key on purpose and show the turn failing over to **the same model on provider B**, with the fallback notice and a different cost. Then break the only endpoint of another model to show failover to a different model.
6. Attach an image or PDF; ask a question needing a tool (calculator, datetime, or web fetch); expand the tool card.
7. Show the Usage view or the Router Lab dry-run: "over these 20 prompts, always-cheap costs X, always-expensive costs Y."
8. Close: what comes next (classifier, semantic cache, gateway with private keys).

**Likely questions and honest answers**
- *Where is the classifier?* Next phase. The strategy interface and the routing log are already in place; baselines are recorded as reference lines.
- *How is this different from OpenRouter?* This is a router you control end to end, with cost-aware routing, caching, and robustness evaluation as the research contribution.
- *Where are the private keys and multi-tenancy?* Phase 2: the same `core/` wrapped by an OpenAI-compatible gateway with an accounts layer.
- *How will you measure quality?* LLM-as-judge on a RouterBench subset, giving the cost-quality Pareto frontier against these baselines.

**Backups:** mock-adapter demo profile, local Ollama model, and a screen recording.

---

## Part 16. Prompt template for each agent task

> Read `AGENTS.md` and PLAN sections [list relevant parts]. Your task is **[ID and name]**. Acceptance: [copy the "Done when" cell]. Before editing, list the files you will create or change. Do not modify any other files or add dependencies without asking. If the plan is ambiguous or you need to guess a provider API detail, stop and ask. When finished, run `pytest`, summarize what changed and how you verified it, and commit.

Working habits that prevent most agent mistakes: one task per session; review the diff before committing; keep `main` always runnable; ask the agent to write the tests *first* for router and adapter work; and when something breaks, paste the actual error plus the relevant PLAN section instead of describing it.

---

## Part 17. Definition of done for the midterm

- Fresh clone, install, and run works from the README.
- At least 3 models across at least 2 tiers, including 1 local model, added via config or Settings with no code changes.
- At least one model with 2 or more endpoints on different providers (different `api_model` strings and prices), selectable per provider or automatically, with same-model-first failover demonstrated.
- Auto routing with random, cheapest-first, and expensive-first, each visibly different, with reason, tokens, cost, and latency shown per message.
- Fallback demonstrated.
- Streaming, markdown, code blocks, stop, regenerate, persistent conversations.
- At least attachments and one working tool-use example (P1), demonstrated on more than one provider.
- Routing log populated and viewable; usage summary available.
- Demo rehearsed twice with a backup recording.
