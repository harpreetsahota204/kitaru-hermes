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
"""Hermes state.db extractor and export CLI."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


def export_hermes_sessions(
    db_path: str,
    output_path: str | None = None,
    limit: int | None = None,
    min_tool_calls: int = 0,
) -> list[dict[str, Any]]:
    """Export sessions and messages from Hermes state.db into Kitaru-ready JSON records."""
    db_file = Path(db_path).expanduser().resolve()
    if not db_file.exists():
        raise FileNotFoundError(f"Hermes database not found at {db_file}")

    con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Discover column names dynamically to support older and newer Hermes schemas
    session_cols = {col[1] for col in cur.execute("PRAGMA table_info(sessions);").fetchall()}

    has_tool_col = "tool_call_count" in session_cols
    has_started_col = "started_at" in session_cols

    query = "SELECT * FROM sessions WHERE 1=1"
    params: list[Any] = []
    if min_tool_calls > 0 and has_tool_col:
        query += " AND tool_call_count >= ?"
        params.append(min_tool_calls)
    if has_started_col:
        query += " ORDER BY started_at DESC"
    else:
        query += " ORDER BY id DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    sessions_rows = cur.execute(query, params).fetchall()
    results = []

    for s_row in sessions_rows:
        sess_dict = dict(s_row)
        sess_id = sess_dict["id"]

        # Fetch messages
        msg_rows = cur.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (sess_id,)
        ).fetchall()
        messages = [dict(m) for m in msg_rows]
        sess_dict["messages"] = messages
        results.append(sess_dict)

    con.close()

    if output_path:
        out_file = Path(output_path).expanduser().resolve()
        with open(out_file, "w", encoding="utf-8") as f:
            for item in results:
                f.write(json.dumps(item) + "\n")

    return results


def main() -> None:
    """CLI entrypoint for exporting Hermes sessions."""
    parser = argparse.ArgumentParser(description="Export Hermes agent sessions for Kitaru replay.")
    parser.add_argument(
        "--db",
        default="~/.hermes/state.db",
        help="Path to Hermes state.db (default: ~/.hermes/state.db)",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Target output JSONL file path",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Maximum number of sessions to export",
    )
    parser.add_argument(
        "--min-tools",
        type=int,
        default=0,
        help="Only export sessions with at least N tool calls",
    )

    args = parser.parse_args()
    try:
        exported = export_hermes_sessions(
            db_path=args.db,
            output_path=args.output,
            limit=args.limit,
            min_tool_calls=args.min_tools,
        )
        print(f"Exported {len(exported)} Hermes sessions to {args.output}")
    except Exception as e:
        print(f"Error exporting Hermes sessions: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
