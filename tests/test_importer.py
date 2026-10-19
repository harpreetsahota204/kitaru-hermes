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
"""Tests for kitaru-hermes importer."""

import json
from kitaru.api_models.v1.session import SessionStatus
from kitaru.api_models.v1.session_node import NodeType
from kitaru.task.importer import ImportedSession
from kitaru_hermes.importer import parse


def _mock_hermes_session() -> dict:
    return {
        "id": "20261019_test_session_123",
        "source": "cli",
        "title": "Debug EspoCRM Port Conflict",
        "model": "google/gemini-3.8-flash",
        "billing_provider": "nous",
        "started_at": 1792426770.0,
        "ended_at": 1792426800.0,
        "status": "completed",
        "input_tokens": 1200,
        "output_tokens": 350,
        "cache_read_tokens": 400,
        "reasoning_tokens": 150,
        "estimated_cost_usd": 0.0042,
        "messages": [
            {
                "id": 1,
                "role": "user",
                "content": "Check which process is listening on port 8080",
                "timestamp": 1792426771.0,
            },
            {
                "id": 2,
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "terminal",
                            "arguments": "{\"command\": \"netstat -tulnp | grep 8080\"}",
                        },
                    }
                ],
                "timestamp": 1792426773.0,
            },
            {
                "id": 3,
                "role": "tool",
                "tool_name": "terminal",
                "tool_call_id": "call_1",
                "content": "tcp 0 0 0.0.0.0:8080 0.0.0.0:* LISTEN 1234/docker-proxy",
                "timestamp": 1792426774.0,
            },
            {
                "id": 4,
                "role": "assistant",
                "content": "Port 8080 is currently occupied by docker-proxy for EspoCRM.",
                "timestamp": 1792426776.0,
            },
        ],
    }


def test_parse_hermes_session_jsonl() -> None:
    session_data = _mock_hermes_session()
    payload = (json.dumps(session_data) + "\n").encode("utf-8")

    items = list(parse(payload, {}))
    assert len(items) == 1
    session = items[0]
    assert isinstance(session, ImportedSession)
    assert session.external_id == "20261019_test_session_123"
    assert session.status == SessionStatus.COMPLETED
    assert session.framework == "hermes"
    assert session.name == "Debug EspoCRM Port Conflict"
    assert session.inputs == {"prompt": "Check which process is listening on port 8080"}
    assert session.outputs == {
        "response": "Port 8080 is currently occupied by docker-proxy for EspoCRM."
    }

    assert len(session.nodes) == 4
    # User prompt
    assert session.nodes[0].node_type == NodeType.SPAN
    assert session.nodes[0].inputs == {"prompt": "Check which process is listening on port 8080"}
    # Assistant tool call
    assert session.nodes[1].node_type == NodeType.LLM_CALL
    assert session.nodes[1].model == "google/gemini-3.8-flash"
    assert session.nodes[1].outputs["tool_calls"][0]["function"]["name"] == "terminal"
    # Tool execution
    assert session.nodes[2].node_type == NodeType.TOOL_CALL
    assert session.nodes[2].tool_name == "terminal"
    # Final response
    assert session.nodes[3].node_type == NodeType.LLM_CALL
    assert session.nodes[3].tokens is not None
    assert session.nodes[3].tokens.input_tokens == 1200
    assert session.nodes[3].tokens.output_tokens == 350


def test_parse_hermes_session_array() -> None:
    session_data = _mock_hermes_session()
    payload = json.dumps([session_data]).encode("utf-8")

    items = list(parse(payload, {}))
    assert len(items) == 1
    assert isinstance(items[0], ImportedSession)
