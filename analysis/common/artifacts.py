"""Artifact readers: thin wrappers over the already-correct `compute_results.py`
loaders (do not reimplement the join/discovery logic they already get right),
plus a few new pure readers for formats `compute_results.py` never needed to
read: policy YAML and the summary CSV.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml
from interbolt_agentdojo.compute_results import (
    _case_to_run_id,
    _discover_results,
    _events_by_run_id,
    _load_call_records,
    _load_jsonl,
)

# Re-exported under public names -- these are the exact join/discovery
# functions that already produced the published, verified CSV.
load_jsonl = _load_jsonl
load_call_records = _load_call_records
events_by_run_id = _events_by_run_id
discover_results = _discover_results
case_to_run_id = _case_to_run_id


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def load_policy_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """(header, rows) preserving raw string cells, for verbatim display."""
    with Path(path).open(newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]
