"""Standalone RAGAS evaluation runner for Vektor RAG pipelines.

Usage:
    pip install 'vektor[eval]'
    python tests/eval/run_ragas_eval.py --dataset tests/eval/rag_eval_dataset.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any


async def _run_eval(dataset_path: Path, output_path: Path | None) -> dict[str, Any]:
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
    except ImportError as exc:
        raise RuntimeError(
            "RAGAS evaluation requires optional dependencies: pip install 'vektor[eval]'"
        ) from exc

    rows = json.loads(dataset_path.read_text(encoding="utf-8"))
    records: dict[str, list[Any]] = {
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": [],
    }
    for row in rows:
        records["question"].append(row["question"])
        records["answer"].append(row.get("answer") or row["ground_truth"])
        records["contexts"].append(row.get("contexts") or [row["ground_truth"]])
        records["ground_truth"].append(row["ground_truth"])

    dataset = Dataset.from_dict(records)
    result = evaluate(
        dataset=dataset,
        metrics=[faithfulness, context_precision, context_recall, answer_relevancy],
    )
    summary: dict[str, Any] = dict(result)
    if output_path is not None:
        output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation against Vektor RAG dataset.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("tests/eval/rag_eval_dataset.json"),
        help="Path to JSON evaluation dataset.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path for JSON metrics report.",
    )
    args = parser.parse_args()
    summary = asyncio.run(_run_eval(args.dataset, args.output))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
