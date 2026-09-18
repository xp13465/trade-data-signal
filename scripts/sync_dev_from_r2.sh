#!/usr/bin/env bash
# =============================================================================
# sync_dev_from_r2.sh — 本机 dev 数据刷新(纯本地, 非上线)
# =============================================================================
# 用途: 本机 dev 数据冻在旧日期时, 从 R2 每日 DB 备份(signal-backup bucket)
#       拉最新 DB, 覆盖本机权威路径(留底备份), 然后本机 export 重算静态产物,
#       最后只读对账 R2(不 PUT)输出不一致项清单。
#
# 用法: bash scripts/sync_dev_from_r2.sh
#
# 时点注意:
#   - 本机 dev 刷新, 非上线。不 push main、不跑 deploy.sh、不上传 R2、不 rsync 云服务器。
#   - 纯本地操作, 交易日盘中/盘后任意时段均可跑(不影响生产; 生产在云上 systemd timer)。
#   - export 全量重算耗时几分钟, 正常等待。
#
# 幂等: 可重复跑。download-db 每次拉最新(同名覆盖), 留底按时间戳子目录不互相覆盖,
#        export 重算覆盖产物, 对账只读无副作用。
#
# 退出码: 0=成功; 非 0=失败(下载/覆盖/export 任一步失败, 或对账发现"真数据差异")。
#
# 环境/依赖:
#   - R2 凭证 source /Users/linhuichen/code/trade/.env
#   - 用 trade-data/.venv/bin/python
# =============================================================================
set -euo pipefail

# ---------- 常量 ----------
TRADE=/Users/linhuichen/code/trade
REPO=/Users/linhuichen/code/trade-data          # 本机权威数据侧(主库/产物)
PY="$REPO/.venv/bin/python"
UP="$TRADE/scripts/upload_r2.py"
R2SYNC=/tmp/r2sync                               # 临时下载目录
OLD="$R2SYNC/old_backup"                         # 留底目录
LOG_DIR="$REPO/data/logs"
TS=$(date +%Y%m%d-%H%M%S)
LOG="$LOG_DIR/sync_dev_from_r2-$TS.log"

mkdir -p "$R2SYNC" "$OLD" "$LOG_DIR"

# 日志双写(tee) + 显式 echo 进度文件(主控监控用)
log() {
  local msg="[$(date +%H:%M:%S)] $*"
  echo "$msg" | tee -a "$LOG"
  echo "$msg" >> /tmp/agent-progress-dev-sync.md
}

# ---------- 凭证 ----------
set -a; source "$TRADE/.env"; set +a
export REPO="$REPO"

log "===== sync_dev_from_r2 开始 TS=$TS ====="

# ---------- 步骤1: download-db 拉 R2 最新 DB ----------
log "step1: download-db 拉取最新 DB(sentiment + etf_national_team)"
SENT_DB=$("$PY" "$UP" download-db sentiment "$R2SYNC" 2>>"$LOG" | tail -1)
ETF_DB=$("$PY" "$UP" download-db etf_national_team "$R2SYNC" 2>>"$LOG" | tail -1)
log "  sentiment -> $SENT_DB"
log "  etf_national_team -> $ETF_DB"
test -f "$SENT_DB" || { log "FAIL: sentiment DB 下载失败"; exit 1; }
test -f "$ETF_DB" || { log "FAIL: etf_national_team DB 下载失败"; exit 1; }

# ---------- 步骤2: 留底旧 DB + 覆盖权威路径 ----------
# 权威路径: trade-data/data/(回测脚本 ETF 优先 trade-data, app/db.py DB_PATH 亦解析到 trade-data/data/sentiment.db)
# 两处独立文件(不同 inode), 都刷保持一致。
BACKUP_SUB="$OLD/$TS"
mkdir -p "$BACKUP_SUB"
for db in sentiment etf_national_team; do
  for side in "$REPO/data" "$TRADE/data"; do
    if [ -f "$side/$db.db" ]; then
      cp -p "$side/$db.db" "$BACKUP_SUB/$(basename "$side")-$db.db.pre-sync"
      log "  留底: $side/$db.db -> $BACKUP_SUB/$(basename "$side")-$db.db.pre-sync"
    fi
  done
