"""Debug V7 verifier: see raw LLM responses"""
import sys, os, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%H:%M:%S')

from src.verifier import _call_llm, _parse_verdicts, VERIFIER_PROMPT

issues = [
    {"title": "裸except: 捕获未指定异常类型", "severity": "LOW",
     "description": "多个测试函数中使用了裸except:，捕获所有异常但未做任何处理。应指定具体异常类型。测试代码。"},
    {"title": "新增__all__可能破坏向后兼容性", "severity": "MEDIUM",
     "description": "该diff在__init__.py中新增了显式的__all__元组，限制了通过`from requests import *`导出的符号。"},
]

items = []
for idx, iss in enumerate(issues):
    items.append(f"### Issue #{idx}\n**Severity**: {iss['severity']}\n**Title**: {iss['title']}\n**Description**: {iss['description']}")

user_prompt = "## Issues to verify\n\n" + "\n\n".join(items) + "\n\n## Diff\n```diff\n+except:\n+    is_open = False\n+__all__ = ['get', 'post']\n```"

messages = [
    {"role": "system", "content": VERIFIER_PROMPT},
    {"role": "user", "content": user_prompt},
]

print("=== PROMPT LAST 800 CHARS ===")
print(VERIFIER_PROMPT[-800:])
print("\n=== CALLING LLM ===")
raw = _call_llm(messages)
print(f"\n=== RAW RESPONSE ({len(raw)} chars) ===")
print(raw)
verdicts = _parse_verdicts(raw, 2)
print("\n=== PARSED ===")
for k, v in verdicts.items():
    print(f"  Issue #{k}: {v}")
