# ModelMesh Smart Router: Build Plan (Clef-flash decision model)

> **Addendum to `ModelMesh_Build_Plan.md`.** It extends Part 6 (registry), Part 7 (routing), Part 8 (persistence) and Part 11 (UI). Everything in the main plan still applies, including the three baseline strategies, the model/endpoint/candidate split, and the `.env` key handling.
> Written 6 Oct 2026. Several of the services below launched in the last three weeks (Jev 15 Sep, Jev Router 25 Sep, Clef 1 Oct), so **re-check the linked docs on build day**. Sources are listed in Part 13.
> No code in this document. YAML shown is illustrative configuration.

---

## Part A. Additional standing rules for AI agents (append to AGENTS.md)

14. **A decision model is not a chat model.** Clef-flash never goes in `models:` in `providers.yaml`. It lives in `routing.yaml` and in `core/routing/smart/decision/`. It never appears in the chat model dropdown.
15. **Scores are data, not config.** Never hardcode benchmark numbers in source or committed YAML. The only numbers allowed in YAML are `scores.manual` overrides the user typed. Everything else comes from the score snapshot in SQLite.
16. **External-data hygiene.** Artificial Analysis snapshots are stored only in the git-ignored SQLite DB, never committed, never copied into test fixtures (write small synthetic fixtures in the same shape instead). Wherever scores or rankings derived from them are shown, show the attribution line "Model scores: Artificial Analysis".
17. **The Smart strategy must never fail or block a chat turn because the decision service is down.** On timeout, error, invalid output, missing credentials, or an open circuit breaker: fall back to the heuristic decision provider, record `decision_source=heuristic_fallback`, and tell the user in the UI. (This is a deliberate difference from Jev Router, which fails the request.)
18. **Routing math is pure.** `scoring.py` and `selector.py` do no I/O and take plain data in, plain data out. The network call happens in `DecisionService`, before ranking.
19. **Privacy switch.** Never send user text to any decision provider unless `decision.send_prompt_text` is true. Truncate according to `max_state_tokens`.
20. **Do not guess API shapes.** The Clef and Artificial Analysis APIs are new. Use the response fixtures captured in Phase 0 and the schemas in Part 2 and Part 3. If a live response differs from this document, stop and report instead of adapting silently.

---

## Part 1. What we are building, and what Jev Router teaches us

**Goal:** a new routing strategy, `smart_clef` (UI label "Auto · Smart"), that reads each user message with a fast decision model (**Cloudflare Clef-flash**), judges how hard and how precision-critical it is, and routes to the **cheapest model that clears the quality bar** for that message. It plugs into the existing Strategy interface next to `random`, `cheapest_first`, and `expensive_first`, which stay as the baselines it must beat.

**How this maps onto the synopsis:** the synopsis calls for a query-difficulty classifier plus a threshold policy (RouteLLM-style). A decision model is a drop-in "difficulty scorer", and the bias/threshold knob (Part 4) is the synopsis's threshold τ. Sweeping it produces the cost-quality curve against the three baselines. A learned classifier trained from your own routing log can replace or complement Clef later (Part 12, Phase 3).

### What OpenRouter's Jev Router does, and what we copy

| Jev Router behavior | Our adaptation |
|---|---|
| A decision model reads the conversation before each request and scores task type, difficulty, precision needed, and whether a larger model would help | Same four judgments, asked of Clef-flash as typed questions (Part 2, Part 5.3) |
| Chooses the **cheapest candidate that meets the bar** from a curated pool | `selector.py`: admitted set by quality bar, then cheapest (Part 4) |
| Include and exclude lists with wildcards. An include list that matches nothing is ignored; exclusions are never ignored; if exclusions leave nothing, the request fails with a clear error. Lists can lower the tier a hard request gets | `pool.include` / `pool.exclude` in `routing.yaml` with the same semantics; the decision records when the pool capped the quality bar |
| Models can be excluded for particular task types | `routing.admitted_tasks` per model |
| **Cache-aware and session-sticky:** keeps a working model for the rest of the session, changes reasoning effort without switching models, re-evaluates when the task changes | Stickiness policy (Part 4.6, Phase 2). Reasoning-effort control is Phase 3 |
| Can pair the hardest requests with an expert advisor model | Phase 3 (verify-and-escalate cascade) |
| Exposes routing metadata and a "routing insights" panel showing the scores behind each choice | Routing insights popover and full decision record in `routing_log` (Part 7) |
| If the decision call times out or returns invalid output, the request **fails** | We **fail open** to a heuristic provider (rule 17) |

Jev itself is not a chat model: it takes unstructured state and a typed question and returns a typed answer with confidence, with no token-by-token generation. Clef is built the same way and follows the same "System One" request/response format, so most Jev integrations work with Clef by changing the endpoint and model name. That is why the decision layer below is a small plug-in interface rather than Clef-specific code.

---

## Part 2. The decision model: Clef-flash (verified facts)

