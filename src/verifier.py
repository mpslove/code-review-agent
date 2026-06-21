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
2. **安全漏洞**：注入、XSS、信息泄露、权限绕过、资源耗尽（OOM/DoS）、缓存投毒、输入校验绕过
3. **性能缺陷**：重复I/O、O(n²)循环、不必要的大对象分配、冗余计算——**必须有diff中的具体代码行证据，不能是推测**
4. **逻辑错误**：条件判断反了、边界条件错误、资源泄漏、死循环
5. **不完整实现**：函数体为空、缺少return、异常被吞没处理

### 误报 (FP) → 回复 NO
**自动NO（不需思考）**：
1. **DRY/代码重复**：建议提取公共函数/类/helper — 一律NO，这是代码组织偏好
2. **魔法数字/硬编码常量**：建议定义命名常量 — 一律NO，无bug后果
3. **缺少类型注解**：建议添加type hints — 一律NO，不影响正确性
4. **参数过多/函数签名复杂**：建议重构参数列表 — 一律NO，设计偏好
5. **缺少docstring/注释**：建议补充文档 — 一律NO
6. **asyncio Event/Condition.wait()无超时**：这是Python异步编程的标准行为 — NO
7. **单层循环切片/拷贝声称O(n²)**：没有嵌套循环证据，是O(n) — NO
8. **测试代码中的裸except/异常处理风格**：测试代码用裸except检测任意异常是常见模式 — NO
9. **添加`__all__`限制星号导入**：这是Python标准实践，不是破坏兼容性的bug — NO
10. **`exc_info=异常实例`参数类型声称不匹配**：传入异常实例会让logging内部调用sys.exc_info()，功能等效 — NO
11. **`raise exc from None`异常链抑制**：Python 3显式语法，是有意识的设计选择 — NO
12. **`raise e`替代裸`raise`**：Python 3中raise e保留__context__异常链，traceback差异不构成bug — NO
13. **函数签名增加可选参数**：新参数有默认值(=None)，完全向后兼容，不是破坏性变更 — NO
14. **函数名与实现不一致/互换**：这类声称需要两个函数的完整diff对比证据。如果diff只是代码移动/内联重构，不是bug — NO

**⚠️ 自动NO规则不适用于安全/并发/资源耗尽/TOCTOU类问题**：这些属于运行时错误或安全漏洞，即使描述中使用"可能""潜在"等推测性语言，也需上下文判断。
**⚠️ 安全类issue标题或描述含UNCERTAIN前缀的不适用自动NO**：这是安全reviewer主动标记的"不确定但值得检查"，需逐条判断。

**标题优先原则（仅适用于非安全/非架构/非性能类issue）**：如果issue的标题/核心主张命中自动NO类别，且issue不是category=security或category=architecture或category=performance，则即使描述很详细还必须NO。
**安全（category=security）、架构（category=architecture）、性能（category=performance）类issue，必须完整阅读描述后再判断，不适用标题优先原则。**
**注意：性能reviewer发现的并发竞态/数据竞争/无锁写入问题，属于运行时错误，以具体代码行证据为准判断。**

**并发竞态/TOCTOU/内存泄漏类issue的判断标准**：
- 多个线程写入共享list/dict而没有锁 → YES
- 函数内创建的缓存/dict在多次调用间持续增长无上限 → YES
- 检查文件存在后到使用之间有时间窗口 → YES（TOCTOU）

**需上下文判断**：
6. **证据不成立**：如果issue声称"缺少X"但diff中明显有X — NO
7. **推测性性能问题**：如"可能O(n²)"但没有benchmark或具体循环嵌套证据 — NO
8. **纯设计意见**：违反SOLID/DIP/SRP但没有具体bug后果 — NO
9. **风格偏好**：应该用X模式而不是Y模式、exception chaining方式、type:ignore注释等 — NO
10. **"紧耦合"、"职责混乱"等抽象批评**，除非伴随具体的错误链 — NO
11. **测试辅助/模拟代码中的性能问题**：test mock/helper中的O(n²)不构成实际问题 — NO
12. **内部重构导致的信息变化**：如异常参数修改但调用方在同一文件内已适配 — NO

## 关键原则
- **有代码行证据 + 可验证后果** → YES
- **只有抽象原则/模式批评，无具体错误链** → NO
- **DRY/魔法数字/类型注解/docstring → 一律NO**
- **测试代码异常处理/test mock性能 → 一律NO**
- **证据与diff矛盾（声称缺X但diff有X）→ NO**
- **设计选择（__all__、exc_info、from None）→ NO**

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
    前置硬规则：并发竞态/TOCTOU/资源耗尽直接放行，不经过LLM。
    """
    if not issues:
        return []

    # 前置硬规则：已知为真的模式直接放行，不给LLM误杀机会
    auto_yes_patterns = [
        "无锁写入", "并发竞态", "数据竞争", "race condition", "竞态条件",
        "TOCTOU", "竞态窗口", "时间窗口",
        "无上限缓存", "无限增长", "OOM风险", "内存耗尽",
        "日志中记录.*邮箱", "敏感信息泄露.*日志", "泄露.*PII",
        "无限制.*线程", "无线程池",
        "无连接池复用", "每次.*创建.*连接", "连接池",
        "无超时.*轮询", "无超时.*循环", "无限轮询", "忙等待.*无超时", "while.*True.*无超时",
        "忙等待轮询", "轮询.*任务完成.*无超时",
        "硬编码.*密钥", "硬编码.*密码", "私钥",
    ]
    auto_yes = []
    needs_llm = []
    for iss in issues:
        title = iss.get("title", "")
        is_auto = any(re.search(p, title) for p in auto_yes_patterns)
        if is_auto:
            logger.info(f"  Auto-pass (hard rule): {title[:60]}")
            auto_yes.append(iss)
        else:
            needs_llm.append(iss)

    # LLM验证剩下的
    if needs_llm:
        llm_passed = _verify_with_llm(needs_llm, diff_text, max_issues)
    else:
        llm_passed = []

    passed = auto_yes + llm_passed
    logger.info(f"Verification: {len(issues)} total → {len(passed)} passed "
                f"({len(auto_yes)} auto-yes, {len(llm_passed)} llm-passed, "
                f"{len(needs_llm) - len(llm_passed)} llm-filtered)")
    return passed


def _verify_with_llm(issues: List[Dict], diff_text: str, max_issues: int = 15) -> List[Dict]:
    """纯LLM验证流程（分离出来以便硬规则前置）"""
    
    # 构建验证prompt
    items = []
    for idx, iss in enumerate(issues):
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
        verdicts = _parse_verdicts(raw, len(issues))
    except Exception as e:
        logger.warning(f"Verification failed: {e}, keeping all issues")
        return issues
    
    # 过滤FP
    passed = []
    for idx, iss in enumerate(issues):
        verdict = verdicts.get(idx, "YES")  # 默认保留
        if verdict == "YES":
            passed.append(iss)
        else:
            logger.info(f"  Filtered FP: {iss.get('title', '?')[:60]}")
    
    logger.info(f"Verification: {len(issues)} checked → {len(passed)} passed, {len(issues)-len(passed)} filtered")
    return passed


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
