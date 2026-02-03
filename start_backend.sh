#!/bin/bash
echo "启动 FastAPI 后端..."
uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
