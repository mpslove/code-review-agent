"""Debug verifier: see raw LLM responses for the 2 remaining FPs"""
import sys, os, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%H:%M:%S')

from src.verifier import _call_llm, _parse_verdicts, VERIFIER_PROMPT

issues = [
    {
        "title": "send_data中缺少超时机制，可能导致永久阻塞",
        "description": "wait操作没有超时参数。函数已有timeout参数但未在wait()中使用。如果对端永不发送WINDOW_UPDATE帧，此协程将永久挂起。",
        "severity": "CRITICAL",
    },
    {
        "title": "大对象重复拷贝导致O(n²)内存开销",
        "description": "循环内通过切片data[:chunk_size]分割数据，剩余数据反复拷贝，总复杂度O(n²)。",
        "severity": "HIGH",
    },
]

diff_text = """
+    async def send_data(self, stream_id: int, data: bytes, timeout: TimeoutConfig = None) -> None:
+        while len(data) > 0:
+            flow_control = self.local_flow_control_window(stream_id)
+            chunk_size = min(len(data), flow_control, self.max_outbound_frame_size)
+            if chunk_size == 0:
+                await self.window_update_received[stream_id].wait()
+            chunk, data = data[:chunk_size], data[chunk_size:]
"""

items = []
for idx, iss in enumerate(issues):
    items.append(
        f"### Issue #{idx}\n"
        f"**Severity**: {iss['severity']}\n"
        f"**Title**: {iss['title']}\n"
        f"**Description**: {iss['description'][:500]}"
    )

user_prompt = "## Issues to verify\n\n" + "\n\n".join(items) + "\n\n## Diff\n```diff\n" + diff_text + "\n```"

messages = [
    {"role": "system", "content": VERIFIER_PROMPT},
    {"role": "user", "content": user_prompt},
]

print("=== SYSTEM PROMPT (last 500 chars) ===")
print(VERIFIER_PROMPT[-500:])
print("\n=== CALLING LLM ===")
raw = _call_llm(messages)
print("\n=== RAW RESPONSE ===")
print(raw)
verdicts = _parse_verdicts(raw, 2)
print("\n=== PARSED VERDICTS ===")
for k, v in verdicts.items():
    print(f"  Issue #{k}: {v}")
