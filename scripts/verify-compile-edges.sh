#!/usr/bin/env bash
# Verify that the live backend returns subsample->as_X and subsample->as_y edges
# for the medium script. Run after 'make run' to ensure the backend has the latest code.
# Exit 0 if OK, 1 if edges are missing (restart backend with: make stop && make run).

set -e
API="${API_BASE:-http://localhost:8000}"

echo "Fetching medium script from $API/api/scripts/medium ..."
CONTENT=$(curl -s "$API/api/scripts/medium" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(json.dumps(d.get('content', '')))
" 2>/dev/null)

if [ -z "$CONTENT" ] || [ "$CONTENT" = '""' ]; then
  echo "ERROR: Could not fetch script. Is the backend running at $API?"
  exit 1
fi

echo "POSTing to $API/api/compile ..."
RESULT=$(curl -s -X POST "$API/api/compile" \
  -H "Content-Type: application/json" \
  -d "{\"input_code\": $CONTENT}")

echo "$RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
edges = d.get('edges', [])
nodes = d.get('nodes', [])
subsample = next((n['id'] for n in nodes if n.get('label')=='skb.subsample'), None)
as_x = next((n['id'] for n in nodes if n.get('label')=='as_X'), None)
as_y = next((n['id'] for n in nodes if n.get('label')=='as_y'), None)
pairs = {(e['source'],e['target']) for e in edges}
ok_x = (subsample, as_x) in pairs if subsample and as_x else False
ok_y = (subsample, as_y) in pairs if subsample and as_y else False
if ok_x and ok_y:
    print('OK: subsample->as_X and subsample->as_y edges present')
    sys.exit(0)
else:
    print('FAIL: Missing edges!')
    print('  subsample->as_X:', ok_x)
    print('  subsample->as_y:', ok_y)
    print('  Edges:', [(e['source'],e['target']) for e in edges])
    print('')
    print('Restart the backend to pick up the latest code: make stop && make run')
    sys.exit(1)
"
