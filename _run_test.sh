#!/bin/bash
# Load env and run benchmark
source ~/AppData/Local/hermes/.env
cd D:/security-agents/code-review-agent
mkdir -p tests/benchmark/v4_balanced tests/benchmark/v4_deep

# Run one test
python -m src.main \
  --diff-file tests/benchmark/new_prs/encode_starlette_60.diff \
  --rounds 3 --mode balanced \
  --output tests/benchmark/v4_balanced/star60_test.md \
  2>&1 | tail -5
echo "EXIT: $?"
