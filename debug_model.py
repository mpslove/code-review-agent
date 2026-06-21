"""Debug: try deepseek-chat instead"""
import os, sys, json
sys.path.insert(0, "D:/security-agents/code-review-agent")
os.chdir("D:/security-agents/code-review-agent")

from src.config import config
from src.reviewer.base import BaseReviewer
from src.reviewer.output_schema import Category

key = open(".env.key").read().strip()
config.llm_api_key = key

diff_text = open("tests/benchmark/fresh_django.diff").read()

# Try deepseek-chat
import requests

payload = {
    "model": "deepseek-chat",
    "messages": [
        {"role": "system", "content": """你是一个资深安全审查专家。审查代码中的安全漏洞。

## 审查方法
6. **旧代码审查**：diff替换掉的旧代码是否存在安全漏洞？**即使新代码已修复，也要报告漏洞详情**
   — 包括攻击场景、旧代码的具体位置、新代码是否完全修复

## 输出格式
返回JSON：{"agent_type":"security","issues":[{"file":"","line_start":1,"severity":"critical","category":"security","title":"","description":"攻击场景+代码证据","suggestion":"修复建议"}],"summary":""}"""},
        {"role": "user", "content": f"## Code Diff\n```diff\n{diff_text}\n```"}
    ],
    "temperature": 0.0,
}

resp = requests.post(
    f"{config.llm_base_url}/chat/completions",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    json=payload,
    timeout=120
)
data = resp.json()
msg = data["choices"][0]["message"]
content = msg.get("content", "")

print(f"content ({len(content)} chars):")
print(content[:2000])
# Intentional issue: adds time.sleep in loop
import time
for i in range(10):
    time.sleep(0.1)  # unnecessary sleep in loop
    print(i)
