#!/usr/bin/env bash
# =============================================================================
# fetch_data.sh — 一键全量复原 tdsignal JSON 数据产物
#
# 读 data/manifest.json,把每个文件项下载到 static-site/data/{path} 并按 sha256
# 完整性校验。可重复运行:已下载且 sha256 匹配的文件自动跳过;失败自动重试。
#
# 用法:
#   bash fetch_data.sh                # 全量下载(默认)
#   bash fetch_data.sh --sample 5     # 抽样下载 N 个文件(验证用)
#   bash fetch_data.sh --resume       # 断点续传(curl -C -,校验仍以 sha256 为准)
#
# 依赖: bash + curl + python3(解析 manifest,本项目已依赖)
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$ROOT/data/manifest.json"
DEST="$ROOT/static-site/data"
MODE="full"
SAMPLE_N=0
RESUME=0

for arg in "$@"; do
  case "$arg" in
    --resume) RESUME=1 ;;
    --sample=*) SAMPLE_N="${arg#*=}" ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -f "$MANIFEST" ]; then
  echo "✗ 未找到 $MANIFEST(先跑 scripts/gen_data_manifest.py 生成)" >&2
  exit 1
fi

# 生成下载任务行: path<TAB>url<TAB>sha256  (--sample=N 时随机抽 N 个)
if [ "$SAMPLE_N" -gt 0 ]; then
  TASKS="$(python3 - "$MANIFEST" "$SAMPLE_N" <<'PY'
import json, random, sys
m = json.load(open(sys.argv[1]))
n = int(sys.argv[2])
random.seed(20260810)
for f in random.sample(m["files"], min(n, len(m["files"]))):
    print(f'{f["path"]}\t{f["url"]}\t{f["sha256"]}')
PY
)"
else
  TASKS="$(python3 - "$MANIFEST" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for f in m["files"]:
    print(f'{f["path"]}\t{f["url"]}\t{f["sha256"]}')
PY
)"
fi

[ -z "$TASKS" ] && { echo "✗ manifest 无文件项" >&2; exit 1; }

TOTAL="$(printf '%s\n' "$TASKS" | wc -l | tr -d ' ')"
OK=0; SKIP=0; FAIL=0
FAILED_LIST=""

echo "═══ tdsignal 数据全量复原 ═══"
echo "目标目录: $DEST"
echo "任务数  : $TOTAL$( [ "$SAMPLE_N" -gt 0 ] && echo " (抽样)" )"
echo "─────────────────────────────────────────"

I=0
while IFS=$'\t' read -r rel url sha; do
  [ -z "$rel" ] && continue
  I=$((I+1))
  out="$DEST/$rel"
  # 已下载且 sha256 匹配 -> 跳过
  if [ -f "$out" ]; then
    cur="$(shasum -a 256 "$out" | awk '{print $1}')"
    if [ "$cur" = "$sha" ]; then
      SKIP=$((SKIP+1))
      printf '[%s/%s] 跳过(已存在) %s\n' "$I" "$TOTAL" "$rel"
      continue
    fi
  fi
  # 下载 + 校验 + 重试(最多 3 次)
  mkdir -p "$(dirname "$out")"
  tmp="${out}.part"
  attempt=0
  dl_ok=0
  while [ "$attempt" -lt 3 ]; do
    attempt=$((attempt+1))
    curl_args=(-f -L --max-time 600 -sS -o "$tmp")
    [ "$RESUME" -eq 1 ] && curl_args+=(-C -)
    if curl "${curl_args[@]}" "$url" 2>/dev/null; then
      cur="$(shasum -a 256 "$tmp" | awk '{print $1}')"
      if [ "$cur" = "$sha" ]; then
        mv "$tmp" "$out"
        dl_ok=1
        break
      else
        echo "  ⚠ sha256 不匹配,重试($attempt/3): $rel" >&2
      fi
    else
      echo "  ⚠ 下载失败($attempt/3): $url" >&2
    fi
  done
  if [ "$dl_ok" -eq 1 ]; then
    OK=$((OK+1))
    printf '[%s/%s] ✓ %s\n' "$I" "$TOTAL" "$rel"
  else
    FAIL=$((FAIL+1))
    FAILED_LIST="$FAILED_LIST
    $rel"
    printf '[%s/%s] ✗ %s\n' "$I" "$TOTAL" "$rel" >&2
    rm -f "$tmp"
  fi
done <<< "$TASKS"

echo "─────────────────────────────────────────"
echo "完成: 下载 $OK / 跳过 $SKIP / 失败 $FAIL (共 $TOTAL)"
if [ "$FAIL" -gt 0 ]; then
  echo "失败清单:$FAILED_LIST" >&2
  exit 1
fi
# DB 归档提示
python3 - "$MANIFEST" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
if m.get("databases"):
    print("提示: 原始 SQLite 数据库归档(tar.gz)在 GitHub Release,可选下载:")
    for d in m["databases"]:
        print(f"  - {d['name']}  ({d['size']/1024/1024/1024:.2f}GB 原始) {d['url']}")
PY
echo "✅ 全部数据就绪: $DEST"
