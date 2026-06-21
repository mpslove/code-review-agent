"""
静态分析引擎 — 基于Python AST的真实代码分析
不使用LLM，纯编译技术（抽象语法树遍历、模式匹配）
"""

from .engine import StaticAnalyzer, Finding, Severity
from .detectors import ALL_DETECTORS

__all__ = ["StaticAnalyzer", "Finding", "Severity", "ALL_DETECTORS"]
