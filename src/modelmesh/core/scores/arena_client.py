"""LMArena leaderboard client: human-preference ratings per model and category.

Reads the official ``lmarena-ai/leaderboard-dataset`` file (CC BY 4.0). The URL
and categories come from ``scores.arena`` in routing.yaml (Rule 6). The column
names below were checked against the published file; if they change we stop
and report instead of guessing (Rule 20).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import httpx

from modelmesh.core.errors import ProviderError

ARENA_SOURCE: str = "lmarena"
ARENA_ATTRIBUTION_TEXT: str = "LMArena ratings (CC BY 4.0)"

REQUIRED_COLUMNS = ("model_name", "rating", "category", "leaderboard_publish_date")
OPTIONAL_COLUMNS = ("organization", "vote_count")
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024


def _error(message: str, category: str, retryable: bool) -> ProviderError:
    return ProviderError(message=message, category=category, provider_id=ARENA_SOURCE, retryable=retryable)


def records_from_rows(rows: Sequence[Dict[str, Any]], categories: Sequence[str]) -> List[Dict[str, Any]]:
    """Group leaderboard rows (one per model and category) into one record per model.

    Each record looks like ``{"slug": name, "name": name, "organization": ...,
    "ratings": {category: rating}, "votes": {category: count}}``; the model name
    doubles as the slug so records fit ``ScoreSnapshot``.
    """
    wanted = set(categories)
    by_name: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = row.get("model_name")
        cat = row.get("category")
        rating = row.get("rating")
        if not name or cat not in wanted or rating is None:
            continue
        rec = by_name.setdefault(name, {
            "slug": name, "name": name, "organization": row.get("organization") or "",
            "ratings": {}, "votes": {},
        })
        rec["ratings"][cat] = float(rating)
        if row.get("vote_count") is not None:
            rec["votes"][cat] = int(row["vote_count"])
    return list(by_name.values())


def parse_leaderboard(data: bytes) -> List[Dict[str, Any]]:
    """Read leaderboard rows from parquet bytes, checking the expected columns exist."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    try:
        # Single-threaded: the file is small, and pyarrow's reader thread pool kept
        # the interpreter from exiting after reading from an in-memory buffer.
        table = pq.read_table(pa.BufferReader(data), use_threads=False)
    except Exception as exc:
        raise _error(f"LMArena file is not a readable parquet file: {exc}", "server", False) from exc
    missing = [c for c in REQUIRED_COLUMNS if c not in table.column_names]
    if missing:
        raise _error(
            f"LMArena file no longer has columns {missing}; the format changed. Not adapting automatically.",
            "bad_request",
            False,
        )
    keep = list(REQUIRED_COLUMNS) + [c for c in OPTIONAL_COLUMNS if c in table.column_names]
    return table.select(keep).to_pylist()


class LMArenaClient:
    """Downloads the LMArena text leaderboard and turns it into a score snapshot."""

    def __init__(
        self,
        url: Optional[str] = None,
        categories: Optional[List[str]] = None,
        timeout: float = 30.0,
    ) -> None:
        from modelmesh.core.config.routing_config import load_routing_config

        arena_cfg = load_routing_config().scores.arena
        self.url = url or arena_cfg.url
        self.categories = categories or list(arena_cfg.categories)
        self.timeout = timeout

    def download(self, client: Optional[httpx.Client] = None) -> bytes:
        """Fetch the leaderboard file, following the CDN redirect."""
        if not self.url:
            raise _error("scores.arena.url is not set in routing.yaml", "bad_request", False)
        owns_client = client is None
        http = client or httpx.Client(timeout=self.timeout, follow_redirects=True)
        try:
            resp = http.get(self.url)
        except httpx.TimeoutException as exc:
            raise _error(f"Timeout downloading LMArena leaderboard: {exc}", "network", True) from exc
        except httpx.RequestError as exc:
            raise _error(f"Network error downloading LMArena leaderboard: {exc}", "network", True) from exc
        finally:
            if owns_client:
                http.close()
        if resp.status_code == 429:
            raise _error("LMArena download was rate limited; try again later", "rate_limit", True)
        if resp.status_code >= 500:
            raise _error(f"LMArena host error (status {resp.status_code})", "server", True)
        if resp.status_code != 200:
            raise _error(f"LMArena download failed (status {resp.status_code})", "bad_request", False)
        if len(resp.content) > MAX_DOWNLOAD_BYTES:
            raise _error("LMArena file is unexpectedly large; check scores.arena.url", "bad_request", False)
        return resp.content

    def fetch_snapshot(self, client: Optional[httpx.Client] = None) -> Any:
        """Download and parse the leaderboard into a ``ScoreSnapshot`` (source ``lmarena``)."""
        from modelmesh.core.scores.snapshots import ScoreSnapshot

        rows = parse_leaderboard(self.download(client=client))
        records = records_from_rows(rows, self.categories)
        if not records:
            raise _error(
                f"LMArena file has no ratings for categories {self.categories}", "bad_request", False
            )
        published = max((str(r.get("leaderboard_publish_date") or "") for r in rows), default="") or None
        return ScoreSnapshot.from_raw(models_list=records, index_version=published, source=ARENA_SOURCE)
