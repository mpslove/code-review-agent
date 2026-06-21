"""
QA Agent — CLI入口

三种模式：
  1. review (默认) — LLM多Agent代码审查
  2. static — AST静态分析
  3. testgen — 测试用例自动生成

Usage:
    # 代码审查（review模式，默认）
    python -m src.main --diff-file diff.txt
    python -m src.main --pr owner/repo#123

    # 静态分析（static模式，AST技术）
    python -m src.main --mode static --file path/to/file.py
    python -m src.main --mode static --dir path/to/project

    # 测试生成（testgen模式）
    python -m src.main --mode testgen --file path/to/module.py
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path.home() / "AppData" / "Local" / "hermes" / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("qa-agent")


def _build_parser() -> argparse.ArgumentParser:
    """构建CLI参数解析器"""
    parser = argparse.ArgumentParser(
        description="QA Agent — AI驱动的代码审查 + 静态分析 + 测试生成"
    )
    parser.add_argument(
        "--mode", type=str, choices=["review", "static", "testgen", "full"],
        default="review",
    )
    parser.add_argument("--diff-file", type=str)
    parser.add_argument("--pr", type=str)
    parser.add_argument("--file", type=str)
    parser.add_argument("--dir", type=str)
    parser.add_argument("--func", type=str)
    parser.add_argument("--pr-title", type=str, default="Code Review")
    parser.add_argument("--pr-url", type=str, default="")
    parser.add_argument("--output", type=str)
    parser.add_argument("--format", type=str, choices=["markdown", "json"], default="markdown")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--post-comment", action="store_true")
    parser.add_argument("--rag-project", type=str)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--min-consensus", type=int, default=2)
    parser.add_argument("--vote-mode", type=str, choices=["strict", "balanced", "recall"], default="balanced")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--unified", action="store_true")
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--context-lines", type=int, default=8)
    return parser


def handle_static(args, config) -> str:
    """Static模式：AST静态分析，0次LLM调用"""
    from .static_analysis import StaticAnalyzer
    analyzer = StaticAnalyzer()

    if args.dir:
        logger.info(f"Static analysis on directory: {args.dir}")
        skip_dirs = set(config.static_skip_dirs.split(","))
        import os
        all_files = []
        for root, dirs, files in os.walk(args.dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                if f.endswith(".py"):
                    all_files.append(os.path.join(root, f))
        logger.info(f"Found {len(all_files)} Python files")
        all_findings = []
        t0 = time.time()
        for fp in all_files:
            findings = analyzer.analyze_file(fp)
            all_findings.extend(findings)
            if findings:
                logger.info(f"  {fp}: {len(findings)} issues")
        elapsed = time.time() - t0
        logger.info(f"Static analysis complete: {len(all_findings)} issues in {len(all_files)} files ({elapsed:.1f}s)")
        return analyzer.format_report(all_findings)

    elif args.file:
        logger.info(f"Static analysis on file: {args.file}")
        findings = analyzer.analyze_file(args.file)
        logger.info(f"Found {len(findings)} issues")
        return analyzer.format_report(findings)

    logger.error("Static mode requires --file or --dir")
    sys.exit(1)


def handle_testgen(args, config) -> str:
    """Testgen模式：AI测试用例生成"""
    from .test_generator import TestGenerator
    if not args.file:
        logger.error("Testgen mode requires --file")
        sys.exit(1)

    output_path = args.output or str(
        Path(config.testgen_output_dir) / f"test_{Path(args.file).stem}.py"
    )
    logger.info(f"Generating tests for: {args.file}")
    generator = TestGenerator()
    t0 = time.time()
    test_code = generator.generate(
        source_path=args.file, func_name=args.func, output_path=output_path,
    )
    elapsed = time.time() - t0
    if test_code:
        logger.info(f"Tests generated in {elapsed:.1f}s → {output_path}")
        return f"--- Saved to {output_path} ---\nRun with: python -m pytest {output_path} -v"
    logger.error("Test generation failed")
    return ""


def _read_diff(args) -> tuple[str, str, str]:
    """读取diff文本，返回 (diff_text, pr_title, pr_url)"""
    pr_title = args.pr_title
    pr_url = args.pr_url
    if args.pr:
        from .github import GitHubIntegration
        github = GitHubIntegration()
        try:
            diff_text, pr_title, pr_url = github.fetch_pr_diff(args.pr)
            logger.info(f"Fetched PR #{pr_title}")
            if not args.pr_url:
                pr_url = pr_url
            return diff_text, pr_title, pr_url
        except RuntimeError as e:
            logger.error(f"GitHub fetch failed: {e}")
            sys.exit(1)
    elif args.diff_file:
        diff_text = Path(args.diff_file).read_text(encoding="utf-8")
        logger.info(f"Loaded diff from {args.diff_file}")
        return diff_text, pr_title, pr_url
    diff_text = sys.stdin.read()
    if not diff_text.strip():
        logger.error("No input. Use --diff-file, --pr, or pipe to stdin.")
        sys.exit(1)
    return diff_text, pr_title, pr_url


def _run_multi_round_review(diff_text, indexer, args):
    """多轮投票审查（2+ rounds）"""
    from .voting import VotingOrchestrator

    if args.unified:
        from .reviewer.unified import UnifiedReviewer
        reviewers = [UnifiedReviewer()]
    else:
        from .reviewer.security import SecurityReviewer
        from .reviewer.performance import PerformanceReviewer
        from .reviewer.architecture import ArchitectureReviewer
        from .reviewer.style import StyleReviewer
        reviewers = [
            SecurityReviewer(), PerformanceReviewer(),
            ArchitectureReviewer(), StyleReviewer(),
        ]
    min_c = min(args.min_consensus, args.rounds)
    logger.info(f"Multi-round voting: {args.rounds} rounds, min consensus {min_c}/{args.rounds}")

    all_voted = {}
    sev_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    for run_i in range(args.runs):
        if args.runs > 1:
            logger.info(f"--- Run {run_i+1}/{args.runs} ---")
        vo = VotingOrchestrator(reviewers, rounds=args.rounds, min_consensus=min_c,
                               mode=args.vote_mode, deep=args.deep)
        voted = vo.review(diff_text, rag_context=(indexer.query(diff_text) if indexer else ""))
        for cat, issues in voted.items():
            if cat not in all_voted:
                all_voted[cat] = {}
            for vi in issues:
                loc_key = (vi.issue.file, vi.issue.line_start // 5)
                if loc_key not in all_voted[cat]:
                    all_voted[cat][loc_key] = vi
                else:
                    existing = all_voted[cat][loc_key]
                    if sev_order.get(vi.issue.severity.value.upper(), 0) > sev_order.get(existing.issue.severity.value.upper(), 0):
                        all_voted[cat][loc_key] = vi
                    elif vi.vote_count > existing.vote_count:
                        all_voted[cat][loc_key] = vi
    return {cat: list(d.values()) for cat, d in all_voted.items()}, vo


def _apply_verifier(voted, diff_text, args):
    """Verifier过滤"""
    if args.no_verify or not voted:
        return voted
    from .verifier import verify_issues
    for cat, issues in list(voted.items()):
        issue_dicts = [{
            "title": vi.issue.title, "description": vi.issue.description,
            "severity": vi.issue.severity.value, "file": vi.issue.file,
            "line_start": vi.issue.line_start,
        } for vi in issues]
        passed = verify_issues(issue_dicts, diff_text)
        passed_titles = {p["title"] for p in passed}
        voted[cat] = [vi for vi in issues if vi.issue.title in passed_titles]
    return voted


def _cross_dedup(voted):
    """跨category去重"""
    if not voted:
        return voted
    from collections import defaultdict
    sev_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    cross_merged = {}
    for cat, issues in list(voted.items()):
        for vi in issues:
            loc_key = (vi.issue.file, vi.issue.line_start)
            if loc_key in cross_merged:
                existing = cross_merged[loc_key]
                if sev_order.get(vi.issue.severity.value.upper(), 0) > sev_order.get(existing.issue.severity.value.upper(), 0):
                    cross_merged[loc_key] = vi
                cross_merged[loc_key].vote_count = max(cross_merged[loc_key].vote_count, vi.vote_count)
            else:
                cross_merged[loc_key] = vi
    voted_out = defaultdict(list)
    for vi in cross_merged.values():
        voted_out[vi.issue.category].append(vi)
    return voted_out


def handle_review(diff_text: str, args, config) -> str:
    """Review模式：LLM多Agent代码审查"""
    from .tools.diff_parser import get_diff_stats, analyze_test_coverage
    stats = get_diff_stats(diff_text)
    logger.info(f"Diff stats: {stats['files_changed']} files, +{stats['additions']} -{stats['deletions']}")

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
        except Exception as e:
            logger.warning(f"RAG indexing failed: {e}")

    # Full模式：先跑static
    static_report = ""
    static_inject = ""
    if args.mode == "full":
        from .static_analysis import StaticAnalyzer
        logger.info("Phase 1: Static analysis...")
        analyzer = StaticAnalyzer()
        static_findings = analyzer.analyze_diff(diff_text)
        static_report = analyzer.format_report(static_findings)
        logger.info(f"Static analysis: {len(static_findings)} issues")
        if static_findings:
            lines = []
            for f in static_findings:
                loc = f"{f.file}:{f.line}" if hasattr(f, 'file') else f"L{f.line}"
                lines.append(f"- **{loc}**: {f.message[:100]}")
            static_inject = (
                "\n\n## 🛑 静态扫描已确认的问题（请勿重复报告）\n"
                + "\n".join(lines)
                + "\n\n以上行已被静态扫描确认存在问题，不要重复报告。"
                "请专注于审查**其他区域**的新问题。\n"
            )

    # LLM审查 — 注入AST结果到diff中
    logger.info("=" * 50)
    t0 = time.time()
    pr_title = args.pr_title
    review_diff = diff_text + static_inject  # 带AST注入的diff，给LLM看

    if args.rounds > 1:
        voted, vo = _run_multi_round_review(review_diff, indexer, args)
        voted = _apply_verifier(voted, review_diff, args)
        voted = _cross_dedup(voted)
        coverage = analyze_test_coverage(diff_text)
        diff_stats_str = f"{stats['files_changed']} files, +{stats['additions']} -{stats['deletions']}"
        output = vo.to_markdown_report(voted, diff_stats=diff_stats_str, unified=args.unified, coverage=coverage)
        total = sum(len(v) for v in voted.values())
        logger.info(f"Done: {total} consensus issues in {time.time()-t0:.1f}s")
    else:
        from .orchestrator import Orchestrator
        from .forum import ForumEngine
        from .summarizer import Summarizer
        logger.info("Running 4 specialized reviewers in parallel...")
        orchestrator = Orchestrator(indexer=indexer)
        reviews = orchestrator.review(diff_text)
        forum = ForumEngine()
        deduped = forum.deduplicate(reviews)
        summarizer = Summarizer()
        result = summarizer.summarize(deduped, stats, pr_title, args.pr_url)
        output = summarizer.format_comment(result, for_github=False)
        logger.info(f"Done: {sum(len(r.issues) for r in deduped)} issues in {time.time()-t0:.1f}s")

    # 合并static报告
    if args.mode == "full" and static_report and "未发现问题" not in static_report:
        output = static_report + "\n\n" + output
    return output


def main():
    """入口：解析参数 → 分发到对应handler"""
    parser = _build_parser()
    args = parser.parse_args()

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    from .config import config

    # 分发到模式handler
    if args.mode == "static":
        output = handle_static(args, config)
    elif args.mode == "testgen":
        output = handle_testgen(args, config)
    else:
        diff_text, _, _ = _read_diff(args)
        if not diff_text.strip():
            logger.error("Empty input")
            sys.exit(1)
        output = handle_review(diff_text, args, config)

    # 输出
    if args.post_comment:
        logger.info("GitHub comment posting is disabled for safety")
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
        logger.info(f"Report saved to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
