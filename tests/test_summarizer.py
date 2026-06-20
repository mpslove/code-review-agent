"""测试 Summarizer — S-4 到 S-8"""
import pytest
from src.summarizer import Summarizer
from src.reviewer.output_schema import (
    AgentReviewResult, SingleIssue, Severity, Category, MergedReviewResult
)


def make_issue(file="a.py", line=10, sev=Severity.HIGH, cat=Category.SECURITY,
               title="SQL injection found", desc="Found SQL injection in query",
               sugg="Use parameterized queries"):
    return SingleIssue(file=file, line_start=line, severity=sev, category=cat,
                       title=title, description=desc, suggestion=sugg)


def make_review(cat=Category.SECURITY, summary="Security review summary text",
                issues=None):
    return AgentReviewResult(agent_type=cat, summary=summary,
                             issues=issues or [])


class TestSummarizer:
    def setup_method(self):
        self.s = Summarizer()

    # S-4: format_comment 包含必需元素
    def test_format_comment_structure(self):
        r1 = make_review(issues=[make_issue()])
        result = MergedReviewResult(
            pr_title="Test PR",
            pr_url="https://github.com/test/pull/1",
            files_changed=2,
            total_issues=1,
            agent_reviews=[r1],
            merged_summary="This is a test summary for validation purposes",
        )
        comment = self.s.format_comment(result)

        assert "🤖 AI Code Review" in comment
        assert "Test PR" in comment
        assert "https://github.com/test/pull/1" in comment
        assert "SQL injection" in comment
        assert "HIGH" in comment.upper()
        assert "Code Review Agent" in comment

    # S-5: 无issue的agent不出现
    def test_no_issue_agent_omitted(self):
        r1 = make_review(issues=[make_issue()])
        r2 = make_review(Category.PERFORMANCE, summary="Performance review text")
        result = MergedReviewResult(
            pr_title="Test", files_changed=1, total_issues=1,
            agent_reviews=[r1, r2],
            merged_summary="This is a test summary for validation",
        )
        comment = self.s.format_comment(result)
        assert "Security Review" in comment
        assert "Performance Review" not in comment  # 无issue不出现

    # S-7: fallback with no issues
    def test_fallback_no_issues(self):
        fb = self.s._fallback_summary([], 0, 0)
        assert "✅" in fb
        assert "未发现" in fb

    # S-7b: fallback with critical
    def test_fallback_with_critical(self):
        r1 = make_review(issues=[make_issue(sev=Severity.CRITICAL,
                                            title="Critical SQL injection")])
        fb = self.s._fallback_summary([r1], 1, 0)
        assert "严重" in fb or "critical" in fb.lower()

    # S-8: 严重度emoji映射
    def test_severity_emojis(self):
        r1 = make_review(issues=[
            make_issue(sev=Severity.CRITICAL, title="Critical SQL injection"),
            make_issue(file="b.py", line=20, sev=Severity.HIGH,
                       title="High severity XSS"),
        ])
        result = MergedReviewResult(
            pr_title="Test", files_changed=1, total_issues=2,
            agent_reviews=[r1],
            merged_summary="This is a test summary for validation purposes",
        )
        comment = self.s.format_comment(result)
        assert "🔴" in comment
        assert "🟠" in comment

    # S-8b: medium emoji
    def test_medium_emoji(self):
        r1 = make_review(issues=[
            make_issue(sev=Severity.MEDIUM, title="Medium severity found"),
        ])
        result = MergedReviewResult(
            pr_title="Test", files_changed=1, total_issues=1,
            agent_reviews=[r1],
            merged_summary="This is a test summary for validation purposes",
        )
        comment = self.s.format_comment(result)
        assert "🟡" in comment
