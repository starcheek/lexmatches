#!/bin/sh
# Runs ON THE SERVER in /opt/lexmatches after new code has been copied there (the GitHub workflow does both;
# by hand: sh deploy/remote-deploy.sh). Rebuilds what changed, restarts it, and fails loudly if the site
# does not answer. Data (database, uploaded books, audio) lives in Docker volumes and is not touched.
set -eu
cd "$(dirname "$0")/.."
compose="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

$compose up -d --build --remove-orphans

for _ in $(seq 1 60); do
  if $compose exec -T web wget -qO- http://127.0.0.1/api/health >/dev/null 2>&1; then
    docker image prune -f >/dev/null   # old image layers would fill a small disk
    echo "Live: $(cat REVISION 2>/dev/null || echo unknown revision)"
    exit 0
  fi
  sleep 3
done

echo "::error::the site did not answer /api/health after the deploy"
$compose ps
$compose logs --tail 60 api web
exit 1
