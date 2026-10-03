"""SQLite persistence for conversations, messages, routing logs, and usage totals."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from modelmesh.core.types import (
    Candidate,
    Message,
    RoutingDecision,
    Usage,
)

SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    system_prompt TEXT,
    settings_json TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    model_id TEXT,
    endpoint_id TEXT,
    provider_id TEXT,
    routing_log_id TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost REAL DEFAULT 0.0,
    latency_ms INTEGER DEFAULT 0,
    status TEXT DEFAULT 'complete',
    created_at REAL NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS routing_log (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    conversation_id TEXT,
    message_id TEXT,
    strategy TEXT NOT NULL,
    chosen_model_id TEXT NOT NULL,
    chosen_endpoint_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    fallback_chain_json TEXT,
    candidates_scores_json TEXT,
    features_json TEXT,
    reason TEXT,
    cache_status TEXT DEFAULT 'miss',
    ttft_ms INTEGER DEFAULT 0,
    total_latency_ms INTEGER DEFAULT 0,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    estimated_cost REAL DEFAULT 0.0,
    error_category TEXT
);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    message_id TEXT,
    name TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    stored_path TEXT,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tool_runs (
    id TEXT PRIMARY KEY,
    message_id TEXT,
    tool TEXT NOT NULL,
    args_json TEXT NOT NULL,
    result_text TEXT,
    latency_ms INTEGER DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_routing_created ON routing_log(created_at);
CREATE INDEX IF NOT EXISTS idx_routing_endpoint ON routing_log(chosen_endpoint_id);
"""


def get_default_db_path() -> Path:
    """Determine SQLite database storage path in project data directory."""
    data_dir = Path.cwd() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "modelmesh.db"


