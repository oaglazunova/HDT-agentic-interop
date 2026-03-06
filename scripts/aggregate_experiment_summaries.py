from __future__ import annotations

import argparse
import glob
import json
from collections import Counter
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Root folder containing *.jsonl and *.summary.json files")
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--out-md", required=True)
    return ap.parse_args()


def read_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main() -> int:
    args = parse_args()
    root = args.root

    # Find all conditions by matching summary files
    summary_files = sorted(glob.glob(str(Path(root) / "**" / "*.summary.json"), recursive=True))

    rows = []
    for s in summary_files:
        summ = read_json(s)
        model = summ.get("model", "")
        # condition name from filename: baseline.summary.json -> baseline
        condition = Path(s).name.replace(".summary.json", "")
        model_dir = Path(s).parent

        jsonl_path = model_dir / f"{condition}.jsonl"
        jsonl_rows = read_jsonl(str(jsonl_path)) if jsonl_path.exists() else []

        # Aggregate top error types from JSONL failures
        err_counter = Counter()
        for r in jsonl_rows:
            if not r.get("ok", False):
                for t in (r.get("first_error_types") or []):
                    err_counter[t] += 1
        top_errors = ", ".join([f"{k}({v})" for k, v in err_counter.most_common(5)])

        rows.append(
            {
                "model": model,
                "condition": condition,
                "tasks_defined": summ.get("tasks_defined", ""),
                "repeats": summ.get("repeats", ""),
                "runs": summ.get("runs", ""),
                "ok": summ.get("ok", ""),
                "success_rate": summ.get("success_rate", ""),
                "avg_iterations": summ.get("avg_iterations", ""),
                "avg_elapsed_ms": summ.get("avg_elapsed_ms", ""),
                "avg_error_count": summ.get("avg_error_count", ""),
                "avg_warning_count": summ.get("avg_warning_count", ""),
                "top_error_types": top_errors,
            }
        )

    # Write CSV
    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    headers = list(rows[0].keys()) if rows else []
    with out_csv.open("w", encoding="utf-8") as f:
        f.write(",".join(headers) + "\n")
        for r in rows:
            f.write(",".join(str(r.get(h, "")).replace(",", ";") for h in headers) + "\n")

    # Write Markdown table (paper-friendly)
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    def fmt(x: Any) -> str:
        if isinstance(x, float):
            return f"{x:.3f}"
        return str(x)

    md_lines = []
    md_lines.append("| model | condition | success_rate | avg_iterations | avg_elapsed_ms | top_error_types |")
    md_lines.append("|---|---:|---:|---:|---:|---|")
    for r in rows:
        md_lines.append(
            f"| {r['model']} | {r['condition']} | {fmt(r['success_rate'])} | {fmt(r['avg_iterations'])} | {fmt(r['avg_elapsed_ms'])} | {r['top_error_types']} |"
        )
    out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Wrote {out_csv} and {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
