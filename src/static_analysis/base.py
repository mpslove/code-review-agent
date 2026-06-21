"""
Detector基类和Finding模型
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Finding:
    """静态分析发现的问题"""
    detector: str            # 检测器名称
    severity: Severity       # 严重度
    file: str                # 文件路径（相对或绝对）
    line: int                # 行号
    col: int = 0             # 列号（可选）
    message: str = ""        # 问题描述
    suggestion: str = ""     # 修复建议
    code_snippet: str = ""   # 问题代码片段

    def to_dict(self) -> dict:
        return {
            "detector": self.detector,
            "severity": self.severity.value,
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "message": self.message,
            "suggestion": self.suggestion,
            "code_snippet": self.code_snippet,
        }


class BaseDetector:
    """所有检测器的基类"""
    name: str = ""
    description: str = ""

    def run(self, file_path: str, source: str) -> list[Finding]:
        """运行检测器，返回发现的issues"""
        raise NotImplementedError
