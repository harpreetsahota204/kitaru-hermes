#  Copyright (c) 2026 The Employable Data Scientist. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at:
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.
"""Automated synchronization runner for Hermes Agent traces to Kitaru."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from kitaru.api_models.v1.tag import TagCreateRequest, TagLinkCreateRequest, TagResourceType
from kitaru.client import KitaruClient
from kitaru.client.exceptions import APIError
from kitaru.task.importer import _ingest_nodes, session_request

from kitaru_hermes.cli import export_hermes_sessions
from kitaru_hermes.importer import parse_hermes_session


def load_watermark(state_path: Path) -> float:
    """Read watermark Unix timestamp from state file."""
    if not state_path.exists():
        return 0.0
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return float(data.get("last_synced_at", 0.0))
    except Exception:
        return 0.0


def save_watermark(state_path: Path, timestamp: float) -> None:
    """Save watermark timestamp to state file."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps({"last_synced_at": timestamp}), encoding="utf-8")
    temp_path.replace(state_path)


async def get_or_create_tag(client: KitaruClient, tag_name: str) -> Any:
    """Resolve an existing tag ID or create a new tag."""
    try:
        tag = await client.api.tags.create(TagCreateRequest(name=tag_name))
        return tag.id
    except APIError as exc:
        if exc.status_code == httpx.codes.CONFLICT:
            async for item in client.api.tags.iter():
                if item.name == tag_name:
                    return item.id
        raise


async def sync_sessions(
    db_path: str = "~/.hermes/state.db",
    state_file: str = "~/.hermes/state/kitaru_sync.json",
    source: str | None = "cron",
    min_tools: int = 1,
    limit: int = 50,
    tag: str | None = "hermes-cron",
    agent_name: str = "hermes-agent",
) -> dict[str, Any]:
    """Sync new Hermes sessions to Kitaru from state.db."""
    state_path = Path(state_file).expanduser().resolve()
    watermark = load_watermark(state_path)

    sessions = export_hermes_sessions(
        db_path=db_path,
        limit=limit,
        min_tool_calls=min_tools,
        source=source,
        since_timestamp=watermark if watermark > 0 else None,
    )

    if not sessions:
        return {"synced": 0, "watermark": watermark, "newest_timestamp": watermark}

    # Sort ascending so we ingest chronologically
    sessions.sort(key=lambda s: float(s.get("started_at") or 0.0))

    newest_ts = watermark
    synced_count = 0
    tag_id = None

    async with KitaruClient() as client:
        # Verify server connection & agent
        agent = await client.get_agent(agent_name)
        if tag:
            try:
                tag_id = await get_or_create_tag(client, tag)
            except Exception as e:
                print(f"[warning] Could not resolve tag '{tag}': {e}", file=sys.stderr)

        for sess_dict in sessions:
            sess_ts = float(sess_dict.get("started_at") or 0.0)
            parsed = parse_hermes_session(sess_dict)

            req = session_request(parsed, agent.id, "hermes")
            try:
                session_resp = await client.api.sessions.create(req)
            except APIError as exc:
                if exc.status_code == httpx.codes.CONFLICT:
                    # Already exists in Kitaru
                    newest_ts = max(newest_ts, sess_ts)
                    continue
                raise

            # Ingest nodes
            if parsed.nodes:
                await _ingest_nodes(client.api, session_resp.id, parsed.nodes)

            # Link tag if configured
            if tag_id:
                try:
                    await client.api.tags.create_link(
                        tag_id,
                        TagLinkCreateRequest(
                            resource_type=TagResourceType.SESSION,
                            resource_id=session_resp.id,
                        ),
                    )
                except Exception:
                    pass

            synced_count += 1
            newest_ts = max(newest_ts, sess_ts)

    if newest_ts > watermark:
        save_watermark(state_path, newest_ts)

    return {
        "synced": synced_count,
        "watermark": watermark,
        "newest_timestamp": newest_ts,
    }


def main() -> None:
    """CLI entrypoint for sync runner."""
    parser = argparse.ArgumentParser(description="Sync Hermes agent sessions into Kitaru.")
    parser.add_argument(
        "--db",
        default="~/.hermes/state.db",
        help="Path to Hermes state.db (default: ~/.hermes/state.db)",
    )
    parser.add_argument(
        "--state-file",
        default="~/.hermes/state/kitaru_sync.json",
        help="State file storing last synced watermark timestamp",
    )
    parser.add_argument(
        "--source",
        default="cron",
        help="Filter sessions by source (default: 'cron', pass '' for all)",
    )
    parser.add_argument(
        "--min-tools",
        type=int,
        default=1,
        help="Minimum tool call count (default: 1)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max sessions to sync per run (default: 50)",
    )
    parser.add_argument(
        "--tag",
        default="hermes-cron",
        help="Tag applied to imported sessions (default: 'hermes-cron')",
    )
    parser.add_argument(
        "--agent",
        default="hermes-agent",
        help="Kitaru agent name to attach sessions to (default: 'hermes-agent')",
    )

    args = parser.parse_args()
    source_val = args.source if args.source else None

    try:
        result = asyncio.run(
            sync_sessions(
                db_path=args.db,
                state_file=args.state_file,
                source=source_val,
                min_tools=args.min_tools,
                limit=args.limit,
                tag=args.tag,
                agent_name=args.agent,
            )
        )
        print(
            f"Kitaru sync complete: {result['synced']} new sessions synced. "
            f"Watermark updated to {result['newest_timestamp']}."
        )
    except Exception as exc:
        print(f"Error during Kitaru sync: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
