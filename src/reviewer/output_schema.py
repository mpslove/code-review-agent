"""
Pydantic输出模型 — 所有Agent的输出必须遵守此Schema
用于JSON校验，防止LLM幻觉
"""
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional
from enum import Enum

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

class Category(str, Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    ARCHITECTURE = "architecture"
    STYLE = "style"

class SingleIssue(BaseModel):
    """单个问题"""
    file: str = Field(..., description="文件路径，相对于仓库根")
    line_start: int = Field(..., ge=0, description="问题起始行号")
    line_end: Optional[int] = Field(None, description="问题结束行号，单行则为None")
    severity: Severity = Field(..., description="严重程度")
    category: Category = Field(..., description="问题分类")
    title: str = Field(..., min_length=5, max_length=200, description="问题简述")
    description: str = Field(..., min_length=10, max_length=2000, description="详细描述")
    suggestion: str = Field(..., min_length=5, max_length=3000, description="修复建议，含代码示例")
    rule_ref: Optional[str] = Field(None, description="引用的规则编号，如CWE-79")

class AgentReviewResult(BaseModel):
    """单个Agent的审查结果"""
    agent_type: Category = Field(..., description="Agent类型")
    issues: list[SingleIssue] = Field(default_factory=list, description="发现的问题列表")
    summary: str = Field(..., min_length=10, max_length=500, description="该Agent维度的总结")

class MergedReviewResult(BaseModel):
    """汇总后的审查结果——最终输出"""
    pr_title: str = Field(..., description="PR标题")
    pr_url: Optional[str] = Field(None, description="PR链接")
    files_changed: int = Field(..., ge=0, description="变更文件数")
    total_issues: int = Field(..., ge=0, description="问题总数")
    agent_reviews: list[AgentReviewResult] = Field(..., description="各Agent审查结果")
    merged_summary: str = Field(..., min_length=10, max_length=2000, description="综合总结")

class QAReport(BaseModel):
    """QA Agent审批报告"""
    module: str = Field(..., description="被检查的模块名")
    passed: bool = Field(..., description="是否通过")
    issues: list[str] = Field(default_factory=list, description="发现的问题")
    tests_run: int = Field(0, description="运行的测试数")
    tests_passed: int = Field(0, description="通过的测试数")
    schema_compliant: bool = Field(False, description="输出Schema是否吻合")
