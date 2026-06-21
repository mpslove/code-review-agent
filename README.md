<p align="center">
  <h1 align="center">QA Agent</h1>
  <p align="center">AI驱动的代码审查 + 静态分析 + 测试生成工具</p>
<p align="center">
  <a href="https://github.com/mpslove/code-review-agent/actions/workflows/ci.yml">
    <img src="https://github.com/mpslove/code-review-agent/actions/workflows/ci.yml/badge.svg" alt="CI Status"/>
  </a>
</p>
</p>

## 概述

QA Agent 是一个面向软件质量保障的智能化工具，提供三种互补的代码分析能力：

| 模式 | 命令 | 技术 | 用途 |
|------|------|------|------|
| **static** | `--mode static` | AST模式匹配（0 LLM调用） | 快速发现已知bug模式 |
| **review** | `--mode review` | 4个LLM专精Agent × 2轮投票 | 深入审查逻辑/安全/性能问题 |
| **testgen** | `--mode testgen` | AST签名提取 + LLM生成 | 自动生成pytest单元测试 |
| **full** | `--mode full` | static + review 合并输出 | 最全面的分析 |

**适用场景：**
- 代码审查（Code Review）：给一个GitHub PR链接或diff文件，自动输出审查报告
- 静态扫描：批量扫描项目代码中的潜在缺陷
- 测试生成：根据函数签名自动生成单元测试骨架

---

## 快速开始

### 环境要求

- Python 3.11+
- DeepSeek API key（review / testgen 模式需要）

### 安装

```bash
# 克隆项目
git clone https://github.com/mpslove/code-review-agent.git
cd code-review-agent

# 安装依赖
pip install -r requirements.txt
```

### 配置

```bash
# 在项目根目录创建 .env 文件
echo "DEEPSEEK_API_KEY=sk-your-key" > .env
```

### 使用示例

**静态分析（AST，不需要API key）：**
```bash
# 分析单个文件
python -m src.main --mode static --file path/to/file.py

# 批量扫描整个目录
python -m src.main --mode static --dir path/to/project
```

**代码审查（需要API key）：**
```bash
# 审查GitHub PR
python -m src.main --pr owner/repo#123

# 审查本地diff文件
python -m src.main --diff-file changes.diff

# 完整模式（静态+审查合并）
python -m src.main --mode full --diff-file changes.diff
```

**测试生成（需要API key）：**
```bash
python -m src.main --mode testgen --file path/to/module.py
```

---

## 技术架构

### 数据流

```
diff / PR / 文件
    │
    ├── [static 模式] ──→ AST解析 ──→ 10个检测器并行 ──→ 报告
    │
    └── [review 模式] ──→ 4个LLM Agent (安全/性能/架构/风格)
                              │
                          [多轮投票] ──→ Verifier ──→ 合并去重 ──→ 报告
                              │
                         [testgen 模式]
                          AST签名提取 ──→ LLM生成 ──→ pytest文件
```

### 静态分析引擎（AST模式匹配）

使用Python内置的 `ast` 模块解析抽象语法树，不依赖LLM。每个检测器独立实现：

| 检测器 | 原理 | 阈值 |
|--------|------|------|
| MutableDefaultArgs | 检测 `def foo(x=[])` 等可变默认参数 | — |
| BareExcept | 检测 `except:` 会吞掉 KeyboardInterrupt | — |
| DangerousFunctions | 检测 eval/exec/pickle/subprocess(shell=True) | — |
| SQLInjection | 检测 SQL 关键字 + f-string/format 拼接 | — |
| PathTraversal | 数据流追踪：参数→`os.path.join` | — |
| HardcodedSecrets | 正则匹配 password/api_key/private key | — |
| UnusedVariable | `定义集 - 引用集` | — |
| ResourceLeak | 检测 `open()` 不在 `with` 内 | — |
| AssertInProduction | 非test文件中的assert | — |
| CompareWithSelf | 检测 `if x == x:` 恒真比较 | — |
| CyclomaticComplexity | McCabe圈复杂度 | >10警告，>20错误 |

### LLM多Agent审查

