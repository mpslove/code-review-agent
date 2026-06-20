"""
标注器 — 第一阶段的便宜扫描。
用一个通用prompt快速扫diff，标注所有可疑行。
不判断对错，只标注"可能有问题"的位置。
"""
import json
import re
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field

import requests

from .config import config

logger = logging.getLogger(__name__)


@dataclass
class FlaggedLine:
    """标注的一条可疑代码行"""
    file: str
    line_start: int
    categories: List[str]  # ["security", "performance", ...]
    confidence: str        # high / medium / low
    reason: str
    diff_snippet: str = ""  # diff原文片段
    context: str = ""       # ±N行上下文（后续填充）


class Annotator:
    """
    预扫描标注器。
    
    用法:
        annotator = Annotator()
        flagged = annotator.scan(diff_text)
        # flagged: List[FlaggedLine]
    """

    def __init__(self):
        self._session = requests.Session()

    def scan(self, diff_text: str, max_flagged: int = 30) -> List[FlaggedLine]:
        """
        扫描diff，标注可疑行。
        
        Args:
            diff_text: 完整git diff
            max_flagged: 最多标注多少行（避免爆炸）
            
        Returns:
            标注列表，按confidence排序（high在前）
        """
        if not diff_text.strip():
            return []

        # 限制diff大小
        max_chars = config.max_diff_size // 2  # 标注用一半就够了
        if len(diff_text) > max_chars:
            diff_text = diff_text[:max_chars//2] + "\n... [truncated] ...\n" + diff_text[-max_chars//2:]

        from .reviewer.prompts import ANNOTATOR_PROMPT
        
        user_prompt = (
            "## Diff to scan\n```diff\n" + diff_text + "\n```\n\n"
            "## Instructions\n"
            "Scan every changed line. Flag anything suspicious. "
            "Be aggressive — it's better to flag 20 and be wrong about 10 than miss 1 real bug.\n"
            f"Return at most {max_flagged} flagged lines."
        )

        messages = [
            {"role": "system", "content": ANNOTATOR_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        raw = self._call_llm(messages)
        return self._parse_flags(raw)

    def _call_llm(self, messages: list) -> str:
        """调用LLM（复用base.py的逻辑）"""
        headers = {
            "Authorization": f"Bearer {config.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.llm_model,
            "messages": messages,
            "temperature": 0.05,
            "max_tokens": 4096,
        }

        for attempt in range(config.max_retries):
            try:
                resp = self._session.post(
                    f"{config.llm_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=config.max_review_timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                msg = choice["message"]
                content = msg.get("content", "")
                if not content or len(content.strip()) < 10:
                    reasoning = msg.get("reasoning_content", "")
                    if reasoning:
                        content = reasoning
                return content
            except requests.Timeout:
                if attempt == config.max_retries - 1:
                    raise
            except Exception as e:
                if attempt == config.max_retries - 1:
                    raise RuntimeError(f"Annotator LLM call failed: {e}")
        return ""

    def _parse_flags(self, raw: str) -> List[FlaggedLine]:
        """解析LLM返回的JSON标注列表"""
        # 提取JSON
        json_text = raw.strip()
        if not json_text.startswith("{"):
            m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
            if m:
                json_text = m.group(1).strip()
            else:
                start = raw.find("{")
                end = raw.rfind("}")
                if start >= 0 and end > start:
                    json_text = raw[start:end + 1]

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            logger.warning("Annotator JSON parse failed, attempting regex extraction")
            data = self._regex_extract(raw)

        flagged_raw = data.get("flagged", [])
        if not isinstance(flagged_raw, list):
            logger.warning(f"Annotator returned non-list flagged: {type(flagged_raw)}")
            return []

        results = []
        for item in flagged_raw:
            if not isinstance(item, dict):
                continue
            try:
                categories = item.get("categories", [])
                if isinstance(categories, str):
                    categories = [categories]
                categories = [c.strip().lower() for c in categories if c.strip().lower() 
                            in ("security", "performance", "architecture", "style")]
                if not categories:
                    categories = ["security"]  # 默认

                results.append(FlaggedLine(
                    file=str(item.get("file", "unknown")),
                    line_start=int(item.get("line_start", 0)),
                    categories=categories,
                    confidence=str(item.get("confidence", "medium")).lower(),
                    reason=str(item.get("reason", "No reason provided")),
                    diff_snippet=str(item.get("diff_snippet", "")),
                ))
            except (ValueError, TypeError) as e:
                logger.debug(f"Skipping malformed flag: {e}")
                continue

        # 按confidence排序
        conf_order = {"high": 0, "medium": 1, "low": 2}
        results.sort(key=lambda x: conf_order.get(x.confidence, 3))
        return results

    def _regex_extract(self, raw: str) -> dict:
        """当JSON失解析失败时的兜底提取"""
        flagged = []
        for m in re.finditer(
            r'"file"\s*:\s*"([^"]+)".*?"line_start"\s*:\s*(\d+).*?"reason"\s*:\s*"([^"]+)"',
            raw, re.DOTALL
        ):
            flagged.append({
                "file": m.group(1),
                "line_start": int(m.group(2)),
                "categories": ["security"],
                "confidence": "medium",
                "reason": m.group(3)[:200],
            })
        return {"flagged": flagged}

    def group_by_category(self, flagged: List[FlaggedLine]) -> Dict[str, List[FlaggedLine]]:
        """
        按category分组标注行。
        
        Returns:
            {"security": [FlaggedLine, ...], "performance": [...], ...}
        """
        from collections import defaultdict
        groups = defaultdict(list)
        for fl in flagged:
            for cat in fl.categories:
                groups[cat].append(fl)
        return dict(groups)

    def enrich_context(self, flagged: List[FlaggedLine], diff_text: str, radius: int = 8) -> List[FlaggedLine]:
        """
        为每个标注行添加上下文代码（从diff中提取±radius行）。
        """
        # 按文件分组
        by_file: Dict[str, List[FlaggedLine]] = {}
        for fl in flagged:
            by_file.setdefault(fl.file, []).append(fl)

        for filepath, flags in by_file.items():
            # 提取该文件在diff中的所有行
            file_diff = self._extract_file_diff(diff_text, filepath)
            if not file_diff:
                continue
            diff_lines = file_diff.split('\n')
            
            for fl in flags:
                # 在diff中找对应行
                target = fl.line_start
                for i, line in enumerate(diff_lines):
                    if line.startswith('@@'):
                        m = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                        if m:
                            new_start = int(m.group(1))
                            offset = i
                    # 计算当前行号
                    if i > offset:
                        line_no = new_start + (i - offset - 1)
                        if line_no == target:
                            # 取前后radius行
                            start = max(0, i - radius)
                            end = min(len(diff_lines), i + radius + 1)
                            fl.context = '\n'.join(diff_lines[start:end])
                            break

        return flagged

    def _extract_file_diff(self, diff_text: str, filepath: str) -> str:
        """从完整diff中提取单个文件的diff块"""
        # 匹配 "diff --git a/path b/path" 到下一个diff块
        escaped = re.escape(filepath)
        m = re.search(
            rf'diff --git a/{escaped} b/{escaped}\n.*?(?=\ndiff --git |\Z)',
            diff_text, re.DOTALL
        )
        if m:
            return m.group(0)
        # 备选：匹配 +++ b/filepath
        m = re.search(
            rf'\+\+\+ b/{escaped}\n(.*?)(?=\ndiff --git |\Z)',
            diff_text, re.DOTALL
        )
        return m.group(1) if m else ""
