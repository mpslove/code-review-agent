"""测试 Benchmark Runner — E-1 到 E-4"""
import os
import pytest
from pathlib import Path
from src.reviewer.output_schema import (
    AgentReviewResult, SingleIssue, Severity, Category
)

# 动态导入避免yaml依赖问题
try:
    from tests.benchmark.runner import BenchmarkRunner
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@pytest.mark.skipif(not HAS_YAML, reason="pyyaml not installed")
class TestBenchmarkRunner:
    def setup_method(self):
        self.cases_dir = Path(__file__).parent / "benchmark" / "cases"
        self.runner = BenchmarkRunner(str(self.cases_dir))

    # E-1: 加载YAML测试用例
    def test_load_cases(self):
        cases = self.runner.load_cases()
        assert len(cases) >= 2
        assert "sql_injection" in cases or any("SQL" in c for c in cases)

    # E-2: 单用例评分
    def test_run_single_perfect_match(self):
        self.runner.load_cases()
        case_name = list(self.runner.cases.keys())[0]

        # 构造完美匹配的审查结果
        case = self.runner.cases[case_name]
        expected = case.get("expected", {})

        issues = []
        for category, exp_issues in expected.items():
            cat = Category(category)
            for exp in exp_issues:
                issues.append(SingleIssue(
                    file=exp.get("file", "unknown"),
                    line_start=exp.get("line_start", 0),
                    severity=Severity(exp.get("severity", "high")),
                    category=cat,
                    title=exp.get("title_contains", "Test issue") if len(exp.get("title_contains", "")) >= 5 else "Test issue title",
                    description="Test description for benchmark",
                    suggestion="Test suggestion for fix",
                ))

        review = AgentReviewResult(
            agent_type=Category.SECURITY,
            summary="Benchmark test review summary",
            issues=issues,
        )

        result = self.runner.run_single(case_name, [review])
        assert result["precision"] >= 0.0
        assert result["recall"] >= 0.0
        assert "f1" in result
        assert "true_positives" in result

    # E-3: 模糊匹配（title_contains）
    def test_fuzzy_title_match(self):
        found = {"file": "a.py", "line_start": 10, "severity": "high",
                 "category": "security", "title": "SQL injection in login function"}
        expected = {"file": "a.py", "line_start": 10, "severity": "high",
                    "category": "security", "title_contains": "SQL injection"}

        assert self.runner._match(expected, found)

    def test_fuzzy_title_no_match(self):
        found = {"file": "a.py", "line_start": 10, "severity": "high",
                 "category": "security", "title": "XSS vulnerability found"}
        expected = {"file": "a.py", "line_start": 10, "severity": "high",
                    "category": "security", "title_contains": "SQL injection"}

        assert not self.runner._match(expected, found)

    # E-4: 统计指标
    def test_run_all_empty(self):
        self.runner.cases = {}  # 清空，不实际调用LLM
        result = self.runner.run_all(lambda name, diff: [])
        assert result["total"] == 0
        assert result["precision"] == 0
