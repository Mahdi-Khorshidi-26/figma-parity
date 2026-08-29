"""Measure whether the loop actually finds everything.

The claim this project makes is "never misses details". That claim is only
worth anything if it is measured, so this runs the cases in cases.json and
records what the ledger says about coverage — the number that would have
caught the original failure.

    PYTHONPATH=src python3 evals/run_evals.py --project /path/to/scratch/app
    PYTHONPATH=src python3 evals/run_evals.py --project ... --case moes-faq-canvas
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from figma_parity.config import settings  # noqa: E402
from figma_parity.runner import run_parity  # noqa: E402

CASES = Path(__file__).parent / "cases.json"
RESULTS = Path(__file__).parent / "results"


async def run_case(case: dict, project_path: Path) -> dict:
    print(f"\n=== {case['id']} ===\n{case['figma_url']}")
    result = await run_parity(case["figma_url"], project_path)
    led = result.ledger

    record = {
        "case_id": case["id"],
        "figma_url": case["figma_url"],
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "verified": result.verified,
        "error": result.error,
        "cost_usd": result.cost_usd,
        "turns": result.turns,
        "nodes_extracted": led.nodes_extracted if led else 0,
        "nodes_total": led.nodes_total if led else 0,
        "coverage_complete": led.coverage_complete if led else False,
        "rows_total": led.total if led else 0,
        "rows_todo": led.todo if led else 0,
        "rows_unjustified": len(led.unjustified) if led else 0,
    }

    expected = case.get("expected_min_nodes")
    if expected is not None:
        record["meets_expected_nodes"] = record["nodes_total"] >= expected
        record["expected_min_nodes"] = expected

    print(result.report())
    return record


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="scratch project to implement into")
    ap.add_argument("--case", help="run a single case id")
    args = ap.parse_args()

    project_path = settings.validate_project_path(args.project)
    cases = json.loads(CASES.read_text())["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"no case named {args.case}", file=sys.stderr)
            return 2

    records = [await run_case(c, project_path) for c in cases]

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"{stamp}.json"
    out.write_text(json.dumps(records, indent=2))

    print(f"\n--- summary ---")
    for r in records:
        cov = f"{r['nodes_extracted']}/{r['nodes_total']}"
        print(f"  {r['case_id']:<32} verified={str(r['verified']):<5} "
              f"coverage={cov:<9} open={r['rows_todo'] + r['rows_unjustified']}")
    print(f"written to {out}")
    return 0 if all(r["verified"] for r in records) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
