#!/bin/sh
# Run the Playwright specs in the official Playwright image against the running stack
# (start it first with `docker compose up -d --build`). Screenshots land in e2e/screenshots/.
#   sh e2e/run.sh                 # all specs
#   sh e2e/run.sh --grep upload   # extra args go to `playwright test`
set -e
cd "$(dirname "$0")/.."
docker run --rm --network host --ipc=host \
  -v "$PWD/e2e:/e2e" \
  -v "$PWD/tests/fixtures:/fixtures:ro" \
  -v lexmatches-e2e-node-modules:/e2e/node_modules \
  -w /e2e \
  -e BASE_URL="${BASE_URL:-http://localhost:3100}" \
  -e FIXTURES_DIR=/fixtures \
  -e ADMIN_TOKEN \
  mcr.microsoft.com/playwright:v1.56.1-noble \
  sh -c "npm ci --no-audit --no-fund --loglevel=error && npx playwright test $*"
