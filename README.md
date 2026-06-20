# 🤖 Code Review Agent

**Multi-Agent AI Code Review System** — 4 specialized LLM reviewers with multi-round voting, false-positive verification, and ensemble mode.

Run on 20 real open-source PRs. Finds runtime bugs, security vulnerabilities, and performance defects that human reviewers sometimes miss.

## Quick Start

```bash
# Install
pip install -e .

# Set your DeepSeek API key
export DEEPSEEK_API_KEY=sk-...

# Review a diff
python -m src.main --diff-file path/to/diff.txt

# Review a GitHub PR
python -m src.main --pr owner/repo#123

# Ensemble mode (3 runs → max coverage)
python -m src.main --diff-file diff.txt --runs 3
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
     |  Security   |  | Performance|  | Architecture|  ...
     |  Reviewer   |  |  Reviewer  |  |  Reviewer   |
     +--------+----+  +-----+------+  +----+--------+
              |              |              |
              +------+-------+------+-------+
                     |              |
              +------v------+  +---v-----------+
              | 2-Round     |  | FP Verifier   |
              | Voting      |  | (LLM二次确认) |
              +------+------+  +---+-----------+
                     |              |
                     +------+-------+
                            |
                     +------v------+
                     | Ensemble    |
                     | (--runs N)  |
                     +------+------+
                            |
                     +------v------+
                     |   Report    |
                     +-------------+
```

**4 Reviewers:**
- **Security** — injections, XSS, auth bypass, crypto flaws
- **Performance** — blocking I/O, O(n²) loops, memory leaks, redundant computation
- **Architecture** — missing error handling, lifecycle bugs, module coupling, unchecked exceptions
- **Style** — missing returns, incorrect conditions, uninitialized attributes, type errors

**Pipeline:**
1. 4 reviewers run in parallel on the diff
2. 2-round voting keeps only consensus issues
3. FP Verifier filters subjective opinions, keeps real bugs
4. Ensemble mode (`--runs N`) runs N times and deduplicates by file+line

## Benchmark Results (20 Real PRs)

| Metric | Value |
|--------|-------|
| PRs Tested | 20 (aiohttp, django, httpx, pytest, redis, requests, starlette, uvicorn…) |
| Agent Issues Found | 76 (single run) / 51 unique (3-run ensemble on aiohttp#159) |
| Human Review Comments | 197 |
| Agent/Human Coverage | 38.6% |
| Spot-check Precision | 60% (random sample) |
| Confirmed True Bugs | 8/10 verified (lop typo, infinite loop, missing return, NameError, blocking I/O, CRLF injection, AttributeError, TypeError) |
| False Positives Filtered | 11 subjective opinions (SRP/DIP violations, parameter count, style nits) |
| Time per PR | ~75s (single) / ~270s (3-run ensemble) |
| API Calls per PR | 9 (single) / 27 (ensemble) |

### Agent finds what humans miss

On **httpx#153**, the agent flagged a timeout handling bug that 3 human reviewers missed. On **django#11414**, it found Content-Length computed by reading the entire file (O(n) I/O waste).

### Agent is weak at what humans do well

- Test coverage suggestions (subTest(), parametrize)
- Naming nitpicks ("utf8" vs "utf-8")
- Context-dependent design discussions

## Usage

```bash
# Basic review
python -m src.main --diff-file diff.txt

# Multi-round voting (2 rounds, min consensus 2)
python -m src.main --diff-file diff.txt --rounds 2

# Ensemble mode: 3 runs, union of findings (best coverage)
python -m src.main --diff-file diff.txt --rounds 2 --runs 3

# Strict mode: only issues appearing in ALL rounds
python -m src.main --diff-file diff.txt --rounds 3 --min-consensus 3 --mode strict

# Output as JSON
python -m src.main --diff-file diff.txt --format json

# Save report to file
python -m src.main --diff-file diff.txt --output report.md

# Review GitHub PR directly
python -m src.main --pr encode/httpx#153 --output report.md
```

## Configuration

Environment variables (or `src/config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPSEEK_API_KEY` | (required) | DeepSeek API key |
| `CR_LLM_MODEL` | `deepseek-v4-flash` | Model name |
| `CR_LLM_BASE_URL` | `https://api.deepseek.com/v1` | API endpoint |
| `CR_LLM_TEMPERATURE` | `0.0` | Deterministic output |

## Known Limitations

1. **LLM non-determinism** — same diff, different runs → different results. Use `--runs 3` to maximize coverage.
2. **Precision ceiling ~60%** — spot-check shows 2/5 issues are subjective opinions.
3. **Weak on test/style review** — agent excels at bugs/performance, not at "should use subTest()" suggestions.
4. **Diff-only context** — cannot see full file, may miss context-dependent issues.
5. **DeepSeek-specific** — some prompts optimized for DeepSeek API behavior (e.g., reasoning_content handling).

## Project Structure

```
code-review-agent/
├── src/
│   ├── main.py              # CLI entry point
│   ├── orchestrator.py      # Parallel reviewer dispatch
│   ├── voting.py            # Multi-round voting + ensemble
│   ├── verifier.py          # FP filter (LLM二次确认)
│   ├── forum.py             # Deduplication engine
│   ├── summarizer.py        # Report generation
│   ├── config.py            # Configuration
│   ├── reviewer/
│   │   ├── base.py          # Base reviewer (LLM call, JSON parse)
│   │   ├── prompts.py       # Reviewer prompts + checklists
│   │   ├── security.py      # Security reviewer
│   │   ├── performance.py   # Performance reviewer
│   │   ├── architecture.py  # Architecture reviewer
│   │   ├── style.py         # Style/Correctness reviewer
│   │   └── output_schema.py # Pydantic models
│   ├── tools/
│   │   └── diff_parser.py   # Diff statistics + context extraction
│   └── rag/                 # Optional RAG integration (chromadb)
├── tests/
│   ├── benchmark/           # 20 PR test data + results
│   └── test_*.py            # Unit tests (45 passing)
├── setup.py
└── README.md
```

## License

MIT
