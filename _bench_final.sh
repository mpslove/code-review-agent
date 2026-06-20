#!/bin/bash
KEY=$(grep "^DEEPSEEK_API_KEY=*** "$LOCALAPPDATA/hermes/.env" | cut -d= -f2-)
export DEEPSEEK_API_KEY=*** D:/security-agents/code-review-agent
mkdir -p tests/benchmark/v4_final

echo "========== V4 FINAL (checklist + JSON fix + suggestion fix) =========="
for pair in \
  "tests/benchmark/new_prs/aio-libs_aiohttp_159.diff:aio159" \
  "tests/benchmark/new_prs/encode_uvicorn_65.diff:uv65" \
  "tests/benchmark/new_prs/encode_starlette_60.diff:star60" \
  "tests/benchmark/new_prs/redis_redis-py_1040.diff:redis1040" \
  "tests/benchmark/real_prs/django_django_11414.diff:django11414"
do
  diff="${pair%%:*}"
  label="${pair##*:}"
  echo "--- $label ---"
  python -m src.main --diff-file "$diff" --rounds 3 --mode balanced \
    --output "tests/benchmark/v4_final/${label}_report.md" 2>&1 | grep "Done:"
done
echo "ALL 5 DONE"
