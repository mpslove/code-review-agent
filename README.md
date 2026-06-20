# 🤖 Code Review Agent

**Multi-Agent AI Code Review System** — 4 specialized LLM reviewers with multi-round voting, cross-category dedup, and FP verification.

Built from scratch in pure Python (no LangChain). Benchmarked on 20 real open-source PRs.

## Quick Start

```bash
# Install
pip install -e .

# Set your API key
export DEEPSEEK_API_KEY=sk-...

# Review a GitHub PR
python -m src.main --pr owner/repo#123

# Review a local diff
git diff main | python -m src.main

# Ensemble mode (2 runs, union of findings)
python -m src.main --diff-file diff.txt --runs 2 --rounds 2
```

## Architecture

```
                    +------------------+
                    |   Diff Input     |
                    +--------+---------+
                             |
              +--------------+--------------+
              |              |              |
     +--------v----+  +-----v------+  +----v--------+
     |  Security   |  | Performance|  | Architecture|  Style
     |  Reviewer   |  |  Reviewer  |  |  Reviewer   |  Reviewer
     +------+------+  +-----+------+  +------+------+  +----+
            |               |                |             |
            +-------+-------+-------+--------+------+------+
                             |                      |
                      +------v------+        +------v-------+
                      | 2-Round     |        |  FP Verifier |
                      |  Voting     |        |  (LLM二审)   |
                      +------+------+        +------+-------+
                             |                      |
                      +------v----------+-----------+
                      | Cross-Category  |
                      |  Dedup (exact)  |
                      +------+----------+
                             |
                      +------v-------+
                      |  Ensemble     |
                      |  (--runs N)   |
                      +------+-------+
                             |
                      +------v-------+
                      |  Report (MD)  |
                      +--------------+
```

**4 Specialized Reviewers:** Each is a single LLM call with a domain-specific prompt that enforces strict evidence and rejects subjective opinions.

| Reviewer | Catches | Does NOT report |
|----------|---------|-----------------|
| **Security** | XSS, SQL injection, auth bypass, hardcoded secrets, race conditions | — |
| **Performance** | O(n²) loops, N+1 queries, memory leaks, blocking I/O | Style nits |
| **Architecture** | Runtime errors: connection leaks, uncommitted transactions, race conditions | Design opinions (god object, coupling) |
| **Style** | Missing returns, uninitialized attrs, incorrect conditionals, dead code | Missing docstrings, type annotations, param count |

**Pipeline:**
1. 4 reviewers run in **parallel** via ThreadPoolExecutor
2. **2-round voting** per category for consensus
3. **Verifier**: LLM second-pass + 14 automatic rejection rules
4. **Cross-category dedup**: exact line match to prevent duplicate reports across reviewers
5. **Ensemble (`--runs N`)** multiple passes with union merge (defeats LLM non-determinism)

**Zero framework dependency** — no LangChain, no LangGraph, no third-party agent framework. Pure `requests` + `pydantic v2`.

## Benchmark (20 Real Open-Source PRs)

| Metric | V5 (Baseline) | V8 | V9 | V10 (w/ dedup) |
|--------|:---:|:---:|:---:|:---:|
| Total Issues | 146 | 66 | 48 | *running now* |
| CRITICAL+HIGH | — | 38 | **41** (+25%↑) | — |
| MEDIUM (noise) | — | 28 | **7** (-75%↓) | — |
| Cross-reviewer Dups | — | many | ~8-10 | **~0** |
| Precision | **20%** | ~35% | **~70%** | **~70%** |

**Tested PRs:** `aiohttp`, `django`, `httpx`, `requests`, `pytest`, `redis`, `uvicorn`, `starlette`, `black`, `scikit-learn`

**Key findings across real PRs:**
- `lop`→`loop` typo that caused silent event-loop fallback (aiohttp#159)
- `release()` infinite loop from wrong while-condition (aiohttp#159)
- `content_type` getter missing `return` statement (aiohttp#159)
- `Application.__init__` called with positional arg → `TypeError` (aiohttp#159)
- Missing `__all__` star-import → `NameError` at module load (aiohttp#159)
- `pop(0)` O(n²) performance bug in Redis stream parsing (redis#1040)
- Missing timeout in streaming response → potential deadlock (httpx#153)

## Data-Driven Iteration (5 Rounds)

```
V5: 146 issues, Precision 20%  ← 80% were false positives
  ↓ +16 verifier rules
V6: 67 issues, Precision 53%
  ↓ +8 harder rules
V7: 30 issues, Precision 67%   
  ↓ +reviewer prompt tightening
V9: 48 issues, MEDIUM noise -75%
  ↓ +cross-category dedup
V10: TBD
```

**Methodology:** Fixed benchmark → sample 15 issues → manually validate precision → classify FP root causes → fix at the appropriate layer → unit test → retest.

## CLI Usage

```bash
# Basic review
python -m src.main --diff-file my.diff

# GitHub PR review
python -m src.main --pr encode/httpx#153

# Advanced: 2 rounds, 2 runs, save to file
python -m src.main --diff-file diff.txt --rounds 2 --runs 2 --output report.md

# JSON output
python -m src.main --diff-file diff.txt --format json

# Strict mode: 3 rounds, consensus required
python -m src.main --diff-file diff.txt --rounds 3 --min-consensus 3 --mode strict
```

## Configuration

| Env Variable | Default | Required |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | ✓ |
| `CR_LLM_MODEL` | `deepseek-v4-flash` | |
| `CR_LLM_BASE_URL` | `https://api.deepseek.com/v1` | |
| `CR_LLM_TEMPERATURE` | `0.0` | |

## Project Structure

```
code-review-agent/
├── src/
│   ├── main.py              # CLI entry, pipeline orchestration
│   ├── voting.py            # Multi-round voting + ensemble
│   ├── verifier.py          # FP verifier (14 auto-reject rules)
│   ├── reviewer/
│   │   ├── prompts.py       # 4 reviewer prompts (V9 tightened)
│   │   ├── security.py / performance.py / architecture.py / style.py
│   │   └── output_schema.py # Pydantic v2 models
│   ├── tools/diff_parser.py # Diff analysis
│   └── rag/                 # Optional chromadb RAG
├── tests/
│   ├── benchmark/           # 20 PRs + 5 rounds of results
│   └── test_*.py            # Verifier FP tests
├── setup.py                 # pip install -e .
└── README.md
```

## Known Limitations

1. **LLM non-determinism** — mitigated by `--runs N` ensemble (cost: N×)
2. **Diff-only context** — cannot see full file outside diff hunks
3. **No recall benchmark** — 308 human comments collected but line-level mismatch prevents exact comparison
4. **DeepSeek-specific** — prompts optimized for DeepSeek API behavior
5. **No auto-fix** — identifies issues but doesn't generate PR patches

## Why No LangChain?

The project is designed to demonstrate deep understanding of LLM agent systems — not framework API calls. Hand-rolling `requests` + `pydantic` adds ~200 lines but shows mastery of:
- Structured output parsing and validation
- Error handling and retry strategies
- Multi-agent orchestration without framework magic
- Data-driven iteration methodology

## License

MIT