- **4个专精Agent**：安全（Security）、性能（Performance）、架构（Architecture）、风格（Style）
- **多轮投票**：每个Agent运行N轮，取共识（默认2/2）
- **Verifier过滤器**：前置硬规则（并发/TOCTOU/缓存OOM）绕过LLM直接放行 + LLM二次确认其他issue
- **跨类别去重**：相同文件+行号的issue合并保留高严重度

---

## 验证结果

### 检出率验证（埋9个bug）

在同一份测试代码中埋入9个真实bug模式，三种模式的检出结果：

| Bug类型 | Static | Review | Full |
|---------|:------:|:------:|:----:|
| SQL注入 | ✅ | ✅ | ✅ |
| 无上限缓存OOM | ❌ | ✅ | ✅ |
| 并发竞态（无锁append） | ❌ | ✅ | ✅ |
| 路径遍历 | ✅ | ⚠️ 部分误杀 | ✅ 互补 |
| 日志泄露邮箱 | ❌ | ✅ | ✅ |
| TOCTOU | ❌ | ✅ | ✅ |
| 无线程池限制 | ❌ | ✅ | ✅ |
| MD5不安全哈希 | ❌ | 🟡 Verifier判定合理 | 🟡 |
| run_batch并发 | ❌ | ❌ 边界问题 | ❌ |

**结论：9种埋点检出8类，其中7类通过全部验证。Static和Review互补覆盖关键缺陷。**

### 自己审自己（Dogfooding）

QA Agent 对自己全部28个源文件进行扫描：

```
28 files → 25 issues → 0 LLM calls → 0.3 seconds
```

发现的最严重问题：

| 文件 | 问题 | 修复 |
|------|------|------|
| `src/main.py` | 圈复杂度51（入口函数过大） | 拆成5个handler函数 → 归零 |
| `src/voting.py` | assert在生产代码中（`python -O`禁用） | 改为 `raise ValueError` |
| `src/reviewer/base.py` | JSON提取函数圈复杂度18 | 重写提取策略 |

**证明链：工具发现自己的问题 → 动手修复 → 工具验证修复成功 → 问题数从27降至25。**

### Verifier稳定性

前置硬规则确保关键类别100%通过，不再依赖LLM判断：

```
Auto-pass 并发竞态  × 3（三轮全部通过）
Auto-pass TOCTOU   × 2（三轮全部通过）
Auto-pass OOM缓存  × 3（三轮全部通过）
Auto-pass 日志泄露  × 2（三轮全部通过）
```

---

## 项目结构

```
src/
├── main.py                 # CLI入口
├── config.py               # 配置中心
├── static_analysis/        # 静态分析引擎（AST模式匹配）
│   ├── base.py             # Finding模型 + 检测器基类
│   ├── detectors.py        # 11个检测器实现
│   └── engine.py           # 分析引擎（文件/目录/diff）
├── test_generator/         # 测试用例生成器
│   └── __init__.py
├── reviewer/               # LLM专精Agent
│   ├── base.py             # JSON提取 + 修复 + 校验
│   ├── security.py         # 安全Agent
│   ├── performance.py      # 性能Agent
│   ├── architecture.py     # 架构Agent
│   ├── style.py            # 风格Agent
│   └── prompts.py          # 各Agent提示词
├── verifier.py             # 后验证过滤器（硬规则+LLM）
├── voting.py               # 多轮投票引擎
├── github.py               # GitHub集成（gh CLI）
├── rag/                    # RAG上下文（可选）
├── tools/                  # 工具函数
└── tools/diff_parser.py    # diff解析 + 测试覆盖分析
```

---

## 与岗位JD的对应

| JD要求 | 项目中对应 |
|--------|-----------|
| 基于AI的代码缺陷检测与静态分析 | `--mode static` — 11个AST检测器，0 LLM |
| 大模型辅助Code Review | `--mode review` — 4 Agent × 2轮投票 |
| 识别逻辑漏洞、边界问题与代码坏味道 | 圈复杂度检测 + 并发竞态/TOCTOU/路径遍历检测 |
| AI驱动测试用例自动生成 | `--mode testgen` — AST签名提取 + LLM生成 |
| 利用大模型辅助分析缺陷、定位问题根因 | Verifier逐条验证 + 跨category去重 |
| 沉淀工具与方法 | 统一CLI + markdown/json输出 |

---

## License

MIT
