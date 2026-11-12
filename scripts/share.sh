#!/bin/sh
# Start the whole stack plus the public Cloudflare address and print the links to hand out.
#   sh scripts/share.sh          start (or keep running) and print the links
#   sh scripts/share.sh stop     take the public address down; the site stays on http://localhost:3100
#   sh scripts/share.sh new      get a fresh public address (the old one stops working)
# From Windows:  wsl -d Ubuntu -- sh /root/lexmatches/scripts/share.sh
set -e
cd "$(dirname "$0")/.."

case "${1:-}" in
  stop) docker compose --profile tunnel rm -sf tunnel; echo "Public address is down."; exit 0 ;;
  new) docker compose --profile tunnel rm -sf tunnel >/dev/null 2>&1 || true ;;
esac

docker compose --profile tunnel up -d

url=""
for _ in $(seq 1 45); do
  # the newest address in the log: the container gets a new one on every start
  url="$(docker compose logs tunnel 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1)"
  [ -n "$url" ] && curl -fs -m 10 -o /dev/null "$url/api/health" && break
  sleep 2
done
if [ -z "$url" ] || ! curl -fs -m 10 -o /dev/null "$url/api/health"; then
  echo "The public address did not come up. Check:  docker compose logs tunnel" >&2
  exit 1
fi

token="$(grep '^ADMIN_TOKEN=' .env 2>/dev/null | tail -1 | cut -d= -f2-)"
signup="unknown"
if [ -n "$token" ]; then
  signup="$(curl -s -m 10 -H "Authorization: Bearer $token" http://localhost:3100/api/admin/settings | grep -q 'true' && echo OPEN || echo closed)"
fi

echo
echo "Site for testers:      $url"
if [ -n "$token" ]; then
  echo "Admin (keep private):  $url/admin#$token"
  echo "Admin on this PC:      http://localhost:3100/admin#$token"
else
  echo "Admin: off. Set ADMIN_TOKEN in .env, then: docker compose up -d api"
fi
echo "Public sign-up:        $signup"
[ "$signup" = "OPEN" ] && echo "  Anyone with the address can register and spend your API key. Close it on the admin page."
exit 0
