"""
Test verifier with known FPs from V5 Precision sampling.
Verifies the strengthened verifier correctly identifies false positives.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.verifier import verify_issues


# Representative FPs from V5 Precision sampling
# Each test case: (issue_dict, diff_snippet, expected_verdict, description)

def test_verifier_known_fps():
    """
    Feed 5 representative FPs into real verifier, check they get filtered.
    This is a live API test — uses DeepSeek credits.
    """
    print("=" * 60)
    print("Verifier FP Detection Test")
    print("=" * 60)

    # Test issues covering all FP categories in new prompt
    test_issues = [
        # FP category 1: DRY/代码重复 → should be NO
        {
            "title": "测试中App类定义重复 (DRY)",
            "description": "每个测试函数内部都定义了一个同名的`App`类，其结构几乎完全相同。共出现7次。违反DRY原则。应提取为共享辅助类。",
            "severity": "MEDIUM",
            "file": "tests/test_websocket.py",
            "line_start": 29,
        },
        # FP category 2: 魔法数字 → should be NO
        {
            "title": "魔法数字：未命名的硬编码常量",
            "description": "max_size=10000000和max_queue=10000000含义不明，应定义为命名常量。",
            "severity": "MEDIUM",
            "file": "uvicorn/protocols/websocket.py",
            "line_start": 17,
        },
        # FP category 3: 缺少类型注解 → should be NO
        {
            "title": "缺少类型注解",
            "description": "所有新增函数均未提供类型注解，应添加type hints以增强可读性。",
            "severity": "MEDIUM",
            "file": "uvicorn/protocols/websocket.py",
            "line_start": 7,
        },
        # FP category 6: 证据不成立（声称缺X但diff有X）
        {
            "title": "send_data中缺少超时机制，可能导致永久阻塞",
            "description": "wait操作没有超时参数。函数已有timeout参数但未在wait()中使用。",
            "severity": "CRITICAL",
            "file": "httpx/dispatch/http2.py",
            "line_start": 125,
        },
        # FP category 7: 推测性性能问题（O(n²)无证据）
        {
            "title": "大对象重复拷贝导致O(n²)内存开销",
            "description": "循环内通过切片data[:chunk_size]分割数据，剩余数据反复拷贝，总复杂度O(n²)。",
            "severity": "HIGH",
            "file": "httpx/dispatch/http2.py",
            "line_start": 127,
        },
    ]

    # Minimal diff snippets for context
    diff_text = """
diff --git a/tests/test_websocket.py b/tests/test_websocket.py
+class App:
+    def __init__(self, scope):
+        self.scope = scope

diff --git a/uvicorn/protocols/websocket.py b/uvicorn/protocols/websocket.py
+class WebSocketProtocol:
+    def __init__(self, http, handshake_headers):
+        super().__init__(max_size=10000000, max_queue=10000000)
+
+def websocket_upgrade(http):
+    check_request(http.request_headers)

diff --git a/httpx/dispatch/http2.py b/httpx/dispatch/http2.py
+    async def send_data(self, stream_id: int, data: bytes, timeout: TimeoutConfig = None) -> None:
+        while len(data) > 0:
+            flow_control = self.local_flow_control_window(stream_id)
+            chunk_size = min(len(data), flow_control, self.max_outbound_frame_size)
+            if chunk_size == 0:
+                await self.window_update_received[stream_id].wait()
+            chunk, data = data[:chunk_size], data[chunk_size:]
"""

    print(f"\nTesting {len(test_issues)} known FPs...\n")

    result = verify_issues(test_issues, diff_text)

    print(f"Result: {len(test_issues)} issues → {len(result)} passed\n")

    # Check each
    passed_titles = {r["title"] for r in result}
    all_passed = True
    for iss in test_issues:
        label = "✓ FILTERED" if iss["title"] not in passed_titles else "✗ PASSED (bad)"
        if iss["title"] in passed_titles:
            all_passed = False
        print(f"  {label} | {iss['title'][:60]}")

    print(f"\n{'ALL FPs FILTERED — PASS' if all_passed else 'SOME FPs LEAKED — FAIL'}")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    ok = test_verifier_known_fps()
    sys.exit(0 if ok else 1)
