# kitaru-hermes

A Kitaru plugin, session importer, and continuous sync runner for **Hermes Agent** (Nous Research).

Turn production Hermes Agent execution histories into replayable, evaluatable, and regression-tested sessions inside [Kitaru](https://github.com/zenml-io/kitaru).

---

## Why

Hermes Agent operates autonomously in developer environments: modifying files, running commands, managing databases, and calling external APIs. Evaluating improvements to Hermes (system prompt updates, skill additions, model migrations like switching to Gemini Flash or Claude 3.7) has traditionally required:
- Manual prompt testing.
- Live reruns that risk executing duplicate commands, overwriting files, or re-sending external messages.

`kitaru-hermes` bridges Hermes Agent's SQLite state store (`~/.hermes/state.db`) with Kitaru's replay engine:
1. **Trace to Session Normalization:** Ingests Hermes turns (user messages, tool invocations, tool outputs, token usage, and costs) as structured Kitaru DAG nodes.
2. **Replay Sandboxing:** Re-executes agent reasoning against historical sessions while mocking/answering tool calls from trace evidence—preventing unwanted real-world side effects.
3. **Cohort Evaluation:** Freeze real-world CLI and cron work sessions into golden benchmarks to detect prompt regressions and quantify model quality deltas.
4. **Continuous Background Sync:** Sync completed cron or CLI sessions automatically into your Kitaru dashboard using watermark tracking.

---

## Features

- **CLI Session Extractor:** Export sessions directly from local `state.db` filtered by tool count, source (`cron`, `cli`, `discord`), since-timestamp, or limits.
- **Continuous Sync Runner (`kitaru-hermes-sync`):** Incrementally synchronizes new sessions directly into Kitaru with zero worker queue dependencies and tag linkage.
- **Kitaru Importer Protocol:** Native `parse(payload, params)` compliance for Kitaru worker and server pipelines.
- **Node-Level Fidelity:** Preserves role transitions, tool names, tool call IDs, reasoning tokens, token counts, and dollar costs.
- **Zero-Dependency Core:** Only depends on `kitaru>=0.27.0`.

---

## Installation

```bash
pip install kitaru-hermes
# or using uv:
uv add kitaru-hermes
```

For local development:
```bash
git clone https://github.com/harpreetsahota204/kitaru-hermes.git
cd kitaru-hermes
uv venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Quickstart

### 1. Continuous Automated Sync (Recommended)

To continuously push completed Hermes cron sessions to your local or remote Kitaru server, use the built-in sync command:

```bash
kitaru-hermes-sync \
  --db ~/.hermes/state.db \
  --state-file ~/.hermes/state/kitaru_sync.json \
  --source cron \
  --min-tools 1 \
  --tag hermes-cron \
  --agent hermes-agent
```

This command tracks the last synced session in a state watermark file (`~/.hermes/state/kitaru_sync.json`). When run periodically (e.g. via Hermes script cron, systemd timer, or crontab), it only ingests new completed runs.

### 2. Manual Export to JSONL

Export sessions from your Hermes database with at least 1 tool call:

```bash
kitaru-hermes --db ~/.hermes/state.db --min-tools 1 --source cron -n 25 -o hermes-sessions.jsonl
```

### 3. Register with Kitaru & Batch Import

Register Hermes as an agent in Kitaru:
```bash
kitaru agent register hermes-agent \
  --command "hermes run" \
  --description "Autonomous developer agent for technical workflows" \
  --display-version baseline-v1 \
  --working-dir .
```

Register the importer plugin script with Kitaru:
```bash
kitaru importer register hermes \
  --script src/kitaru_hermes/importer.py \
  --entrypoint parse \
  --description "Hermes Agent session importer plugin" \
  --display-version 0.1.0
```

Import exported traces via the Kitaru CLI:
```bash
kitaru session import hermes-sessions.jsonl \
  --importer hermes@latest \
  --agent hermes-agent@1 \
  --tag hermes-baseline \
  --wait
```

### 4. Inspect Sessions in Kitaru UI
Open your Kitaru dashboard (default: `http://localhost:8000`) or query the CLI:
```bash
kitaru session list --agent hermes-agent --tag hermes-cron
```

---

## Development & Testing

```bash
pytest tests/
```

---

## License

Apache 2.0
