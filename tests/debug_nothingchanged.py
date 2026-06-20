"""Debug: NothingChanged FP"""
import sys, os, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%H:%M:%S')

from src.verifier import verify_issues

issues = [{
    "title": "异常信息丢失: NothingChanged不再携带文件路径",
    "description": "diff中NothingChanged异常从raise NothingChanged(src)改为raise NothingChanged，去掉了参数。这改变了异常携带的信息，导致上层catch无法得知是哪个文件没有变化。调用方已在同文件中适配（从assertRaises改为assertFalse）。",
    "severity": "MEDIUM",
    "file": "black.py",
    "line_start": 74,
}]

diff_text = """
diff --git a/black.py b/black.py
-        raise NothingChanged(src)
+        raise NothingChanged

diff --git a/tests/test_black.py b/tests/test_black.py
-        self.assertRaises(NothingChanged, ff, src)
+        self.assertFalse(ff(src))
"""

result = verify_issues(issues, diff_text)
print(f"Result: {len(issues)} → {len(result)} passed")
for r in result:
    print(f"  KEPT: {r['title'][:60]}")