done
log "step2: 覆盖权威路径(两处独立文件都刷)"
cp -p "$SENT_DB" "$REPO/data/sentiment.db"
cp -p "$ETF_DB" "$REPO/data/etf_national_team.db"
cp -p "$SENT_DB" "$TRADE/data/sentiment.db"
cp -p "$ETF_DB" "$TRADE/data/etf_national_team.db"
log "  done: trade-data/data/ + trade/data/ 均覆盖为最新备份"

# ---------- 步骤2.1: rsync 云上冻结表(signal_kelly_etf_freeze.json) ----------
# 背景(2026-09-18 根治「冻结分时点漂移」): 冻结表 key=date|index_id|signal → top1 ETF,
# 回测脚本首次碰到未冻结信号会「用当时 best_etf 就地补冻」。本机 dev sync 拉新 DB 后,
# 本机冻结表停在旧日期, 回测首次碰到 9-14~9-17 历史信号 → 用本机今天(9-18)的 board_etf_map
# 重新冻结 → 冻结分漂移(hs300 9-16: 云上 81.5 → 本机重冻 78.7)。
# 根治双管: ①signal_kelly_backtest.py 拒绝补冻历史信号(只补当天盘后新信号);
#           ②此处把云上权威冻结表 rsync 到本机, 冻结表齐全 → 历史信号走已冻结值, 不重冻。
# 权威源 = 云上运行树 /home/ubuntu/code/trade-data/data/signal_kelly_etf_freeze.json(生产实际状态)。
# ⚠ 冻结表不在 R2(s3 全 404), 只能 rsync, 不走 upload_r2/download-db 拉它。
# ⚠ 与 DB 同步一致, 双写两处: trade-data/data/ + trade/data/(signal_kelly_backtest.py 的
#   _etf_freeze_path 按 ROOT 解析, ROOT 可能落 trade 侧, 双处都刷保持一致)。
FROZEN_SRC="/home/ubuntu/code/trade-data/data/signal_kelly_etf_freeze.json"
log "step2.1: rsync 云上冻结表(权威源 $FROZEN_SRC)"
if ! rsync -az -e "ssh -i ~/tdsignal.pem" \
     "ubuntu@122.51.111.173:$FROZEN_SRC" \
     "$REPO/data/signal_kelly_etf_freeze.json" >>"$LOG" 2>&1; then
  log "  ⚠ rsync 冻结表失败(网络/云上不可达?), 回测将可能触发「历史信号拒绝补冻」告警"
else
  cp -p "$REPO/data/signal_kelly_etf_freeze.json" "$TRADE/data/signal_kelly_etf_freeze.json" 2>>"$LOG" \
    && log "  ✓ 冻结表已 rsync 并双写: trade-data/data/ + trade/data/($(md5 -q "$REPO/data/signal_kelly_etf_freeze.json" | cut -c1-8))" \
    || log "  ⚠ 冻结表双写 trade/data/ 失败(不阻断, 回测读 trade-data 侧为权威)"
fi

# ---------- 步骤2.5: 刷新 board_etf_map.json(从新 DB 重新生成, 对齐 deploy.sh 项6/6.1) ----------
# 背景(2026-09-18 dev-sync 事故): export.py 的 track_score 唯一计算源 = board_etf_map.json(build 产物),
#   export 只读不重算。若跳过此步, export 读到旧 map(冻在旧 DB 日期) -> index 详情 etfs 与 R2 对不上
#   (37 条纯 ETF vs 45 条含 LOF, track_tier strong vs related)。
# 顺序对齐 deploy.sh 项6: gen_etf_index_map.py(build 输入) -> build_board_etf_map.py(写 data/) ->
#   cp 到 REPO/static-site/data/(前端 R2 上传源) + GIT_REPO/data/(双树单源, queries.py 读侧)。
# 本机 dev 刷新(非上线): gen/build 会调 akshare fund_etf_spot_em() 实时行情, 结果与云上同日 build 可能
#   有微小成交额差异(amount 字段), 属正常; 但 ETF 宇宙/成分/score/tier 由 DB 决定, 与 R2 对齐。
log "step2.5: build_board_etf_map(从新 DB 重新生成 map, 对齐生产顺序)"
cd "$TRADE"
log "  gen_etf_index_map.py(刷新 build 输入, 失败不阻断)"
"$PY" "$TRADE/scripts/gen_etf_index_map.py" >>"$LOG" 2>&1 || {
  log "  ⚠ gen_etf_index_map.py 失败(akshare 反爬/网络?), build 将走名称匹配兜底"
}
log "  build_board_etf_map.py(写 data/board_etf_map.json)"
"$PY" "$TRADE/scripts/build_board_etf_map.py" >>"$LOG" 2>&1
BUILD_RC=$?
if [ "$BUILD_RC" -ne 0 ]; then
  log "  FAIL: build_board_etf_map.py 失败(exit $BUILD_RC, 14 宽基校验未过/akshare 兜底失败), 终止(防静默旧 map)"
  exit "$BUILD_RC"
