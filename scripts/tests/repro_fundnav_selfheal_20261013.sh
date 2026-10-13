#!/usr/bin/env bash
# repro_fundnav_selfheal_20261013.sh — nav_bucket「DB 领先产物」自愈(C1) + 第三口径治假绿(C2)
#                                   的端到端复现 / 负控脚本(**人工跑, 不进 CI**)。
#
# 与 pytest 的分工:
#   · scripts/tests/test_fundnav_selfheal_dbday_20261013.py  —— 进 CI 门禁 ⑧, 全桩化(快、零生产触达);
#   · 本脚本 —— 人工跑, 用**真 export_fund_nav.py + 真 check_fund_nav**(deploy 闸门同一函数),
#     在 tmp 沙箱里从「造 stale」到「自愈转 PASS」跑完整闭环, 作为 §23.2 负控证据。
#
# 沙箱隔离(硬保证, 脚本自检): 沙箱 scripts/app/.venv 全为真仓库的 symlink, 而 export_fund_nav.py
#   的 ROOT 由 `Path(__file__).absolute().parent.parent` 推导(刻意不 resolve symlink)⇒ 读写全部落在
#   沙箱 `$SB/` 内。脚本开跑即打印并断言 DB_PATH/STATIC_OUT 都在 $SB 下, 否则立即 abort(防误写真树)。
#
# 零外发 / 零生产触达(§18 L48):
#   · 不跑 deploy.sh、不上传 R2(FUNDNAV_SELFHEAL_ASYNC_UPLOAD=0)
#   · WITH_LOCK_NOTIFY_DRY_RUN=1(with_lock 排队超时告警只会打印不真发)
#   · 自愈脚本自身不含任何 notify 调用(见 C5 静态断言)
#
# 用法: bash scripts/tests/repro_fundnav_selfheal_20261013.sh
#   可选: KEEP=1 保留沙箱路径; SANDBOX=/path 指定沙箱目录
set -u

REAL_REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SB="${SANDBOX:-$(mktemp -d -t fundnav-selfheal)}"
mkdir -p "$SB"
LOG="$SB/repro.log"
FAILED=0

