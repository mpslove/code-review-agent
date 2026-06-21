"""
静态分析引擎 — 运行所有检测器并汇总结果
"""

import os
import ast
import logging
from typing import Optional

from .base import Finding, Severity
from .detectors import ALL_DETECTORS

logger = logging.getLogger(__name__)


class StaticAnalyzer:
    """
    静态分析引擎

    使用Python AST对代码进行模式匹配分析，不依赖LLM。
    支持单文件和批量分析。
    """

    def __init__(self, detectors: Optional[list] = None):
        self.detectors = detectors or ALL_DETECTORS

    def analyze_file(self, file_path: str) -> list[Finding]:
        """分析单个Python文件"""
        path = os.path.abspath(file_path)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except (IOError, PermissionError) as e:
            logger.warning(f"Cannot read {path}: {e}")
            return []

        return self.analyze_source(path, source)

    def analyze_source(self, file_path: str, source: str) -> list[Finding]:
        """分析源代码字符串"""
        all_findings = []
        for detector in self.detectors:
            try:
                findings = detector.run(file_path, source)
                all_findings.extend(findings)
            except SyntaxError:
                # Non-Python files, skip
                pass
            except Exception as e:
                logger.debug(f"Detector {detector.name} failed on {file_path}: {e}")
        return all_findings

    def analyze_diff(self, diff_text: str, repo_root: str = ".") -> list[Finding]:
        """
        分析diff中修改的Python文件。
        先尝试精确路径匹配，失败则按文件名搜索。
        """
        findings = []
        changed_files = set()

        # 收集所有修改过的Python文件路径
        for line in diff_text.split('\n'):
            if line.startswith('+++ b/'):
                fpath = line[6:].strip()
                if fpath.endswith('.py'):
                    changed_files.add(fpath)
            elif line.startswith('--- a/'):
                fpath = line[6:].strip()
                if fpath.endswith('.py'):
                    changed_files.add(fpath)

        # 分析每个文件
        for fpath in sorted(changed_files):
            full_path = os.path.join(repo_root, fpath)
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        full_source = f.read()
                    file_findings = self.analyze_source(full_path, full_source)
                    findings.extend(file_findings)
                except Exception as e:
                    logger.debug(f"Cannot analyze {full_path}: {e}")
            else:
                # 按文件名搜索
                import glob
                matches = glob.glob(os.path.join(repo_root, "**", os.path.basename(fpath)), recursive=True)
                if matches:
                    full_path = os.path.abspath(matches[0])
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            full_source = f.read()
                        file_findings = self.analyze_source(full_path, full_source)
                        findings.extend(file_findings)
                    except Exception as e:
                        logger.debug(f"Cannot analyze {full_path}: {e}")
                else:
                    logger.debug(f"Cannot find file from diff: {fpath}")

        # 去重
        seen = set()
        deduped = []
        for f in findings:
            key = (f.file, f.line, f.detector)
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        return deduped

    def analyze_directory(self, directory: str, pattern: str = "*.py") -> dict[str, list[Finding]]:
        """
        批量分析目录中的所有Python文件
        返回 {file_path: [Finding, ...]}
        """
        import glob
        results = {}
        for file_path in glob.glob(os.path.join(directory, "**", pattern), recursive=True):
            if os.path.isfile(file_path):
                findings = self.analyze_file(file_path)
                if findings:
                    results[file_path] = findings
        return results

    def format_report(self, findings: list[Finding], file_filter: Optional[str] = None) -> str:
        """生成可读的报告"""
        if file_filter:
            findings = [f for f in findings if file_filter in f.file]

        if not findings:
            return "## ✅ 静态分析结果\n\n未发现问题。\n"

        lines = ["## 🔬 静态分析结果（AST模式匹配）", ""]
        lines.append(f"共发现 **{len(findings)}** 个问题：")
        lines.append("")

        # 按严重度分组
        by_severity = {"error": [], "warning": [], "info": []}
        for f in findings:
            by_severity.setdefault(f.severity.value, []).append(f)

        sev_labels = {"error": "🔴 ERROR", "warning": "🟡 WARNING", "info": "ℹ️ INFO"}
        for sev in ("error", "warning", "info"):
            items = by_severity.get(sev, [])
            if items:
                lines.append(f"### {sev_labels[sev]} ({len(items)})")
                lines.append("")
                for f in items:
                    loc = f"{f.file}:{f.line}"
                    if f.col:
                        loc += f":{f.col}"
                    lines.append(f"- **{loc}** [{f.detector}]")
                    lines.append(f"  {f.message}")
                    if f.suggestion:
                        lines.append(f"  > 💡 {f.suggestion}")
                    if f.code_snippet:
                        lines.append(f"  ```\n  {f.code_snippet}\n  ```")
                    lines.append("")
                lines.append("")

        lines.append("---\n*静态分析引擎：AST模式匹配，无LLM调用*\n")
        return "\n".join(lines)
