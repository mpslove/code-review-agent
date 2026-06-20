"""
多轮投票引擎 — 同一PR跑N次，取一致性高的结果

策略：
- 每个reviewer独立跑N轮
- 同一file+line_start+category的issue在 >= min_consensus 轮中出现才保留
- 最终输出标注每条的共识轮数
"""
import logging
import time
import copy
from collections import defaultdict
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field

from .reviewer.base import BaseReviewer
from .reviewer.output_schema import AgentReviewResult, Category, SingleIssue
from .config import config

logger = logging.getLogger(__name__)


@dataclass
class VotedIssue:
    """带投票信息的issue"""
    issue: SingleIssue
    vote_count: int           # 出现了几轮
    total_rounds: int         # 总共跑了几轮
    round_severities: List[str] = field(default_factory=list)  # 各轮的严重度

    @property
    def consensus_ratio(self) -> float:
        return self.vote_count / self.total_rounds

    @property
    def dominant_severity(self) -> str:
        """取出现最多的严重度"""
        if not self.round_severities:
            return "medium"
        from collections import Counter
        return Counter(self.round_severities).most_common(1)[0][0]


def _issue_key_fuzzy(iss: dict, line_tolerance: int = 5) -> tuple:
    """生成模糊匹配键：file + (line_start//tolerance) + category"""
    return (
        str(iss.get("file", "")),
        int(iss.get("line_start", 0)) // max(1, line_tolerance),
        str(iss.get("category", "")),
    )


def _merge_fuzzy(issues: List[SingleIssue], line_tolerance: int = 5) -> List[SingleIssue]:
    """
    同file+同category+行号相邻 → 合并为一个（取行号最小的）  
    """
    if not issues:
        return issues
    groups: Dict[tuple, List[SingleIssue]] = defaultdict(list)
    for iss in issues:
        key = _issue_key_fuzzy(iss.model_dump(), line_tolerance)
        groups[key].append(iss)
    merged = []
    for group in groups.values():
        # 取行号最小的，但保留最完整的描述
        best = min(group, key=lambda x: x.line_start)
        # 合并description（取最长的）
        longest_desc = max(group, key=lambda x: len(x.description))
        best.description = longest_desc.description
        merged.append(best)
    return sorted(merged, key=lambda x: (x.file, x.line_start))