class Storage:
    """Thread-safe SQLite storage layer for ModelMesh."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else get_default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        db_str = str(self.db_path)
        if db_str == ":memory:":
            if not hasattr(self, "_mem_conn") or self._mem_conn is None:
                self._mem_conn = sqlite3.connect(
                    "file:memdb_shared?mode=memory&cache=shared",
                    uri=True,
                    check_same_thread=False,
                    timeout=15.0,
                )
                self._mem_conn.row_factory = sqlite3.Row
            return self._mem_conn

        conn = sqlite3.connect(
            db_str,
            check_same_thread=False,
            timeout=15.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.executescript(SCHEMA_SQL)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION};")
                conn.commit()

    # --- Conversation Operations ---

    def create_conversation(
        self,
        title: str = "New Chat",
        system_prompt: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        conv_id: Optional[str] = None,
    ) -> str:
        cid = conv_id or str(uuid.uuid4())
        now = time.time()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO conversations (id, title, created_at, updated_at, system_prompt, settings_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        title,
                        now,
                        now,
                        system_prompt,
                        json.dumps(settings or {}),
                    ),
                )
                conn.commit()
        return cid

    def get_conversation(self, conv_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
                if not row:
                    return None
                d = dict(row)
                d["settings"] = json.loads(d["settings_json"] or "{}")
                return d

    def list_conversations(self) -> List[Dict[str, Any]]:
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
                results = []
                for r in rows:
                    d = dict(r)
                    d["settings"] = json.loads(d["settings_json"] or "{}")
                    results.append(d)
                return results

    def update_conversation(
        self,
        conv_id: str,
        title: Optional[str] = None,
        system_prompt: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            with self._get_connection() as conn:
                now = time.time()
                updates = ["updated_at = ?"]
                params: List[Any] = [now]
                if title is not None:
                    updates.append("title = ?")
                    params.append(title)
                if system_prompt is not None:
                    updates.append("system_prompt = ?")
                    params.append(system_prompt)
                if settings is not None:
                    updates.append("settings_json = ?")
                    params.append(json.dumps(settings))
                params.append(conv_id)
                conn.execute(f"UPDATE conversations SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()

    def delete_conversation(self, conv_id: str) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
                conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
                conn.commit()

    # --- Message Operations ---

    def save_message(
        self,
        message: Message,
        conversation_id: str,
        model_id: Optional[str] = None,
        endpoint_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        routing_log_id: Optional[str] = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
        latency_ms: int = 0,
        status: str = "complete",
    ) -> None:
        content_dict = {
            "parts": [p.to_dict() for p in message.parts],
            "tool_calls": [tc.to_dict() for tc in message.tool_calls],
            "tool_call_id": message.tool_call_id,
            "meta": message.meta,
        }
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO messages (
                        id, conversation_id, role, content_json, model_id, endpoint_id,
                        provider_id, routing_log_id, tokens_in, tokens_out, cost,
                        latency_ms, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.id,
                        conversation_id,
                        message.role,
                        json.dumps(content_dict),
                        model_id,
                        endpoint_id,
                        provider_id,
                        routing_log_id,
                        tokens_in,
                        tokens_out,
                        cost,
                        latency_ms,
                        status,
                        message.created_at,
                    ),
                )
                # Touch conversation updated_at
                conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (time.time(), conversation_id))
                conn.commit()

    def get_messages(self, conversation_id: str) -> List[Message]:
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                    (conversation_id,),
                ).fetchall()
                messages: List[Message] = []
                for r in rows:
                    raw_content = json.loads(r["content_json"])
                    raw_content["id"] = r["id"]
                    raw_content["role"] = r["role"]
                    raw_content["created_at"] = r["created_at"]
                    msg = Message.from_dict(raw_content)
                    msg.meta.update({
                        "model_id": r["model_id"],
                        "endpoint_id": r["endpoint_id"],
                        "provider_id": r["provider_id"],
                        "tokens_in": r["tokens_in"],
                        "tokens_out": r["tokens_out"],
                        "cost": r["cost"],
                        "latency_ms": r["latency_ms"],
                        "status": r["status"],
                    })
                    messages.append(msg)
                return messages

    # --- Routing Log Operations ---

    def record_routing_log(
        self,
        decision: RoutingDecision,
        chosen_candidate: Candidate,
        usage: Usage,
        cost_usd: float,
        latency_ms: int,
        ttft_ms: int = 0,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
        error_category: Optional[str] = None,
    ) -> str:
        log_id = decision.decision_id or str(uuid.uuid4())
        fallback_ids = [c.endpoint_id for c in decision.fallback_chain]
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO routing_log (
                        id, created_at, conversation_id, message_id, strategy,
                        chosen_model_id, chosen_endpoint_id, provider_id,
                        fallback_chain_json, candidates_scores_json, features_json,
                        reason, cache_status, ttft_ms, total_latency_ms,
                        tokens_in, tokens_out, cached_tokens, reasoning_tokens,
                        estimated_cost, error_category
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        log_id,
                        decision.created_at,
                        conversation_id,
                        message_id,
                        decision.strategy_name,
                        chosen_candidate.model_id,
                        chosen_candidate.endpoint_id,
                        chosen_candidate.provider_id,
                        json.dumps(fallback_ids),
                        json.dumps(decision.eligible_candidates),
                        json.dumps(decision.request_features),
                        decision.reason,
                        "miss",
                        ttft_ms,
                        latency_ms,
                        usage.input_tokens,
                        usage.output_tokens,
                        usage.cached_tokens,
                        usage.reasoning_tokens,
                        cost_usd,
                        error_category,
                    ),
                )
                conn.commit()
        return log_id

    def get_routing_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM routing_log ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]

    def get_usage_summary(self) -> Dict[str, Any]:
        """Aggregate usage metrics by model, provider/endpoint, and overall total."""
        with self._lock:
            with self._get_connection() as conn:
                # Total summary
                total_row = conn.execute(
                    """
                    SELECT COUNT(*) as total_requests,
                           SUM(tokens_in) as total_tokens_in,
                           SUM(tokens_out) as total_tokens_out,
                           SUM(estimated_cost) as total_cost,
                           AVG(total_latency_ms) as avg_latency_ms
                    FROM routing_log
                    """
                ).fetchone()

                # By model
                by_model_rows = conn.execute(
                    """
                    SELECT chosen_model_id,
                           COUNT(*) as request_count,
                           SUM(tokens_in) as tokens_in,
                           SUM(tokens_out) as tokens_out,
                           SUM(estimated_cost) as total_cost,
                           AVG(total_latency_ms) as avg_latency_ms
                    FROM routing_log
                    GROUP BY chosen_model_id
                    ORDER BY total_cost DESC
                    """
                ).fetchall()

                # By endpoint
                by_endpoint_rows = conn.execute(
                    """
                    SELECT chosen_endpoint_id, provider_id,
                           COUNT(*) as request_count,
                           SUM(tokens_in) as tokens_in,
                           SUM(tokens_out) as tokens_out,
                           SUM(estimated_cost) as total_cost,
                           AVG(total_latency_ms) as avg_latency_ms
                    FROM routing_log
                    GROUP BY chosen_endpoint_id, provider_id
                    ORDER BY total_cost DESC
                    """
                ).fetchall()

                return {
                    "totals": dict(total_row) if total_row else {},
                    "by_model": [dict(r) for r in by_model_rows],
                    "by_endpoint": [dict(r) for r in by_endpoint_rows],
                }
