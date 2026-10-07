"""Headless CLI test harness for ModelMesh engine, routing, and scores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Ensure src is in sys.path when script is run directly
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from modelmesh.core.engine import ChatEngine
from modelmesh.core.keys import load_env
from modelmesh.core.registry import load_default_registry
from modelmesh.core.routing.router import Router
from modelmesh.core.scores.aa_client import (
    ATTRIBUTION_TEXT,
    ArtificialAnalysisClient,
)
from modelmesh.core.scores.matcher import suggest_model_slugs
from modelmesh.core.scores.snapshots import (
    ScoreSnapshot,
    ScoreStore,
    resolve_effective_scores,
)
from modelmesh.core.storage import Storage
from modelmesh.core.types import ChatRequest, Message, StreamEventType, Usage


def handle_scores_command(args: argparse.Namespace, storage: Storage) -> int:
    """Handle CLI subcommands for intelligence scores."""
    store = ScoreStore(storage)
    registry = load_default_registry()

    if args.scores_action == "refresh":
        print("Fetching latest models from Artificial Analysis API...")
        client = ArtificialAnalysisClient()
        try:
            models, index_version, remaining = client.fetch_all_models()
            snap = ScoreSnapshot.from_raw(
                models_list=models,
                index_version=index_version,
                rate_limit_remaining=remaining,
            )
            sid = store.save_snapshot(snap)
            print(f"Success! Saved snapshot '{sid}' with {len(models)} models (Index version: {index_version}).")
            if remaining is not None:
                print(f"API Rate limit remaining: {remaining}/100 requests.")
            print(f"\n{ATTRIBUTION_TEXT}")
            return 0
        except Exception as exc:
            print(f"Error refreshing scores: {exc}", file=sys.stderr)
            return 1

    elif args.scores_action == "show":
        snapshot = store.get_latest_snapshot()
        print(f"\n=== ModelMesh Model Intelligence Scores ===")
        if snapshot:
            print(f"Active Snapshot: {snapshot.id} (Fetched: {snapshot.fetched_at}, Index v{snapshot.index_version})")
        else:
            print("Notice: No snapshot found in database. Run 'modelmesh scores refresh' to fetch from AA.")

        print(f"{'Model ID':<22} | {'Linked AA Slug':<30} | {'Intel':<7} | {'Code':<7} | {'Agent':<7} | {'Status'}")
        print("-" * 93)
        for m in registry.models():
            eff = resolve_effective_scores(m, snapshot)
            intel_s = f"{eff.intelligence:.1f}" if eff.intelligence is not None else "-"
            if eff.coding is not None:
                code_s = f"{eff.coding:.1f}*" if eff.is_coding_inherited else f"{eff.coding:.1f}"
            else:
                code_s = "-"
            if eff.agentic is not None:
                agent_s = f"{eff.agentic:.1f}*" if eff.is_agentic_inherited else f"{eff.agentic:.1f}"
            else:
                agent_s = "-"
            slug_s = (m.scores.aa_slug or "-")[:28]
            status = eff.source
            print(f"{m.id:<22} | {slug_s:<30} | {intel_s:<7} | {code_s:<7} | {agent_s:<7} | {status}")

        print(f"\n{ATTRIBUTION_TEXT}")
        print("Legend: * = Inherited from Intelligence Index (sub-index not separately benchmarked by AA)\n")
        return 0

    elif args.scores_action == "auto-match":
        snapshot = store.get_latest_snapshot()
        if not snapshot:
            print("Error: No score snapshot found. Run 'scores refresh' first.", file=sys.stderr)
            return 1
        raw_models = snapshot.raw_payload.get("models", [])
        print("\n=== Proposed Slug Matches for Unlinked Models ===")
        for m in registry.models():
            if not m.scores.aa_slug:
                suggestions = suggest_model_slugs(m.id, raw_models, limit=3)
                print(f"\nModel: {m.id} ({m.display_name})")
                if suggestions:
                    for s in suggestions:
                        print(f"  -> {s['slug']:<32} | Intel: {s.get('intelligence')} | Similarity: {s['similarity']}")
                else:
                    print("  -> No close matches found.")
        print(f"\n{ATTRIBUTION_TEXT}\n")
        return 0

    return 0


def main() -> int:
    # Check if scores subcommand is invoked
    if len(sys.argv) > 1 and sys.argv[1] == "scores":
        scores_parser = argparse.ArgumentParser(
            description="ModelMesh Model Intelligence Scores Manager",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        scores_parser.add_argument("subcommand", choices=["scores"])
        scores_parser.add_argument("scores_action", choices=["refresh", "show", "auto-match"], help="Score action")
        args = scores_parser.parse_args()

        load_env()
        storage = Storage()
        return handle_scores_command(args, storage)

    parser = argparse.ArgumentParser(
        description="ModelMesh Headless CLI Test Harness and Scoring Manager",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("prompt", nargs="?", default="Hello! Could you explain the difference between a mutex and a semaphore in operating systems?", help="User prompt to send")
    parser.add_argument(
        "--strategy",
        choices=["random", "cheapest_first", "expensive_first", "manual", "smart_clef", "auto"],
        default="smart_clef",
        help="Routing strategy",
    )
    parser.add_argument("--model", type=str, default=None, help="Target model ID (manual mode)")
    parser.add_argument("--endpoint", type=str, default=None, help="Specific target endpoint ID (manual mode)")
    parser.add_argument("--config", type=str, default=None, help="Path to custom providers.yaml or config dir")
    parser.add_argument("--env-file", type=str, default=None, help="Path to .env secrets file")

    args = parser.parse_args()

    # Load environment variables (.env)
    env_path = Path(args.env_file) if args.env_file else None
    load_env(env_path)

    storage = Storage()
    prompt_text = args.prompt
    config_dir = Path(args.config) if args.config else None
    registry = load_default_registry(config_dir)

    router = Router(registry=registry, storage=storage)
    engine = ChatEngine(registry=registry, router=router, storage=storage)

    candidate = None
    pinned_model = None
    pinned_endpoint = None

    if args.endpoint:
        pinned_endpoint = args.endpoint
        candidate = registry.get_candidate(args.endpoint)
        if not candidate:
            print(f"Error: Endpoint '{args.endpoint}' not found in registry.", file=sys.stderr)
            return 1
    elif args.model:
        pinned_model = args.model

    request = ChatRequest(
        messages=[Message.from_text(role="user", text=prompt_text)]
    )

    strat_label = "smart_clef" if args.strategy == "auto" else args.strategy
    print(f"\n--- ModelMesh Turn Start (Strategy: {strat_label}) ---")

    done_event_data = {}
    chosen_candidate = None
    final_usage: Usage = Usage()

    try:
        events = engine.run_turn(
            request=request,
            candidate=candidate,
            strategy_name=strat_label,
            pinned_model_id=pinned_model,
            pinned_endpoint_id=pinned_endpoint,
        )

        for ev in events:
            if ev.type == StreamEventType.ROUTED:
                cand = ev.data.get("candidate")
                chosen_candidate = cand
                reason = ev.data.get("reason", "")
                if cand:
                    print(f"[ROUTED] Candidate: {cand.endpoint_id} ({cand.provider_id}) | {reason}")
            elif ev.type == StreamEventType.FALLBACK:
                from_c = ev.data.get("from_candidate")
                to_c = ev.data.get("to_candidate")
                err = ev.data.get("error")
                print(f"\n[FALLBACK] {from_c.endpoint_id} failed ({err}) -> Trying {to_c.endpoint_id}...")
            elif ev.type == StreamEventType.REASONING_DELTA and ev.reasoning:
                sys.stdout.write(f"\033[90m{ev.reasoning}\033[0m")
                sys.stdout.flush()
            elif ev.type == StreamEventType.TEXT_DELTA and ev.text:
                sys.stdout.write(ev.text)
                sys.stdout.flush()
            elif ev.type == StreamEventType.USAGE and ev.usage:
                final_usage = ev.usage
            elif ev.type == StreamEventType.ERROR:
                err_msg = ev.data.get("error")
                print(f"\n[ERROR] {err_msg}", file=sys.stderr)
                return 1
            elif ev.type == StreamEventType.DONE:
                done_event_data = ev.data
                if ev.usage:
                    final_usage = ev.usage

        print("\n")
        if done_event_data:
            cand = done_event_data.get("candidate", chosen_candidate)
            cand_id = cand.endpoint_id if cand else "unknown"
            prov_id = cand.provider_id if cand else "unknown"
            cost = done_event_data.get("cost_usd", 0.0)
            lat = done_event_data.get("latency_sec", 0.0)
            in_tok = final_usage.input_tokens
            out_tok = final_usage.output_tokens
            print(f"--- [Turn Completed] Endpoint: {cand_id} | Provider: {prov_id} | In/Out Tokens: {in_tok}/{out_tok} | Cost: ${cost:.6f} | Latency: {lat}s ---")

        return 0
    except Exception as exc:
        print(f"\nFatal Engine Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
