#!/bin/bash
# A/B test: V4 balanced vs V4 deep on 5 PRs
KEY=$(grep "^DEEPSEEK_API_KEY=" "$LOCALAPPDATA/hermes/.env" | cut -d= -f2-)
export DEEPSEEK_API_KEY="$KEY"
cd D:/security-agents/code-review-agent
mkdir -p tests/benchmark/v4_balanced tests/benchmark/v4_deep

echo "========== V4 BALANCED (new prompts, checklist, 3 rounds) =========="
for pair in \
  "tests/benchmark/new_prs/aio-libs_aiohttp_159.diff:aio159" \
  "tests/benchmark/new_prs/encode_uvicorn_65.diff:uv65" \
  "tests/benchmark/new_prs/encode_starlette_60.diff:star60" \
  "tests/benchmark/new_prs/redis_redis-py_1040.diff:redis1040" \
  "tests/benchmark/real_prs/django_django_11414.diff:django11414"
do
  diff="${pair%%:*}"
  label="${pair##*:}"
  echo "--- $label (balanced) ---"
  python -m src.main --diff-file "$diff" --rounds 3 --mode balanced \
    --output "tests/benchmark/v4_balanced/${label}_report.md" 2>&1 | grep "Done:"
done

echo ""
echo "========== V4 DEEP (two-stage, 3 rounds) =========="
for pair in \
  "tests/benchmark/new_prs/aio-libs_aiohttp_159.diff:aio159" \
  "tests/benchmark/new_prs/encode_uvicorn_65.diff:uv65" \
  "tests/benchmark/new_prs/encode_starlette_60.diff:star60" \
  "tests/benchmark/new_prs/redis_redis-py_1040.diff:redis1040" \
  "tests/benchmark/real_prs/django_django_11414.diff:django11414"
do
  diff="${pair%%:*}"
  label="${pair##*:}"
  echo "--- $label (deep) ---"
  python -m src.main --diff-file "$diff" --rounds 3 --mode balanced --deep \
    --output "tests/benchmark/v4_deep/${label}_report.md" 2>&1 | grep "Done:"
done

echo "ALL DONE"
