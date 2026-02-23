#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Check prerequisites
if ! command -v uv &>/dev/null; then
  echo "Error: uv is not installed. Install it from https://docs.astral.sh/uv/"
  exit 1
fi

if ! command -v node &>/dev/null; then
  echo "Error: Node.js is not installed. Install Node.js 18+ from https://nodejs.org/"
  exit 1
fi

echo "Installing Python dependencies..."
uv sync

echo "Installing frontend dependencies..."
cd frontend && npm install && cd ..

echo "Creating upload directories..."
mkdir -p uploads/cases uploads/hats uploads/branding

echo "Initializing database..."
uv run python -c "import asyncio; from headroom.database import init_db; asyncio.run(init_db())"

echo ""
echo "Setup complete! Next steps:"
echo "  Backend:  uv run uvicorn headroom.app:app --reload"
echo "  Frontend: cd frontend && npm run dev"
