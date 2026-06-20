"""
后验证过滤器 — 投票后用一次LLM调用二次确认HIGH/CRITICAL issue。
过滤掉明显的误报，提升Precision。
"""
import json
import re
import logging
from typing import List, Dict
import requests

from .config import config

logger = logging.getLogger(__name__)

VERIFIER_PROMPT = """你是一个代码审查二审专家。初审agent找到了一些问题，你需要逐条判断是真bug还是误报（FP）。

## 判断标准

### 真bug (TP) → 回复 YES
以下任一情况：
1. **运行时错误**：空指针、KeyError、类型错误、未处理异常、race condition
2. **安全漏洞**：注入、XSS、信息泄露、权限绕过
3. **性能缺陷**：重复I/O、O(n²)循环、不必要的大对象分配、冗余计算——只要diff中能定位到具体代码行
4. **逻辑错误**：条件判断反了、边界条件错误、资源泄漏、死循环
5. **不完整实现**：函数体为空、缺少return、异常被吞没处理

### 误报 (FP) → 回复 NO
以下情况：
1. **纯设计意见**：违反SOLID/DIP/SRP但没有具体bug后果、命名建议、抽象层过多的批评
2. **风格偏好**：代码风格、代码组织方式、应该用X模式而不是Y模式（无bug）
3. **推测性问题**：需要diff之外的大量上下文才能判断、假设了一个不太可能发生的场景
4. **"紧耦合"、"职责混乱"等抽象批评**，除非伴随具体的错误链（如"A调用B的方式会导致X错误"）

## 关键原则
- **有代码行证据 + 可验证后果** → YES
- **只有抽象原则/模式批评，无具体错误链** → NO
- **性能问题必须给出具体场景**（如"循环内执行I/O"）才算TP，"可能影响性能"不算

对每条issue回复 YES（真bug）或 NO（误报）+ 一句话理由。

## 输出格式
```json
{
  "verifications": [
    {"issue_id": 0, "verdict": "YES", "reason": "line 42: 未处理FileNotFoundError导致崩溃"},
    {"issue_id": 1, "verdict": "NO", "reason": "空异常类是Python常见模式，无实际危害"},
    {"issue_id": 2, "verdict": "YES", "reason": "line 128: 循环内重复打开文件，O(n) I/O浪费"}
  ]
}
```"""


def verify_issues(issues: List[Dict], diff_text: str, max_issues: int = 15) -> List[Dict]:
    """
    用LLM二次确认issue是否为真bug。
    
    Args:
        issues: [{"title": ..., "description": ..., "severity": ..., "file": ..., "line_start": ...}, ...]
        diff_text: 原始diff
        max_issues: 最多验证多少条（避免prompt过长）
        
    Returns:
        通过验证的issue列表
    """
    if not issues:
        return []
    
    # 只验证HIGH和CRITICAL
    to_verify = [i for i in issues if i.get("severity", "").upper() in ("HIGH", "CRITICAL")]
    rest = [i for i in issues if i not in to_verify]
    
    if not to_verify:
        return issues
    
    to_verify = to_verify[:max_issues]
    
    # 构建验证prompt
    items = []
    for idx, iss in enumerate(to_verify):
        items.append(
            f"### Issue #{idx}\n"
            f"**Severity**: {iss.get('severity', '?')}\n"
            f"**Location**: {iss.get('file', '?')}:{iss.get('line_start', '?')}\n"
            f"**Title**: {iss.get('title', '?')}\n"
            f"**Description**: {iss.get('description', '?')[:500]}"
        )
    
    # 限制diff大小
    max_diff = config.max_diff_size // 4
    if len(diff_text) > max_diff:
        diff_text = diff_text[:max_diff//2] + "\n...[truncated]...\n" + diff_text[-max_diff//2:]
    
    user_prompt = (
        "## Issues to verify\n\n" + "\n\n".join(items) + "\n\n"
        "## Diff (for reference)\n```diff\n" + diff_text + "\n```"
    )
    
    messages = [
        {"role": "system", "content": VERIFIER_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    
    try:
        raw = _call_llm(messages)
        verdicts = _parse_verdicts(raw, len(to_verify))
    except Exception as e:
        logger.warning(f"Verification failed: {e}, keeping all issues")
        return issues
    
    # 过滤FP
    passed = []
    for idx, iss in enumerate(to_verify):
        verdict = verdicts.get(idx, "YES")  # 默认保留
        if verdict == "YES":
            passed.append(iss)
        else:
            logger.info(f"  Filtered FP: {iss.get('title', '?')[:60]}")
    
    logger.info(f"Verification: {len(to_verify)} checked → {len(passed)} passed, {len(to_verify)-len(passed)} filtered")
    return passed + rest


def _call_llm(messages: list) -> str:
    headers = {
        "Authorization": f"Bearer {config.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.llm_model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 2048,
    }
    
    for attempt in range(config.max_retries):
        try:
            resp = requests.post(
                f"{config.llm_base_url}/chat/completions",
                headers=headers, json=payload, timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content", "") or msg.get("reasoning_content", "")
            return content
        except Exception as e:
            if attempt == config.max_retries - 1:
                raise
    return ""


def _parse_verdicts(raw: str, expected_count: int) -> Dict[int, str]:
    """Parse verification results. Returns {issue_id: 'YES'/'NO'}"""
    # 策略1: JSON解析
    json_text = raw.strip()
    if not json_text.startswith("{"):
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        if m:
            json_text = m.group(1).strip()
        else:
            s = json_text.find("{")
            e = json_text.rfind("}")
            if s >= 0 and e > s:
                json_text = json_text[s:e+1]
    
    try:
        data = json.loads(json_text)
        verdicts = {}
        for v in data.get("verifications", []):
            vid = v.get("issue_id", -1)
            verdict = str(v.get("verdict", "YES")).upper()
            verdicts[vid] = "YES" if verdict.startswith("Y") else "NO"
        if verdicts:
            return verdicts
    except Exception:
        pass
    
    # 策略2: 正则兜底 — 匹配 "Issue #N: YES/NO"
    verdicts = {}
    for m in re.finditer(r'Issue\s*#?(\d+).*?(YES|NO)', raw, re.IGNORECASE):
        vid = int(m.group(1))
        verdicts[vid] = "YES" if m.group(2).upper() == "YES" else "NO"
    
    if verdicts:
        return verdicts
    
    # 策略3: 匹配 "verdict": "YES"/"NO" 或 "verdict": "yes"/"no"
    for m in re.finditer(r'"verdict"\s*:\s*"(YES|NO|yes|no)"', raw):
        # 找到最近的issue_id
        before = raw[:m.start()]
        id_match = re.findall(r'"issue_id"\s*:\s*(\d+)', before)
        if id_match:
            vid = int(id_match[-1])
            verdicts[vid] = "YES" if m.group(1).upper() == "YES" else "NO"
    
    if verdicts:
        return verdicts
    
    # 全失败：默认全保留
    logger.warning("All verdict parse strategies failed, keeping all issues")
    return {}