# venv 定位: worktree 内无 .venv(untracked 不进 worktree) -> 走主仓库(主 .git 所在树)的 venv。
# 复用同一 venv 保证依赖一致; 可用 PY=... 覆盖。
if [ -z "${PY:-}" ]; then
  GCD="$(git -C "$REAL_REPO" rev-parse --git-common-dir 2>/dev/null || true)"
  case "$GCD" in ""|/*) ;; *) GCD="$REAL_REPO/$GCD" ;; esac
  MAIN_REPO="$(dirname "$GCD")"
  for cand in "$REAL_REPO/.venv" "$MAIN_REPO/.venv" /Users/linhuichen/code/trade/.venv; do
    if [ -x "$cand/bin/python" ]; then PY="$cand/bin/python"; VENV_ROOT="$cand"; break; fi
  done
fi
: "${PY:?未找到可用 venv python(可用 PY=/path/to/.venv/bin/python 指定)}"
VENV_ROOT="${VENV_ROOT:-$(dirname "$(dirname "$PY")")}"
echo "  PY=$PY"

pass() { echo "  ✓ $1" | tee -a "$LOG"; }
fail() { echo "  ✗ $1" | tee -a "$LOG"; FAILED=$((FAILED + 1)); }

echo "=== repro_fundnav_selfheal_20261013 开始 $(date '+%F %T') ===" | tee "$LOG"
echo "  REAL_REPO=$REAL_REPO" | tee -a "$LOG"
echo "  SANDBOX=$SB" | tee -a "$LOG"

# ── 沙箱搭建(真仓库 symlink, 数据全造)────────────────────────────────────────────
mkdir -p "$SB/data" "$SB/static-site/data"
ln -sfn "$REAL_REPO/scripts" "$SB/scripts"
ln -sfn "$REAL_REPO/app" "$SB/app"
ln -sfn "$VENV_ROOT" "$SB/.venv"
ln -sfn "$REAL_REPO/config" "$SB/config" 2>/dev/null || true

export REPO="$SB"
export GIT_REPO="$SB"
export FUNDNAV_SELFHEAL_ASYNC_UPLOAD=0        # 零 R2
export FUNDNAV_SELFHEAL_LOCK="$SB/selfheal.lock"
export FUNDNAV_SELFHEAL_NOW=1200              # 固定非窗口时刻(免真实时钟落 17:25-18:35)
export FUNDNAV_SELFHEAL_TIMEOUT=600
export WITH_LOCK_NOTIFY_DRY_RUN=1             # §18 L48

# ── 沙箱路径自证(防误写真树)────────────────────────────────────────────────────
echo "[0] 沙箱路径自证" | tee -a "$LOG"
PATHS=$("$PY" - <<PY 2>&1
import sys
sys.path.insert(0, "$SB/scripts")
sys.path.insert(0, "$SB")
from app.collector.public_fund import DB_PATH, STATIC_DATA_DIR
print(DB_PATH)
print(STATIC_DATA_DIR)
PY
)
DB_PATH_PRINTED=$(printf '%s' "$PATHS" | sed -n '1p')
STATIC_PRINTED=$(printf '%s' "$PATHS" | sed -n '2p')
echo "  DB_PATH=$DB_PATH_PRINTED  STATIC_DATA_DIR=$STATIC_PRINTED" | tee -a "$LOG"
case "$DB_PATH_PRINTED" in "$SB"/*) pass "DB_PATH 落在沙箱内" ;; *) fail "DB_PATH 不在沙箱(可能误写真树): $DB_PATH_PRINTED"; exit 9 ;; esac
case "$STATIC_PRINTED" in "$SB"/*) pass "STATIC_DATA_DIR 落在沙箱内" ;; *) fail "STATIC_DATA_DIR 不在沙箱: $STATIC_PRINTED"; exit 9 ;; esac

# ── fixture: 3 只基金, mode 控制 DB 状态 ────────────────────────────────────────
#   old  = 仅 D0 有净值(产物与 DB 同源一致 -> 正常态)
#   new  = D0 + D1 均有净值(D1 更近; 若产物未重出 = 「DB 领先产物」病灶)
#   null = D0 有值 + D1 整列 NULL(源 DB 整日破损, 治假绿负控)
mkfix() {  # $1=mode(old|new|null)
  "$PY" - "$SB/data/public_fund.db" "$1" <<'PY'
import sqlite3, sys
db, mode = sys.argv[1], sys.argv[2]
d0, d1 = "20260930", "20261012"      # d1 更近
codes = [("000001", "华夏成长混合"), ("110011", "易方达中小盘"), ("519066", "汇添富蓝筹")]
conn = sqlite3.connect(db)
conn.execute("DROP TABLE IF EXISTS fund_daily_nav")
conn.execute("CREATE TABLE fund_daily_nav (date TEXT NOT NULL, fund_code TEXT NOT NULL, "
             "fund_name TEXT, unit_nav REAL, acc_nav REAL, PRIMARY KEY (date, fund_code))")
rows = [(d0, c, n, 1.00, 2.00) for c, n in codes]
if mode == "new":
    rows += [(d1, c, n, 1.10, 2.10) for c, n in codes]
elif mode == "null":
    rows += [(d1, c, n, None, None) for c, n in codes]
conn.executemany("INSERT INTO fund_daily_nav (date, fund_code, fund_name, unit_nav, acc_nav) "
                 "VALUES (?,?,?,?,?)", rows)
conn.commit(); conn.close()
print(f"fixture mode={mode}: {len(rows)} 行")
PY
}

check_fund_nav_rc() {  # 直接调 deploy 闸门同一函数(含 _deploy_mode 收紧), 首行打印 status
  "$PY" - "$REAL_REPO/scripts/check_data_integrity.py" "$SB/static-site/data" <<'PY'
import sys, pathlib, importlib.util
spec = importlib.util.spec_from_file_location("cdi", sys.argv[1])
m = importlib.util.module_from_spec(spec)
sys.modules["cdi"] = m
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
m._deploy_mode = True   # 复刻 deploy 闸门阈值(覆盖率 <98% FAIL 等)
r = m.check_fund_nav(pathlib.Path(sys.argv[2]))
print(str(r.status))          # "ok" / "warn" / "fail"
print(r.msg[:300])
PY
}
status_of() { printf '%s' "$1" | sed -n '1p'; }

echo | tee -a "$LOG"
echo "[1] 构造正常态 → 真 export → 校验应 PASS(负控前置: 不构造时不许误触发)" | tee -a "$LOG"
mkfix old >>"$LOG" 2>&1
"$PY" "$SB/scripts/export_fund_nav.py" >>"$LOG" 2>&1 || fail "真 export 失败"
OUT=$(check_fund_nav_rc)
echo "  check: $(printf '%s' "$OUT" | tr '\n' ' ')" | tee -a "$LOG"
case "$(status_of "$OUT")" in ok) pass "正常态校验 OK" ;; *) fail "正常态应 OK 实际: $OUT" ;; esac
PROBE=$("$PY" "$SB/scripts/check_data_integrity.py" --fundnav-stale-probe --data-dir "$SB/static-site/data" 2>&1) || true
echo "  probe: $PROBE" | tee -a "$LOG"
case "$PROBE" in *"rc=0"*) pass "正常态探针 rc=0(不会误触发重出)" ;; *) fail "正常态探针应 rc=0: $PROBE" ;; esac

echo | tee -a "$LOG"
echo "[2] 复现病灶: DB 新增更近净值(产物未重出)→ 应判 FAIL(DB 领先产物)" | tee -a "$LOG"
mkfix new >>"$LOG" 2>&1
OUT=$(check_fund_nav_rc)
echo "  check: $(printf '%s' "$OUT" | tr '\n' ' ')" | tee -a "$LOG"
case "$(status_of "$OUT")" in ok) fail "应 FAIL(DB 领先产物) 实际 OK" ;; *) pass "已复现 FAIL($(status_of "$OUT"))" ;; esac
PROBE=$("$PY" "$SB/scripts/check_data_integrity.py" --fundnav-stale-probe --data-dir "$SB/static-site/data" 2>&1) || true
echo "  probe: $PROBE" | tee -a "$LOG"
case "$PROBE" in *"rc=3"*) pass "探针命中 rc=3" ;; *) fail "探针应 rc=3: $PROBE" ;; esac

echo | tee -a "$LOG"
echo "[3] 跑自愈(真 export + 互斥)→ 应 exit 0 且产物重出 → 校验转 PASS" | tee -a "$LOG"
bash "$SB/scripts/fund_nav_selfheal.sh" >>"$LOG" 2>&1
HEAL_RC=$?
echo "  selfheal exit=$HEAL_RC" | tee -a "$LOG"
if [ "$HEAL_RC" -eq 0 ]; then pass "自愈 exit=0"; else fail "自愈应 exit 0 实际 $HEAL_RC"; fi
OUT=$(check_fund_nav_rc)
echo "  check-after: $(printf '%s' "$OUT" | tr '\n' ' ')" | tee -a "$LOG"
case "$(status_of "$OUT")" in ok) pass "自愈后校验 PASS(闭环)" ;; *) fail "自愈后应 OK 实际: $OUT" ;; esac

echo | tee -a "$LOG"
echo "[4] C2 负控: DB 最新显著日 unit_nav 整列 NULL → 应 FAIL(修前同源比对会假绿)" | tee -a "$LOG"
"$PY" - "$SB/data/public_fund.db" <<'PY' >>"$LOG" 2>&1
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("DROP TABLE IF EXISTS fund_daily_nav")
conn.execute("CREATE TABLE fund_daily_nav (date TEXT NOT NULL, fund_code TEXT NOT NULL, "
             "fund_name TEXT, unit_nav REAL, acc_nav REAL, PRIMARY KEY (date, fund_code))")
rows = []
for i in range(1200):                        # 1200 行 >= FUND_NAV_DBDAY_MIN_ROWS(1000) -> "显著交易日"
    c = f"{i:06d}"
    rows.append(("20260930", c, f"基金{c}", 1.00, 2.00))
    rows.append(("20261012", c, f"基金{c}", None, None))   # 最新日整列 NULL
conn.executemany("INSERT INTO fund_daily_nav (date, fund_code, fund_name, unit_nav, acc_nav) "
                 "VALUES (?,?,?,?,?)", rows)
conn.commit(); conn.close()
print(f"fixture ok: {len(rows)} 行(最新日 {1200} 行 unit_nav 全 NULL)")
PY
"$PY" "$SB/scripts/export_fund_nav.py" >>"$LOG" 2>&1 || fail "export 失败(C2 fixture)"
OUT=$(check_fund_nav_rc)
echo "  check: $(printf '%s' "$OUT" | tr '\n' ' ')" | tee -a "$LOG"
case "$(status_of "$OUT")" in ok) fail "C2 应 FAIL 实际 OK(假绿未治)" ;; *) pass "C2 已 FAIL(第三口径生效)" ;; esac
# 同时证「同源比对本身看不出问题」: 探针/抽样侧无 DB 领先信号(假绿机理)
PROBE=$("$PY" "$SB/scripts/check_data_integrity.py" --fundnav-stale-probe --data-dir "$SB/static-site/data" 2>&1) || true
echo "  probe: $PROBE" | tee -a "$LOG"
case "$PROBE" in *"rc=0"*) pass "同源侧无领先信号(rc=0)—— 正是修前假绿机理, 现由第三口径拦下" ;; *) echo "  (注: probe=$(printf '%s' "$PROBE"))" | tee -a "$LOG" ;; esac

echo | tee -a "$LOG"
echo "=== 结果: FAILED=$FAILED ===" | tee -a "$LOG"
if [ "$KEEP" = "1" ]; then echo "  沙箱保留: $SB"; else rm -rf "$SB"; fi
[ "$FAILED" -eq 0 ] && { echo "ALLPASS"; exit 0; } || { echo "HASFAIL"; exit 1; }