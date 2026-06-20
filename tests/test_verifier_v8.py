"""Verify V8 verifier catches remaining V7 FPs + borderlines"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.verifier import verify_issues

# V7 FPs + borderlines that should be caught by new rules
test_issues = [
    # FP #5: docstring (rule #5 should catch, reinforced by "标题优先")
    {
        "title": "测试辅助类缺少docstring",
        "description": "新增的TestFile类（第49-92行）没有docstring。该类模拟了一个没有tell方法的可seek文件，用于测试特定边界条件。应提供解释说明。",
        "severity": "MEDIUM",
        "file": "tests/responses/test_fileresponse.py",
        "line_start": 49,
    },
    # FP #15: is_delimiter sig change — new param with default (rule #13)
    {
        "title": "向后兼容性破坏 — is_delimiter函数签名和语义变更",
        "description": "is_delimiter函数签名从(leaf: Leaf) -> int修改为(leaf: Leaf, previous: Leaf = None) -> int，并且内部实现完全改变。",
        "severity": "MEDIUM",
        "file": "black.py",
        "line_start": 1393,
    },
    # BORDERLINE #4: raise e (rule #12)
    {
        "title": "使用 raise e 丢失异常链",
        "description": "在send_packed_command中，将raise改为raise e同样会丢失原始异常信息。",
        "severity": "HIGH",
        "file": "redis/connection.py",
        "line_start": 604,
    },
    # FP #1: function name swap (rule #14)
    {
        "title": "函数名与实际逻辑不一致：_compare_gt_set 和 _compare_gte_set 的实现与名称互换",
        "description": "在 diff 中，_compare_gt_set被重写为_gte_set的旧实现，而_compare_gte_set被重写为_gt_set的旧实现。这是内联重构，不是bug。",
        "severity": "CRITICAL",
        "file": "src/_pytest/assertion/_compare_set.py",
        "line_start": 33,
    },
    # BORDERLINE #6: content_type (no specific rule — expect to leak)
    {
        "title": "潜在破坏性变更 — content_type 处理逻辑向后不兼容",
        "description": "修改前如果Content-Type以text/html开头则覆盖。修改后仅当没有显式提供content_type参数时才覆盖。",
        "severity": "MEDIUM",
        "file": "django/http/response.py",
        "line_start": 438,
    },
]

diff_text = """
diff --git a/tests/responses/test_fileresponse.py b/tests/responses/test_fileresponse.py
+        class TestFile:
+            def __init__(self, path, *args, **kwargs):
+                self._file = open(path, *args, **kwargs)

diff --git a/black.py b/black.py
-def is_delimiter(leaf: Leaf) -> int:
+def is_delimiter(leaf: Leaf, previous: Leaf = None) -> int:

diff --git a/redis/connection.py b/redis/connection.py
-            raise
+            raise e

diff --git a/src/_pytest/assertion/_compare_set.py b/src/_pytest/assertion/_compare_set.py
-def _compare_gt_set(x, y, context):
-    return _compare_gte_set(x, y, context) and x != y
+def _compare_gt_set(x, y, context):
+    return all(e in y for e in x) and x != y
"""

print("=" * 60)
print("V8 Verifier Test: V7 remaining FPs + borderlines")
print("=" * 60)
print(f"\nTesting {len(test_issues)} known FP/borderline issues...\n")

result = verify_issues(test_issues, diff_text)

print(f"Result: {len(test_issues)} issues → {len(result)} passed\n")

passed_titles = {r.get("title", "") for r in result}
all_filtered = True
for iss in test_issues:
    label = "✓ FILTERED" if iss["title"] not in passed_titles else "✗ LEAKED"
    if iss["title"] in passed_titles:
        all_filtered = False
    print(f"  {label} | {iss['title'][:60]}")

print(f"\n{'✓ ALL FILTERED' if all_filtered else '✗ SOME LEAKED'}")
print("=" * 60)
