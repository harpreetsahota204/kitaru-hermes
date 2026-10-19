# kitaru-hermes

A Kitaru plugin and session importer for **Hermes Agent** (Nous Research).

Turn production Hermes Agent execution histories into replayable, evaluatable, and regression-tested sessions inside [Kitaru](https://github.com/zenml-io/kitaru).

---

## Why

Hermes Agent operates autonomously in developer environments: modifying files, running commands, managing databases, and calling external APIs. Evaluating improvements to Hermes (system prompt updates, skill additions, model migrations like switching to Gemini Flash or Claude 3.7) has traditionally required:
- Manual prompt testing.
- Live reruns that risk executing duplicate commands, overwriting files, or re-sending external messages.

`kitaru-hermes` bridges Hermes Agent's SQLite state store (`~/.hermes/state.db`) with Kitaru's replay engine:
1. **Trace to Session Normalization:** Ingests Hermes turns (user messages, tool invocations, tool outputs, token usage, and costs) as structured Kitaru DAG nodes.
2. **Replay Sandboxing:** Re-executes agent reasoning against historical sessions while mocking/answering tool calls from trace evidence—preventing unwanted real-world side effects.
3. **Cohort Evaluation:** Freeze real-world CLI work sessions into golden benchmarks to detect prompt regressions and quantify model quality deltas.

---

## Features

- **CLI Session Extractor:** Export sessions directly from local `state.db` filtered by tool count, tags, or session IDs.
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

---

## Quickstart

### 1. Export Hermes Sessions to JSONL
Export sessions from your Hermes database with at least 1 tool call:

```bash
kitaru-hermes --db ~/.hermes/state.db --min-tools 1 -n 25 -o hermes-sessions.jsonl
```

### 2. Register with Kitaru & Import

Register Hermes as an agent in Kitaru:
```bash
kitaru agent register hermes-agent \
  --command "hermes run" \
  --description "Autonomous developer agent for technical workflows" \
  --display-version baseline-v1 \
  --working-dir .
```

Import sessions into your Kitaru server using `kitaru-hermes`:
```bash
# Register the importer plugin script
kitaru importer register hermes \
  --script src/kitaru_hermes/importer.py \
  --entrypoint parse \
  --description "Hermes Agent session importer plugin" \
  --display-version 0.1.0

# Import your traces
kitaru session import hermes-sessions.jsonl \
  --importer hermes@latest \
  --agent hermes-agent@1 \
  --tag hermes-baseline \
  --wait
```

### 3. Inspect Sessions in Kitaru UI
Open your Kitaru dashboard (default: `http://localhost:8000`) or query the CLI:
```bash
kitaru session list --agent hermes-agent --tag hermes-baseline
```

---

## Development & Testing

```bash
git clone https://github.com/harpreetsahota204/kitaru-hermes.git
cd kitaru-hermes
uv venv .venv
source .venv/bin/activate
uv pip install -e .
pytest tests/
```

---

## License

Apache 2.0
