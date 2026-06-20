#!/bin/bash
# Run agent with NVIDIA API key from Hermes .env
KEY=$(grep "^NVIDIA_API_KEY=" "$LOCALAPPDATA/hermes/.env" | cut -d= -f2-)
export NVIDIA_API_KEY="*** "DEEPSEEK_API_KEY", "")
export DEEPSEEK_API_KEY=*** D:/security-agents/code-review-agent
exec python -m src.main "$@"