#!/bin/bash
# Demo: Run code review agent on a sample diff
# Usage: bash demo.sh

set -e

# Find a small sample diff
SAMPLE="tests/benchmark/real_prs/django_django_18542.diff"
if [ ! -f "$SAMPLE" ]; then
    SAMPLE=$(find tests/benchmark -name "*.diff" -type f | head -1)
fi

echo "============================================"
echo "  Code Review Agent — Demo"
echo "  Reviewing: $(basename "$SAMPLE")"
echo "============================================"
echo ""

bash run_agent.sh --diff-file "$SAMPLE" --rounds 2 --mode balanced --output /tmp/cr_demo.md 2>&1 | grep -v "^$\|DEBUG"

echo ""
echo "============================================"
echo "  Report saved to /tmp/cr_demo.md"
echo ""
head -10 /tmp/cr_demo.md
echo "  ..."
echo "============================================"
