"""Rescore a saved evaluation run with the current scorer, without new model calls.

Reads results.jsonl and each attempt's saved report.json (CLI runners) or
response.json (held-out runner), scores every attempt again with the runner's
current classify(), and writes the result to a new directory. The original
run folder is only read, never changed.

Output:
    rescored.jsonl   one line per attempt: case, round, old and new outcome
    summary.json     old and new totals and every attempt whose outcome changed

Usage (PowerShell, from the VeriSight repository root, venv active):
    python evaluation\\rescore.py evaluation\\heldout\\run_heldout_eval.py `
        F:\\verisight-validation-artifacts\\heldout\\run-1 `
        --out F:\\verisight-validation-artifacts\\rescore\\heldout-run-1
"""

import argparse
import inspect
import json
import runpy
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any


def _status(body: dict[str, Any]) -> int:
    """Recover the HTTP status of a saved held-out response body."""
    if "upload_error" in body:
        return 0
    if "status" in body:
        return 200
    return 503 if body.get("code") == "provider_unavailable" else 422


def rescore(runner: Path, run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    module = runpy.run_path(str(runner), run_name="rescore")
    cases = {case.case_id: case for case in module["CASES"]}
    classify = module["classify"]
    web = list(inspect.signature(classify).parameters)[0] == "status"
    lines: list[dict[str, Any]] = []
    for text in (run_dir / "results.jsonl").read_text("utf-8").splitlines():
        if not text.strip():
            continue
        old = json.loads(text)
        case = cases[old["case_id"]]
        attempt = run_dir / "attempts" / f"round-{old['round']:02d}-{case.case_id}"
        if web:
            body = json.loads((attempt / "response.json").read_text("utf-8"))
            new = classify(_status(body), body, case)
        else:
            path = attempt / "report.json"
            report = json.loads(path.read_text("utf-8")) if path.exists() else None
            new = classify(report, case, Decimal(str(old["expected"])))
        lines.append(
            {
                "round": old["round"],
                "case_id": case.case_id,
                "old_outcome": old["outcome"],
                "new_outcome": new["outcome"],
                "numeric_match": new.get("numeric_match"),
                "actual": new.get("actual"),
                "expected": old["expected"],
            }
        )
    summary = {
        "runner": runner.as_posix(),
        "run": str(run_dir),
        "attempts": len(lines),
        "old_totals": dict(Counter(line["old_outcome"] for line in lines)),
        "new_totals": dict(Counter(line["new_outcome"] for line in lines)),
        "changed": [
            line for line in lines if line["old_outcome"] != line["new_outcome"]
        ],
    }
    return lines, summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("runner", type=Path, help="The runner that produced the run.")
    parser.add_argument("run_dir", type=Path, help="A saved run folder (read only).")
    parser.add_argument("--out", type=Path, required=True, help="New directory.")
    args = parser.parse_args()
    lines, summary = rescore(args.runner, args.run_dir)
    args.out.mkdir(parents=True, exist_ok=False)
    with (args.out / "rescored.jsonl").open("x", encoding="utf-8", newline="\n") as log:
        for line in lines:
            log.write(json.dumps(line) + "\n")
    with (args.out / "summary.json").open("x", encoding="utf-8", newline="\n") as out:
        json.dump(summary, out, indent=2)
        out.write("\n")
    print(json.dumps({k: summary[k] for k in ("attempts", "old_totals", "new_totals")}))
    print(f"changed outcomes: {len(summary['changed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
