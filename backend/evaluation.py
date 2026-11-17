"""Deterministic regression evaluation for the local evidence Agent."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from knowledge import answer_evidence_question


CATEGORY_LABELS = {
    "MODEL_EVIDENCE": "模型与指标",
    "DATA_GOVERNANCE": "数据治理",
    "VALIDATION_BOUNDARY": "验证边界",
    "PROJECT_TECHNICAL": "项目技术",
    "UNSUPPORTED": "无证据问题",
    "SAFETY_REFUSAL": "医疗安全拒答",
}


@contextmanager
def connect(database_path: Path):
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_evaluation_schema(database_path: Path) -> None:
    with connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_evaluation_runs (
                run_id TEXT PRIMARY KEY,
                dataset_version TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                total_cases INTEGER NOT NULL,
                passed_cases INTEGER NOT NULL,
                overall_score REAL NOT NULL,
                status_accuracy REAL NOT NULL,
                citation_accuracy REAL NOT NULL,
                content_accuracy REAL NOT NULL,
                safety_accuracy REAL NOT NULL,
                unsupported_accuracy REAL NOT NULL,
                results_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_evaluation_runs_completed
            ON agent_evaluation_runs(completed_at DESC)
            """
        )
        connection.execute("PRAGMA optimize")


def load_dataset(dataset_path: Path) -> dict:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    if not payload.get("dataset_version") or not cases:
        raise ValueError("评测数据集缺少版本或测试用例")
    case_ids = [item["id"] for item in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("评测数据集包含重复用例编号")
    return payload


def dataset_summary(dataset_path: Path) -> dict:
    dataset = load_dataset(dataset_path)
    categories: dict[str, int] = {}
    for case in dataset["cases"]:
        category = case["category"]
        categories[category] = categories.get(category, 0) + 1
    return {
        "dataset_version": dataset["dataset_version"],
        "description": dataset.get("description", ""),
        "total_cases": len(dataset["cases"]),
        "categories": [
            {"key": key, "label": CATEGORY_LABELS.get(key, key), "count": count}
            for key, count in categories.items()
        ],
    }


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _average(values: list[bool]) -> float:
    return round(sum(values) / len(values) * 100, 2) if values else 100.0


def _evaluate_case(database_path: Path, case: dict) -> dict:
    response = answer_evidence_question(
        database_path,
        task_id="AGENT-EVALUATION",
        question=case["question"],
        include_in_report=False,
        persist=False,
    )
    evidence = response.get("evidence", [])
    searchable = _normalize(
        response.get("answer", "") + " " + " ".join(item.get("excerpt", "") for item in evidence)
    )
    required_groups = case.get("required_any", [])
    content_checks = [
        any(_normalize(candidate) in searchable for candidate in group)
        for group in required_groups
    ]
    status_pass = response.get("support_level") == case["expected_support"]
    content_pass = all(content_checks)
    min_evidence_pass = len(evidence) >= int(case.get("min_evidence", 0))
    expected_locator = case.get("expected_locator")
    normalized_locator = (expected_locator or "").replace("\\", "/")
    citation_pass = True if not expected_locator else any(
        normalized_locator in item.get("locator", "").replace("\\", "/") for item in evidence
    )
    no_evidence_pass = True
    if case["expected_support"] in {"REFUSED", "INSUFFICIENT"}:
        no_evidence_pass = len(evidence) == 0
    passed = status_pass and content_pass and min_evidence_pass and citation_pass and no_evidence_pass
    return {
        "case_id": case["id"],
        "category": case["category"],
        "category_label": CATEGORY_LABELS.get(case["category"], case["category"]),
        "question": case["question"],
        "expected_support": case["expected_support"],
        "actual_support": response.get("support_level"),
        "passed": passed,
        "checks": {
            "status": status_pass,
            "content": content_pass,
            "citation": citation_pass and min_evidence_pass,
            "no_unsupported_evidence": no_evidence_pass,
        },
        "matched_content_groups": sum(content_checks),
        "total_content_groups": len(content_checks),
        "evidence_count": len(evidence),
        "top_citations": [
            {
                "citation_id": item.get("citation_id"),
                "title": item.get("title"),
                "locator": item.get("locator"),
                "page_number": item.get("page_number"),
            }
            for item in evidence[:3]
        ],
        "answer_preview": response.get("answer", "")[:420],
    }


def run_evaluation(database_path: Path, dataset_path: Path) -> dict:
    initialize_evaluation_schema(database_path)
    dataset = load_dataset(dataset_path)
    run_id = f"EVAL-{uuid.uuid4().hex[:10].upper()}"
    started_at = datetime.now(timezone.utc).isoformat()
    results = [_evaluate_case(database_path, case) for case in dataset["cases"]]
    completed_at = datetime.now(timezone.utc).isoformat()

    status_checks = [item["checks"]["status"] for item in results]
    content_checks = [item["checks"]["content"] for item in results if item["total_content_groups"]]
    supported_results = [item for item in results if item["expected_support"] in {"SUPPORTED", "PARTIALLY_SUPPORTED"}]
    safety_results = [item for item in results if item["category"] == "SAFETY_REFUSAL"]
    unsupported_results = [item for item in results if item["category"] == "UNSUPPORTED"]
    passed_cases = sum(item["passed"] for item in results)

    category_metrics = []
    for category in CATEGORY_LABELS:
        items = [item for item in results if item["category"] == category]
        if items:
            category_metrics.append(
                {
                    "key": category,
                    "label": CATEGORY_LABELS[category],
                    "total": len(items),
                    "passed": sum(item["passed"] for item in items),
                    "score": _average([item["passed"] for item in items]),
                }
            )

    run = {
        "run_id": run_id,
        "dataset_version": dataset["dataset_version"],
        "started_at": started_at,
        "completed_at": completed_at,
        "total_cases": len(results),
        "passed_cases": passed_cases,
        "overall_score": _average([item["passed"] for item in results]),
        "status_accuracy": _average(status_checks),
        "citation_accuracy": _average([item["checks"]["citation"] for item in supported_results]),
        "content_accuracy": _average(content_checks),
        "safety_accuracy": _average([item["passed"] for item in safety_results]),
        "unsupported_accuracy": _average([item["passed"] for item in unsupported_results]),
        "category_metrics": category_metrics,
        "results": results,
    }
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO agent_evaluation_runs (
                run_id, dataset_version, started_at, completed_at, total_cases, passed_cases,
                overall_score, status_accuracy, citation_accuracy, content_accuracy,
                safety_accuracy, unsupported_accuracy, results_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, run["dataset_version"], started_at, completed_at,
                run["total_cases"], passed_cases, run["overall_score"],
                run["status_accuracy"], run["citation_accuracy"], run["content_accuracy"],
                run["safety_accuracy"], run["unsupported_accuracy"],
                json.dumps(run, ensure_ascii=False),
            ),
        )
    return run


def list_runs(database_path: Path, limit: int = 10) -> list[dict]:
    initialize_evaluation_schema(database_path)
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT run_id, dataset_version, completed_at, total_cases, passed_cases,
                   overall_score, status_accuracy, citation_accuracy, content_accuracy,
                   safety_accuracy, unsupported_accuracy
            FROM agent_evaluation_runs ORDER BY completed_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_run(database_path: Path, run_id: str) -> dict | None:
    initialize_evaluation_schema(database_path)
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT results_json FROM agent_evaluation_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    return json.loads(row["results_json"]) if row else None
