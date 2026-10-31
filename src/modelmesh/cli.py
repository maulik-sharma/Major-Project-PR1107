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
from modelmesh.core.scores.arena_client import ARENA_ATTRIBUTION_TEXT, ARENA_SOURCE, LMArenaClient
from modelmesh.core.scores.matcher import arena_votes, match_identifiers, strict_match
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

    if args.scores_action == "refresh" and getattr(args, "source", "aa") == "arena":
        print("Downloading the LMArena text leaderboard...")
        try:
            snap = LMArenaClient().fetch_snapshot()
            store.save_snapshot(snap)
            print(f"Success! Saved {len(snap.models_by_slug)} models (published {snap.index_version}).")
            print(f"\n{ARENA_ATTRIBUTION_TEXT}")
            return 0
        except Exception as exc:
            print(f"Error refreshing LMArena ratings: {exc}", file=sys.stderr)
            return 1

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

    snapshot, note = store.get_active_snapshot(registry.models())
    arena = store.get_latest_snapshot(source=ARENA_SOURCE)

    if args.scores_action == "show":
        print(f"\n=== ModelMesh Model Scores ===")
        if snapshot:
            print(f"AA snapshot: {snapshot.id} (Fetched: {snapshot.fetched_at}, Index v{snapshot.index_version})")
            if note:
                print(f"Note: {note}")
        else:
            print("Notice: No AA snapshot. Run 'modelmesh-cli scores refresh'.")
        print(f"Arena snapshot: published {arena.index_version}" if arena
              else "Notice: No LMArena snapshot. Run 'modelmesh-cli scores refresh --source arena'.")

        def fmt(v: Optional[float], d: int = 1) -> str:
            return f"{v:.{d}f}" if v is not None else "-"

        print(f"{'Model ID':<22} | {'Intel':<6} | {'Code':<6} | {'Agent':<6} | {'Arena':<6} | {'ArCode':<6} | {'Status'}")
        print("-" * 78)
        for m in registry.models():
            eff = resolve_effective_scores(m, snapshot, arena)
            print(
                f"{m.id:<22} | {fmt(eff.intelligence):<6} | {fmt(eff.coding):<6} | {fmt(eff.agentic):<6} | "
                f"{fmt(eff.arena.get('overall'), 0):<6} | {fmt(eff.arena.get('coding'), 0):<6} | {eff.source}"
            )
        print(f"\n{ATTRIBUTION_TEXT} · {ARENA_ATTRIBUTION_TEXT}")
        print("Legend: - = not benchmarked. Smart ranks each task on the first metric that covers enough models.\n")
        return 0

    elif args.scores_action == "auto-match":
        aa_records = list(snapshot.models_by_slug.values()) if snapshot else []
        arena_records = list(arena.models_by_slug.values()) if arena else []
        if not aa_records and not arena_records:
            print("Error: No score snapshot found. Run 'scores refresh' first.", file=sys.stderr)
            return 1
        print("\n=== Exact Matches for Models (current link -> exact match) ===")
        for m in registry.models():
            ids = match_identifiers(m)
            aa_hit = strict_match(ids, aa_records) if aa_records else None
            arena_hit = strict_match(ids, arena_records, arena_votes) if arena_records else None
            print(f"{m.id:<22} AA: {m.scores.aa_slug or '-'} -> {aa_hit or 'no exact match'}"
                  f" | Arena: {m.scores.arena_name or '-'} -> {arena_hit or 'no exact match'}")
        print("\nEdit providers.yaml (scores.aa_slug / scores.arena_name) or use Settings > Scores to apply.")
        print(f"\n{ATTRIBUTION_TEXT} · {ARENA_ATTRIBUTION_TEXT}\n")
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
        scores_parser.add_argument("--source", choices=["aa", "arena"], default="aa", help="Score source to refresh")
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
