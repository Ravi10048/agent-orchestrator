#!/usr/bin/env bash
set -euo pipefail

# ─── The ONE command ───────────────────────────────────────────────────
# Copies .env on first run, then builds + starts the whole stack.

if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ created .env from .env.example"
  echo "  • Add GROQ_API_KEY to run agents       (free: https://console.groq.com)"
  echo "  • Add TELEGRAM_BOT_TOKEN for the channel (free: @BotFather on Telegram)"
  echo ""
fi

docker compose up --build
# backend → http://localhost:8000   |   frontend → http://localhost:5173
