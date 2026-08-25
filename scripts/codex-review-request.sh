#!/bin/bash
# codex-review-request.sh — Claude 主控用此脚本向 Codex 派发 review 任务
# 用法: echo '<json>' | bash scripts/codex-review-request.sh <request_id>
# 2026-08-24 升级(来源:外部 reviewer codex 回馈,详见 docs/codex-collab-protocol.md「写入与清理规范」):
#   ①stdin 先存临时文件做 JSON 校验(hash-object --stdin 会消费 stdin,不能边读边验),
#     必填字段含 status(pending|processing|completed);校验失败报错退出且不写 ref、不留垃圾 blob
#   ②先清场再立 ref:写 ref 前自动 rm 旧报告 /tmp/codex-reports/<id>.json,
#     保证「ref 出现」时绝无同 id 旧完整报告残留被误读为本次结果(同 id 重跑的真缺口)
set -euo pipefail

REQUEST_ID="${1:?用法: codex-review-request.sh <request_id>}"

case "$REQUEST_ID" in
    [A-Za-z0-9]*)
        if ! printf '%s' "$REQUEST_ID" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'; then
            echo "错误：request_id 只允许字母/数字/._-,长度 1-128" >&2
            exit 1
        fi
        ;;
    *)
        echo "错误：request_id 只允许字母/数字/._-,长度 1-128" >&2
        exit 1
        ;;
esac

if [ -t 0 ]; then
    echo "错误：请通过 stdin 提供 JSON 内容" >&2
    exit 1
fi

# stdin 只能读一次,先落临时文件供「校验」「写库」两步使用
TMP_JSON=$(mktemp "/tmp/codex-req-${REQUEST_ID}.XXXXXX")
trap 'rm -f "$TMP_JSON"' EXIT
cat > "$TMP_JSON"

# JSON 校验(在 hash-object 之前,防垃圾 blob 留库):解析 + 必填字段 + status 取值 + 与参数一致性
python3 - "$REQUEST_ID" "$TMP_JSON" <<'PYEOF'
import json, sys

request_id, path = sys.argv[1], sys.argv[2]
required = ["request_id", "repo", "base", "head", "task_type", "requirement", "status"]

try:
    d = json.load(open(path))
except Exception as e:
    print(f"❌ request JSON 解析失败: {e}", file=sys.stderr)
    sys.exit(1)

missing = [k for k in required if k not in d]
if missing:
    print(f"❌ 缺少必填字段: {missing}(必填={required})", file=sys.stderr)
    sys.exit(1)

if d["status"] not in ("pending", "processing", "completed"):
    print(f"❌ status 非法: {d['status']!r}(只允许 pending|processing|completed)", file=sys.stderr)
    sys.exit(1)

if d["request_id"] != request_id:
    print(f"❌ request_id 不一致: JSON 内 {d['request_id']!r} != 参数 {request_id!r}(会导致报告落在别的 id 名下)", file=sys.stderr)
    sys.exit(1)

print(f"✅ request JSON 校验通过(status={d['status']})")
PYEOF

BLOB_SHA=$(git hash-object -w "$TMP_JSON")
REF="refs/codex/req/${REQUEST_ID}"
SIGNAL_DIR="/tmp/codex-reports/signals/codex-inbox"

# JSON blob 已入库,释放第一段临时文件并让信号临时文件接管 EXIT trap
rm -f "$TMP_JSON"
trap - EXIT

# 先清场再立 ref:ref 一旦出现,本 id 必无旧报告可误读
rm -f "/tmp/codex-reports/${REQUEST_ID}.json"
# 同 id 重跑也清掉旧唤醒信号与失败残留,防止 watcher 消费上一轮状态
rm -f "${SIGNAL_DIR}/${REQUEST_ID}.ready" \
      "${SIGNAL_DIR}/${REQUEST_ID}.done" \
      "${SIGNAL_DIR}/${REQUEST_ID}.failed"

git update-ref "$REF" "$BLOB_SHA"

mkdir -p "$SIGNAL_DIR"
TMP_SIGNAL=$(mktemp "${SIGNAL_DIR}/.${REQUEST_ID}.XXXXXX")
trap 'rm -f "$TMP_SIGNAL"' EXIT
cat > "$TMP_SIGNAL" <<EOF
{"request_id":"${REQUEST_ID}"}
EOF
mv "$TMP_SIGNAL" "${SIGNAL_DIR}/${REQUEST_ID}.ready"
trap - EXIT

echo "✅ request 已写入"
echo "  ref: $REF"
echo "  sha: $BLOB_SHA"
echo "  id:  $REQUEST_ID"
echo "  signal: ${SIGNAL_DIR}/${REQUEST_ID}.ready"
