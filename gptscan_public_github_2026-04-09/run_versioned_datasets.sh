#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
DATA_ROOT="$REPO_ROOT/Dataset&Result"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing_python_env: $PYTHON_BIN" >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "missing_openai_api_key: export OPENAI_API_KEY before running this script" >&2
  exit 1
fi

run_batch() {
  local dataset_dir="$1"
  local output_dir="$2"
  echo "scanning dataset=$dataset_dir"
  mkdir -p "$output_dir"
  "$PYTHON_BIN" "$REPO_ROOT/batch_scan_demo.py" \
    --dataset-dir "$dataset_dir" \
    --output-dir "$output_dir"
}

run_batch "$DATA_ROOT/GPTScan-Top200-0.7x" "$DATA_ROOT/GPTScan-Top200-0.7x_results"
run_batch "$DATA_ROOT/GPTScan-Top200-0.8x" "$DATA_ROOT/GPTScan-Top200-0.8x_results"
run_batch "$DATA_ROOT/DeFiVulnLabs-0.7x" "$DATA_ROOT/DeFiVulnLabs-0.7x_results"
run_batch "$DATA_ROOT/DeFiVulnLabs-0.8x" "$DATA_ROOT/DeFiVulnLabs-0.8x_results"

echo "all_batches_finished"
