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
"""Tests for kitaru-hermes sync functionality."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from kitaru_hermes.cli import export_hermes_sessions
from kitaru_hermes.sync import load_watermark, save_watermark, sync_sessions


def _create_test_db(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            started_at REAL,
            ended_at REAL,
            tool_call_count INTEGER,
            model TEXT,
            billing_provider TEXT,
            estimated_cost_usd REAL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp REAL
        );
        """
    )
    cur.execute(
        """
        INSERT INTO sessions (id, source, title, started_at, ended_at, tool_call_count, model, billing_provider, estimated_cost_usd)
        VALUES ('cron_1', 'cron', 'Daily Scout', 1000.0, 1010.0, 5, 'test-model', 'nous', 0.01);
        """
    )
    cur.execute(
        """
        INSERT INTO messages (id, session_id, role, content, timestamp)
        VALUES (1, 'cron_1', 'user', 'Run scout', 1001.0);
        """
    )
    cur.execute(
        """
        INSERT INTO messages (id, session_id, role, content, timestamp)
        VALUES (2, 'cron_1', 'assistant', 'Scout complete', 1005.0);
        """
    )
    con.commit()
    con.close()


def test_watermark_roundtrip(tmp_path: Path) -> None:
    state_file = tmp_path / "kitaru_sync.json"
    assert load_watermark(state_file) == 0.0
    save_watermark(state_file, 1793041234.5)
    assert load_watermark(state_file) == 1793041234.5


def test_export_hermes_sessions_filtering(tmp_path: Path) -> None:
    db_file = tmp_path / "state.db"
    _create_test_db(db_file)

    # Filter by source
    cron_sessions = export_hermes_sessions(str(db_file), source="cron")
    assert len(cron_sessions) == 1
    assert cron_sessions[0]["id"] == "cron_1"

    cli_sessions = export_hermes_sessions(str(db_file), source="cli")
    assert len(cli_sessions) == 0

    # Filter by since
    after_sessions = export_hermes_sessions(str(db_file), since_timestamp=1050.0)
    assert len(after_sessions) == 0

    before_sessions = export_hermes_sessions(str(db_file), since_timestamp=900.0)
    assert len(before_sessions) == 1