fi
log "  cp 到双树: REPO/static-site/data/ + GIT_REPO/data/(单源对齐)"
cp -p "$REPO/data/board_etf_map.json" "$REPO/static-site/data/board_etf_map.json" 2>>"$LOG" \
  && log "  ✓ board_etf_map.json 同步到 REPO/static-site/data/ (前端 R2 上传源)" \
  || log "  ⚠ 同步 REPO/static-site/data/ 失败(不阻断, export 仍用 data/ 新版)"
cp -p "$REPO/data/board_etf_map.json" "$TRADE/data/board_etf_map.json" 2>>"$LOG" \
  && log "  ✓ board_etf_map.json 同步到 GIT_REPO/data/ (双树单源)" \
  || log "  ⚠ 同步 GIT_REPO/data/ 失败(不阻断)"

# ---------- 步骤3: 本机 export 重算静态产物(EXPORT_SKIP_R2=1 不上传) ----------
log "step3: export 重算(EXPORT_SKIP_R2=1, 可能耗时几分钟)"
cd "$REPO"
if ! EXPORT_SKIP_R2=1 REPO="$REPO" "$PY" static-site/export.py >>"$LOG" 2>&1; then
  log "FAIL: export.py 执行失败(详见 $LOG)"
  exit 1
fi
log "  export done"

# ---------- 步骤4: 只读对账 R2(复用 upload_r2 通道表, 不 PUT, 8 线程并发 HEAD) ----------
log "step4: 只读对账 R2(verify-r2 只读版, 不 PUT 不上传, 8 线程并发)"
# 说明: 不直接调 upload_r2.py verify-r2 —— 原版发现不一致会"自动补传"(PUT 到 R2),
#       违反本任务「纯本地不上传」; 且原版用整文件字节 md5, 会把 generated_at/
#       written_at/exported_at 等时间戳字段差异误报为不一致。此处做归一化对账:
#       剔除时间戳字段后再比 md5, 只报告不修改。并发 HEAD 对齐 verify-r2 原版
#       (ThreadPoolExecutor 8 workers)。
# 对账范围 = 本次 export 真正重算的产物通道(index/industry/data-large)。
#   ⚠ 不含 all-data(r2_prefix=data 顶层 *.json) —— 该前缀混入大量「独立生成器产物」
#   (nextday_plan/auto_trade_steps/alert_analyze/signal_kelly_backtest/daily_brief/
#    summary 盘中实时快照/schedule_stats/news_digest 等), 非 export.py 重算, 本机
#   本次未跑对应生成器 -> 产物停在旧日期/为空; R2 侧是各自生成器不同时点产的最新
#   版, 对账必然 FAIL 且无意义(2026-09-18 主控定性: 对账范围过宽, 收窄)。
#   同样排除 fund-nav/etf-hist/accum-nav/lab/trade-sim/kelly-* 等独立生成器通道。
set +e
"$PY" - "$R2SYNC" <<'PYEOF' 2>>"$LOG" | tee -a "$LOG"
import json
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
os.environ.setdefault("REPO", "/Users/linhuichen/code/trade-data")
os.environ.setdefault("GIT_REPO", "/Users/linhuichen/code/trade")
import upload_r2 as ur

# 本次 export 重算的产物通道(export.py 写 static-site/data 顶层 + index/ + industry-*-indices/)
# ⚠ 只收窄 {index, industry, data-large}: all-data 混入独立生成器产物(见上注释), 不纳入。
TARGET_LABELS = {"index", "industry", "data-large"}

# 时间戳/元数据字段(剔除后再比 md5, 与 _kelly_parts_md5/_etf_hist_md5 同精神)
META_KEYS = {"generated_at", "written_at", "exported_at", "period_cutoffs", "buy_amount"}
BIG = 2 * 1024 * 1024  # >2MB 文件不下载 R2 做归一化二次判断(仅 HEAD 报告)
MAX_WORKERS = 8        # 对齐 verify-r2 原版并发度


