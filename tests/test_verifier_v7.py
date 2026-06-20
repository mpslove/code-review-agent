"""Test V7 verifier against V6's 5 remaining FPs + 2 borderlines"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.verifier import verify_issues

# The 5 FPs + 2 borderlines from V6 Precision sampling
test_issues = [
    # FP #3: 测试代码裸except
    {
        "title": "裸except: 捕获未指定异常类型",
        "description": "多个测试函数中使用了裸except:，捕获所有异常但未做任何处理。应指定具体异常类型。",
        "severity": "LOW",
        "file": "tests/test_websocket.py",
        "line_start": 174,
    },
    # FP #7: __all__破坏兼容
    {
        "title": "新增__all__可能破坏向后兼容性",
        "description": "该diff在__init__.py中新增了显式的__all__元组，限制了通过`from requests import *`导出的符号。",
        "severity": "MEDIUM",
        "file": "src/requests/__init__.py",
        "line_start": 185,
    },
    # FP #9: NothingChanged丢路径
    {
        "title": "异常信息丢失: NothingChanged不再携带文件路径",
        "description": "diff中NothingChanged异常从raise NothingChanged(src)改为raise NothingChanged，去掉了参数。这改变了异常携带的信息。",
        "severity": "MEDIUM",
        "file": "black.py",
        "line_start": 74,
    },
    # FP #11: exc_info不匹配
    {
        "title": "日志记录时 exc_info 参数类型不匹配导致异常信息丢失",
        "description": "在 lifespan.py 第 32 行，self.logger.debug(msg, exc_info=exc) 中 exc_info 参数被传递为一个异常实例。Python 标准库 logging 期望布尔值或元组。",
        "severity": "MEDIUM",
        "file": "uvicorn/lifespan.py",
        "line_start": 32,
    },
    # FP #13: 裸except(重复)
    {
        "title": "裸except捕获所有异常，未指定异常类型",
        "description": "在test_send_and_close_connection中，捕获异常时使用裸except:，这会吞掉所有异常。",
        "severity": "MEDIUM",
        "file": "tests/test_websocket.py",
        "line_start": 141,
    },
    # BOUNDARY #4: raise exc from None
    {
        "title": "无意义的异常链抑制",
        "description": "两处 raise exc from None 会丢失原始异常上下文。原始代码使用 raise 更简洁并保留链。",
        "severity": "MEDIUM",
        "file": "uvicorn/middleware/debug.py",
        "line_start": 82,
    },
    # BOUNDARY #14: O(n²) in test utils
    {
        "title": "大数据传输时重复切片导致O(n²)内存复制",
        "description": "send_return_data方法同样使用while循环和切片更新剩余数据，导致与send_data相同的性能问题。",
        "severity": "MEDIUM",
        "file": "tests/dispatch/utils.py",
        "line_start": 155,
    },
]

diff_text = """
diff --git a/tests/test_websocket.py b/tests/test_websocket.py
+try:
+    await websocket.recv()
+except:
+    is_open = False

diff --git a/src/requests/__init__.py b/src/requests/__init__.py
+__all__ = ['get', 'post', 'head', 'put', 'delete', 'patch', 'options', 'request']

diff --git a/black.py b/black.py
-raise NothingChanged(src)
+raise NothingChanged

diff --git a/uvicorn/lifespan.py b/uvicorn/lifespan.py
+self.logger.debug(msg, exc_info=exc)

diff --git a/uvicorn/middleware/debug.py b/uvicorn/middleware/debug.py
+raise exc from None

diff --git a/tests/dispatch/utils.py b/tests/dispatch/utils.py
+chunk, data = data[:chunk_size], data[chunk_size:]
"""

print("=" * 60)
print("V7 Verifier FP Test: 5 FPs + 2 Borderlines")
print("=" * 60)
print(f"\nTesting {len(test_issues)} known false/borderline issues...\n")

result = verify_issues(test_issues, diff_text, max_issues=10)

print(f"Result: {len(test_issues)} issues → {len(result)} passed\n")

passed_titles = {r["title"] for r in result}
all_filtered = True
for iss in test_issues:
    label = "✓ FILTERED" if iss["title"] not in passed_titles else "✗ LEAKED"
    if iss["title"] in passed_titles:
        all_filtered = False
    print(f"  {label} | {iss['title'][:60]}")

print(f"\n{'✓ ALL FILTERED — V7 READY' if all_filtered else '✗ SOME LEAKED — needs more rules'}")
print("=" * 60)
