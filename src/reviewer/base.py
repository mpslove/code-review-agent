"""
Agent基类 — 所有审查Agent继承此类
处理LLM调用、重试、JSON校验、输出验证

v2: 改进JSON解析容错、降低幻觉
"""
import json
import re
import time
import logging
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

import requests
from pydantic import ValidationError

from ..config import config
from .output_schema import AgentReviewResult, Category, SingleIssue

logger = logging.getLogger(__name__)

RETRY_BASE_DELAY = 2  # 指数退避基数


class BaseReviewer(ABC):
    """
    审查Agent基类。
    子类只需实现：
    - category: Category枚举
    - system_prompt: str
    """

    @property
    @abstractmethod
    def category(self) -> Category:
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        ...

    def build_user_prompt(self, diff_text: str, rag_context: str = "") -> str:
        """Build user prompt for LLM. Subclasses may override."""
        nl = chr(10)
        # 限制diff大小，保留前后完整性
        if len(diff_text) > config.max_diff_size:
            half = config.max_diff_size // 2
            diff_text = diff_text[:half] + "\n... [middle truncated] ...\n" + diff_text[-half:]

        parts = ["## Code Diff" + nl + "```diff" + nl + diff_text + nl + "```"]
        if rag_context:
            parts.append("## Related Code Context" + nl + rag_context)
        parts.append(
            "## Task" + nl + "Review the above diff from a " + self.category.value
            + " perspective. Return ONLY valid JSON matching the schema. "
            + "For each issue found, quote the specific diff line(s) as evidence in the description."
        )
        return (nl + nl).join(parts)

    # ============================================================
    # LLM调用（子类不需覆写）
    # ============================================================

    def _call_llm(self, messages: list[dict]) -> str:
        """调用LLM，带重试"""
        headers = {
            "Authorization": f"Bearer {config.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.llm_model,
            "messages": messages,
            "temperature": 0.0,  # deterministic
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
                choice = data["choices"][0]
                msg = choice["message"]

                # DeepSeek v3/v4 可能把实际内容放在 reasoning_content 而非 content
                content = msg.get("content", "")
                if not content or len(content.strip()) < 10:
                    reasoning = msg.get("reasoning_content", "")
                    if reasoning and len(reasoning.strip()) > 10:
                        logger.warning("LLM returned empty content, using reasoning_content")
                        content = reasoning

                return content
            except requests.Timeout:
                last_error = f"Timeout (attempt {attempt + 1})"
                time.sleep(RETRY_BASE_DELAY ** attempt)
            except Exception as e:
                last_error = str(e)
                if attempt < config.max_retries - 1:
                    time.sleep(RETRY_BASE_DELAY ** attempt)

        raise RuntimeError(f"LLM call failed after {config.max_retries} retries: {last_error}")

    # ============================================================
    # JSON解析 + 容错（核心改进）
    # ============================================================

    # 严重度映射（LLM可能用的别名）
    _SEVERITY_MAP = {
        "major": "medium", "minor": "low", "error": "high",
        "warning": "medium", "severe": "high", "fatal": "critical",
        "urgent": "critical", "important": "high", "trivial": "info",
        "none": "info", "note": "info", "suggestion": "low",
        "enhancement": "low", "cosmetic": "info",
    }

    # 字段别名映射（LLM可能用不同名称）
    _FIELD_ALIASES = {
        # line 相关
        "line": "line_start", "lineno": "line_start", "line_no": "line_start",
        "line_number": "line_start", "start_line": "line_start",
        "end_line": "line_end", "line_end": "line_end",
        # title 相关
        "name": "title", "issue": "title", "summary": "title",
        "title_text": "title", "heading": "title",
        # suggestion 相关
        "fix": "suggestion", "recommendation": "suggestion",
        "solution": "suggestion", "proposed_fix": "suggestion",
        # description 相关
        "detail": "description", "details": "description",
        "explanation": "description", "analysis": "description",
        "body": "description", "message": "description",
        # category 相关
        "type": "category", "kind": "category", "issue_type": "category",
        "tag": "category", "label": "category",
        # ref 相关
        "ref": "rule_ref", "rule": "rule_ref", "cwe": "rule_ref",
        "reference": "rule_ref",
        # file 相关
        "path": "file", "filename": "file", "file_path": "file",
        # severity 相关
        "level": "severity", "priority": "severity",
        "impact": "severity", "risk": "severity",
    }

    def _extract_json(self, raw_text: str) -> str:
        """从LLM输出中提取最可能的JSON部分"""
        raw = raw_text.strip()
        
        # 预处理：如果输出包含检查清单，提取JSON部分
        # 检查清单格式: [YES/NO] ... 或 1. YES/NO ...
        checklist_markers = [
            "## 审查结果", "```json", '"agent_type"',
            '"issues"', "### JSON", "## JSON",
        ]
        for marker in checklist_markers:
            idx = raw.find(marker)
            if idx > 0:
                candidate = raw[idx:]
                # 找JSON
                json_start = candidate.find('{')
                if json_start >= 0:
                    raw = candidate[json_start:]
                    break

        # 方法1: 裸JSON
        if raw.startswith("{") and raw.endswith("}"):
            return raw

        # 方法2: ```json ... ``` 包裹
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        if m:
            return m.group(1).strip()

        # 方法3: 找第一个 { 到最后一个 }
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return raw[start:end + 1]

        # 方法4: 如果LLM返回了文本+JSON混合，尝试提取issues数组
        m = re.search(r'"issues"\s*:\s*\[(.*?)\]', raw, re.DOTALL)
        if m:
            issues_text = m.group(1)
            return '{"agent_type": "' + self.category.value + '", "issues": [' + issues_text + '], "summary": "extracted"}'

        return raw

    def _normalize_issue(self, raw_issue: dict) -> dict:
        """标准化单条issue的字段"""
        if not isinstance(raw_issue, dict):
            return raw_issue

        normalized = {}

        # 1. 字段别名映射
        for old_key, val in raw_issue.items():
            new_key = self._FIELD_ALIASES.get(old_key, old_key)
            normalized[new_key] = val

        # 2. 严重度标准化
        if "severity" in normalized:
            sev = str(normalized["severity"]).lower().strip()
            normalized["severity"] = self._SEVERITY_MAP.get(sev, sev)
            # 如果不在合法值内，默认medium
            if normalized["severity"] not in ("critical", "high", "medium", "low", "info"):
                normalized["severity"] = "medium"

        # 3. 必填字段默认值
        defaults = {
            "file": "unknown",
            "line_start": 0,
            "severity": "medium",
            "category": self.category.value,
            "title": "Untitled issue",
            "description": "No description provided",
            "suggestion": "No suggestion provided",
        }
        for field, default in defaults.items():
            if field not in normalized or normalized[field] is None:
                normalized[field] = default

        # 4. line_start: 确保是int且>=0
        try:
            normalized["line_start"] = int(normalized["line_start"])
        except (ValueError, TypeError):
            normalized["line_start"] = 0
        if normalized["line_start"] < 0:
            normalized["line_start"] = 0

        # 5. line_end: 可选，但如果是0转为None
        if "line_end" in normalized:
            try:
                le = int(normalized["line_end"])
                normalized["line_end"] = le if le > 0 else None
            except (ValueError, TypeError):
                normalized["line_end"] = None

        # 6. 字符串长度兜底
        for field in ("title", "description", "suggestion"):
            val = str(normalized.get(field, ""))
            if field == "title" and len(val) < 5:
                val = val + " (needs investigation)"
            if field == "description" and len(val) < 10:
                val = val + " [details truncated - see diff context]"
            if field == "suggestion" and len(val.strip()) < 5:
                # 如果有好的description，用它作suggestion
                desc = str(normalized.get("description", ""))
                if len(desc) > 50:
                    val = desc[:300]
                else:
                    val = "Review the identified issue and apply appropriate fix"
            normalized[field] = val[:3000]  # 截断防超长

        return normalized

    def _parse_and_validate(self, raw_json: str) -> AgentReviewResult:
        """解析LLM返回的JSON，Pydantic校验。最大程度保留有效数据。"""
        raw = self._extract_json(raw_json)

        # 解析JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("JSON parse failed for all extraction methods")
            # 最后尝试：正则提取
            data = self._regex_extract_issues(raw)

        if not isinstance(data, dict):
            logger.warning(f"Parsed data is not dict: {type(data)}")
            data = {"issues": [], "summary": "JSON parse completely failed"}

        # 确保顶层字段
        data.setdefault("agent_type", self.category.value)
        data.setdefault("issues", [])
        data.setdefault("summary", "No summary provided")

        # 标准化所有issues
        raw_issues = data.get("issues", [])
        if not isinstance(raw_issues, list):
            raw_issues = []
        normalized_issues = [self._normalize_issue(i) for i in raw_issues if isinstance(i, dict)]

        # 逐条构造SingleIssue，失败的用fallback
        valid_issues: List[SingleIssue] = []
        for raw_iss in normalized_issues:
            try:
                valid_issues.append(SingleIssue(**raw_iss))
            except ValidationError:
                # 用最小化fallback重试
                try:
                    fallback = {
                        "file": str(raw_iss.get("file", "unknown")),
                        "line_start": max(0, int(raw_iss.get("line_start", 0))),
                        "severity": str(raw_iss.get("severity", "info")),
                        "category": str(raw_iss.get("category", self.category.value)),
                        "title": str(raw_iss.get("title", "Issue"))[:200],
                        "description": str(raw_iss.get("description", "No details"))[:2000],
                        "suggestion": str(raw_iss.get("suggestion", "Review needed"))[:3000],
                    }
                    valid_issues.append(SingleIssue(**fallback))
                except Exception:
                    pass  # truly unfixable — skip this issue

        # 构造汇总结果
        summary = str(data.get("summary", ""))
        if len(summary) < 10:
            summary = f"Found {len(valid_issues)} issue(s) from {self.category.value} perspective"

        return AgentReviewResult(
            agent_type=self.category,
            issues=valid_issues,
            summary=summary[:500],
        )

    def _regex_extract_issues(self, raw_text: str) -> dict:
        """当JSON完全不可解析时，用正则尝试提取issues"""
        issues = []

        # 尝试匹配形如 "file": "xxx", "line_start": N, "title": "xxx"
        # 的片段
        issue_blocks = re.split(r'\}\s*,\s*\{', raw_text)
        for block in issue_blocks:
            file_match = re.search(r'"file"\s*:\s*"([^"]+)"', block)
            line_match = re.search(r'"line(?:_start)?\s*"\s*:\s*(\d+)', block)
            sev_match = re.search(r'"severity"\s*:\s*"([^"]+)"', block)
            title_match = re.search(r'"title"\s*:\s*"([^"]+)"', block)
            desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', block)
            sugg_match = re.search(r'"suggestion"\s*:\s*"((?:[^"\\]|\\.)*)"', block)

            if file_match and title_match:
                desc = (desc_match.group(1) if desc_match else "No description provided")[:2000]
                sugg = (sugg_match.group(1) if sugg_match else "No suggestion provided")
                # 清理转义
                sugg = sugg.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
                if len(sugg.strip()) < 5:
                    sugg = desc[:200] + "..." if len(desc) > 200 else desc
                issues.append({
                    "file": file_match.group(1),
                    "line_start": int(line_match.group(1)) if line_match else 0,
                    "severity": sev_match.group(1) if sev_match else "medium",
                    "category": self.category.value,
                    "title": title_match.group(1)[:200],
                    "description": desc,
                    "suggestion": sugg[:3000],
                })

        return {
            "agent_type": self.category.value,
            "issues": issues,
            "summary": f"Regex extraction yielded {len(issues)} issue(s)",
        }

    # ============================================================
    # 主流程
    # ============================================================

    def review(self, diff_text: str, rag_context: str = "") -> AgentReviewResult:
        """
        执行审查。
        
        Args:
            diff_text: git diff 文本
            rag_context: RAG检索到的相关代码上下文
            
        Returns:
            AgentReviewResult: 结构化审查结果
        """
        if len(diff_text) > config.max_diff_size:
            half = config.max_diff_size // 2
            diff_text = diff_text[:half] + "\n... [truncated] ...\n" + diff_text[-half:]

        user_prompt = self.build_user_prompt(diff_text, rag_context)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        raw = self._call_llm(messages)
        result = self._parse_and_validate(raw)
        return result

    def review_focused(self, diff_text: str, focus_areas: list[dict]) -> AgentReviewResult:
        """
        聚焦审查 — 两阶段模式的第二阶段。
        
        Args:
            diff_text: 完整diff（作为背景参考）
            focus_areas: [{"file": ..., "line_start": ..., "reason": ..., "context": ...}, ...]
                预扫描标注的可疑区域
        
        Returns:
            AgentReviewResult: 结构化审查结果
        """
        from .prompts import build_focus_prompt
        
        if len(diff_text) > config.max_diff_size:
            half = config.max_diff_size // 2
            diff_text = diff_text[:half] + "\n... [truncated] ...\n" + diff_text[-half:]

        user_prompt = build_focus_prompt(
            self.category.value, diff_text, focus_areas
        )
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        
        raw = self._call_llm(messages)
        result = self._parse_and_validate(raw)
        return result
