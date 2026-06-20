"""
Summarizer — 汇总4个Agent结果，生成最终PR评论
使用LLM生成自然的摘要文本
"""
import json
import logging

import requests

from .config import config
from .reviewer.output_schema import (
    AgentReviewResult,
    MergedReviewResult,
    SingleIssue,
    Severity,
)
from .reviewer.prompts import ORCHESTRATOR_PROMPT

logger = logging.getLogger(__name__)

SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟠",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "🔵",
    Severity.INFO: "⚪",
}


class Summarizer:
    """汇总去重后的审查结果，生成最终PR评论"""

    def summarize(
        self,
        reviews: list[AgentReviewResult],
        diff_stats: dict,
        pr_title: str = "Code Review",
        pr_url: str = "",
    ) -> MergedReviewResult:
        """
        汇总审查结果。

        Args:
            reviews: 去重后的各Agent结果
            diff_stats: get_diff_stats()的输出
            pr_title: PR标题
            pr_url: PR链接

        Returns:
            MergedReviewResult: 最终汇总结果
        """
        total_issues = sum(len(r.issues) for r in reviews)
        critical_count = sum(
            1 for r in reviews for i in r.issues if i.severity == Severity.CRITICAL
        )
        high_count = sum(
            1 for r in reviews for i in r.issues if i.severity == Severity.HIGH
        )

        # 用LLM生成综合摘要
        try:
            merged_summary = self._llm_merge(reviews, diff_stats)
        except Exception as e:
            logger.warning(f"LLM merge failed: {e}, using fallback summary")
            merged_summary = self._fallback_summary(reviews, critical_count, high_count)

        return MergedReviewResult(
            pr_title=pr_title,
            pr_url=pr_url if pr_url else None,
            files_changed=diff_stats.get("files_changed", 0),
            total_issues=total_issues,
            agent_reviews=reviews,
            merged_summary=merged_summary[:2000],
        )

    def _llm_merge(
        self, reviews: list[AgentReviewResult], diff_stats: dict
    ) -> str:
        """调用LLM生成综合摘要"""
        # 构建简洁的输入
        reviews_summary = []
        for r in reviews:
            issue_list = []
            for i in r.issues:
                issue_list.append(
                    f"  [{i.severity.value}] {i.file}:{i.line_start} — {i.title}"
                )
            reviews_summary.append(
                f"## {r.agent_type.value}\n"
                + (f"{r.summary}\n" if r.summary else "")
                + ("\n".join(issue_list) if issue_list else "No issues found")
            )

        user_prompt = (
            f"变更统计: {diff_stats.get('files_changed', 0)} files, "
            f"+{diff_stats.get('additions', 0)} -{diff_stats.get('deletions', 0)}\n\n"
            + "\n\n".join(reviews_summary)
            + "\n\n请生成综合总结（200-500字），包括：关键发现、整体评价、建议优先修复项。"
        )

        messages = [
            {"role": "system", "content": ORCHESTRATOR_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        headers = {
            "Authorization": f"Bearer {config.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.llm_model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 600,
        }

        last_error = None
        for attempt in range(config.max_retries):
            try:
                resp = requests.post(
                    f"{config.llm_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=config.max_review_timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                msg = data["choices"][0]["message"]
                text = msg.get("content", "")
                if not text or not text.strip():
                    text = msg.get("reasoning_content", "")
                # 过滤推理模型的CoT前缀
                if text.strip().startswith(("我们被问到", "We are asked", "我们被要求")):
                    lines = text.strip().split(chr(10))
                    for line in reversed(lines):
                        line = line.strip()
                        if line and not line.startswith(("我们", "注意", "我选择", "所以", "Note", "We", "I choose", "Therefore")):
                            text = line
                            break
                    else:
                        text = text[:2000]
                if not text or not text.strip():
                    raise ValueError("LLM returned empty content")
                return text.strip()
            except requests.Timeout:
                last_error = f"Timeout (attempt {attempt + 1})"
                import time
                time.sleep(2 ** attempt)
            except Exception as e:
                last_error = str(e)
                if attempt < config.max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"LLM merge failed after {config.max_retries} retries: {last_error}")

    def _fallback_summary(
        self, reviews: list[AgentReviewResult], critical: int, high: int
    ) -> str:
        """LLM不可用时的降级摘要"""
        parts = []
        if critical:
            parts.append(f"发现 {critical} 个严重问题，必须立即修复。")
        if high:
            parts.append(f"发现 {high} 个高危问题，建议优先修复。")

        agent_summaries = []
        for r in reviews:
            if r.issues:
                agent_summaries.append(
                    f"**{r.agent_type.value}**: {len(r.issues)}个问题 — {r.summary[:100]}"
                )

        if not parts and not agent_summaries:
            return "✅ 未发现明显问题，代码质量良好。"

        return "## 审查总结\n\n" + " ".join(parts) + "\n\n" + "\n".join(agent_summaries)

    def format_comment(
        self, result: MergedReviewResult, for_github: bool = True
    ) -> str:
        """
        将MergedReviewResult格式化为可读的PR评论。

        Args:
            result: 汇总结果
            for_github: True=GitHub Markdown, False=纯文本

        Returns:
            格式化后的评论字符串
        """
        lines = []
        lines.append(f"## 🤖 AI Code Review Report")
        lines.append("")
        lines.append(f"**PR**: {result.pr_title}")
        if result.pr_url:
            lines.append(f"**Link**: {result.pr_url}")
        lines.append(
            f"**Files Changed**: {result.files_changed} | "
            f"**Issues Found**: {result.total_issues}"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        # Summary
        lines.append(result.merged_summary)
        lines.append("")
        lines.append("---")
        lines.append("")

        # Agent breakdown
        for review in result.agent_reviews:
            if not review.issues:
                continue
            lines.append(f"### {review.agent_type.value.title()} Review")
            lines.append("")

            for issue in review.issues:
                emoji = SEVERITY_EMOJI.get(issue.severity, "⚪")
                lines.append(
                    f"{emoji} **[{issue.severity.value.upper()}]** "
                    f"`{issue.file}:{issue.line_start}` — {issue.title}"
                )
                lines.append("")
                lines.append(f"> {issue.description}")
                lines.append("")

                if issue.suggestion:
                    lines.append("<details>")
                    lines.append("<summary>💡 Suggestion</summary>")
                    lines.append("")
                    lines.append("```")
                    lines.append(issue.suggestion)
                    lines.append("```")
                    lines.append("</details>")
                    lines.append("")

                if issue.rule_ref:
                    lines.append(f"📎 *Ref: {issue.rule_ref}*")
                    lines.append("")

        lines.append("---")
        lines.append("*Generated by Code Review Agent — 4 specialized AI reviewers*")

        return "\n".join(lines)
