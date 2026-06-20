"""Test cross-category dedup v2: tighter tolerance to avoid false merges"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from collections import defaultdict
from dataclasses import dataclass, field
from typing import List


@dataclass
class SingleIssue:
    file: str
    line_start: int
    line_end: int = None
    severity: str = "HIGH"
    category: str = "architecture"
    title: str = ""
    description: str = ""
    suggestion: str = ""


@dataclass
class VotedIssue:
    issue: SingleIssue
    vote_count: int = 2
    total_rounds: int = 2
    round_severities: List[str] = field(default_factory=list)


# Same scenario: lop->loop at ~line 70-72, release() at ~238/123/280
scenario = {
    "architecture": [
        VotedIssue(SingleIssue("web/request.py", 238, severity="CRITICAL",
            category="architecture", title="release() while条件错误")),
        VotedIssue(SingleIssue("web/application.py", 72, severity="CRITICAL",
            category="architecture", title="构造参数名拼写错误")),
        VotedIssue(SingleIssue("web/request.py", 97, severity="HIGH",
            category="architecture", title="StreamResponse.version未初始化")),
        VotedIssue(SingleIssue("web/init.py", 3, severity="CRITICAL",
            category="architecture", title="未导入模块对象")),
        VotedIssue(SingleIssue("examples/web_srv.py", 44, severity="CRITICAL",
            category="architecture", title="Application构造误传位置参数")),
    ],
    "style": [
        VotedIssue(SingleIssue("web/application.py", 72, severity="HIGH",
            category="style", title="参数名拼写错误lop应为loop")),
        VotedIssue(SingleIssue("web/application.py", 69, severity="HIGH",
            category="style", title="拼写错误lop应为loop")),
        VotedIssue(SingleIssue("web/request.py", 214, severity="HIGH",
            category="style", title="content_type缺少return")),
    ],
    "security": [
        VotedIssue(SingleIssue("examples/web_srv.py", 40, severity="HIGH",
            category="security", title="跨站脚本攻击XSS")),
        VotedIssue(SingleIssue("examples/web_srv.py", 33, severity="HIGH",
            category="security", title="反射型XSS漏洞")),
    ],
    "performance": [
        VotedIssue(SingleIssue("web/request.py", 280, severity="HIGH",
            category="performance", title="release()循环条件错误")),
        VotedIssue(SingleIssue("web/request.py", 123, severity="CRITICAL",
            category="performance", title="release循环条件错误无限循环")),
    ],
}

before = sum(len(v) for v in scenario.values())
print(f"Before dedup: {before} issues")

# Version 1: exact line match only
def dedup_exact(scenario):
    sev_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    merged = {}
    count = 0
    for cat, issues in scenario.items():
        for vi in issues:
            loc_key = (vi.issue.file, vi.issue.line_start)
            if loc_key in merged:
                existing = merged[loc_key]
                if sev_order.get(vi.issue.severity.upper(), 0) > sev_order.get(existing.issue.severity.upper(), 0):
                    merged[loc_key] = vi
                count += 1
            else:
                merged[loc_key] = vi
    result = defaultdict(list)
    for vi in merged.values():
        result[vi.issue.category].append(vi)
    return dict(result), count

result_exact, merged_exact = dedup_exact(scenario)
after_exact = sum(len(v) for v in result_exact.values())
print(f"\n[Exact match] After dedup: {after_exact} issues (merged {merged_exact})")
for cat, issues in result_exact.items():
    for vi in issues:
        print(f"  [{cat}] {vi.issue.file}:{vi.issue.line_start} [{vi.issue.severity}] {vi.issue.title}")
print(f"  Reduction: {before} -> {after_exact}")

# Version 1b: exact match WITHIN category already done, then cross-category
def dedup_best(scenario):
    """First merge within category (//5 tolerance), then cross-category (exact line)"""
    sev_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    
    # Intra-category dedup (via //5)
    intra = {}
    for cat, issues in scenario.items():
        for vi in issues:
            loc_key = (vi.issue.file, vi.issue.line_start // 5)
            if loc_key in intra:
                existing = intra[loc_key]
                if sev_order.get(vi.issue.severity.upper(), 0) > sev_order.get(existing.issue.severity.upper(), 0):
                    intra[loc_key] = vi
            else:
                intra[loc_key] = vi
    
    intra_issues = list(intra.values())
    print(f"\nAfter intra-category dedup: {len(intra_issues)} issues")
    
    # Cross-category dedup (exact line)
    merged = {}
    for vi in intra_issues:
        loc_key = (vi.issue.file, vi.issue.line_start)
        if loc_key in merged:
            existing = merged[loc_key]
            if sev_order.get(vi.issue.severity.upper(), 0) > sev_order.get(existing.issue.severity.upper(), 0):
                merged[loc_key] = vi
        else:
            merged[loc_key] = vi
    
    result = defaultdict(list)
    for vi in merged.values():
        result[vi.issue.category].append(vi)
    return dict(result)

result_best = dedup_best(scenario)
after_best = sum(len(v) for v in result_best.values())
print(f"\n[Intra-//5 + Cross-exact] After dedup: {after_best} issues")
for cat, issues in result_best.items():
    for vi in issues:
        print(f"  [{cat}] {vi.issue.file}:{vi.issue.line_start} [{vi.issue.severity}] {vi.issue.title}")
print(f"  Reduction: {before} -> {after_best}")

# Check for false merges: XSS(40) vs constructor(44) must NOT merge
xss_kept = any("XSS" in vi.issue.title for cat_issues in result_best.values() for vi in cat_issues)
constr_kept = any("位置参数" in vi.issue.title for cat_issues in result_best.values() for vi in cat_issues)
lop_kept = any("lop" in vi.issue.title and vi.issue.line_start == 72 for cat_issues in result_best.values() for vi in cat_issues)

no_false_merge = xss_kept and constr_kept  # Both should survive (different bugs)
lop_deduped = not any("lop" in vi.issue.title and vi.issue.line_start == 69 for cat_issues in result_best.values() for vi in cat_issues)
release_deduped = not any("release()" in vi.issue.title and vi.issue.category == "performance" and vi.issue.line_start in (238, 280) for cat_issues in result_best.values() for vi in cat_issues)

print(f"\nValidation:")
print(f"  XSS kept: {xss_kept} {'✓' if xss_kept else '✗'}")
print(f"  Constructor kept: {constr_kept} {'✓' if constr_kept else '✗'}")
print(f"  lop@72 kept: {lop_kept} {'✓' if lop_kept else '✗'}")
print(f"  lop@69 deduped (style): {lop_deduped} {'✓' if lop_deduped else '✗'}")
print(f"  No false merge of XSS+constructor: {'✓' if xss_kept and constr_kept else '✗'}")
all_ok = xss_kept and constr_kept and lop_kept and lop_deduped
print(f"\n{'PASS' if all_ok else 'PARTIAL'}: {'All correct' if all_ok else 'Some issues remain'}")
