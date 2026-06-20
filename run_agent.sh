#!/bin/bash
# Run agent with DeepSeek key from Hermes .env
KEY=$(grep "^DEEPSEEK_API_KEY=" "$LOCALAPPDATA/hermes/.env" | cut -d= -f2-)
export DEEPSEEK_API_KEY="$KEY"
cd D:/security-agents/code-review-agent
exec python -m src.main "$@"
