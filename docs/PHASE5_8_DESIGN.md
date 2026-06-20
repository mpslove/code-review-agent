# Code Review Agent — Worker任务书 (Phase 5-8)

> OpenCode QA: 严格对照本文档逐条审批。每条标准必须通过或明确说明未通过原因。

---

## Phase 5: RAG集成 Pipeline

### 目标
将 `src/rag/indexer.py` 的 CodeIndexer 接入审查pipeline，为reviewer提供相关代码上下文。

### 文件: `src/rag/__init__.py` (更新)
导出 `CodeIndexer` 类。

### 文件: `src/orchestrator.py` (更新)

新增可选参数 `indexer: Optional[CodeIndexer] = None`：
- 如果传入 indexer，`review()` 在调用每个reviewer之前，从diff中提取变更文件名，检索相关代码上下文作为 `rag_context`
- 如果 indexer 为 None 或无索引数据，rag_context 为空字符串

### 文件: `src/main.py` (更新)

新增 CLI 参数：
- `--rag-project <path>`: 索引的项目根目录（可选）
- 如果指定，自动创建 CodeIndexer 并索引项目，传入 Orchestrator

### 验收标准

- [ ] R-1: `src/rag/__init__.py` 导出 `CodeIndexer`
- [ ] R-2: Orchestrator 接受 `indexer` 参数（Optional，默认None）
- [ ] R-3: 有indexer时，从diff提取变更文件，调用 `indexer.search()` 获取上下文
- [ ] R-4: 无indexer时，rag_context为空字符串，不影响原有逻辑
- [ ] R-5: `--rag-project` 参数可用，自动索引项目

---

## Phase 6: GitHub CLI集成

### 目标
通过 `gh` CLI 获取PR diff并发布评论，无需webhook服务器。

### 文件: `src/github.py`

```python
class GitHubIntegration:
    def fetch_pr_diff(self, pr_ref: str) -> tuple[str, str, str]:
        """
        通过 gh pr view/diff 获取PR信息。
        pr_ref: "owner/repo#123" 或 "#123"（当前repo）
        Returns: (diff_text, pr_title, pr_url)
        """

    def post_comment(self, pr_ref: str, comment: str) -> bool:
        """
        通过 gh pr comment 发布审查评论。
        Returns: True 如果发布成功
        """

def parse_pr_ref(ref: str) -> tuple[str, str, int]:
    """
    解析 "owner/repo#123" → (owner, repo, pr_number)
    或 "#123" → (None, None, 123)
    """
```

### 文件: `src/main.py` (更新)

新增 CLI 参数：
- `--pr <ref>`: GitHub PR引用（如 `owner/repo#123` 或 `#123`）
- 自动调用 GitHubIntegration.fetch_pr_diff() 获取diff
- 可配合 `--post-comment` 发布审查结果到PR

### 验收标准

- [ ] G-1: `parse_pr_ref("owner/repo#123")` 返回 `("owner", "repo", 123)`
- [ ] G-2: `parse_pr_ref("#123")` 返回 `(None, None, 123)`
- [ ] G-3: `fetch_pr_diff` 调用 `gh pr view` 和 `gh pr diff` 命令
- [ ] G-4: `post_comment` 调用 `gh pr comment` 命令
- [ ] G-5: gh 命令不存在时返回明确错误（不抛未处理异常）
- [ ] G-6: CLI `--pr` 参数与 `--diff-file` 互斥
- [ ] G-7: CLI `--post-comment` 参数需要 `--pr` 参数

---

## Phase 7: 评测基准框架

### 目标
可复现的评测脚本，衡量审查质量。

### 文件: `tests/benchmark/runner.py`

```python
class BenchmarkRunner:
    def __init__(self, test_cases_dir: str):
        """加载测试用例目录"""

    def run_all(self) -> dict:
        """
        运行所有测试用例。
        Returns: {
            "total": N,
            "precision": 0.xx,
            "recall": 0.xx,
            "f1": 0.xx,
            "per_case": [...]
        }
        """

    def run_single(self, case_name: str) -> dict:
        """运行单个测试用例"""
```

### 测试用例格式: `tests/benchmark/cases/<name>.yaml`

```yaml
name: "SQL injection in auth"
diff_file: "tests/fixtures/sql_injection.diff"
expected:
  security:
    - file: "src/auth.py"
      line_start: 7
      severity: "critical"
      title_contains: "SQL"
    - file: "src/auth.py"
      line_start: 12
      severity: "critical"
      title_contains: "SQL"
  performance:
    - file: "src/auth.py"
      line_start: 18
      title_contains: "N+1"
```

### 验收标准

- [ ] E-1: `BenchmarkRunner` 加载指定目录下所有 `.yaml` 测试用例
- [ ] E-2: `run_single()` 运行单次审查并计算匹配分数
- [ ] E-3: 匹配规则：file+line_start+title_contains（模糊匹配）
- [ ] E-4: 输出含 precision、recall、f1 指标
- [ ] E-5: 至少包含 5 个测试用例
- [ ] E-6: 测试用例覆盖 4 个agent维度

---

## Phase 8: 测试套件

### 目标
单元测试覆盖核心逻辑，不依赖LLM API。

### 文件: `tests/test_forum.py`
覆盖 F-1~F-7 所有验收标准。

### 文件: `tests/test_orchestrator.py`
覆盖 O-1~O-6（不含LLM调用的 O-7）。

### 文件: `tests/test_summarizer.py`
覆盖 S-4~S-8（不含LLM调用的 S-1~S-3）。

### 文件: `tests/test_github.py`
覆盖 G-1~G-2 解析逻辑。

### 文件: `tests/test_diff_parser.py`
覆盖 diff_parser 所有函数。

### 文件: `tests/test_benchmark.py`
覆盖 E-1~E-4。

### 验收标准

- [ ] T-1: `pytest tests/` 运行所有测试（不含LLM调用的除外）
- [ ] T-2: 每个测试文件可独立运行
- [ ] T-3: 覆盖率 >70%（核心逻辑）
- [ ] T-4: 不依赖外部API密钥

---

## 通用规则

1. 不修改已有模块的公开接口（可新增可选参数）
2. 类型注解完整
3. 无硬编码密钥
4. 异常不吞没——日志记录后降级
5. 新增文件遵循项目现有结构
