#!/bin/bash
OUTPUT=$(/root/.openclaw/workspace/jimi_venv/bin/python /root/.openclaw/workspace/jimi_audit/scripts/scanner.py --json 2>/dev/null)
# Check if output starts with { (direct JSON)
FIRST_CHAR=$(echo "$OUTPUT" | head -c 1)
if [ "$FIRST_CHAR" = "{" ]; then
    echo "$OUTPUT"
else
    echo "$OUTPUT" | python3 -c "
import sys, json
text = sys.stdin.read()
lines = text.split('\n')
for i, line in enumerate(lines):
    if line.strip().startswith('{'):
        depth = 0
        for j in range(i, len(lines)):
            for ch in lines[j]:
                if ch == '{': depth += 1
                elif ch == '}': depth -= 1
            if depth == 0:
                blob = '\n'.join(lines[i:j+1])
                try:
                    json.loads(blob)
                    print(blob)
                    sys.exit(0)
                except:
                    break
        break
print('ERROR: No valid JSON found', file=sys.stderr)
sys.exit(1)
"
fi
