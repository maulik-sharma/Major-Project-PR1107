# ModelMesh

ModelMesh is an open-source desktop LLM routing client and proxy layer built with Python and PyQt6. It pools models across multiple commercial and local providers (OpenAI, Anthropic, Google Gemini, Groq, OpenRouter, and Ollama) and dynamically routes individual prompts to the most cost-effective model that satisfies the task requirements.

Instead of locking conversations to a single model or making manual switches between providers, ModelMesh analyzes incoming requests, evaluates required capabilities and complexity, resolves live benchmark scores, and dispatches the turn to optimal endpoints with automatic cross-provider failover.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Capabilities](#key-capabilities)
3. [Architecture and Design Principles](#architecture-and-design-principles)
4. [Routing Strategies](#routing-strategies)
   - [Auto · Smart Strategy (Clef-flash + Benchmark Scores)](#auto--smart-strategy-clef-flash--benchmark-scores)
   - [Baseline Strategies](#baseline-strategies)
5. [Candidate-Based Model Hierarchy](#candidate-based-model-hierarchy)
6. [Tools and Skills System](#tools-and-skills-system)
7. [Desktop Interface](#desktop-interface)
8. [CLI and Headless Harness](#cli-and-headless-harness)
9. [Installation and Setup](#installation-and-setup)
10. [Configuration Reference](#configuration-reference)
    - [providers.yaml](#providersyaml)
    - [routing.yaml](#routingyaml)
    - [Environment Variables (.env)](#environment-variables-env)
11. [Running the Application](#running-the-application)
12. [Testing](#testing)
13. [Project Structure](#project-structure)
14. [Attribution](#attribution)

---

## Overview

Modern LLM development often involves juggling multiple model APIs:
- Frontier reasoning models for complex architecture, proofs, or refactoring.
- Mid-tier models for standard coding, translation, and structured data extraction.
- High-throughput, low-cost (or free) models for simple queries, formatting, and classification.
- Provider-level redundancy to prevent service disruptions when rate limits or outages occur.

ModelMesh acts as an intelligent intermediary. For every chat turn, it:
1. Evaluates prompt complexity, required precision, and task category.
2. Identifies all eligible candidate endpoints that meet the capability bar.
3. Selects the lowest-cost endpoint above that threshold.
4. Streams the response with synchronous provider dispatch and token tracking.
5. Catches any runtime errors (429 rate limits, 500 server outages, timeouts) and immediately fails over to the next candidate in the generated fallback chain.

---

## Key Capabilities

- **Intelligent Prompt Routing**: Uses Cloudflare Workers AI Clef-flash decision model (or a deterministic heuristic fallback) to categorize tasks (coding, reasoning, creative, summarization, etc.) and calculate a difficulty score in milliseconds without blocking chat execution.
- **Dynamic Quality Bar Scoring**: Resolves model capabilities using normalized intelligence, coding, and agentic benchmark indexes from Artificial Analysis snapshots stored locally in SQLite.
- **Multi-Provider Failover**: Decouples logical models from physical provider endpoints. If an endpoint fails, ModelMesh falls back to alternate providers (e.g., OpenRouter free tier -> Groq -> Google Gemini -> Anthropic) without dropping the message.
- **Synchronous Worker Architecture**: Offloads all network I/O, streaming, and tool execution to background `QThread` workers, keeping the desktop UI responsive at 60 FPS.
- **Integrated Tool Execution**: Native support for safe AST calculation, local filesystem search/read/write, and live DuckDuckGo web search.
- **Prompt-Driven Skills**: Modular, Markdown-based skill packs that can be explicitly loaded or referenced via `@skill-name` syntax in prompt text.
- **Full Transparency & Insights**: Message footers display exact token usage, generation latency, calculated cost, and an interactive routing inspection popover detailing decision breakdowns and admitted candidates.

---

## Architecture and Design Principles

ModelMesh enforces strict software layering to ensure testability, reliability, and modularity:

```
+-------------------------------------------------------------------+
|                           PyQt6 UI Layer                          |
|  MainWindow, ChatView (WebEngine), Composer, Settings, Sidebar   |
+---------------------------------+---------------------------------+
                                  | (Qt Signals / Plain Data)
                                  v
+-------------------------------------------------------------------+
|                        Worker Threads Layer                       |
|           ChatWorker (QThread), Synchronous Streaming            |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|                        Core Engine Layer                          |
|   ChatEngine, Router, DecisionService, ToolRegistry, Skills      |
+------------------+------------------------------+-----------------+
                   |                              |
                   v                              v
+-----------------------------------+  +----------------------------+
|         Provider Adapters         |  |      Storage & Cache       |
| OpenAI, Anthropic, Gemini, Groq,  |  | SQLite: conversations,     |
| OpenRouter, Ollama, Mock          |  | logs, decision cache,      |
+-----------------------------------+  | score snapshots            |
                                       +----------------------------+
```

### Core Invariants

1. **Layer Separation**: `core/` contains pure Python domain logic and never imports PyQt or UI packages. `ui/` consumes `core/` via plain dataclasses and communicates over Qt signals.
2. **Provider Isolation**: Provider-specific SDK formatting and quirks live exclusively inside `src/modelmesh/core/providers/`. Adding a new OpenAI-compatible endpoint requires zero code modifications (configured via YAML).
3. **Pure Routing Math**: Scoring and candidate ranking logic (`scoring.py`, `selector.py`) are pure functions with no network I/O. Network calls happen upstream in `DecisionService`.
4. **Fail-Open Decisioning**: If the Cloudflare Clef-flash decision service experiences timeouts, API errors, or network partitions, the router immediately falls back to local heuristic classification (`decision_source=heuristic_fallback`) so chat turns are never blocked.
5. **No Secret Leakage**: API keys live only in the local, git-ignored `.env` file. Keys are never logged, printed, or exposed in error tracebacks.

---

## Routing Strategies

ModelMesh supports several routing strategies selectable per turn or configured globally:

### Auto · Smart Strategy (Clef-flash + Benchmark Scores)

The `smart_clef` strategy balances quality and cost per prompt through a four-stage pipeline:

1. **Decision Analysis**: Cloudflare's Clef-flash model (9B prefill-only decision model) processes the user prompt against a structured rubric to determine:
   - Primary task category (coding, math reasoning, creative writing, extraction, analysis, agentic tool use, or general chat).
   - Intellectual difficulty level ($0$ trivial to $4$ expert).
   - Logical precision requirement ($0$ casual to $3$ exact).
   - Larger model benefit ($0$ none to $3$ critical).
2. **Quality Bar Calculation**: The engine computes the required quality bar ($q_{\text{bar}}$) using configured rubric weights, uncertainty adjustments, and user profile biases (frugal, balanced, or quality).
3. **Admitted Set Filtering**: Candidates in the active model pool are filtered against the task-specific benchmark score (e.g. coding index for coding tasks, agentic index for tool tasks, intelligence index for general tasks).
4. **Cost-Optimal Selection**: The router selects the cheapest candidate whose score meets or exceeds the bar ($q \ge q_{\text{bar}}$) and constructs an ordered fallback chain from remaining eligible candidates.

### Baseline Strategies

- **Cheapest First (`cheapest_first`)**: Sorts all eligible candidates strictly by input and output token price.
- **Expensive / Frontier First (`expensive_first`)**: Prioritizes the highest-tier models for maximum capability.
- **Random (`random`)**: Selects uniformly at random across all eligible candidates.
- **Manual (`manual`)**: Directly routes to a user-pinned model or endpoint.

---

## Candidate-Based Model Hierarchy

ModelMesh differentiates between logical models, physical endpoints, and candidates:

- **Model**: A logical identity and capability baseline (e.g., `qwen-27b`, `claude-sonnet-5-5`, `gemma-26b`).
- **Endpoint**: A specific provider instance serving that model with its own `api_model` name, base URL, pricing per million tokens, priority, and quirks (e.g., `qwen-27b@groq` vs `qwen-27b@openrouter`).
- **Candidate**: The pair of a logical model and an active endpoint evaluated by the router.

---

## Tools and Skills System

### Built-in Tools

- **Calculator**: Secure mathematical expression evaluation using a restricted AST parser (supports trigonometry, logarithms, exponentials, and basic arithmetic without arbitrary Python execution).
- **Filesystem**: Workspace directory listing, text file reading, file creation/modification, and regex search across project files.
- **Web Search**: DuckDuckGo search querying and clean text extraction from public web pages.

### Skills Engine

Skills are modular domain instructions stored under `skills/<skill_name>/SKILL.md`. They support:
- YAML frontmatter defining name, version, and trigger descriptions.
- Markdown bodies containing specialized workflow instructions injected into the system prompt.
- Sub-resource loading via the `load_skill` tool.
- Explicit inline mentions (e.g., typing `@code-review` or `@deep-research` in chat).

---

## Desktop Interface

The ModelMesh desktop client is built on PyQt6 and QtWebEngine:

- **Web-Rendered Chat Canvas**: Markdown parsing, fenced code highlighting via Pygments, LaTeX math formatting with KaTeX, and copy-to-clipboard blocks.
- **Insights Popover**: Click the badge in any message footer to view the routing breakdown, prompt classification, quality bar calculation, and alternative candidate rankings.
- **Settings Dialog**:
  - **Endpoints Tab**: View and edit configured provider endpoints, priorities, and token pricing.
  - **Routing Tab**: Adjust decision provider options, privacy toggles, rubric weights, and profile biases.
  - **Scores Tab**: View active Artificial Analysis snapshot metadata, trigger score refreshes, run automatic slug matching, and manage manual score overrides.
  - **Tools Tab**: Configure allowed workspace paths, default web search limits, and tool permissions.
  - **Appearance Tab**: Switch between dark and light themes with custom palette styling.

---

## CLI and Headless Harness

ModelMesh includes a CLI tool (`modelmesh-cli` or `python3 src/modelmesh/cli.py`) for headless execution, automated testing, and score synchronization.

### Interactive and One-Shot Chat

```bash
# Run a one-shot turn with Auto · Smart routing
python3 src/modelmesh/cli.py "Explain the raft consensus algorithm in three bullet points" --strategy smart_clef

# Pin a specific model or endpoint
python3 src/modelmesh/cli.py "Write a merge sort in Rust" --model qwen-27b --strategy manual
```

### Intelligence Scores Management

```bash
# Refresh score snapshots from Artificial Analysis API
python3 src/modelmesh/cli.py scores refresh

# Display current model scores and effective rankings
python3 src/modelmesh/cli.py scores show

# Find fuzzy slug match suggestions for unlinked models
python3 src/modelmesh/cli.py scores auto-match
```

---

## Installation and Setup

### Prerequisites

- Python 3.11 or higher
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/maulik-sharma/Major-Project-PR1107.git
cd Major-Project-PR1107
```

### 2. Set Up a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies

```bash
# Install package in editable mode with development dependencies
pip install -e ".[dev]"
```

### 4. Configure Environment Variables

Create a `.env` file in the project root by copying the example file:

```bash
cp .env.example .env
```

Open `.env` and add API keys for the providers you intend to use:

```env
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
GROQ_API_KEY=your_groq_key
OPENROUTER_API_KEY=your_openrouter_key
GEMINI_API_KEY=your_gemini_key

# Cloudflare Workers AI (Required for Clef-flash decision routing)
CLOUDFLARE_ACCOUNT_ID=your_cloudflare_account_id
CLOUDFLARE_AUTH_TOKEN=your_cloudflare_workers_ai_token

# Artificial Analysis (Required for live benchmark scores)
ARTIFICIAL_ANALYSIS_API_KEY=your_artificial_analysis_key
```

---

## Configuration Reference

### providers.yaml

Located at `config/providers.yaml`, this file defines provider connections and the model catalog:

```yaml
providers:
  - id: groq
    protocol: openai_compat
    base_url: https://api.groq.com/openai/v1
    auth_env: [GROQ_API_KEY]

  - id: openrouter
    protocol: openai_compat
    base_url: https://openrouter.ai/api/v1
    auth_env: [OPENROUTER_API_KEY]

models:
  - id: qwen-27b
    display_name: "Qwen 3.8 27B"
    tier: mid
    context_window: 131072
    max_output: 8192
    capabilities: [streaming, tools]
    scores:
      aa_slug: "qwen3-8-27b"
    endpoints:
      - id: qwen-27b@groq
        provider: groq
        api_model: "qwen/qwen3.8-27b"
        price_in_per_mtok: 0.20
        price_out_per_mtok: 0.60
        priority: 1
        enabled: true
      - id: qwen-27b@openrouter
        provider: openrouter
        api_model: "qwen/qwen3.8-27b"
        price_in_per_mtok: 0.20
        price_out_per_mtok: 0.60
        priority: 2
        enabled: true
```

### routing.yaml

Located at `config/routing.yaml`, this file controls decision models, rubric weights, and selection rules:

```yaml
decision:
  active: clef-flash
  fallback: heuristic
  send_prompt_text: true
  timeout_s: 1.5
  max_state_tokens: 2000

need:
  weights:
    difficulty: 0.5
    precision: 0.2
    larger_model_benefit: 0.3
  bias: 0.0
  uncertainty_k: 0.15
  slack: 0.10

pool:
  include: ["*"]
  exclude: ["mock-*"]

profiles:
  frugal:
    bias: -0.15
  balanced:
    bias: 0.0
  quality:
    bias: 0.15
```

---

## Running the Application

### Launching the Desktop Client

```bash
python3 src/modelmesh/app.py
```

Or using the installed package entrypoint:

```bash
modelmesh
```

---

## Testing

ModelMesh includes a full test suite covering providers, adapters, tool execution, pure scoring math, routing fallback chains, and UI workers.

Run the test suite with pytest:

```bash
pytest
```

To run with verbose output:

```bash
pytest -v
```

---

## Project Structure

```
.
├── config/
│   ├── presets.yaml              # Strategy presets and default configurations
│   ├── providers.example.yaml    # Example provider and model definitions
│   ├── providers.yaml            # Active configured providers and endpoints
│   └── routing.yaml              # Smart decision rules, rubrics, and weights
├── data/
│   └── modelmesh.db              # SQLite persistence (conversations, scores, logs)
├── skills/                       # Built-in and user-defined Markdown skills
│   ├── code-review/
│   ├── deep-research/
│   └── ...
├── src/
│   └── modelmesh/
│       ├── app.py                # Desktop GUI application entrypoint
│       ├── cli.py                # Headless CLI and score management harness
│       ├── core/                 # Core engine layer (no GUI dependencies)
│       │   ├── config/           # Pydantic configuration schemas
│       │   ├── engine.py         # Chat turn generator and streaming coordinator
│       │   ├── providers/        # OpenAI, Anthropic, Gemini, Groq, Ollama adapters
│       │   ├── registry.py       # Model, provider, and candidate registry
│       │   ├── routing/          # Routing strategies, pure scoring math, and selector
│       │   │   └── smart/        # Clef-flash decision layer and heuristics
│       │   ├── scores/           # Artificial Analysis API client, snapshots, matcher
│       │   ├── storage.py        # SQLite schema migrations and persistence
│       │   └── tools/            # Built-in calculator, filesystem, and web tools
│       └── ui/                   # PyQt6 desktop client
│           ├── chat_view.py      # QWebEngineView integration
│           ├── composer.py       # Input editor, attachment handling, streaming actions
│           ├── main_window.py    # Main window and toolbar layout
│           ├── settings/         # Endpoints, Routing, Scores, Tools, Appearance tabs
│           ├── theme.py          # Dark and light QSS stylesheets
│           └── workers.py        # Background QThread execution
└── tests/                        # Comprehensive unit and integration test suite
```

---

## Datasets:
1. https://huggingface.co/datasets/routellm/gpt4_judge_battles
2. https://huggingface.co/datasets/routellm/gpt4_dataset
3. https://huggingface.co/datasets/routellm/arena_battles_embeddings
4. https://huggingface.co/datasets/routellm/mmlu_battles_embeddings
5. https://huggingface.co/datasets/routellm/gpt4_judge_battles_embeddings
6. https://huggingface.co/datasets/routellm/mmlu_battles
7. https://huggingface.co/datasets/routellm/lmsys-arena-human-preference-55k-thresholds

## Models
https://huggingface.co/routellm/models
   
## Attribution

Model intelligence metrics and benchmark ratings are provided by [Artificial Analysis](https://artificialanalysis.ai).

Decision classification is powered by Cloudflare Workers AI Clef-flash.
