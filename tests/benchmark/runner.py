"""
评测基准运行器 — 衡量审查质量
"""
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from src.reviewer.output_schema import AgentReviewResult, Severity

logger = logging.getLogger(__name__)

SEVERITY_WEIGHT = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "info": 1,
}


class BenchmarkRunner:
    """加载测试用例，运行审查，计算指标"""

    def __init__(self, test_cases_dir: str):
        self.cases_dir = Path(test_cases_dir)
        self.cases: dict[str, dict] = {}

    def load_cases(self) -> list[str]:
        """加载所有 .yaml 测试用例，返回用例名列表"""
        self.cases = {}
        for yaml_file in sorted(self.cases_dir.glob("*.yaml")):
            with open(yaml_file, encoding="utf-8") as f:
                case = yaml.safe_load(f)
            name = case.get("name", yaml_file.stem)
            case["_file"] = str(yaml_file)
            self.cases[name] = case
        return list(self.cases.keys())

    def run_single(self, case_name: str, reviews: list[AgentReviewResult]) -> dict:
        """
        对单个测试用例计算匹配分数。

        Args:
            case_name: 用例名
            reviews: Agent审查结果列表

        Returns:
            {"name": ..., "precision": float, "recall": float, "f1": float, "details": [...]}
        """
        case = self.cases[case_name]
        expected = case.get("expected", {})

        # 收集所有实际发现的issue
        found_issues: list[dict] = []
        for review in reviews:
            for issue in review.issues:
                found_issues.append({
                    "file": issue.file,
                    "line_start": issue.line_start,
                    "severity": issue.severity.value,
                    "category": issue.category.value,
                    "title": issue.title,
                })

        # 收集所有期望的issue
        expected_issues: list[dict] = []
        for category, issues in expected.items():
            for exp in issues:
                expected_issues.append({
                    "file": exp.get("file", ""),
                    "line_start": exp.get("line_start", 0),
                    "severity": exp.get("severity", ""),
                    "category": category,
                    "title_contains": exp.get("title_contains", ""),
                    "severity_contains": exp.get("severity_contains", ""),
                })

        # 匹配：found vs expected
        matched_expected = set()
        matched_found = set()

        for ei, exp in enumerate(expected_issues):
            for fi, found in enumerate(found_issues):
                if fi in matched_found:
                    continue
                if self._match(exp, found):
                    matched_expected.add(ei)
                    matched_found.add(fi)
                    break

        tp = len(matched_expected)
        fp = len(found_issues) - len(matched_found)
        fn = len(expected_issues) - len(matched_expected)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        return {
            "name": case_name,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "expected_count": len(expected_issues),
            "found_count": len(found_issues),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
        }

    def run_all(self, review_fn) -> dict:
        """
        运行所有测试用例。

        Args:
            review_fn: callable(case_name, diff_text) → list[AgentReviewResult]

        Returns:
            {"total": N, "precision": ..., "recall": ..., "f1": ..., "per_case": [...]}
        """
        if not self.cases:
            self.load_cases()

        results = []
        for case_name, case in self.cases.items():
            diff_file = self.cases_dir.parent / case.get("diff_file", "")
            if not diff_file.exists():
                logger.warning(f"Diff file not found: {diff_file}")
                continue

            diff_text = diff_file.read_text(encoding="utf-8")
            reviews = review_fn(case_name, diff_text)
            result = self.run_single(case_name, reviews)
            results.append(result)

        if not results:
            return {"total": 0, "precision": 0, "recall": 0, "f1": 0, "per_case": []}

        avg_precision = sum(r["precision"] for r in results) / len(results)
        avg_recall = sum(r["recall"] for r in results) / len(results)
        avg_f1 = sum(r["f1"] for r in results) / len(results)

        return {
            "total": len(results),
            "precision": round(avg_precision, 3),
            "recall": round(avg_recall, 3),
            "f1": round(avg_f1, 3),
            "per_case": results,
        }

    def _match(self, expected: dict, found: dict) -> bool:
        """检查一个found issue是否匹配expected。行号容差±2。"""
        if expected["file"] and expected["file"] != found["file"]:
            return False
        if expected["line_start"]:
            diff = abs(expected["line_start"] - found["line_start"])
            if diff > 2:  # 行号容差±2
                return False
        if expected["title_contains"]:
            if expected["title_contains"].lower() not in found["title"].lower():
                return False
        if expected.get("severity_contains"):
            if expected["severity_contains"] not in found["severity"]:
                return False
        return True
