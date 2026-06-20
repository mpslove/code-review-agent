"""测试 Forum Engine — F-1 到 F-7 验收标准"""
import pytest
from src.forum import ForumEngine
from src.reviewer.output_schema import (
    AgentReviewResult, SingleIssue, Severity, Category
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


class TestForumEngine:
    def setup_method(self):
        self.forum = ForumEngine()

    # F-1: 空列表
    def test_empty_reviews(self):
        assert self.forum.deduplicate([]) == []

    # F-2: 同一位置不同severity → 保留高的
    def test_same_pos_diff_severity(self):
        r1 = make_review(Category.SECURITY, issues=[
            make_issue(sev=Severity.HIGH)])
        r2 = make_review(Category.PERFORMANCE, summary="Performance review text",
                         issues=[make_issue(sev=Severity.MEDIUM, cat=Category.PERFORMANCE,
                                            title="N+1 query detected")])
        result = self.forum.deduplicate([r1, r2])
        total = sum(len(r.issues) for r in result)
        assert total == 1
        # 保留HIGH
        all_issues = [i for r in result for i in r.issues]
        assert all_issues[0].severity == Severity.HIGH

    # F-3: 同一位置相同severity → 合并suggestion
    def test_same_pos_same_severity_merge(self):
        r1 = make_review(Category.SECURITY, issues=[
            make_issue(sev=Severity.HIGH, sugg="Fix method A")])
        r2 = make_review(Category.PERFORMANCE, summary="Performance review text",
                         issues=[make_issue(sev=Severity.HIGH, cat=Category.PERFORMANCE,
                                            title="N+1 query detected", sugg="Fix method B")])
        result = self.forum.deduplicate([r1, r2])
        total = sum(len(r.issues) for r in result)
        assert total == 1
        all_issues = [i for r in result for i in r.issues]
        assert "[also from performance]" in all_issues[0].suggestion

    # F-4: 不同位置 → 全部保留
    def test_different_positions(self):
        r1 = make_review(issues=[make_issue(file="a.py", line=10)])
        r2 = make_review(Category.PERFORMANCE, summary="Performance review text",
                         issues=[make_issue(file="b.py", line=20, cat=Category.PERFORMANCE,
                                            title="N+1 query detected")])
        result = self.forum.deduplicate([r1, r2])
        total = sum(len(r.issues) for r in result)
        assert total == 2

    # F-4b: 同agent类型不同位置 → 不重复计数
    def test_same_agent_diff_positions(self):
        r1 = make_review(issues=[make_issue(file="a.py", line=10)])
        r2 = make_review(issues=[make_issue(file="b.py", line=20,
                                            title="XSS vulnerability")])
        result = self.forum.deduplicate([r1, r2])
        total = sum(len(r.issues) for r in result)
        assert total == 2

    # F-5: 同一agent重复提交同一位置 → 去重为1条
    def test_same_agent_duplicate(self):
        issue = make_issue()
        r1 = make_review(issues=[issue, issue])  # 同一review内重复
        result = self.forum.deduplicate([r1])
        total = sum(len(r.issues) for r in result)
        assert total == 1

    # F-6: get_stats
    def test_get_stats(self):
        r1 = make_review(issues=[make_issue(sev=Severity.HIGH)])
        result = self.forum.deduplicate([r1])
        stats = self.forum.get_stats(result)
        assert stats["total_issues"] == 1
        assert stats["by_severity"]["high"] == 1
        assert stats["by_category"]["security"] == 1

    def test_get_stats_multi(self):
        r1 = make_review(issues=[
            make_issue(sev=Severity.HIGH),
            make_issue(file="b.py", line=20, sev=Severity.LOW,
                       title="Minor style issue")])
        result = self.forum.deduplicate([r1])
        stats = self.forum.get_stats(result)
        assert stats["total_issues"] == 2
        assert stats["by_severity"]["high"] == 1
        assert stats["by_severity"]["low"] == 1

    # F-7: 不修改原数据
    def test_no_mutation(self):
        r1 = make_review(issues=[make_issue()])
        original = r1.model_copy(deep=True)
        self.forum.deduplicate([r1])
        assert r1 == original
