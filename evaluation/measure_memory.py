"""Measure peak memory of the website under a full local workload, with no model.

Scripted replies replace Gemini, so this uses no quota. The workload is five uploads
of one file near the 20 MB limit, charts on each so that the loaded cache fills, two
questions at once with second queries, and then one upload of five such files.

Usage (PowerShell, from the repository root, venv active):
    python evaluation\\measure_memory.py --out <new file>.json
"""

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.web import create_app
from verisight.web.config import WebSettings

TARGET_BYTES = 19_500_000
MIB = 1024 * 1024
FIRST = "SELECT SUM(amount) AS total FROM data"
SECOND = (
    "SELECT SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) "
    "AS cross_check_answer FROM data"
)


def peak_bytes() -> int:
    """Highest memory this process has held since it started."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        return int(counters.PeakWorkingSetSize)
    import resource

    used = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(used if sys.platform == "darwin" else used * 1024)


def csv_bytes(seed: int) -> tuple[bytes, int]:
    rng = random.Random(seed)
    lines = ["order_id,region,product,year,day,amount,quantity,note"]
    size = len(lines[0]) + 1
    number = 0
    while size < TARGET_BYTES:
        number += 1
        line = (
            f"{number},{rng.choice(['East', 'West', 'North', 'South'])},"
            f"item {rng.randint(1, 500)},{rng.randint(2015, 2024)},"
            f"20{rng.randint(15, 24)}-{rng.randint(1, 12):02d}-"
            f"{rng.randint(1, 28):02d},"
            f"{rng.randint(1, 900000) / 100:.2f},{rng.randint(1, 50)},"
            f"note {rng.randint(1, 9999)}"
        )
        lines.append(line)
        size += len(line) + 1
    return ("\n".join(lines) + "\n").encode("utf-8"), number


class _Script:
    def __init__(self, items: list[str]) -> None:
        self.items = list(items)

    def generate(self, prompt: str) -> str:
        return self.items.pop(0)


def _decision(question: str | None) -> str:
    action = "finish" if question is None else "investigate"
    return json.dumps({"action": action, "reasoning": "r", "question": question})


def engine(settings: Settings, total: str) -> VeriSight:
    synthesis = json.dumps(
        {
            "conclusion": f"The total is {total}.",
            "claims": [
                {
                    "operation": "value",
                    "expected": total,
                    "left": {"observation_index": 0, "row_index": 0, "column": "total"},
                    "right": None,
                }
            ],
        }
    )
    return VeriSight(
        settings=settings.model_copy(update={"gemini_cross_check_model": None}),
        planner=GenerativeQueryPlanner(_Script([FIRST, SECOND])),
        investigator=GenerativeInvestigator(
            _Script([_decision("Add up the amounts"), _decision(None)])
        ),
        synthesizer=StructuredInvestigationSynthesizer(_Script([synthesis] * 2)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    samples: list[dict[str, Any]] = []

    def mark(stage: str) -> None:
        samples.append(
            {
                "stage": stage,
                "peak_mib": round(peak_bytes() / MIB, 1),
                "seconds": round(time.perf_counter() - started, 1),
            }
        )
        print(samples[-1], flush=True)

    body, rows = csv_bytes(1)
    mark("started")
    frame_total = sum(float(line.split(b",")[5]) for line in body.splitlines()[1:])
    total = format(round(frame_total, 2), ".2f")
    app = create_app(
        settings=Settings(gemini_api_key=None),
        web=WebSettings(questions_per_hour=10_000, uploads_per_hour=10_000),
        factory=lambda settings: engine(settings, total),
    )
    questions = {"question": "How much came in altogether?", "consent": True}
    with TestClient(app) as client:
        ids = []
        for number in range(5):
            upload = client.post("/api/datasets", files=[("files", ("data.csv", body))])
            upload.raise_for_status()
            ids.append(upload.json()["dataset_id"])
            client.post(
                f"/api/datasets/{ids[-1]}/dashboard", json={"relation": "data"}
            ).raise_for_status()
            mark(f"upload and charts {number + 1}")

        def ask(dataset_id: str) -> int:
            reply = client.post(
                f"/api/datasets/{dataset_id}/ask", json={**questions, "api_key": "k"}
            )
            return reply.status_code

        with ThreadPoolExecutor(2) as pool:
            statuses = list(pool.map(ask, ids[-2:]))
        mark(f"two questions at once {statuses}")
        many = client.post(
            "/api/datasets",
            files=[("files", (f"data{n}.csv", body)) for n in range(5)],
        )
        many.raise_for_status()
        mark("one upload of five files")
    peak = peak_bytes()
    report = {
        "rows_per_file": rows,
        "bytes_per_file": len(body),
        "samples": samples,
        "peak_mib": round(peak / MIB, 1),
        "target_mib": 1024,
        "passed": peak < 1024 * MIB,
    }
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ("peak_mib", "passed")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
