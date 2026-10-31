# ModelMesh

ModelMesh is a desktop chat client that routes each prompt to the cheapest model capable of answering it. It is written in Python with PyQt6 and pools models from several providers (OpenAI, Anthropic, Google Gemini, Groq, OpenRouter and local Ollama) behind a single conversation view.

For every turn, ModelMesh classifies the prompt, works out how capable a model it needs, ranks the configured models on published benchmark data, and sends the request to the cheapest model that clears the bar. If that endpoint fails, the turn moves to the next candidate without losing the message.

---

## Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Architecture](#architecture)
4. [Routing](#routing)
5. [Model Scores](#model-scores)
6. [Provider Model Catalog](#provider-model-catalog)
7. [Models, Endpoints and Candidates](#models-endpoints-and-candidates)
8. [Tools and Skills](#tools-and-skills)
9. [Desktop Interface](#desktop-interface)
10. [Command-Line Interface](#command-line-interface)
11. [Installation](#installation)
12. [Configuration](#configuration)
13. [Running and Testing](#running-and-testing)
14. [Project Structure](#project-structure)
15. [Changelog](#changelog)
16. [Datasets and Models](#datasets-and-models)
17. [Attribution](#attribution)

---

## Overview

Using several model APIs usually means choosing between them by hand: a frontier model for hard reasoning, a mid-tier model for everyday coding, and a free or low-cost model for simple questions. ModelMesh makes that choice per turn. For each message it:

1. Classifies the task (coding, math, writing, summarisation, translation, research, tool use or general chat) and rates its difficulty and precision requirements.
2. Converts those ratings into a required quality level.
3. Ranks the eligible models on the benchmark metric that best fits the task.
4. Sends the turn to the cheapest model at or above the required level, streaming the reply and recording tokens, latency and cost.
5. On a rate limit, outage, timeout or exhausted account, retries on the next candidate in the fallback chain.

---

## Features

- **Per-turn routing.** Prompts are classified by Cloudflare's Clef-flash decision model, or by a local heuristic when the service is unavailable. A failed decision call never blocks a turn.
- **Two score sources.** Model quality comes from Artificial Analysis indexes and LMArena ratings, stored locally in SQLite and refreshed on demand.
- **Cross-provider failover.** A logical model can be served by several providers. Unhealthy endpoints are put in a cooldown and recover on their own; a provider whose account has run out of credit is skipped for the rest of the session.
- **Provider catalog checks.** ModelMesh compares the configured models with each provider's live model list and proposes additions, removals, price changes and limit corrections for review.
- **Responsive interface.** Network I/O, streaming, file processing and tool execution run on background threads. Stop takes effect immediately, even on a stalled stream.
- **Tools and skills.** A restricted calculator, workspace file tools and web search, plus Markdown skill packs that can be referenced with `@skill-name`.
- **Routing transparency.** Each reply shows the model, provider, strategy, decision source, tokens, latency and cost, with a details panel explaining how the model was chosen and why other models were not.

---

## Architecture

```
+-------------------------------------------------------------------+
|                          PyQt6 UI layer                           |
|  MainWindow, ChatView (QtWebEngine), Composer, Settings, Sidebar  |
+---------------------------------+---------------------------------+
                                  |  Qt signals carrying plain data
                                  v
+-------------------------------------------------------------------+
|                          Worker threads                           |
|     ChatWorker, TurnController, catalog and score refreshers      |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|                            Core engine                            |
|   ChatEngine, Router, DecisionService, ToolRegistry, Skills       |
+------------------+------------------------------+-----------------+
                   |                              |
                   v                              v
+-----------------------------------+  +----------------------------+
|         Provider adapters         |  |     Storage (SQLite)       |
| OpenAI-compatible, Anthropic,     |  | conversations, routing     |
| mock                              |  | log, decision cache,       |
+-----------------------------------+  | score snapshots            |
                                       +----------------------------+
```

### Design rules

1. **Layering.** `core/` is plain Python and never imports PyQt. `ui/` depends on `core/`, never the reverse.
2. **Provider isolation.** Request and response formats for each provider family live only in `core/providers/`. Adding a model or an OpenAI-compatible provider is a configuration change.
3. **Pure routing maths.** `scoring.py` and `selector.py` perform no I/O. The decision-model network call happens earlier, in `DecisionService`.
4. **Fail-open decisions.** On a timeout, invalid output, missing credentials or an open circuit breaker, the router uses the local heuristic, records `decision_source=heuristic_fallback`, and says so in the chat.
5. **Secrets.** API keys live only in the git-ignored `.env` file and are removed from error messages before display.

---

## Routing

### Auto (Smart) strategy

The `smart_clef` strategy works in four steps.

1. **Decision.** The Clef-flash model, or the local heuristic, answers a fixed rubric about the latest message: task category, difficulty (0 to 4), precision (0 to 3), benefit from a larger model (0 to 3), whether it needs deliberate reasoning, and whether the topic has changed. The prompt text is sent to the remote service only when `decision.send_prompt_text` is enabled, and it is truncated to `max_state_tokens`.
2. **Required quality.** The answers are combined with configurable weights, an uncertainty term and the selected profile bias (frugal, balanced or quality) to give a need value. The bar is the need minus a configurable slack.
3. **Metric choice and ranking.** Each task has an ordered list of preferred metrics in `routing.yaml`; coding, for example, prefers the LMArena coding rating, then the Artificial Analysis coding index, then the general intelligence index. The first metric that covers at least `min_metric_coverage` of the pool (75% by default) is used, so every model in a turn is ranked on the same scale. Scores are normalised to the range 0 to 1 across the pool.
4. **Selection.** The cheapest model whose score meets the bar is chosen. Ties are broken by quality, endpoint priority and identifier. The remaining eligible models form the fallback chain.

Models with no score on any available metric are left out of Smart routing and listed with the reason. If no model in the pool is scored, the turn falls back to cheapest-first and a notice is shown. Optional stickiness keeps a conversation on its current model unless the task changes or a much cheaper model qualifies.

### Other strategies

- **Cheapest first** orders candidates by input and output price.
- **Strongest first** orders candidates by estimated request cost, most expensive first.
- **Random** picks uniformly among eligible candidates.
- **Manual** sends the turn to a selected model or endpoint, with no cross-model failover.

### Failure handling

| Failure | Effect |
|---|---|
| Rate limit, server error, network error | Endpoint enters a cooldown; other endpoints of the same model remain available |
| Invalid API key | Endpoint is blocked until settings change; remaining endpoints of that provider are skipped for the turn |
| Out of credit | The whole provider is skipped for the rest of the session |
| Bad request, context length | Nothing is recorded against the endpoint, since the request is at fault |
| User presses Stop | The partial reply is kept and marked as stopped; no endpoint is penalised |

---

## Model Scores

ModelMesh reads model quality from two public sources. Neither is committed to the repository; both are downloaded into the local SQLite database.

- **Artificial Analysis.** Intelligence, coding and agentic indexes. When several index versions are available, ModelMesh keeps the version that scores the largest share of configured models, so that a newly published index covering only a few models does not leave the rest unscored.
- **LMArena.** Style-controlled text ratings (overall, coding, hard prompts, math, instruction following and creative writing) read from the public leaderboard dataset on Hugging Face.

Each model links to these sources through `scores.aa_slug` and `scores.arena_name` in `providers.yaml`. The Scores tab shows every model with its linked entries and current values, flags links that no longer resolve, and offers an auto-match that only links exact identifier matches, so a model is never linked to a different version of itself. Manual overrides typed in the Scores tab take precedence over both sources.

---

## Provider Model Catalog

Commercial providers add and retire models frequently, and free-tier offerings change without notice. Each provider in `providers.yaml` can carry a `catalog` block describing how to read its model list:

- `format`: the response shape (`openai`, `gemini` or `anthropic`).
- `free_only`: offer only models priced at zero (used for OpenRouter).
- `assume_free`: treat every model as free (used for the Groq free plan).
- `include` / `exclude`: glob patterns that narrow the list to chat models.

A check runs in the background at most once a day and, when it finds differences, adds a button to the status bar. It can also be run from Settings > Endpoints > Check Provider Models. The review dialog groups proposed changes by type: endpoints no longer offered, retired or deprecated models, models that are no longer free, corrected context and output limits, price changes, and new models. Nothing is written to `providers.yaml` until the selected changes are applied. New models with an unknown price are added for manual selection only and are not used by automatic routing.

---

## Models, Endpoints and Candidates

- **Model.** A logical identity with a tier and default capabilities, for example `claude-sonnet-5-5`.
- **Endpoint.** One provider serving that model, with its own `api_model` string, prices, limits, priority and quirks, for example `qwen-27b@groq` and `qwen-27b@openrouter`.
- **Candidate.** A model paired with one enabled endpoint. The router, engine and adapters always work with candidates.

---

## Tools and Skills

### Built-in tools

- **Calculator.** Evaluates arithmetic, trigonometric, logarithmic and exponential expressions through a restricted AST parser.
- **Filesystem.** Lists, reads, writes and searches files inside the configured workspace folder.
- **Web.** Searches DuckDuckGo and extracts readable text from public pages.

### Skills

Skills are Markdown files stored under `skills/<name>/SKILL.md`, with YAML front matter for the name, version and description. Their bodies are added to the system prompt when a skill is mentioned with `@name` or loaded with the `load_skill` tool. Skill names are restricted to letters, digits, hyphens and underscores, and skill files cannot be written outside the skills folder.

---

## Desktop Interface

- **Chat view.** Markdown rendering with highlight.js code highlighting in dark and light themes, sanitised through DOMPurify. All model, tool and provider output is escaped before display, and only `http`, `https` and `mailto` links are opened.
- **Message footer.** Model, provider, strategy, decision source, latency, cost and token counts, with Copy, Retry and Details actions. Details shows the task classification, need and bar, the metric used, and every candidate with its score and status.
- **Attachments.** Text, PDF and image files are processed on a background thread and shown as chips on the user message.
- **Conversations.** Each conversation keeps its own generation parameters and tools setting. Tool calls and routing notices are saved and shown again after a restart.
- **Settings.**
  - *Endpoints*: providers, models and endpoints, with validation that prevents removing a provider still in use or a model's last endpoint.
  - *Routing*: decision provider, privacy setting, rubric weights, slack, profiles and stickiness.
  - *Scores*: snapshot status, refresh for each source, link checks, auto-match and manual overrides.
  - *Tools*: workspace folder, search limits and tool permissions.
  - *Appearance*: dark and light themes.
- **Usage.** Per-model and per-provider totals for tokens, cost and latency.

---

## Command-Line Interface

The `modelmesh-cli` entry point runs single turns and manages score data without the GUI.

```bash
# One turn with Smart routing
modelmesh-cli "Explain the Raft consensus algorithm in three bullet points" --strategy smart_clef

# Pin a model
modelmesh-cli "Write a merge sort in Rust" --model qwen-27b --strategy manual

# Refresh scores from Artificial Analysis or LMArena
modelmesh-cli scores refresh --source aa
modelmesh-cli scores refresh --source arena

# Show effective scores, or suggest links for unlinked models
modelmesh-cli scores show
modelmesh-cli scores auto-match
```

---

## Installation

### Requirements

- Python 3.11 or later
- Git

### Steps

```bash
git clone https://github.com/maulik-sharma/Major-Project-PR1107.git
cd Major-Project-PR1107

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"

cp .env.example .env
cp config/providers.example.yaml config/providers.yaml
```

Add keys to `.env` for the providers you use. Local models served by Ollama need no key.

```env
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GROQ_API_KEY=
OPENROUTER_API_KEY=
GEMINI_API_KEY=

# Cloudflare Workers AI, for the Clef-flash decision model
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_AUTH_TOKEN=

# Artificial Analysis, for benchmark scores
ARTIFICIAL_ANALYSIS_API_KEY=
```

Without Cloudflare credentials, Smart routing uses the local heuristic. Without an Artificial Analysis key, LMArena ratings and manual overrides are still available.

---

## Configuration

### providers.yaml

`config/providers.yaml` (git-ignored; start from `providers.example.yaml`) defines providers, their catalog settings, and the model list.

```yaml
providers:
  - id: openrouter
    protocol: openai_compat
    base_url: https://openrouter.ai/api/v1
    auth_env: [OPENROUTER_API_KEY]
    catalog:
      format: openai
      free_only: true
      exclude: ["openrouter/*"]

models:
  - id: qwen-27b
    display_name: "Qwen 3.8 27B"
    tier: mid
    context_window: 131072
    max_output: 8192
    capabilities: [streaming, tools]
    scores:
      aa_slug: qwen3-8-27b
      arena_name: "Qwen3.8-27B"
    endpoints:
      - id: qwen-27b@openrouter
        provider: openrouter
        api_model: "qwen/qwen3.8-27b:free"
        price_in_per_mtok: 0.0
        price_out_per_mtok: 0.0
        priority: 1
```

### routing.yaml

`config/routing.yaml` holds the decision providers, the rubric, the need weights, the metric preferences for each task, the model pool, profiles and score source settings.

```yaml
decision:
  active: clef-flash
  send_prompt_text: true
  timeout_s: 1.5
  max_state_tokens: 2000

need:
  weights: {difficulty: 0.45, precision: 0.2, larger_model_benefit: 0.3}
  uncertainty_k: 0.15
  slack: 0.1

metric_by_task:
  coding: [arena_coding, coding, intelligence]
  agentic_tool_use: [agentic, intelligence]
  default: [intelligence, arena_overall]
min_metric_coverage: 0.75

pool:
  include: ["*"]
  exclude: ["mock-*"]
unscored_policy: exclude

profiles:
  frugal: {bias: -0.15}
  balanced: {bias: 0.0}
  quality: {bias: 0.15}
```

---

## Running and Testing

```bash
modelmesh                 # desktop application
pytest                    # full test suite
```

The test suite (226 tests) covers the provider adapters, error mapping, routing strategies, the selector and scoring maths, score sources and matching, catalog parsing and diffing, the chat engine, and the main UI flows under an offscreen Qt platform. Tests make no network calls and do not read real API keys.

---

## Project Structure

```
.
├── config/
│   ├── presets.yaml              Provider presets offered in Settings
│   ├── providers.example.yaml    Example providers, catalog settings and models
│   ├── providers.yaml            Local provider and model configuration (git-ignored)
│   └── routing.yaml              Decision, rubric, metric and pool settings
├── data/
│   └── modelmesh.db              Conversations, routing log and score snapshots (git-ignored)
├── skills/                       Markdown skill packs
├── src/modelmesh/
│   ├── app.py                    Desktop entry point
│   ├── cli.py                    Command-line entry point
│   ├── core/                     Engine layer, no GUI dependencies
│   │   ├── catalog/              Provider model list comparison and updates
│   │   ├── config/               Pydantic configuration schemas
│   │   ├── providers/            Provider adapters and catalog formats
│   │   ├── routing/              Strategies, health tracking and the router
│   │   │   └── smart/            Decision service, scoring, selector, stickiness
│   │   ├── scores/               Artificial Analysis and LMArena clients, matching
│   │   ├── tools/                Calculator, filesystem and web tools
│   │   ├── engine.py             Chat turn execution and failover
│   │   ├── routing_log.py        Routing log records
│   │   ├── streaming.py          Cancellable stream reading
│   │   └── storage.py            SQLite schema and persistence
│   └── ui/                       PyQt6 client
│       ├── settings/             Endpoints, Routing, Scores, Tools, Appearance
│       ├── web/                  Chat view HTML, CSS and JavaScript
│       ├── catalog_dialog.py     Catalog review dialog
│       ├── main_window.py        Main window and toolbar
│       ├── turn_controller.py    Active turn lifecycle
│       └── workers.py            Background threads
└── tests/
```

---

## Changelog

The following changes were made in the most recent revision. They fix defects in the original implementation and add the score and catalog features described above.

### Routing

- Health is now tracked per endpoint rather than per model, so one failing provider no longer disables every other provider serving the same model. Cooldowns expire, and endpoints recover without a restart.
- Request errors (bad request, context length) and user cancellations are no longer counted as endpoint failures.
- Fixed a deadlock when reading health status.
- The context-window check now accounts for the requested output tokens and the safety margin.
- Unknown task labels map to general chat instead of failing the filter.

### Smart strategy

- The decision service now always fails open. Invalid output, cache errors, state-building errors and missing credentials all fall back to the heuristic, and the fallback is shown in the chat.
- The circuit breaker is thread-safe, and a failed half-open probe re-opens it immediately.
- The decision model's endpoint and credentials are read from configuration instead of source code.
- The heuristic reads the actual message text locally, uses whole-word matching (so "trust" is no longer read as the language "rust"), and ignores the context header when judging whether a prompt is trivial.
- Removed hard-coded tier scores and the practice of copying the intelligence score into missing coding scores. Models without data are now excluded and reported, instead of being ranked on invented numbers.
- Each pool is ranked on a single metric chosen from a per-task preference list, so models are never compared across different benchmarks.
- Restored the specified tie-break order. Profiles, bias overrides and stickiness now take effect.
- The details panel explains why each unranked model was left out: no price, not suited to the task, excluded by pool settings, or no score on the chosen metric.

### Scores

- Added LMArena as a second score source, giving coding, math, creative-writing and instruction-following ratings for models that Artificial Analysis does not cover.
- The Artificial Analysis snapshot is now chosen by coverage, so a newer index that scores only a few models does not replace a complete one.
- Auto-match only links exact identifier matches. The previous fuzzy matching linked models to the wrong version.
- The Scores tab was rebuilt with columns for both sources, link checks and a per-model editor.
- Score refreshes respect the configured minimum interval.

### Requests and streaming

- Stop now works on a stalled stream. The stream is read on a helper thread so cancellation does not depend on the network read returning.
- A cancelled stream is no longer recorded as a finished empty reply.
- An invalid key skips the provider's remaining endpoints for the turn; an exhausted account skips the provider for the session, with a clear message.
- SDK-level retries are disabled so failover happens immediately, and HTTP clients are always closed.
- Streamed tool calls from providers that omit the index field are assembled correctly.
- The Anthropic adapter reports a model-list failure instead of returning a fixed list.

### Provider catalog

- Added the catalog check, with parsers for the OpenAI, Gemini and Anthropic model-list formats, free-tier filtering for OpenRouter and Groq, a review dialog, and a daily background check.
- A new model is attached to an existing logical model only when that model has no endpoint on the same provider and the price is known, which prevents an older model from being merged into a newer one.

### Interface

- Fixed a crash when attaching files. Attachments are processed off the UI thread.
- Only one turn can run at a time. Each turn is tied to its conversation, so switching chats during a reply no longer saves the reply to the wrong conversation. Stop, Retry and conversation deletion now leave the composer in a consistent state.
- All untrusted content in the chat view is escaped, closing several script-injection paths. Only web and mail links are opened.
- Settings changes are saved to disk and validated before they are applied.
- Error messages are written for users and have keys removed; technical detail is available on request.
- Copy to clipboard, the usage dashboard, the workspace path setting and tool toggles were fixed.
- Generation parameters and the tools setting are saved per conversation. Tool calls and notices are restored after a restart.
- Theme handling was consolidated, light-mode code highlighting was added, and invalid colour values were corrected.
- Streaming rendering was made incremental, with code highlighted once the reply finishes.
- Skill names and paths are validated so skill files cannot be written outside the skills folder.
- Provider presets and the Artificial Analysis URL moved from source code into configuration.
- Removed decorative emoji from the interface.

### Testing

- The test suite no longer makes network calls or reads real credentials or user settings.
- Added tests for health tracking, decision fallback, metric selection, both score sources, the request path, catalog parsing and application, and the main UI flows. The suite grew from 124 to 226 tests.

---

## Datasets and Models

Datasets:

1. https://huggingface.co/datasets/routellm/gpt4_judge_battles
2. https://huggingface.co/datasets/routellm/gpt4_dataset
3. https://huggingface.co/datasets/routellm/arena_battles_embeddings
4. https://huggingface.co/datasets/routellm/mmlu_battles_embeddings
5. https://huggingface.co/datasets/routellm/gpt4_judge_battles_embeddings
6. https://huggingface.co/datasets/routellm/mmlu_battles
7. https://huggingface.co/datasets/routellm/lmsys-arena-human-preference-55k-thresholds

Models: https://huggingface.co/routellm/models

---

## Attribution

Model scores: [Artificial Analysis](https://artificialanalysis.ai).

LMArena ratings are taken from the [LMArena leaderboard dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset), licensed under CC BY 4.0.

Decision classification uses the Clef-flash model on Cloudflare Workers AI.
