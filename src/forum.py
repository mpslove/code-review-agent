"""
Forum Engine — 4个Agent结果的去重与冲突裁决

去重规则：
- 同一file + line_start → 保留severity最高的
- 同一file + line_start + 相同severity → 合并suggestion（标注来源agent）
- 跟踪issue来源review索引，避免同agent类型重复计数

冲突裁决：
- 如果同一位置被多个Agent标记，保留最严重的那个
"""
import logging
from collections import defaultdict

from .reviewer.output_schema import AgentReviewResult, SingleIssue, Severity

logger = logging.getLogger(__name__)

SEVERITY_RANK = {
    Severity.CRITICAL: 5,
    Severity.HIGH: 4,
    Severity.MEDIUM: 3,
    Severity.LOW: 2,
    Severity.INFO: 1,
}


class ForumEngine:
    """去重 + 冲突裁决"""

    def deduplicate(
        self, reviews: list[AgentReviewResult]
    ) -> list[AgentReviewResult]:
        """
        对多个Agent的结果去重。

        每个issue用 (file, line_start) 作为key。
        同一位置 → 保留severity最高的。
        跟踪每个issue来自哪个review索引，避免同agent类型的重复计数。

        Args:
            reviews: 各Agent审查结果列表

        Returns:
            去重后的结果（新列表，不修改原数据）
        """
        if not reviews:
            return []

        # (file, line_start) → (kept_issue, review_index)
        seen: dict[tuple[str, int], tuple[SingleIssue, int]] = {}

        for review_idx, review in enumerate(reviews):
            for issue in review.issues:
                key = (issue.file, issue.line_start)

                if key in seen:
                    existing, existing_idx = seen[key]
                    if SEVERITY_RANK[issue.severity] > SEVERITY_RANK[existing.severity]:
                        seen[key] = (issue, review_idx)
                    elif SEVERITY_RANK[issue.severity] == SEVERITY_RANK[existing.severity]:
                        if issue.suggestion not in existing.suggestion:
                            existing.suggestion += (
                                f"\n\n[also from {issue.category.value}]: {issue.suggestion}"
                            )
                else:
                    seen[key] = (issue, review_idx)

        # 按review索引重建结果
        review_issues: list[list[SingleIssue]] = [[] for _ in reviews]
        for key, (issue, review_idx) in seen.items():
            review_issues[review_idx].append(issue)

        deduped: list[AgentReviewResult] = []
        for idx, review in enumerate(reviews):
            deduped.append(
                AgentReviewResult(
                    agent_type=review.agent_type,
                    issues=sorted(review_issues[idx], key=lambda i: i.line_start),
                    summary=review.summary,
                )
            )

        original_count = sum(len(r.issues) for r in reviews)
        deduped_count = sum(len(r.issues) for r in deduped)
        logger.info(f"Forum: {original_count} issues → {deduped_count} after dedup")

        return deduped

    def get_stats(self, deduped: list[AgentReviewResult]) -> dict:
        """统计去重后的结果"""
        total = sum(len(r.issues) for r in deduped)
        by_severity: dict[str, int] = defaultdict(int)
        by_category: dict[str, int] = defaultdict(int)

        for review in deduped:
            for issue in review.issues:
                by_severity[issue.severity.value] += 1
                by_category[issue.category.value] += 1

        return {
            "total_issues": total,
            "by_severity": dict(by_severity),
            "by_category": dict(by_category),
        }
