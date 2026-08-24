#!/bin/bash
# codex-review-report.sh — Claude 主控用此脚本校验并读取 Codex review 报告
# 用法: bash scripts/codex-review-report.sh <request_id>
set -euo pipefail

REQUEST_ID="${1:?用法: codex-review-report.sh <request_id>}"
REPORT="/tmp/codex-reports/${REQUEST_ID}.json"

if [ ! -f "$REPORT" ]; then
    echo "❌ 报告不存在: $REPORT" >&2
    exit 1
fi

python3 -c "
import json, sys
d = json.load(open('$REPORT'))
required = ['request_id', 'verdict', 'summary', 'issues', 'impact_surface', 'smoke_results', 'recommendation']
missing = [k for k in required if k not in d]
if missing:
    print(f'缺少必填字段: {missing}', file=sys.stderr)
    sys.exit(1)
print('报告校验通过')
if 'status' in d:
    print(f'  status:  {d[\"status\"]}')
print(f'  verdict: {d[\"verdict\"]}')
print(f'  summary: {d[\"summary\"]}')
print(f'  issues:  {len(d[\"issues\"])}')
for i in d.get('issues', []):
    print(f'    [{i.get(\"severity\",\"?\")}] {i.get(\"file\",\"\")} - {i.get(\"description\",\"\")}')
print(f'  recommendation: {d[\"recommendation\"]}')
"
