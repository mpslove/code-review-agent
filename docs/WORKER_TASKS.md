# Code Review Agent — Worker任务书

> 阅读本文后，在指定文件中实现代码。**严格按接口定义，不要增删文件。**

---

## Worker #1: Security + Performance 审查模块

### 任务
在 `src/reviewer/` 下创建两个Agent实现类。

### 文件1: `src/reviewer/security.py`

```python
from .base import BaseReviewer
from .output_schema import Category
from .prompts import SECURITY_PROMPT

class SecurityReviewer(BaseReviewer):
    @property
    def category(self) -> Category:
        return Category.SECURITY

    @property
    def system_prompt(self) -> str:
        return SECURITY_PROMPT

    def build_user_prompt(self, diff_text: str, rag_context: str = "") -> str:
        # 构建发送给LLM的user prompt
        # 格式：先放diff，再放rag上下文（如有），最后输出要求
        ...
```

### 文件2: `src/reviewer/performance.py`

```python
# 同上结构，使用 PERFORMANCE_PROMPT, Category.PERFORMANCE
```

### 验收标准
- [ ] BaseReviewer的所有抽象方法已实现
- [ ] `build_user_prompt()` 正确格式化diff+rag上下文
- [ ] 导入路径正确：`from .base import BaseReviewer`
- [ ] 能通过以下测试：

```python
from src.reviewer.security import SecurityReviewer
r = SecurityReviewer()
assert r.category.value == "security"
prompt = r.build_user_prompt("fake diff\n+password = '123'", "context here")
assert "fake diff" in prompt
assert "context here" in prompt
assert "JSON" in prompt  # 要求JSON输出
```

---

## Worker #2: Architecture + Style 审查模块

### 文件1: `src/reviewer/architecture.py`
使用 ARCHITECTURE_PROMPT, Category.ARCHITECTURE

### 文件2: `src/reviewer/style.py`  
使用 STYLE_PROMPT, Category.STYLE

### 验收标准同Worker #1

---

## Worker #3: RAG索引 + Diff解析

### 文件1: `src/tools/diff_parser.py`

```python
def parse_diff(diff_text: str) -> list[dict]:
    """
    解析git diff，返回变更文件列表。
    
    Returns:
        [{"file": "src/main.py", "added_lines": [(10, "code"), ...], "removed_lines": [...]}]
    """
    ...

def get_changed_files(diff_text: str) -> list[str]:
    """提取变更的文件路径列表"""
    ...

def get_diff_stats(diff_text: str) -> dict:
    """返回 {files_changed: int, additions: int, deletions: int}"""
    ...
```

### 文件2: `src/rag/indexer.py`

```python
import chromadb

class CodeIndexer:
    """代码索引器 — 将仓库代码分块入库"""
    
    def __init__(self, project_root: str, persist_dir: str = "./data/chroma"):
        ...
    
    def index_file(self, filepath: str) -> None:
        """索引单个文件，按函数/类边界分块"""
        ...
    
    def index_project(self) -> None:
        """索引整个项目"""
        ...
    
    def search(self, query: str, top_k: int = 5) -> list[str]:
        """语义搜索相关代码片段"""
        ...
```

### 验收标准
- [ ] `parse_diff` 能正确解析标准git diff输出
- [ ] `CodeIndexer.index_file` 将Python文件按函数/类分块
- [ ] `CodeIndexer.search` 返回相关代码片段（含函数名和行号）

---

## 通用规则

1. **不要新建额外的文件**，只修改指定的文件
2. **不要改基类**（base.py/output_schema.py/prompts.py/config.py）
3. **类型注解完整**：所有函数参数和返回值有类型
4. **不要mock数据**：diff_parser解析真实git diff格式
5. **可测试**：每个函数独立可测，不依赖全局状态