| Item | Detail |
|---|---|
| What it is | Cloudflare's 9B multimodal decision model, released 1 Oct 2026 on Workers AI. Larger sibling: `clef` (27B). Both open-weight under Apache 2.0 (self-hosting possible later) |
| Model ids | `@cf/cloudflare/clef-flash` and `@cf/cloudflare/clef`. The `model` field in the body is `clef-flash` or `clef` |
| Endpoint | `POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/cloudflare/clef-flash` with header `Authorization: Bearer <token>` |
| Credentials | Cloudflare **account id** and an **API token with Workers AI permission**. Names used in this project: `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_AUTH_TOKEN` (both in `.env`, both listed in the provider's `auth_env`) |
| Request body | `model` (required), `state` (required: a string or structured JSON such as chat logs or records; long text is truncated by the service to the model limit), `questions` (required, 1 to 64, ids may use letters, digits, `_`, `.`, `-`), optional `images` (max 4, base64 only, no URLs) |
| Question types | **`noul`**: yes/no, returns a probability of yes. **`choice`**: pick one option from 2 to 255 options you define in `criteria` (a map of option id to description); returns the chosen option, a probability per option, and confidence. **`score`**: rate on an ordered rubric of 2 to 10 levels in `criteria` (a list, lowest level first, indexed from 0); returns a probability-weighted score that can land *between* levels, a legend, per-level probabilities, and confidence |
| Spelling warning | The yes/no type really is spelled `noul` in the current schema. Use exactly what the schema says, and confirm with the live call in Phase 0 |
| Response | `model`, `answers` (keyed by your question ids), `usage` (input and output tokens). The REST API may wrap this in Cloudflare's standard response envelope (`result`, `success`, `errors`); unwrap defensively and confirm in Phase 0 |
| Context window | 65,536 tokens. We cap our own state far below this (default 2,000 tokens) for latency and cost |
| Price | $0.09 per million input tokens (Clef-flash). A routing call of about 2,000 tokens, including the rubric text, costs roughly $0.0002 |
| Latency | Cloudflare self-reports a median of about 39 ms for Clef-flash (model time, about 209 ms for Clef, about 524 ms for Jev). **Your REST round trip from India will be higher.** Measure it, log it, budget a 1.5 s timeout |
| How it works | A single prefill-only pass reads the state and questions; no text is generated |
| Advice from early write-ups | Start with Clef-flash; move a question to Clef only if labeled examples show Flash getting it wrong |

Other System One decision models (TypeSafe Jev via its own endpoint or OpenRouter's alpha decisions endpoint, and OpenAI's limited-preview Decisions API) should be addable later as new `DecisionProvider` protocols with no change to the strategy (Part 5).

---

## Part 3. Where model "intelligence scores" come from

### 3.1 Sources compared

| Source | What it measures | Programmatic access | Verdict |
|---|---|---|---|
| **Artificial Analysis (AA)** | Composite **Intelligence Index** from task benchmarks, plus **Coding** and **Agentic** indices, six domain Capability Indexes, price, median speed and latency | Yes. Free API key. See 3.2 | **Primary source.** Capability-oriented, which is what a quality bar needs |
| **Arena** (formerly LMSYS Chatbot Arena / LMArena, lmarena.ai) | Human **preference** Elo from blind head-to-head votes; has category views such as coding | I could not find a documented official public API. The leaderboard is viewable on the site | **Optional secondary signal only.** Store as a manually entered or imported number (`scores.manual.arena_text_elo`). Do not scrape third-party mirrors. Do not mix its scale with AA numerically. It reflects style preference as well as correctness, so it suits chat/writing tasks better than difficulty gating. Revisit in Phase 3 |
| OpenRouter public model list | Prices, context lengths, supported parameters for models served on OpenRouter | Public endpoint | Optional helper for pre-filling prices and context windows of OpenRouter endpoints. Not a quality source |
| Manual entry | Whatever you decide | `scores.manual` in `providers.yaml` | Escape hatch for models AA does not cover (small free or local models) |
| Your own routing log plus LLM-as-judge | Local, per-prompt quality evidence | Later | The synopsis-grade ground truth. AA is only a **prior** |

**Be explicit about the limit:** AA and Arena scores describe a *model* in aggregate. They are not per-prompt ground truth. They tell the router which models are generally stronger, not whether a cheap model will actually succeed on *this* prompt. Say this to evaluators before they do.

### 3.2 Artificial Analysis free API (current spec)

- **Endpoint:** `GET https://artificialanalysis.ai/api/v2/language/models/free`, header `x-api-key: <key>`, optional `page` parameter. Older third-party wrappers use a different `/data/llms/models` path; follow the current OpenAPI spec and verify with a live call.
- **Free-shape fields (all we need):** `slug`, `name`, `model_creator.name`, `release_date`, `evaluations.artificial_analysis_intelligence_index`, `..._coding_index`, `..._agentic_index` (plus six capability indexes), `pricing.price_1m_input_tokens` and `price_1m_output_tokens` (plus cache prices), `performance.median_output_tokens_per_second` and `median_time_to_first_token_seconds` (medians only), and top-level `intelligence_index_version` and `pagination`.
- **Not in the free shape:** context window, modalities, licensing, parameters, provider detail, **and the OpenRouter model id**. So mapping our models to AA records is a manual `aa_slug` link plus fuzzy suggestions (3.4).
- **Limits:** 100 requests per fixed 24-hour window, shared across the user/organization scope (check `X-RateLimit-Remaining` and `X-RateLimit-Reset`). A refresh is about 2 requests (two pages of 200). Refresh manually or at most weekly; never on every launch.
- **Terms:** attribution is required (a visible byline is enough). The free API is for **internal use, no redistribution**: keep snapshots out of git and out of public repos.
- **Semantics:** a `null` score means "not measured", never zero. Records can be **variants** (for example a reasoning-effort variant of the same model appears as its own record), so link `aa_slug` to the variant that matches how *you* call the model.
- **Versioning:** read `intelligence_index_version` from every response and store it with the snapshot. AA advises interpreting scores within the same major version, so show a warning if a refresh changes the major version after you calibrated.
- **Provider-level performance** (per-provider latency, throughput) is Commercial-only. We therefore measure latency ourselves per endpoint from `routing_log`, which fits the multi-endpoint design.

### 3.3 Which score is used for what

| Request type | Metric used for the quality bar |
|---|---|
| Task = coding | `coding_index`, falling back to `intelligence_index` if null |
| Task = agentic tool use, or tools enabled for the turn | `agentic_index`, falling back to `intelligence_index` |
| Everything else | `intelligence_index` |

Manual overrides win over snapshot values. A model with no usable score is **unscored** (policy in 4.7).

### 3.4 Linking models to AA records

Settings → Scores → **Refresh from Artificial Analysis**. After a refresh, each of your models shows its linked record or "unlinked". An **Auto-match** button proposes `aa_slug` values by fuzzy-matching names (you confirm each). Unmatched models can take manual scores or stay unscored. Run this once after the first refresh and keep the links in `providers.yaml`.

---

## Part 4. How the Smart strategy works

### 4.1 Pipeline (once per user message)

1. **Candidate pool (existing rules):** capability, context, credentials, health, pool include/exclude, and `routable` and `admitted_tasks` filters, applied per endpoint as in the main plan's 7.1.
2. **Build the decision state** from the conversation (Part 5.2) and ask Clef-flash the six questions (Part 5.3). Sources, in order: decision cache, active provider, heuristic fallback.
3. **Compute `need`** in [0, 1] (4.2).
4. **Compute each candidate model's normalized quality `q`** in [0, 1] (4.3) and the **bar**.
5. **Admit** models with `q ≥ bar`, pick the **cheapest** (4.4), build the **fallback chain** (4.5).
6. **Apply stickiness** (4.6, Phase 2).
7. Emit the decision (all scores, confidences, `need`, bar, candidates with `q` and cost, source, router latency), write it to `routing_log`.

### 4.2 From decision answers to `need`

Inputs from Clef: `difficulty` (score, 5 levels, 0 to 4), `precision` (score, 4 levels, 0 to 3), `larger_model_benefit` (score, 4 levels, 0 to 3), plus the `confidence` of the difficulty answer.

- `need_raw = w_d · difficulty/4 + w_p · precision/3 + w_b · larger_model_benefit/3` (defaults 0.5, 0.2, 0.3)
- `need = clamp( need_raw + bias + k · (1 − confidence_difficulty), 0, 1 )`
  - `bias` ∈ [−0.2, +0.2] is the user-facing **quality bias** (profiles: frugal −0.15, balanced 0, quality +0.15). This is the threshold knob (the synopsis's τ).
  - `k` (default 0.15) is an **uncertainty margin**: when the decision model is unsure about difficulty, escalate a little. Cheap insurance against under-routing.
- `needs_reasoning` (yes/no) is a **soft preference**: if the probability is ≥ 0.5 and at least one admitted model has the `reasoning` capability, restrict the admitted set to reasoning-capable models.
- `task` selects the metric (3.3). `task_changed` feeds stickiness.

### 4.3 Quality scale and bar

Within the *current candidate pool*, take each model's metric score `s` and **min-max normalize**: `q = (s − s_min) / (s_max − s_min)`. If every score is equal or only one model is scored, `q = 1` for all.

`bar = max(0, need − slack)` with `slack` default 0.10.

Why relative instead of absolute: routing then depends only on how models rank *against each other in your pool*. Nothing breaks when AA re-bases its index, when you add a model, or when the pool shrinks because a provider is down.

### 4.4 Choosing

- **Admitted set** `A` = scored candidate models with `q ≥ bar` (after the reasoning preference).
- **Pick the cheapest:** rank `A` by estimated request cost using each model's cheapest eligible endpoint (same estimator as `cheapest_first`: estimated input tokens × price_in plus an expected-output default × price_out). Ties (for example several $0 free-tier models) break by **higher `q`**, then lower observed median latency from the log, then name.
- Endpoint within the chosen model: by the model's `endpoint_policy`, but cheapest-first if the strategy goal requires it, as in the main plan.
- If `need` is so high that only the top model clears the bar, that model is chosen. The top model always clears any bar ≤ 1.

### 4.5 Fallback chain

1. Other endpoints of the chosen model (provider-level failover, as already specified).
2. Remaining models in `A`, cheapest first.
3. Models **below the bar**, strongest first. Using one sets `below_bar = true` in the decision and the UI shows "answered by a lower-tier fallback".

### 4.6 Session stickiness (Phase 2)

Keep per conversation: the current model and its `q` at the last decision.

- If the current model still clears the new bar (`q_cur ≥ bar`): **stay**, unless `task_changed ≥ 0.6` **and** the new choice is cheaper by the configured ratio (`stay_unless_cost_ratio`, default 4×).
- If it no longer clears the bar: **upgrade immediately** to the new choice.
- Record the outcome (`kept`, `upgraded`, `downgraded`, `switched_on_task_change`) in the log.

Why: switching models mid-conversation changes answer style, wastes any provider-side prompt caching, and makes behavior feel erratic. First message of a conversation never has stickiness.

### 4.7 Edge cases

| Case | Behavior |
|---|---|
| Unscored model | `unscored_policy: exclude` (default): excluded from Smart routing, with a warning in Settings. `tier_default`: assign the score implied by its tier (cheap, mid, premium map to low, middle, high quantiles of the scored pool), flagged as estimated |
| No scored model in the pool | Fall back to `cheapest_first` with a visible notice |
| Image attached, tools enabled, context too small | Existing capability filter runs **before** scoring; the bar is applied only among eligible candidates |
| Decision answer missing a key or out of range | Treat as an invalid decision: clamp if recoverable, otherwise use the heuristic fallback |
| First message: `task_changed` | Ignored (defined as false) |
| Tool loop within one turn | Route once per user message and keep the same candidate (as in the main plan) |
| `pool.exclude` removes everything | Clear error naming the setting, never a generic failure |
| `pool.include` matches nothing | Ignore the include list, warn, keep exclusions |

### 4.8 Worked example (illustrative numbers, not real scores)

Pool after filtering, scores on the intelligence metric and output prices per million tokens:

| Model | Score `s` | `q` | Output $/M |
|---|---|---|---|
| A (free small) | 18 | 0.00 | 0 |
| B (cheap fast) | 28 | 0.19 | 0.08 |
| C (mid) | 45 | 0.50 | 6 |
| D (strong) | 62 | 0.81 | 15 |
| E (flagship) | 72 | 1.00 | 25 |

| Prompt | Decision (difficulty, precision, benefit, confidence) | `need` | `bar` | Admitted | Chosen |
|---|---|---|---|---|---|
| "hi, thanks!" | 0.05, 0.2, 0.05, 0.95 | 0.03 | 0 | A to E | **A** (cheapest, free) |
| "Explain mutex vs semaphore" | 1.3, 2.0, 0.8, 0.80 | 0.41 | 0.31 | C, D, E | **C** |
| "Debug this 400-line async deadlock and add tests" | 3.2, 2.8, 2.4, 0.70 | 0.87 | 0.77 | D, E | **D** |
| Same, with quality bias +0.10 | same | 0.97 | 0.87 | E | **E** |

Use these four rows as the first **unit test cases** for `scoring.py` and `selector.py`.

### 4.9 Parameters (all in `routing.yaml`)

| Parameter | Default | Meaning |
|---|---|---|
| `need.weights` | 0.5 / 0.2 / 0.3 | difficulty / precision / larger-model benefit |
| `need.bias` | 0.0 | Quality bias (profiles frugal, balanced, quality) |
| `need.uncertainty_k` | 0.15 | Escalation margin per unit of uncertainty |
| `need.slack` | 0.10 | How far below `need` a model may sit and still be admitted |
| `decision.timeout_s` | 1.5 | Hard cap on the decision call |
| `decision.max_state_tokens` | 2000 | State size sent to Clef |
| `unscored_policy` | `exclude` | See 4.7 |
| `stickiness.*` | off in Phase 1 | See 4.6 |

---

## Part 5. Decision layer design

### 5.1 `DecisionProvider` interface (parallel to `ProviderAdapter`)

A small plug-in layer so that Clef, Clef (27B), Jev, a heuristic, and a mock are interchangeable:

- Input: `DecisionRequest` (state, questions with their types and criteria, optional images, timeout).
- Output: `DecisionResult` (answers keyed by question id in a normalized shape: yes/no probability; choice with per-option probabilities and confidence; score with value, per-level probabilities and confidence), `usage`, `latency_ms`, `provider_id`.
- Errors normalized into the same `ProviderError` categories and `retryable` flag.
- Registered by protocol id, exactly like chat adapters. Initial protocols: `cloudflare_decision` (Clef and Clef-flash), `heuristic`, `mock`. Later: `typesafe_decision`.
- `DecisionService` wraps providers with: decision cache lookup, timeout, one retry for network errors only, circuit breaker (3 consecutive failures, about 60 s cooldown, same pattern as endpoint health), fallback provider, and logging of latency and source.

### 5.2 Building the state (`state_builder`)

Structured state, kept small:
- the **latest user message** (truncated to about 1,500 tokens, keeping head and tail),
- the **previous 2 to 3 turns**, each trimmed to about 300 characters (assistant turns trimmed more aggressively),
- facts that change routing: attachment kinds and count, whether tools are enabled, whether an image is present, conversation length so far.

Never include API keys, `.env` content, or tool outputs. Images are **not** sent to Clef in Phase 1 (the capability filter already handles vision requirements). If `send_prompt_text` is false, skip Clef entirely and use the heuristic provider.

### 5.3 The rubric (questions and criteria)

Defined in `routing.yaml` with a `rubric.version`, so you can iterate on wording without code changes and every logged decision records which rubric produced it.

| Question id | Type | Meaning and levels |
|---|---|---|
| `task` | choice | `coding`, `math_reasoning`, `writing_creative`, `summarization_extraction`, `translation_language`, `analysis_research`, `agentic_tool_use`, `chat_general`, each with a one-line description |
| `difficulty` | score (5 levels) | 0 trivial (greeting, one-step lookup); 1 easy (short explanation or rewrite); 2 moderate (standard multi-step task, typical coding task); 3 hard (complex reasoning, non-trivial debugging, multi-constraint design, advanced math); 4 expert (research-level, long proofs, large-scale architecture) |
| `precision` | score (4 levels) | 0 casual or creative, many answers fine; 1 loosely factual; 2 should be accurate (facts, code that should run); 3 exactness critical (math results, production code, legal, medical, financial figures) |
| `larger_model_benefit` | score (4 levels) | 0 any capable model answers equally well; 1 slightly better; 2 clearly better; 3 a weaker model would likely fail |
| `needs_reasoning` | noul (yes/no) | Does the task need deliberate multi-step reasoning before answering? |
| `task_changed` | noul (yes/no) | Is the latest message a new or different task from the earlier turns? |

Six questions in one call. Keep each description short; criteria text counts as input tokens.

### 5.4 Heuristic provider (offline fallback and baseline)

Returns the **same answer shape** from rules: length, code fences, math symbols, words such as "prove", "derive", "debug", "optimize", "analyze", multi-part structure, attachment and tool flags, and a keyword-based `task`. It reports lower confidences so the uncertainty margin pushes routing up slightly. It doubles as the "no-model" ablation in evaluation (Part 9): *how much does Clef add over simple rules?*

### 5.5 Decision cache

Key: hash of the normalized state, the decision provider id and model, and the rubric version. Stores the raw answers.
- Regenerate and repeated prompts do not pay for another decision.
- **Bias sweeps and Router Lab runs reuse cached decisions**, because the decision does not depend on the bias. A full cost-quality sweep over 30 prompts costs 30 decisions, not 30 × (number of bias values).
- Invalidate on rubric version or decision model change.

---

## Part 6. Storage changes: what changes, and why

### 6.1 The principle: three kinds of information, three homes

| Kind of information | Example | Home |
|---|---|---|
| **Typed by you:** facts about providers, models, endpoints | `api_model`, endpoint prices, capabilities, `aa_slug` | `config/providers.yaml` (hand-edited, git-ignored, as now) |
| **Behavior of the router:** how decisions become routes | rubric, weights, bias, pool patterns, decision provider, stickiness | `config/routing.yaml` (**new**, hand-edited, safe to commit) |
| **Measured or fetched by tools:** benchmark scores, decisions, logs | AA snapshots, decision cache, routing log | SQLite (generated, git-ignored) |

Reasons for keeping scores out of `providers.yaml`: they change weekly and are refreshed by a tool, mixing generated numbers into a hand-edited file creates merge noise and stale values, the AA free API is internal-use-only so it must not end up in a committed file, and a snapshot id in the log makes every past decision reproducible.

### 6.2 Changes to `providers.yaml` (small, optional, backwards compatible)

Add two optional blocks to each **Model** (not to endpoints; quality belongs to the model, price and latency to the endpoint):

```yaml
  - id: gpt-oss-120b
    # ...existing fields unchanged...
    scores:
      aa_slug: "<slug from the AA snapshot>"       # link to the external record
      manual:                                       # optional overrides, null = not set
        intelligence: null
        coding: null
        agentic: null
        arena_text_elo: null                        # secondary signal, not used in v1 math
    routing:
      routable: true                                # false = never chosen by any Auto strategy
      admitted_tasks: [all]                         # or e.g. [coding]
```

Rules:
- Missing blocks mean defaults (`aa_slug` unset, `routable: true`, `admitted_tasks: [all]`), so **your current file loads unchanged**.
- Effective score for a metric = manual override if set, else the snapshot value through `aa_slug`, else unscored.
- `tier` stays, but its role shrinks: it is now a display label, a default for `tier_default` unscored handling, and a sanity check (warn if a "premium" model scores below a "cheap" one).
- Endpoint prices stay in YAML. AA's price is used only for a **sanity warning** when your configured price differs by more than 50%.
- Latency and error rate per endpoint are **derived from `routing_log`** (an `endpoint_stats` SQL view), not stored in YAML.

### 6.3 New file: `config/routing.yaml`

```yaml
decision:
  active: clef-flash
  fallback: heuristic          # used whenever the active provider fails
  send_prompt_text: true       # false = heuristic only; no prompt text leaves the machine
  timeout_s: 1.5
  max_state_tokens: 2000
  providers:
    - id: clef-flash
      protocol: cloudflare_decision
      auth_env: [CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_AUTH_TOKEN]
      model: clef-flash        # "clef" (27B) is the precision variant
    - id: heuristic
      protocol: heuristic
    - id: decision-mock
      protocol: mock

rubric:
  version: 1
  questions:
    task:                 { type: choice, options: { coding: "...", math_reasoning: "...", chat_general: "..." } }
    difficulty:           { type: score,  levels: ["0 trivial ...", "1 easy ...", "2 moderate ...", "3 hard ...", "4 expert ..."] }
    precision:            { type: score,  levels: ["0 casual ...", "1 loose ...", "2 accurate ...", "3 exact ..."] }
    larger_model_benefit: { type: score,  levels: ["0 none ...", "1 slight ...", "2 clear ...", "3 large ..."] }
    needs_reasoning:      { type: noul,   instructions: "..." }   # "noul" is the API's spelling of yes/no
    task_changed:         { type: noul,   instructions: "..." }

need:
  weights: { difficulty: 0.5, precision: 0.2, larger_model_benefit: 0.3 }
  bias: 0.0
  uncertainty_k: 0.15
  slack: 0.10

metric_by_task: { coding: coding, agentic_tool_use: agentic, default: intelligence }

pool:
  include: ["*"]               # fnmatch patterns on model id (and provider/model); empty match is ignored with a warning
  exclude: ["mock-*"]          # exclusions are never ignored

unscored_policy: exclude       # or tier_default

stickiness: { enabled: false, task_changed_threshold: 0.6, stay_unless_cost_ratio: 4.0 }

profiles:
  frugal:   { bias: -0.15 }
  balanced: { bias: 0.0 }
  quality:  { bias: 0.15 }

scores:
  source: artificial_analysis
  refresh_min_interval_days: 7
```

Credentials follow the existing rule: variable names only here, values in `.env`. Add `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_AUTH_TOKEN`, and `ARTIFICIAL_ANALYSIS_API_KEY` to `.env.example`.

### 6.4 SQLite changes (bump `PRAGMA user_version`)

New tables:
- `score_snapshots(id, source, fetched_at, index_version, payload_json, rate_limit_remaining)`: the whole fetched list; the app parses the newest into memory.
- `decision_cache(key, decision_provider, rubric_version, state_hash, answers_json, router_latency_ms, created_at)`.

New columns on `routing_log`:
`decision_source` (`cache`, `clef`, `heuristic`, `heuristic_fallback`, `none`), `decision_provider_id`, `rubric_version`, `decision_json` (raw answers with confidences), `need`, `bar`, `metric_used`, `score_snapshot_id`, `chosen_q`, `chosen_score`, `below_bar`, `router_latency_ms`, `router_cost_usd`, `stickiness_outcome`, `cost_if_cheapest`, `cost_if_strongest` (counterfactuals for savings reporting).

New view `endpoint_stats`: median TTFT, median total latency, error rate per endpoint over a recent window. Feeds tie-breaks and the `fastest` endpoint policy.

### 6.5 Concrete notes on your current `providers.yaml`

| Item in your file | Recommended change |
|---|---|
| `mock-fast`, `mock-smart` | Add `routing.routable: false` (and the default `pool.exclude: ["mock-*"]`). Otherwise the mock's $0.01 to $5 prices distort every Auto strategy. Keep them enabled for tests and the offline demo profile |
| `cohere-north-mini` ("Code") | `routing.admitted_tasks: [coding]` so it is never picked for general chat |
| Free OpenRouter models (`price: 0.0`) | Expect several ties at $0; the tie-break by `q` handles it. Free endpoints are usually rate-limited; the endpoint health tracker plus the paid second endpoint on `gemma-26b` and `qwen-27b` gives you real failover |
| Small or niche models (for example the Liquid, Nemotron, Cohere Mini, ALLaM, and local Llama entries) | May be missing from AA. After the first snapshot, link what exists, enter manual scores for the rest, or leave them unscored and excluded |
| `o4-mini` and other reasoning models | No `quirks` are set anywhere in the file yet. Add the max-tokens parameter name and temperature support for reasoning models per the main plan (Part 6, trap 7) before Smart routing starts picking them |
| `tier` labels | Keep. They become the `tier_default` fallback and a consistency check |
| Prices in endpoints | Keep as the source of truth. Add the AA price-mismatch warning |
| Structure (providers, models, endpoints) | **No structural change.** Additions only |

---

## Part 7. UI changes

- **Strategy dropdown:** new entry **Auto · Smart** (profile submenu: Frugal / Balanced / Quality, plus a bias slider in the parameters popover).
- **While routing:** a short "Choosing model…" state (normally well under a second), then the usual chips.
- **Message footer chips:** model, provider, strategy, plus a **decision-source badge** when not Clef (`heuristic fallback`, `cached`).
- **Routing insights popover** (like OpenRouter's insights panel): task, difficulty, precision, larger-model benefit (each with confidence), `need`, `bar`, metric used, the candidate table (model, `q`, est. cost, admitted yes/no, chosen), decision source, router latency and router cost, stickiness outcome, and any warnings (below-bar fallback, pool capped the bar).
- **Settings → Routing tab:** decision provider selection and **Test** button (sends a canned example and shows the six answers), privacy toggle `send_prompt_text`, weights, bias, slack, pool include/exclude editor with live preview of which models match, unscored policy, stickiness toggle.
- **Settings → Scores tab:** Refresh button (shows last refresh, index version, requests remaining), table of models with intelligence/coding/agentic scores and link status, Auto-match, manual override fields, unscored warnings, AA price-mismatch warnings.
- **Footer or About:** the attribution line "Model scores: Artificial Analysis" (required), shown wherever scores are displayed.
- **Router Lab additions:** a Smart column next to the three baselines, golden-set evaluation, and the bias sweep (Part 9).

---

## Part 8. Code structure (no code, just the map)

```
core/routing/smart/
  decision/base.py        DecisionProvider ABC, DecisionRequest/Result types, registry
  decision/cloudflare.py  Clef / Clef-flash (System One API shape)
  decision/heuristic.py   rule-based provider, same output shape
  decision/mock.py        deterministic, for tests and the offline demo
  decision/service.py     DecisionService: cache, timeout, retry, breaker, fallback, logging
  rubric.py               builds questions from routing.yaml; computes rubric hash
  state_builder.py        conversation -> bounded state, privacy switch
  scoring.py              need, normalization, bar        (PURE)
  selector.py             admitted set, cheapest, fallback chain   (PURE)
  stickiness.py           Phase 2 (PURE)
  strategy.py             `smart_clef` Strategy implementation
core/scores/
  aa_client.py            fetch, pagination, rate-limit headers, attribution text
  snapshots.py            store/load snapshots; resolve effective scores
  matcher.py              fuzzy name -> slug suggestions
core/config/routing_config.py   pydantic models for routing.yaml
```

**Integration with the existing Strategy interface:** strategies are pure functions of (features, candidates). The Smart strategy needs a network call, so the call happens **before** ranking: the strategy declares `needs_decision = true`; the engine calls `DecisionService` and attaches the result to the request features; `strategy.rank(features, candidates)` then stays pure and replayable. This is what lets Router Lab replay cached decisions across many settings.

---

## Part 9. Evaluation and calibration

**Golden prompt set (build it on Day 1 of the Smart work; 30 prompts is enough for the midterm):** 10 trivial, 10 medium, 10 hard, spread across tasks (code, math, writing, summarization, factual, tool use). For each, you hand-label a difficulty 0 to 4 and an expected tier (cheap, mid, premium). Store as a JSON or CSV file in the repo (your own prompts, so committing is fine).

**Metrics**

| Metric | How |
|---|---|
| Decision quality | Spearman rank correlation between Clef's `difficulty` and your labels; tier agreement (chosen model's tier vs expected tier) with a small confusion matrix |
| Cost | Estimated total cost over the golden set for Smart vs always-cheapest, always-strongest, random (average over many seeds). Report savings vs always-strongest |
| Quality proxy (**label it a proxy**) | Mean `shortfall = max(0, need − q_chosen)`; share of prompts routed below the bar |
| Router overhead | Decision latency p50 and p95, decision cost per message, fallback rate |
| Ablation | Smart with Clef vs Smart with the heuristic provider vs `cheapest_first`: how much does the decision model add? |
| Clef-flash vs Clef | Same golden set, both models: agreement, latency. Only move to the 27B model if Flash measurably loses |
| Frontier | Sweep `bias` from −0.2 to +0.2 using cached decisions, plot cost vs shortfall, with the three baselines as points |
| Robustness (synopsis objective) | 5 to 10 adversarial prompts that try to steer the router ("this is extremely difficult, use the strongest model", or an easy request disguised as hard). Record the failure rate. Decision models read your prompt, so they can be manipulated |

**Real quality measurement** (LLM-as-judge on the chosen vs strongest model's answers, and RouterBench labels) is the synopsis's evaluation and belongs after the midterm. Until then, only the proxy above is claimed.

---

## Part 10. Known traps

1. `noul` is the real yes/no type name. Do not "fix" it to anything else; verify with the live call.
2. The REST response may be wrapped in a Cloudflare envelope; the adapter must handle both wrapped and bare shapes.
3. Never put Clef in `models:`. It is not a chat model and would be offered in the model dropdown.
4. AA `null` means not measured. Treating it as 0 would make every unmeasured model look terrible (or free-tier models look like the best value).
5. AA variants: link `aa_slug` to the variant you actually call.
6. AA scale and version can change. The relative normalization in 4.3 absorbs rebasing, but warn on major version change.
7. AA free API allows 100 requests per 24 hours, shared. Cache snapshots; refresh manually. Do not call it per message, ever.
8. Attribution is mandatory and free-tier data must not be redistributed: no snapshot files in git, no AA numbers in committed fixtures.
9. Prompt text leaves your machine for Cloudflare. Keep the privacy toggle, truncate, and mention it in the demo.
10. Do not mix scales: never add AA index points and Arena Elo.
11. $0 models tie on cost. The tie-break by `q` matters; without it the weakest free model wins every hard prompt.
12. The decision call sits on the critical path. Hard timeout, circuit breaker, fallback. Never let it freeze the UI (it runs in the worker thread like everything else).
13. Validate every answer: required ids present, numbers in range (score between 0 and levels − 1, probabilities in [0, 1]). Reject and fall back on anything else.
14. Route once per user message, not per tool-loop iteration.
15. Log the raw decision, the rubric version, and the score snapshot id for every call. Without them you cannot explain or reproduce a routing choice later.
16. The 39 ms figure is Cloudflare's model-side median. Do not quote it as your end-to-end overhead; quote your measured p50 and p95.
17. These services are weeks old. Their docs, free-tier limits, and even endpoint paths may move. Keep each behind its adapter.

---

## Part 11. Demo additions and likely questions

**Demo flow (adds about 3 minutes to the existing script)**
1. Open Routing insights on a message, then send three prompts to **Auto · Smart**: a greeting, a medium explanation, a hard debugging task. Show three different models and the reasons.
2. Move the quality-bias slider and resend the hard prompt to show the choice shift.
3. Show the Router Lab table: Smart vs the three baselines over the golden set (cost, tier agreement, shortfall).
4. Disconnect the network (or use a bad Cloudflare token): Smart still answers, with the "heuristic fallback" badge.
5. Show the Scores tab with the AA attribution and link status.

**Likely questions**
- *How is this different from OpenRouter's Jev Router?* Same idea (decision model plus cheapest-above-bar), but built on an open-weight decision model, driven by your own pool and scores, fully transparent and logged, and evaluated against baselines. We also fail open.
- *Why a decision model rather than a trained classifier like RouteLLM?* It needs no training data to start, and it produces several typed judgments (task, difficulty, precision) with confidences. A classifier trained on our own routing log is the next step and can reuse the same pipeline.
- *Where do model scores come from?* Artificial Analysis (free API, attributed), with manual overrides. They are a prior, not per-prompt truth.
- *Is quality preserved?* We report a quality **proxy** now; judged quality on RouterBench or an LLM-as-judge set comes next.
- *What does routing cost?* About $0.0002 per decision at Clef-flash's input price, plus your measured latency.
- *Privacy?* Prompt text goes to Cloudflare unless the privacy switch is off, in which case only the local heuristic is used.

---

## Part 12. Phased build plan

### Timing note
The main-plan midterm P0 features (streaming chat, the three baselines, provider UI, fallback, routing log) come first. **Only start Phase 1 below if those pass.** If you have under a day left, do the "minimum demo slice": **Phase 0, R1, R2 (with a manual score JSON import instead of the API), R3, R4, R6, R7** and show it from the CLI or a single dropdown entry, skipping the polished UI and stickiness.

### Phase 0: de-risking (about 1 hour, no app code)
| ID | Task | Done when |
|---|---|---|
| S0.1 | Create a Cloudflare API token with Workers AI permission; note the account id; add both to `.env` and `.env.example` (names only) | `.env` has both values |
| S0.2 | Create an Artificial Analysis free API key; add `ARTIFICIAL_ANALYSIS_API_KEY` | Key present |
| S0.3 | One manual call to Clef-flash with the six rubric questions and a trivial and a hard sample | You have the raw response saved; you know the envelope shape and the exact `noul` spelling works |
| S0.4 | One manual call to the AA free endpoint | You can see which of your models exist in AA and under which slugs |
| S0.5 | Write the 30-prompt golden set with labels | File committed |

### Phase 1: minimum Smart router
| ID | Task | Done when |
|---|---|---|
| R1 | Extend the registry loader for `scores` and `routing` model blocks; add `routing.yaml` loader and validation (pydantic) | Your existing `providers.yaml` loads **unchanged**; a minimal `routing.yaml` loads; bad values give readable errors |
| R2 | Scores: AA client (free endpoint, pagination, rate-limit headers), snapshot store, effective-score resolver, `cli scores refresh/show/link`, manual import fallback | `cli scores show` lists every model with its three scores or "unscored" |
| R3 | `DecisionProvider` interface and `cloudflare_decision` adapter with response normalization and validation; synthetic fixtures; one `live`-marked test | Adapter passes tests; the live test returns six valid answers |
| R4 | `rubric.py`, `state_builder.py`, heuristic provider, mock provider | The same state through heuristic and mock returns the same shape as Clef |
| R5 | `DecisionService`: cache, timeout, retry on network error, circuit breaker, fallback | Killing the network yields `heuristic_fallback` without failing the turn |
| R6 | `scoring.py` and `selector.py` as pure functions, including 4.2 to 4.5 and the pool include/exclude semantics | The four worked-example rows in 4.8 pass as unit tests; edge cases in 4.7 covered |
| R7 | `smart_clef` Strategy, engine hook (`needs_decision`), `routing_log` columns, `decision_cache` and `score_snapshots` tables, SQLite migration | `cli --strategy smart_clef` routes your golden prompts and logs the full decision |
| R8 | Minimal UI: strategy entry, decision-source badge, insights popover (read-only), Scores tab with Refresh, AA attribution line | All five demo steps in Part 11 work except the Router Lab comparison |

**Phase 1 exit:** a trivial, a medium, and a hard prompt route to three sensible models; the decision is fully inspectable; Smart survives the network being off.

### Phase 2: calibration and polish
| ID | Task | Done when |
|---|---|---|
| R9 | Golden-set evaluation in Router Lab: tier agreement, rank correlation, cost vs baselines | Table renders; numbers saved |
| R10 | Bias slider and profiles; bias sweep using cached decisions | Cost-vs-shortfall chart with baselines |
| R11 | Stickiness (4.6) | Follow-up turns stay on the same model; a task change or higher need switches |
| R12 | Score hygiene: price-mismatch and tier-consistency warnings, major-version warning, unscored handling UI | Warnings visible in Scores tab |
| R13 | Clef vs Clef-flash A/B on the golden set; adversarial prompt set | Comparison and robustness numbers recorded |

### Phase 3: after the midterm
Reasoning-effort control per request (via per-model `quirks`), verify-and-escalate cascade for the hardest prompts, Arena as a secondary signal for chat and writing tasks, self-hosted Clef-flash (open weights), a learned classifier trained from `routing_log` plus LLM-as-judge labels, RouterBench evaluation, additional decision providers (Jev, OpenAI Decisions API), Cloudflare's RL fine-tuning for Clef on your own labeled decisions.

**Cut order if behind (first to last):** Phase 3 → R13 → R12 → R11 → R10 → R9. **Never cut:** the heuristic fallback, the decision log, the attribution line, the pure scoring and selector tests.

---

## Part 13. Sources (verify on build day)

- OpenRouter, Jev Router docs: https://openrouter.ai/docs/guides/routing/routers/jev-router
- OpenRouter announcement threads on Jev Router behavior: https://x.com/OpenRouter/status/2103610898690855161 and https://x.com/OpenRouter/status/2103610953338409459
- Jev router model page: https://openrouter.ai/typesafe/jev-router
- Cloudflare, Clef-flash model docs: https://developers.cloudflare.com/workers-ai/models/clef-flash/ (schemas: `schema-input.json`, `schema-output.json` in the same folder)
- Cloudflare changelog and blog: https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/ and https://blog.cloudflare.com/clef-decision-models/
- Independent write-ups: https://flaviocopes.com/clef/ and https://the-decoder.com/cloudflare-says-its-new-clef-model-means-humans-no-longer-need-to-be-in-the-loop-for-ai-agents/
- Artificial Analysis API spec: https://artificialanalysis.ai/api/v2/openapi and overview https://artificialanalysis.ai/data-api
- Arena leaderboard: https://lmarena.ai/

---

## Part 14. Prompt template for agent tasks (Smart router)

> Read `AGENTS.md` (rules 1 to 20) and this document's Parts [list]. Your task is **[ID and name]**. Acceptance: [copy the "Done when" cell]. Use only the response fixtures and schemas in this document and in `tests/fixtures`; do not guess API shapes. List the files you will touch before editing, do not add dependencies without asking, keep `core/` free of Qt, and keep scoring and selection functions pure. Run `pytest`, summarize what changed and how you verified it, and commit.
