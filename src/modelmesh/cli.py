"""Headless CLI test harness for ModelMesh engine and routing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src is in sys.path when script is run directly
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from modelmesh.core.engine import ChatEngine
from modelmesh.core.keys import load_env
from modelmesh.core.registry import load_default_registry
from modelmesh.core.types import ChatRequest, Message, StreamEventType, Usage


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ModelMesh Headless CLI Test Harness",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("prompt", nargs="?", default="Hello, test prompt from ModelMesh CLI!", help="User prompt to send")
    parser.add_argument("--strategy", choices=["random", "cheapest_first", "expensive_first", "manual"], default="manual", help="Routing strategy")
    parser.add_argument("--model", type=str, default=None, help="Target model ID (manual mode)")
    parser.add_argument("--endpoint", type=str, default=None, help="Specific target endpoint ID (manual mode)")
    parser.add_argument("--config", type=str, default=None, help="Path to custom providers.yaml or config dir")
    parser.add_argument("--env-file", type=str, default=None, help="Path to .env secrets file")

    args = parser.parse_args()

    # Load environment variables (.env)
    env_path = Path(args.env_file) if args.env_file else None
    load_env(env_path)

    # Load registry
    config_dir = Path(args.config) if args.config else None
    registry = load_default_registry(config_dir)

    # Initialize Router, Storage, and Engine
    from modelmesh.core.routing.router import Router
    from modelmesh.core.storage import Storage
    router = Router(registry=registry)
    storage = Storage()
    engine = ChatEngine(registry=registry, router=router, storage=storage)

    # Select candidate or manual pins if specified
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
        messages=[Message.from_text(role="user", text=args.prompt)]
    )

    print(f"\n--- ModelMesh Turn Start (Strategy: {args.strategy}) ---")

    done_event_data = {}
    chosen_candidate = None
    final_usage: Usage = Usage()

    try:
        events = engine.run_turn(
            request=request,
            candidate=candidate,
            strategy_name=args.strategy,
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
