"""Unit tests for SQLite storage, routing logs, and usage aggregation."""

from pathlib import Path
import pytest

from modelmesh.core.engine import ChatEngine
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.router import Router
from modelmesh.core.storage import Storage
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    EndpointConfig,
    Message,
    ModelConfig,
    ProviderConfig,
    RoutingDecision,
    StreamEventType,
    Usage,
)


def test_storage_conversations_and_messages(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    storage = Storage(db_file)

    # Create conversation
    conv_id = storage.create_conversation(title="Test Chat", system_prompt="Be helpful")
    assert conv_id is not None

    conv = storage.get_conversation(conv_id)
    assert conv["title"] == "Test Chat"
    assert conv["system_prompt"] == "Be helpful"

    # Save messages
    msg1 = Message.from_text(role="user", text="Hello from user")
    msg2 = Message.from_text(role="assistant", text="Hello from assistant")

    storage.save_message(msg1, conversation_id=conv_id)
    storage.save_message(
        msg2,
        conversation_id=conv_id,
        model_id="mock-fast",
        endpoint_id="mock-fast@mock",
        provider_id="mock",
        tokens_in=5,
        tokens_out=10,
        cost=0.0001,
        latency_ms=120,
    )

    messages = storage.get_messages(conv_id)
    assert len(messages) == 2
    assert messages[0].text_content() == "Hello from user"
    assert messages[1].text_content() == "Hello from assistant"
    assert messages[1].meta["model_id"] == "mock-fast"
    assert messages[1].meta["tokens_in"] == 5

    # Update conversation
    storage.update_conversation(conv_id, title="Updated Chat Title")
    conv_updated = storage.get_conversation(conv_id)
    assert conv_updated["title"] == "Updated Chat Title"

    # Delete conversation
    storage.delete_conversation(conv_id)
    assert storage.get_conversation(conv_id) is None
    assert len(storage.get_messages(conv_id)) == 0


def test_routing_log_and_usage_summary(tmp_path: Path) -> None:
    db_file = tmp_path / "test_routing.db"
    storage = Storage(db_file)

    provider = ProviderConfig(id="mock", protocol="mock")
    model = ModelConfig(
        id="mock-fast",
        display_name="Mock Fast",
        endpoints=[
            EndpointConfig(
                id="mock-fast@mock",
                provider="mock",
                api_model="mock-instant",
                price_in_per_mtok=0.01,
                price_out_per_mtok=0.02,
            )
        ],
    )
    cand = Candidate.resolve(model, model.endpoints[0], provider)

    decision = RoutingDecision(
        chosen_candidate=cand,
        fallback_chain=[],
        strategy_name="cheapest_first",
        reason="Cheapest mock model",
        request_features={"input_tokens": 10},
    )

    usage = Usage(input_tokens=100, output_tokens=50)
    log_id = storage.record_routing_log(
        decision=decision,
        chosen_candidate=cand,
        usage=usage,
        cost_usd=0.000002,
        latency_ms=85,
        ttft_ms=25,
    )
    assert log_id == decision.decision_id

    logs = storage.get_routing_logs()
    assert len(logs) == 1
    assert logs[0]["chosen_endpoint_id"] == "mock-fast@mock"
    assert logs[0]["strategy"] == "cheapest_first"
    assert logs[0]["tokens_in"] == 100
    assert logs[0]["tokens_out"] == 50

    summary = storage.get_usage_summary()
    assert summary["totals"]["total_requests"] == 1
    assert summary["totals"]["total_tokens_in"] == 100
    assert summary["totals"]["total_tokens_out"] == 50
    assert len(summary["by_model"]) == 1
    assert summary["by_model"][0]["chosen_model_id"] == "mock-fast"
    assert len(summary["by_endpoint"]) == 1
    assert summary["by_endpoint"][0]["chosen_endpoint_id"] == "mock-fast@mock"


def test_engine_writes_routing_log(tmp_path: Path) -> None:
    db_file = tmp_path / "test_engine_db.db"
    storage = Storage(db_file)

    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="mock", protocol="mock"))
    reg.add_model(
        ModelConfig(
            id="mock-fast",
            display_name="Mock Fast",
            endpoints=[
                EndpointConfig(
                    id="mock-fast@mock",
                    provider="mock",
                    api_model="mock-instant",
                    price_in_per_mtok=0.01,
                    price_out_per_mtok=0.02,
                )
            ],
        )
    )

    router = Router(registry=reg)
    engine = ChatEngine(registry=reg, router=router, storage=storage)
    req = ChatRequest(messages=[Message.from_text("user", "Testing engine persistence")])

    events = list(engine.run_turn(request=req, strategy_name="cheapest_first"))
    assert events[-1].type == StreamEventType.DONE

    # Check that storage has the routing log row
    logs = storage.get_routing_logs()
    assert len(logs) == 1
    assert logs[0]["chosen_model_id"] == "mock-fast"
    assert logs[0]["tokens_in"] > 0
    assert logs[0]["tokens_out"] > 0
