"""
Code Review Agent — CLI入口

Usage:
    # 审查git diff文件
    python -m src.main --diff-file path/to/diff.txt

    # 从stdin读diff
    git diff main | python -m src.main

    # 从GitHub PR获取
    python -m src.main --pr owner/repo#123

    # 输出到文件
    python -m src.main --diff-file diff.txt --output report.md

    # 指定PR信息
    python -m src.main --diff-file diff.txt --pr-title "Fix auth" --pr-url "https://..."

    # RAG上下文（索引项目代码后审查）
    python -m src.main --diff-file diff.txt --rag-project /path/to/repo

    # 发布评论到GitHub PR
    python -m src.main --pr "#42" --post-comment
"""
import argparse
import logging
import sys
import time
from pathlib import Path

from .config import config
from .orchestrator import Orchestrator
from .forum import ForumEngine
from .summarizer import Summarizer
from .tools.diff_parser import get_diff_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("code-review-agent")


def main():
    parser = argparse.ArgumentParser(
        description="Code Review Agent — 4-specialist AI code review"
    )

    # 输入源（互斥）
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--diff-file", type=str, help="Path to git diff file"
    )
    input_group.add_argument(
        "--pr", type=str, help="GitHub PR reference (e.g. owner/repo#123 or #123)"
    )

    parser.add_argument(
        "--pr-title", type=str, default="Code Review", help="PR title"
    )
    parser.add_argument(
        "--pr-url", type=str, default="", help="PR URL"
    )
    parser.add_argument(
        "--output", type=str, help="Output file path (default: stdout)"
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["markdown", "json"],
        default="markdown",
        help="Output format",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress progress output"
    )
    parser.add_argument(
        "--post-comment", action="store_true",
        help="Post review as GitHub PR comment (requires --pr)"
    )
    parser.add_argument(
        "--rag-project", type=str,
        help="Project root to index for RAG context"
    )
    # 多轮投票
    parser.add_argument(
        "--rounds", type=int, default=2,
        help="Number of review rounds for voting (default: 2)"
    )
    parser.add_argument(
        "--min-consensus", type=int, default=2,
        help="Minimum rounds an issue must appear in to be reported (requires --rounds >= 2)"
    )
    parser.add_argument(
        "--mode", type=str, choices=["strict", "balanced", "recall"], default="balanced",
        help="Voting mode: strict=flat threshold | balanced=severity-weighted | recall=keep all (default: balanced)"
    )
    parser.add_argument(
        "--deep", action="store_true",
        help="Enable two-stage deep review (annotate suspicious lines → focused review)"
    )
    parser.add_argument(
        "--unified", action="store_true",
        help="Use single unified reviewer (1 reviewer × N rounds) instead of 4 specialists"
    )
    parser.add_argument(
        "--no-verify", action="store_true",
        help="Skip post-voting verification of HIGH/CRITICAL issues"
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Run pipeline N times and take the union of findings (reduces LLM non-determinism, default: 1)"
    )
    parser.add_argument(
        "--context-lines", type=int, default=8,
        help="Lines of context around each diff hunk (applied in GitHub PR fetch, default: 8)"
    )
    args = parser.parse_args()

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    # 验证 --post-comment 需要 --pr
    if args.post_comment and not args.pr:
        logger.error("--post-comment requires --pr")
        sys.exit(1)

    # 读取diff
    if args.pr:
        from .github import GitHubIntegration
        github = GitHubIntegration()
        try:
            diff_text, pr_title, pr_url = github.fetch_pr_diff(args.pr)
            logger.info(f"Fetched PR #{pr_title}: {pr_url}")
            if not args.pr_title or args.pr_title == "Code Review":
                args.pr_title = pr_title
            if not args.pr_url:
                args.pr_url = pr_url
        except RuntimeError as e:
            logger.error(f"GitHub fetch failed: {e}")
            sys.exit(1)
    elif args.diff_file:
        diff_text = Path(args.diff_file).read_text(encoding="utf-8")
        logger.info(f"Loaded diff from {args.diff_file}")
    else:
        # stdin
        diff_text = sys.stdin.read()
        if not diff_text.strip():
            logger.error("No input provided. Use --diff-file, --pr, or pipe diff to stdin.")
            sys.exit(1)
        logger.info("Loaded diff from stdin")

    if not diff_text.strip():
        logger.error("Empty diff — nothing to review")
        sys.exit(1)

    # 统计
    stats = get_diff_stats(diff_text)
    logger.info(
        f"Diff stats: {stats['files_changed']} files, "
        f"+{stats['additions']} -{stats['deletions']}"
    )

    # RAG索引
    indexer = None
    if args.rag_project:
        from .rag import CodeIndexer
        try:
            indexer = CodeIndexer(
                args.rag_project,
                persist_dir=str(Path(args.rag_project) / ".code-review-chroma"),
            )
            logger.info(f"Indexing project: {args.rag_project}")
            indexer.index_project()
            logger.info("RAG indexing complete")
        except Exception as e:
            logger.warning(f"RAG indexing failed: {e}. Continuing without RAG.")

    # Phase 1-3: 审查（单轮或多轮投票）
    logger.info("=" * 50)
    t0 = time.time()

    if args.rounds > 1:
        # ========== 多轮投票模式 ==========
        from .voting import VotingOrchestrator
        
        if args.unified:
            from .reviewer.unified import UnifiedReviewer
            reviewers = [UnifiedReviewer()]
            logger.info("Using unified reviewer (single agent, all categories)")
        else:
            from .reviewer.security import SecurityReviewer
            from .reviewer.performance import PerformanceReviewer
            from .reviewer.architecture import ArchitectureReviewer
            from .reviewer.style import StyleReviewer
            reviewers = [
                SecurityReviewer(),
                PerformanceReviewer(),
                ArchitectureReviewer(),
                StyleReviewer(),
            ]
        min_c = min(args.min_consensus, args.rounds)

        logger.info(f"Multi-round voting: {args.rounds} rounds, min consensus {min_c}/{args.rounds}"
                     + (f", {args.runs} run(s)" if args.runs > 1 else "")
                     + (" (two-stage deep)" if args.deep else ""))
        
        # Multi-run: collect union of findings across runs, dedup by file+line
        all_voted = {}  # {cat: {(file, line_tolerance): VotedIssue}}
        for run_i in range(args.runs):
            if args.runs > 1:
                logger.info(f"--- Run {run_i+1}/{args.runs} ---")
            vo = VotingOrchestrator(reviewers, rounds=args.rounds, min_consensus=min_c, mode=args.mode, deep=args.deep)
            voted = vo.review(diff_text, rag_context=(indexer.query(diff_text) if indexer else ""))
            
            # Union merge: dedup by file + line_start (±5 line tolerance), same-category dedup
            for cat, issues in voted.items():
                if cat not in all_voted:
                    all_voted[cat] = {}
                for vi in issues:
                    loc_key = (vi.issue.file, vi.issue.line_start // 5)
                    if loc_key not in all_voted[cat]:
                        all_voted[cat][loc_key] = vi
                    else:
                        # Keep the one with more votes or higher severity
                        existing = all_voted[cat][loc_key]
                        sev_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
                        if sev_order.get(vi.issue.severity.value.upper(), 0) > sev_order.get(existing.issue.severity.value.upper(), 0):
                            all_voted[cat][loc_key] = vi
                        elif vi.vote_count > existing.vote_count:
                            all_voted[cat][loc_key] = vi
            if args.runs > 1:
                logger.info(f"  Run {run_i+1} found {sum(len(v) for v in voted.values())} issues")
        
        # Convert back to list format
        voted = {cat: list(d.values()) for cat, d in all_voted.items()}
        if args.runs > 1:
            total_union = sum(len(v) for v in voted.values())
            logger.info(f"Union across {args.runs} runs: {total_union} unique issues (deduped by file+line)")

        # 后验证过滤器
        if not args.no_verify:
            from .verifier import verify_issues
            for cat, issues in list(voted.items()):
                issue_dicts = [{
                    "title": vi.issue.title,
                    "description": vi.issue.description,
                    "severity": vi.issue.severity.value,
                    "file": vi.issue.file,
                    "line_start": vi.issue.line_start,
                } for vi in issues]
                passed = verify_issues(issue_dicts, diff_text)
                # 根据title匹配过滤
                passed_titles = {p["title"] for p in passed}
                voted[cat] = [vi for vi in issues if vi.issue.title in passed_titles]
            logger.info("Post-verification complete")

        # 跨category去重：精确行号匹配（不//5容差），避免XSS(40)+构造函数(44)等false merge
        if voted:
            from collections import defaultdict
            cross_merged = {}  # {(file, line_start): VotedIssue}
            sev_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
            merged_count = 0
            for cat, issues in list(voted.items()):
                for vi in issues:
                    loc_key = (vi.issue.file, vi.issue.line_start)
                    if loc_key in cross_merged:
                        existing = cross_merged[loc_key]
                        new_sev = sev_order.get(vi.issue.severity.value.upper(), 0)
                        old_sev = sev_order.get(existing.issue.severity.value.upper(), 0)
                        if new_sev > old_sev:
                            cross_merged[loc_key] = vi
                        # 合并投票数：取两个category中较高的
                        cross_merged[loc_key].vote_count = max(
                            cross_merged[loc_key].vote_count, vi.vote_count
                        )
                        merged_count += 1
                    else:
                        cross_merged[loc_key] = vi
            if merged_count > 0:
                logger.info(f"Cross-category dedup: merged {merged_count} duplicate issues")
            # 按category重建
            voted = defaultdict(list)
            for vi in cross_merged.values():
                voted[vi.issue.category].append(vi)

        # 测试覆盖分析
        from .tools.diff_parser import analyze_test_coverage
        coverage = analyze_test_coverage(diff_text)
        
        # 生成报告
        diff_stats_str = (
            f"{stats['files_changed']} files, "
            f"+{stats['additions']} -{stats['deletions']}"
        )
        output = vo.to_markdown_report(voted, diff_stats=diff_stats_str, unified=args.unified, coverage=coverage)
        time.sleep(0)  # noqa

        # 统计
        total_voted = sum(len(v) for v in voted.values())
        if not args.quiet:
            logger.info(f"Done: {total_voted} consensus issues in {time.time()-t0:.1f}s")

    else:
        # ========== 单轮模式（原逻辑） ==========
        logger.info("Phase 1: Running 4 specialized reviewers in parallel...")

        orchestrator = Orchestrator(indexer=indexer)
        reviews = orchestrator.review(diff_text)

        phase1_elapsed = time.time() - t0
        total_issues = sum(len(r.issues) for r in reviews)
        logger.info(
            f"Phase 1 done in {phase1_elapsed:.1f}s: {total_issues} raw issues found"
        )

        # Phase 2: 去重
        logger.info("Phase 2: Deduplicating issues...")
        forum = ForumEngine()
        deduped = forum.deduplicate(reviews)
        deduped_count = sum(len(r.issues) for r in deduped)
        forum_stats = forum.get_stats(deduped)
        logger.info(
            f"Phase 2 done: {total_issues} → {deduped_count} after dedup"
        )

        # Phase 3: 汇总
        logger.info("Phase 3: Generating summary...")
        summarizer = Summarizer()
        result = summarizer.summarize(deduped, stats, args.pr_title, args.pr_url)
        logger.info("Phase 3 done")

        # 输出
        if args.format == "json":
            output = result.model_dump_json(indent=2)
        else:
            output = summarizer.format_comment(result, for_github=True)

        # 统计摘要
        if not args.quiet:
            sev = forum_stats.get("by_severity", {})
            sev_str = ", ".join(f"{k}={v}" for k, v in sorted(sev.items()))
            logger.info(
                f"Done: {deduped_count} issues ({sev_str}) in {time.time()-t0:.1f}s"
            )

    # 发布GitHub评论
    if args.post_comment:
        from .github import GitHubIntegration
        github = GitHubIntegration()
        if github.post_comment(args.pr, output):
            logger.info(f"Review posted to {args.pr}")
        else:
            logger.error("Failed to post comment to GitHub")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
        logger.info(f"Report saved to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