class VotingOrchestrator:
    """
    多轮投票编排器。
    
    用法:
        vo = VotingOrchestrator(reviewers, rounds=3, min_consensus=2)
        results = vo.review(diff_text)
        
        # 两阶段深度模式
        vo = VotingOrchestrator(reviewers, rounds=3, deep=True)
        results = vo.review(diff_text)
    """

    def __init__(
        self,
        reviewers: List[BaseReviewer],
        rounds: int = 3,
        min_consensus: int = 2,
        mode: str = "balanced",
        deep: bool = False,
    ):
        """
        Args:
            reviewers: 审查Agent列表（security/perf/architecture/style）
            rounds: 每个Agent跑几轮
            min_consensus: 基础共识轮数（mode=strict时全局生效）
            mode: strict=全局min_consensus | balanced=严重度加权 | recall=全保留
            deep: True=启用两阶段模式（标注→聚焦深挖）
        """
        assert mode in ("strict", "balanced", "recall"), f"Unknown mode: {mode}"
        self.reviewers = reviewers
        self.rounds = max(1, rounds)
        self.min_consensus = max(1, min(min_consensus, rounds))
        self.mode = mode
        self.deep = deep

    def review(self, diff_text: str, rag_context: str = "") -> Dict[Category, List[VotedIssue]]:
        """
        执行多轮审查
        
        Returns:
            {category: [VotedIssue, ...]}  只包含达到共识的issues
        """
        # ========== 两阶段：预扫描标注 ==========
        focus_by_category = {}
        if self.deep:
            logger.info("=== Stage 1: Pre-scan annotation ===")
            from .annotator import Annotator
            from .tools.diff_parser import extract_context
            
            annotator = Annotator()
            flagged = annotator.scan(diff_text)
            logger.info(f"  Annotator flagged {len(flagged)} suspicious lines")
            
            if flagged:
                # 添加上下文字段
                flagged = annotator.enrich_context(flagged, diff_text)
                # 按category分组
                focus_by_category = annotator.group_by_category(flagged)
                for cat, items in focus_by_category.items():
                    logger.info(f"  {cat}: {len(items)} focus areas")
            else:
                logger.info("  No suspicious lines flagged — falling back to full diff review")

        # ========== 多轮投票 ==========
        # {category: {issue_key: [issues_from_each_round]}}
        all_round_issues: Dict[Category, Dict[tuple, List[SingleIssue]]] = defaultdict(
            lambda: defaultdict(list)
        )

        total_time = 0.0
        from concurrent.futures import ThreadPoolExecutor, as_completed

        for rnd in range(1, self.rounds + 1):
            logger.info(f"=== Voting round {rnd}/{self.rounds} ===")

            # 并行执行同一轮的所有reviewer
            round_start = time.time()
            with ThreadPoolExecutor(max_workers=len(self.reviewers)) as executor:
                futures = {}
                for reviewer in self.reviewers:
                    cat_name = reviewer.category.value
                    if self.deep and cat_name in focus_by_category and focus_by_category[cat_name]:
                        focus_list = [{
                            "file": f.file, "line_start": f.line_start,
                            "reason": f.reason, "context": f.context or f.diff_snippet,
                        } for f in focus_by_category[cat_name][:8]]
                        fut = executor.submit(reviewer.review_focused, diff_text, focus_list)
                    else:
                        fut = executor.submit(reviewer.review, diff_text, rag_context)
                    futures[fut] = reviewer

                for fut in as_completed(futures):
                    reviewer = futures[fut]
                    cat = reviewer.category
                    result = fut.result()
                    elapsed = time.time() - round_start
                    logger.info(f"  [{rnd}] {cat.value}: {len(result.issues)} issues (~{elapsed:.0f}s)")

                    for iss in result.issues:
                        key = _issue_key_fuzzy(iss.model_dump())
                        all_round_issues[cat][key].append(iss)

            round_elapsed = time.time() - round_start
            total_time += round_elapsed
            logger.info(f"  Round {rnd} done in {round_elapsed:.0f}s")

        # 统计投票结果
        voted_results: Dict[Category, List[VotedIssue]] = {}

        for cat, issue_map in all_round_issues.items():
            cat_results = []
            for key, issue_list in issue_map.items():
                vote_count = len(issue_list)
                # 严重度加权共识
                severities = [i.severity.value for i in issue_list]

                # 决定该issue所需的最低共识轮数
                from collections import Counter
                best_sev_str = Counter(severities).most_common(1)[0][0]

                if self.mode == "recall":
                    required = 1
                elif self.mode == "balanced":
                    if best_sev_str in ("critical", "high", "medium"):
                        required = 1  # 中危及以上出现就报
                    else:
                        required = max(2, self.rounds // 2 + 1)  # 低危需过半
                else:  # strict
                    required = self.min_consensus

                if vote_count >= required:
                    # 取第一个issue作为代表（保留最完整的信息）
                    representative = copy.deepcopy(issue_list[0])
                    # 用出现最多的severity
                    severities = [i.severity.value for i in issue_list]
                    from collections import Counter
                    best_sev_str = Counter(severities).most_common(1)[0][0]
                    from .reviewer.output_schema import Severity
                    representative.severity = Severity(best_sev_str)

                    cat_results.append(VotedIssue(
                        issue=representative,
                        vote_count=vote_count,
                        total_rounds=self.rounds,
                        round_severities=severities,
                    ))

            voted_results[cat] = cat_results

        # 统计
        total_raw = sum(
            sum(len(il) for il in im.values()) for im in all_round_issues.values()
        )
        total_voted = sum(len(v) for v in voted_results.values())
        logger.info(
            f"Voting done: {total_raw} raw finds → {total_voted} consensus "
            f"(min_consensus={self.min_consensus}/{self.rounds}) in {total_time:.0f}s"
        )

        return voted_results

    def to_flat_list(self, results: Dict[Category, List[VotedIssue]]) -> List[VotedIssue]:
        """展平为单一列表（按严重度排序）"""
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        flat = []
        for issues in results.values():
            flat.extend(issues)
        flat.sort(key=lambda x: sev_order.get(x.issue.severity.value, 5))
        return flat

    def to_markdown_report(
        self,
        results: Dict[Category, List[VotedIssue]],
        diff_stats: str = "",
        unified: bool = False,
        coverage: dict = None,
    ) -> str:
        """生成Markdown报告"""
        lines = [
            "# 🤖 AI Code Review Report (Multi-Round Voting)",
            "",
            f"**Rounds**: {self.rounds} | **Min Consensus**: {self.min_consensus}/{self.rounds}",
        ]
        if diff_stats:
            lines.append(f"**Diff**: {diff_stats}")

        total = sum(len(v) for v in results.values())
        lines.append(f"**Total Consensus Issues**: {total}")
        lines.append("")
        lines.append("---")

        sev_emoji = {
            "critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪",
        }

        # Unified模式：按issue自身的category重新分组
        if unified:
            by_cat: dict = {}
            for issues in results.values():
                for vi in issues:
                    cat = vi.issue.category.value if hasattr(vi.issue.category, 'value') else str(vi.issue.category)
                    by_cat.setdefault(cat, []).append(vi)
            results = {Category(k): v for k, v in by_cat.items()}

        for cat, issues in results.items():
            if not issues:
                lines.append(f"\n### {cat.value.title()} Review\n\n✅ No issues found (all {self.rounds} rounds)")
                continue

            lines.append(f"\n### {cat.value.title()} Review ({len(issues)} consensus)\n")
            for vi in issues:
                iss = vi.issue
                sev_val = iss.severity.value if hasattr(iss.severity, 'value') else str(iss.severity)
                emoji = sev_emoji.get(sev_val, "⚪")
                consensus_str = f"{vi.vote_count}/{vi.total_rounds} rounds"
                lines.append(
                    f"{emoji} **[{sev_val.upper()}]** `{iss.file}:{iss.line_start}` "
                    f"— {iss.title} `[{consensus_str}]`"
                )
                lines.append(f"> {iss.description[:200]}")
                if iss.suggestion and len(iss.suggestion) > 10:
                    lines.append(f"<details><summary>💡 Suggestion</summary>\n\n```\n{iss.suggestion[:500]}\n```\n</details>")
                if iss.rule_ref:
                    lines.append(f"📎 *Ref: {iss.rule_ref}*")
                lines.append("")

        lines.append("---")
        lines.append(f"*Generated by Multi-Round Voting Agent — {self.rounds} rounds per reviewer*")
        
        # 测试覆盖分析
        if coverage:
            lines.append("")
            lines.append("## 📊 Test Coverage Analysis")
            if coverage["missing_tests"]:
                lines.append(f"\n⚠️ **{len(coverage['missing_tests'])} changed functions have no corresponding test:**\n")
                for fpath, fname in coverage["missing_tests"][:10]:
                    lines.append(f"- `{fpath}` → `{fname}()`")
            else:
                lines.append("\n✅ All changed functions have corresponding tests.")
            if coverage["covered"]:
                lines.append(f"\n✅ **{len(coverage['covered'])} functions with test coverage**")
        return "\n".join(lines)