def _norm_md5(payload: dict) -> str:
    """递归剔除 META_KEYS 后规范化序列化 md5。"""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in META_KEYS}
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o
    s = json.dumps(strip(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _check(f, r2_prefix, label, rel):
    """HEAD R2 + 必要时 GET 归一化对比。返回 (label, rel, kind, detail)。
    kind: OK(整文件一致) / META(仅元数据差异) / DIFF(真数据差异) / BIG(>2MB HEAD不一致) / GFAIL(R2 GET失败/404)。"""
    key = f"{r2_prefix}/{rel}"
    try:
        local_md5 = hashlib.md5(f.read_bytes()).hexdigest()
    except OSError:
        return (label, rel, "OK", "本地读失败跳过")
    _st, etag = ur.s3_head(key)
    if etag is not None and etag.strip('"') == local_md5:
        return (label, rel, "OK", "")
    # HEAD 不一致: 尝试二次判断(下载 R2 归一化对比)
    if f.stat().st_size > BIG:
        return (label, rel, "BIG", f"HEAD不一致且>2MB不下载, local_md5={local_md5} etag={etag or '404'}")
    _st2, body = ur.s3_request("GET", key)
    if _st2 != 200:
        return (label, rel, "GFAIL", f"R2 GET失败/{_st2}, local有R2无(缺传或新增)")
    try:
        local_payload = json.loads(f.read_text(encoding="utf-8"))
        r2_payload = json.loads(body.decode("utf-8"))
        if _norm_md5(local_payload) == _norm_md5(r2_payload):
            return (label, rel, "META", "仅元数据差异(剔除时间戳后一致)")
        return (label, rel, "DIFF", "真数据差异(剔除时间戳后仍不一致)")
    except (ValueError, OSError, UnicodeDecodeError):
        return (label, rel, "DIFF", f"解析失败(非JSON?), local_md5={local_md5} etag={etag or '404'}")


report = []
real_diff = 0
meta_only = 0
checked = 0
tasks = []

for ch in ur._R2_CHANNELS:
    label = ch["label"]
    if label not in TARGET_LABELS:
        continue  # 跳过独立生成器通道(本次未重算)
    local_dir = ch["local_dir"]()
    r2_prefix = ch["r2_prefix"]
    if not local_dir.exists():
        report.append(f"[{label}] 本地目录不存在 {local_dir}, 跳过")
        continue
    files = []
    for pat in ch["patterns"]:
        files.extend(local_dir.glob(pat))
    files = sorted(set(files))
    if ch.get("exclude_fn"):
        files = [f for f in files if not ch["exclude_fn"](f)]
    files = [f for f in files if f.exists()]
    if not files:
        report.append(f"[{label}] 无本地文件, 跳过")
        continue
    for f in files:
        rel = str(f.relative_to(local_dir))
        tasks.append((f, r2_prefix, label, rel))

# 并发 HEAD 对账(对齐 verify-r2 原版 8 线程)
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
    futures = [pool.submit(_check, *t) for t in tasks]
    for fut in as_completed(futures):
        label, rel, kind, detail = fut.result()
        checked += 1
        if kind == "OK":
            continue
        if kind == "META":
            meta_only += 1
        else:
            real_diff += 1
        report.append(f"[{label}] {rel}: {detail}")

print(f"[dev-sync verify] checked={checked}(含整文件一致项, 仅指数/行业/顶层产物通道)")
print(f"[dev-sync verify] 不一致项: meta_only={meta_only} real_diff={real_diff}")
for line in report:
    print(f"  {line}")
if real_diff:
    print("[dev-sync verify] RESULT: FAIL(存在真数据差异/缺传)")
    sys.exit(1)
print("[dev-sync verify] RESULT: PASS(仅元数据差异或全一致)")
PYEOF
RC=$?
set -e

if [ "$RC" -ne 0 ]; then
  log "FAIL: 对账发现真数据差异(exit $RC, 详见 $LOG)"
  exit "$RC"
fi
log "verify 对账 PASS(仅元数据差异或全一致)"

# ---------- 收尾 ----------
log "===== sync_dev_from_r2 完成(exit 0) ====="
echo "完成" >> /tmp/agent-progress-dev-sync.md
exit 0
