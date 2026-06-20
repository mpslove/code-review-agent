"""Debug verifier behavior"""
import sys, os, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%H:%M:%S')

from src.verifier import verify_issues, VERIFIER_PROMPT

print("=== VERIFIER PROMPT CHECKS ===")
print("'DRY/代码重复' in prompt:", 'DRY/代码重复' in VERIFIER_PROMPT)
print("'魔法数字' in prompt:", '魔法数字' in VERIFIER_PROMPT)
print("'缺少类型注解' in prompt:", '缺少类型注解' in VERIFIER_PROMPT)
print("'一律NO' in prompt:", '一律NO' in VERIFIER_PROMPT)

issues = [{
    "title": "测试中App类定义重复 (DRY)",
    "description": "每个测试函数内部都定义了一个同名的App类。共出现7次。违反DRY原则。",
    "severity": "MEDIUM",
    "file": "tests/test_websocket.py",
    "line_start": 29,
}]

diff_text = "diff --git a/tests/test_websocket.py b/tests/test_websocket.py\n+class App:\n+    def __init__(self, scope):\n+        self.scope = scope\n"

result = verify_issues(issues, diff_text)
print(f"\nResult: {len(issues)} issues -> {len(result)} passed")
for r in result:
    print(f"  KEPT: {r['title'][:60]}")
