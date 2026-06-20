"""
Orchestrator — 并行调度4个专精Reviewer，收集审查结果
支持可选的RAG上下文注入
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from .config import config
from .reviewer.output_schema import AgentReviewResult
from .reviewer.security import SecurityReviewer
from .reviewer.performance import PerformanceReviewer
from .reviewer.architecture import ArchitectureReviewer
from .reviewer.style import StyleReviewer
from .tools.diff_parser import get_changed_files

logger = logging.getLogger(__name__)


class Orchestrator:
    """并行调度所有审查Agent"""

    def __init__(self, indexer=None):
        """
        Args:
            indexer: 可选的 CodeIndexer 实例，用于RAG上下文检索
        """
        self.reviewers = [
            SecurityReviewer(),
            PerformanceReviewer(),
            ArchitectureReviewer(),
            StyleReviewer(),
        ]
        self.indexer = indexer

    def review(self, diff_text: str, rag_context: str = "") -> list[AgentReviewResult]:
        """
        并行运行所有reviewer，收集结果。

        如果配置了indexer且rag_context为空，自动从diff变更文件中检索上下文。

        Args:
            diff_text: git diff文本
            rag_context: RAG检索到的相关代码上下文（显式传入时优先）

        Returns:
            list[AgentReviewResult]: 按 security/performance/architecture/style 排序
        """
        if not diff_text.strip():
            logger.warning("Empty diff, returning empty results")
            return []

        # 自动RAG上下文检索
        if not rag_context and self.indexer is not None:
            rag_context = self._build_rag_context(diff_text)

        results: list[AgentReviewResult] = []
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._run_one, r, diff_text, rag_context): r
                for r in self.reviewers
            }

            for future in as_completed(futures):
                reviewer = futures[future]
                try:
                    result = future.result(timeout=config.max_review_timeout + 30)
                    results.append(result)
                    logger.info(
                        f"[{reviewer.category.value}] done: {len(result.issues)} issues"
                    )
                except Exception as e:
                    err_msg = f"[{reviewer.category.value}] failed: {e}"
                    logger.error(err_msg)
                    errors.append(err_msg)
                    results.append(
                        AgentReviewResult(
                            agent_type=reviewer.category,
                            issues=[],
                            summary=f"Review failed: {str(e)[:200]}",
                        )
                    )

        if errors:
            logger.warning(f"{len(errors)}/{len(self.reviewers)} reviewers failed")

        results.sort(key=lambda r: r.agent_type.value)
        return results

    def _build_rag_context(self, diff_text: str) -> str:
        """从diff中提取变更文件，检索相关代码上下文"""
        try:
            changed = get_changed_files(diff_text)
            if not changed:
                return ""

            contexts = []
            for filepath in changed[:5]:  # 最多检索5个文件
                results = self.indexer.search(filepath, top_k=3)
                if results:
                    contexts.append(f"--- {filepath} ---\n" + "\n".join(results))

            if contexts:
                return "\n\n".join(contexts)
        except Exception as e:
            logger.warning(f"RAG context retrieval failed: {e}")

        return ""

    def _run_one(
        self, reviewer, diff_text: str, rag_context: str
    ) -> AgentReviewResult:
        """运行单个reviewer"""
        return reviewer.review(diff_text, rag_context)
