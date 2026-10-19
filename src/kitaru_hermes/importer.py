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
# /// script
# requires-python = ">=3.11"
# dependencies = ["kitaru>=0.27.0"]
# ///
"""Hermes Agent session importer for Kitaru.

Parses exported Hermes session JSON/JSONL records or SQLite-derived turn DAGs
into normalized Kitaru sessions and nodes for replay and evaluation.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from kitaru.api_models.v1.imports import ImportFailure
from kitaru.api_models.v1.session import SessionStatus, TokenUsage
from kitaru.api_models.v1.session_node import NodeStatus, NodeType
from kitaru.task.importer import ImportedNode, ImportedSession, Parser


class InvalidImport(ValueError):
    """Raised when Hermes session payload cannot be parsed."""


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a timestamp (float Unix epoch or ISO-8601 string)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        try:
            val_float = float(value)
            return datetime.fromtimestamp(val_float, tz=UTC)
        except ValueError:
            pass
        try:
            cleaned = value.strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _parse_cost(value: Any) -> Decimal | None:
    """Safely parse cost to Decimal."""
    if value is None or value == "":
        return None
    try:
        dec = Decimal(str(value))
        return dec if dec.is_finite() and dec >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def parse_hermes_session(record: dict[str, Any]) -> ImportedSession:
    """Transform one Hermes session dictionary into an ImportedSession."""
    session_id = record.get("id") or record.get("session_id")
    if not session_id:
        raise InvalidImport("Hermes session record must contain an 'id' or 'session_id'")

    title = record.get("title") or f"Hermes Session {session_id}"
    started_at = _parse_datetime(record.get("started_at"))
    ended_at = _parse_datetime(record.get("ended_at"))

    # Determine status
    raw_status = str(record.get("status") or "").lower()
    end_reason = str(record.get("end_reason") or "").lower()
    if raw_status in ("failed", "error") or end_reason in ("error", "failed"):
        status = SessionStatus.FAILED
    else:
        status = SessionStatus.COMPLETED

    model = record.get("model")
    billing_provider = record.get("billing_provider") or "nous"
    metadata = {
        "source": record.get("source", "cli"),
        "user_id": record.get("user_id"),
        "session_key": record.get("session_key"),
        "cwd": record.get("cwd"),
        "git_branch": record.get("git_branch"),
        "billing_provider": billing_provider,
        "model": model,
        "archived": bool(record.get("archived", False)),
    }

    # Aggregate token usage if provided at session level
    in_tok = record.get("input_tokens") or 0
    out_tok = record.get("output_tokens") or 0
    cache_read = record.get("cache_read_tokens") or 0
    cache_write = record.get("cache_write_tokens") or 0
    reasoning_tok = record.get("reasoning_tokens") or 0

    session_tokens = TokenUsage(
        input_tokens=in_tok,
        output_tokens=out_tok,
        cached_input_tokens=cache_read,
        reasoning_tokens=reasoning_tok,
    ) if (in_tok or out_tok) else None

    # Process messages / turns
    raw_messages = record.get("messages", [])
    nodes: list[ImportedNode] = []
    first_user_prompt = None
    last_assistant_output = None

    # Track parents for chaining
    parent_ext_id: str | None = None

    for idx, msg in enumerate(raw_messages):
        msg_id = msg.get("id") or f"msg-{idx}"
        role = msg.get("role", "unknown")
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")
        tool_name = msg.get("tool_name")
        tool_call_id = msg.get("tool_call_id")
        timestamp = _parse_datetime(msg.get("timestamp"))

        # Map role to node type
        if role == "user":
            if first_user_prompt is None and content:
                first_user_prompt = content
            node_type = NodeType.SPAN
            name = "User Prompt"
            inputs = {"prompt": content}
            outputs = None
        elif role == "assistant":
            if tool_calls:
                node_type = NodeType.LLM_CALL
                name = "Assistant Tool Invocation"
                # Parse tool calls json if string or wrap list
                calls_data = tool_calls
                if isinstance(calls_data, str):
                    try:
                        calls_data = json.loads(calls_data)
                    except Exception:
                        calls_data = [{"raw": tool_calls}]
                elif not isinstance(calls_data, (list, dict)):
                    calls_data = [{"raw": str(tool_calls)}]
                inputs = {"role": "assistant"}
                outputs = {"tool_calls": calls_data, "content": content}
            else:
                node_type = NodeType.LLM_CALL
                name = "Assistant Response"
                inputs = {"role": "assistant"}
                outputs = {"content": content}
                if content:
                    last_assistant_output = content
        elif role == "tool":
            node_type = NodeType.TOOL_CALL
            name = f"Tool: {tool_name or 'unnamed'}"
            # Tool result content
            tool_content = content
            if isinstance(tool_content, str):
                try:
                    tool_content = json.loads(tool_content)
                except Exception:
                    pass
            inputs = {"tool_call_id": tool_call_id, "tool_name": tool_name}
            outputs = {"result": tool_content}
        else:
            node_type = NodeType.SPAN
            name = f"Message: {role}"
            inputs = {"content": content}
            outputs = None

        node_ext_id = f"{session_id}-{msg_id}"
        node = ImportedNode(
            external_id=node_ext_id,
            parent_external_id=parent_ext_id,
            trace_id=str(session_id),
            node_type=node_type,
            name=name,
            status=NodeStatus.COMPLETED,
            started_at=timestamp,
            ended_at=timestamp,
            inputs=inputs,
            outputs=outputs,
            model=model if node_type == NodeType.LLM_CALL else None,
            model_provider=billing_provider if node_type == NodeType.LLM_CALL else None,
            tool_name=tool_name if node_type == NodeType.TOOL_CALL else None,
            tokens=session_tokens if (idx == len(raw_messages) - 1 and session_tokens) else None,
            cost=_parse_cost(record.get("estimated_cost_usd")),
            attributes={"role": role, "tool_call_id": tool_call_id},
            metadata={"hermes_message_id": msg_id},
        )
        nodes.append(node)
        parent_ext_id = node_ext_id

    session_inputs = {"prompt": first_user_prompt} if first_user_prompt else {}
    session_outputs = {"response": last_assistant_output} if last_assistant_output else {}

    return ImportedSession(
        status=status,
        name=title,
        inputs=session_inputs,
        outputs=session_outputs,
        started_at=started_at,
        ended_at=ended_at,
        external_id=str(session_id),
        metadata=metadata,
        framework="hermes",
        nodes=nodes,
    )


def parse(
    payload: bytes, params: dict[str, Any]
) -> Iterator[ImportedSession | ImportFailure]:
    """Parse a Hermes session JSON/JSONL payload into Kitaru sessions."""
    _ = params
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidImport("Hermes payload must be UTF-8") from exc

    if not text.strip():
        raise InvalidImport("Hermes payload is empty")

    stripped = text.strip()
    if stripped.startswith("["):
        # JSON Array of sessions
        try:
            records = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise InvalidImport(f"Malformed JSON array: {exc}") from exc
        if not isinstance(records, list):
            raise InvalidImport("Root JSON element must be a list of sessions")
        for idx, item in enumerate(records, start=1):
            if not isinstance(item, dict):
                yield ImportFailure(line=idx, error="Session record must be a JSON object")
                continue
            try:
                yield parse_hermes_session(item)
            except Exception as exc:
                yield ImportFailure(line=idx, external_id=str(item.get("id")), error=str(exc))
        return

    # Process JSONL / single JSON object
    lines = stripped.splitlines()
    for line_number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            yield ImportFailure(line=line_number, error=f"Invalid JSON: {exc}")
            continue

        if not isinstance(data, dict):
            yield ImportFailure(line=line_number, error="Record must be a JSON object")
            continue

        try:
            yield parse_hermes_session(data)
        except Exception as exc:
            yield ImportFailure(
                line=line_number,
                external_id=str(data.get("id") or data.get("session_id")),
                error=str(exc),
            )


class HermesImporter:
    """Kitaru Importer interface wrapper for Hermes Agent traces."""

    def parse(
        self, payload: bytes, params: dict[str, Any]
    ) -> Iterator[ImportedSession | ImportFailure]:
        """Parse Hermes session records."""
        return parse(payload, params)


parser: Parser = parse
