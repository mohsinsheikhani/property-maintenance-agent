"""Trace annotation server for the maintenance-triage evals.

A reviewer opens the page, reads each trace the way Hamel's loop wants it read
(email rendered like an email, the agent's pipeline decisions laid out, the
ground truth one toggle away), and labels pass/fail with free-text notes. The
labels land in a JSON file that exports back to the same schema as
`evals/error_analysis/round_1/trace_labels.csv`, so a review session feeds the
existing taxonomy instead of starting a parallel one.

Deliberately stdlib-only and free of any `agent.*` import: pulling in a node
would drag the Settings/MCP import chain (see CLAUDE.md "Common gotchas"), and
this tool only ever reads run dumps off disk. Run dumps are the contract here,
not the live graph.

    uv run python -m evals.review.server                 # merge evals/runs/*, serve on :8765
    uv run python -m evals.review.server --runs path.jsonl
    uv run python -m evals.review.server --port 9000

Labels persist to evals/review/labels.json on every keystroke-free action. On
first run, if that file is missing, prior labels are seeded from round_1's
trace_labels.csv so the session continues the work rather than blanking it.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
INDEX = HERE / "index.html"
DEFAULT_RUNS = Path("evals/runs")
DEFAULT_LABELS = HERE / "labels.json"
SEED_CSV = Path("evals/error_analysis/round_1/trace_labels.csv")

# The structured fields the extract node writes onto state. Kept here (not
# imported from the node) so the server stays decoupled; order is display order.
EXTRACT_FIELDS = [
    "unit_number",
    "location_in_unit",
    "duration_mentioned",
    "description",
    "callback_phone",
    "related_unit",
    "diy_attempted",
    "tenant_framing",
    "tenant_sentiment",
    "lease_question_present",
]
CLASSIFY_FIELDS = [
    "category",
    "urgency",
    "risk_flags",
    "not_a_maintenance_request",
    "insufficient_info",
    "pm_queue",
]


def _load_records(runs: Path) -> list[dict]:
    """Read run dumps and return one view-model per unique trace id (latest wins).

    `runs` is either a single .jsonl or a directory of run dirs (each holding a
    run.jsonl). Dumps are sorted by path so a later run dir overrides an earlier
    one for the same id, which is how a partial re-run supersedes a stale row.
    """
    if runs.is_file():
        files = [runs]
    else:
        files = sorted(runs.glob("*/run.jsonl"))
    by_id: dict[str, dict] = {}
    for path in files:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            by_id[rec["id"]] = _view_model(rec)
    return sorted(by_id.values(), key=lambda r: r["id"])


def _view_model(rec: dict) -> dict:
    """Flatten a raw run record into what the page renders.

    final_state carries the email, the per-node decisions, and the message
    timeline all at one level; we just regroup them so the front end doesn't
    have to know the node wiring.
    """
    fs = rec.get("final_state") or {}
    extract = {k: fs.get(k) for k in EXTRACT_FIELDS}
    classify = {k: fs.get(k) for k in CLASSIFY_FIELDS}
    return {
        "id": rec["id"],
        "error": rec.get("error"),
        "metadata": rec.get("metadata") or {},
        "expected": rec.get("expected") or {},
        "email": {
            "from": fs.get("from_address", ""),
            "subject": fs.get("subject", ""),
            "body": fs.get("body", ""),
        },
        "pipeline": {
            "pre_filter": {
                "decision": fs.get("pre_filter_decision"),
                "reason": fs.get("pre_filter_reason"),
            },
            "extract": extract,
            "classify": classify,
            "work_order_id": fs.get("work_order_id"),
        },
        "messages": fs.get("messages") or [],
    }


def _seed_labels() -> dict[str, dict]:
    """Bootstrap labels from round_1's CSV so a fresh session isn't blank."""
    if not SEED_CSV.exists():
        return {}
    out: dict[str, dict] = {}
    with SEED_CSV.open() as fh:
        for row in csv.DictReader(fh):
            tid = row.get("trace_id")
            if not tid:
                continue
            verdict = (row.get("pass_or_fail") or "").strip().lower()
            # A few seed rows have an unquoted comma in user_query, which shifts
            # every later column. The verdict is the canary: if it isn't a clean
            # pass/fail the row mis-parsed, so skip it rather than import garbage
            # span/notes. It then shows as unlabeled and gets re-reviewed.
            if verdict not in ("pass", "fail"):
                continue
            out[tid] = {
                "verdict": verdict,
                "first_failed_span": (row.get("first_failed_span") or "").strip().strip("—").strip(),
                "notes": row.get("notes") or "",
                "urgency_correct": (row.get("urgency_correct") or "").strip().upper(),
                "sentiment_correct": (row.get("sentiment_correct") or "").strip().upper(),
                "clarify_correct": (row.get("clarify_correct") or "").strip().upper(),
                "updated_at": "seeded",
            }
    return out


class Store:
    """Thread-safe JSON label file. Writes on every mutation (autosave)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        if path.exists():
            self.labels = json.loads(path.read_text())
        else:
            self.labels = _seed_labels()
            self._flush()

    def _flush(self) -> None:
        self.path.write_text(json.dumps(self.labels, indent=2, sort_keys=True) + "\n")

    def update(self, trace_id: str, fields: dict) -> dict:
        with self._lock:
            row = self.labels.get(trace_id, {})
            row.update(fields)
            row["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.labels[trace_id] = row
            self._flush()
            return row


def _csv_export(records: list[dict], labels: dict[str, dict]) -> str:
    """Render labels in the round_1 trace_labels.csv schema for merge-back."""
    cols = [
        "trace_id", "user_query", "final_answer", "pass_or_fail",
        "first_failed_span", "notes", "urgency_correct",
        "sentiment_correct", "clarify_correct",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    by_id = {r["id"]: r for r in records}
    for tid in sorted(labels):
        lab = labels[tid]
        rec = by_id.get(tid, {})
        clf = rec.get("pipeline", {}).get("classify", {})
        answer = f"{clf.get('category') or '?'}/{clf.get('urgency') or '?'}"
        w.writerow({
            "trace_id": tid,
            "user_query": rec.get("email", {}).get("subject", ""),
            "final_answer": answer,
            "pass_or_fail": lab.get("verdict", ""),
            "first_failed_span": lab.get("first_failed_span", "") or "—",
            "notes": lab.get("notes", ""),
            "urgency_correct": lab.get("urgency_correct", ""),
            "sentiment_correct": lab.get("sentiment_correct", ""),
            "clarify_correct": lab.get("clarify_correct", ""),
        })
    return buf.getvalue()


def make_handler(records: list[dict], store: Store):
    payload = json.dumps(records).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet; this is an interactive local tool
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/traces":
                self._send(200, payload, "application/json")
            elif self.path == "/api/labels":
                body = json.dumps(store.labels).encode()
                self._send(200, body, "application/json")
            elif self.path == "/api/export.csv":
                body = _csv_export(records, store.labels).encode()
                self._send(200, body, "text/csv; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path != "/api/labels":
                self._send(404, b"not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
            tid = data.pop("trace_id", None)
            if not tid:
                self._send(400, b'{"error":"trace_id required"}', "application/json")
                return
            row = store.update(tid, data)
            self._send(200, json.dumps(row).encode(), "application/json")

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=Path, default=DEFAULT_RUNS,
                    help="run.jsonl file or directory of run dirs (default: evals/runs)")
    ap.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    records = _load_records(args.runs)
    if not records:
        raise SystemExit(f"no run records under {args.runs}")
    store = Store(args.labels)
    handler = make_handler(records, store)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"{len(records)} traces loaded from {args.runs}")
    print(f"labels -> {args.labels}")
    print(f"http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
