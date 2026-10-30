#!/usr/bin/env python3
"""#324/#338 备份恢复演练补齐 — verify_backup.sh 行为测试（2026-10-28）。

被测 = scripts/verify_backup.sh（唯一改动文件）。本用例**零网络/零真下载/零真外发**：
  - REPO 指向临时目录，其 `.venv/bin/python` 是测试替身（stub 驱动），拦截
    `upload_r2.py list/download-db`、`docs/scripts/restore_r2_db_backup.py`、`notify.py`；
    只有脚本内嵌的校验 python 块（`$PY -` 标准输入）转交真解释器执行。
  - `date` / `sleep` 也走替身：`date +%u` 返回注入的星期（不写死真实 today，防 L51 跨天红），
    `sleep` 立即返回（避免用例真等 60s 重试窗口）。所有用例日期基准取自运行时 today，
    不出现写死日期字面量。
  - notify 替身只把参数写进临时日志文件，断言"该发/不该发"；`VERIFY_NOTIFY_DRY_RUN=1` 双保险。

覆盖的判定点：
  1. 源码形状：stock_daily 存在性预判 / public_fund 走 restore 脚本 6 线程 / trap 清理 PF 目录
  2. 无 stock_daily 备份 ⇒ SKIP 且不发 severe（#338 设计内过渡态）
  3. public_fund 空间不足 ⇒ SKIP 且发 severe（安全网被关要人处理）
  4. 周日门控：`date +%u`=7 进入 / 非 7 SKIP
  5. 行数三态：备份空 / 备份>本地 / 备份 < 本地×0.95
  6. 三态结论行点名 SKIP，且 SKIP 不把 VERIFY_OK 置 0（运行日冻结在首备日前，防 L51 跨天红）
  7. 新鲜度：备份日期落后 >1 天 ⇒ FAIL
  8. 变异 ≥2：去掉存在性预判 / 空间分支改成不拦，验证用例 2、3 真有判别力
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_backup.sh"
REPO_PATHS_LIB = REPO_ROOT / "scripts" / "lib" / "repo_paths.sh"

# stock_daily 首份备份 2026-10-29 21:00 才产生（backup_db.sh:82 首次含该库）；过了次日仍无 key ⇒ FAIL。
# 这两个是业务日期字面量（不是"今天"），用 fake date 注入，防 L51 跨天红。
BEFORE_FIRST_BACKUP = "20261029"   # 首备日当天：尚无 key 属设计内过渡态
FIRST_BACKUP_DEADLINE = "20261030"  # 首备日之后：仍无 key ⇒ 备份链断了，必须 FAIL

SENT_TABLES = ["score_daily", "daily_metric", "signal_daily", "index_daily",
               "industry_width_daily", "futures_position", "futures_accuracy", "collect_log"]
ETF_TABLES = ["etf_daily", "etf_signal", "etf_holder_quarterly", "national_team_holders"]
STOCK_TABLES = ["baostock_daily_raw", "fapi_daily_raw", "mootdx_daily_raw"]
PF_TABLES = ["fund_daily_nav", "fund_purchase_status", "fund_performance",
             "fund_rating", "fund_basic"]
ALL_TABLES = {
    "sentiment": SENT_TABLES,
    "etf_national_team": ETF_TABLES,
    "stock_daily": STOCK_TABLES,
    "public_fund": PF_TABLES,
}

STUB_PY = r"""#!/bin/bash
# 测试替身：拦截外部脚本调用；`-`（脚本内嵌校验块）交给真 python。
if [ "$1" = "-" ]; then
  case "$2" in
    *upload_r2.py)
      # 台账 HEAD 对账：参数是完整 key（含 "/"），输出 status|Content-Length
      case "$3" in
        */*) echo "${STUB_HEAD_STATUS:-200}|${STUB_HEAD_LEN:-0}"; exit 0 ;;
      esac
      # 存在性预判：输出 NONE / 最新日期 / ERR（复刻库里 _list_keys 的语义）
      name="$3"
      if [ "${STUB_LIST_FAIL:-0}" = "1" ]; then echo "ERR"; exit 0; fi
      grep -q '<Key>' "$STUB_LIST_DIR/$name.xml" 2>/dev/null || { echo "NONE"; exit 0; }
      grep -oE '[0-9]{8}\.db(\.gz)?' "$STUB_LIST_DIR/$name.xml" | sed 's/\.db.*//' | sort -r | head -1
      exit 0
      ;;
    *) exec "$REAL_PY" "$@" ;;
  esac
fi
case "$(basename "$1")" in
  upload_r2.py)
    cmd="$2"
    if [ "$cmd" = "download-db" ]; then
      name="$3"; outdir="$4"
      # 复刻 upload_r2.py:3462-3463 行为：无 key 时 exit 非零
      grep -q '<Key>' "$STUB_LIST_DIR/$name.xml" 2>/dev/null || { echo "无 $name 备份 key in signal-backup2/backup/${name}_*" >&2; exit 1; }
      mkdir -p "$outdir" || exit 1
      cp "$STUB_BAK_DIR/$name.db" "$outdir/${name}_${STUB_DB_DATE}.db" || exit 1
      echo "$outdir/${name}_${STUB_DB_DATE}.db"
      exit 0
    fi
    ;;
  restore_r2_db_backup.py)
    outdir=""
    while [ $# -gt 0 ]; do
      case "$1" in --out-dir) outdir="$2"; shift 2;; *) shift;; esac
    done
    printf 'called' > "$STUB_MARK_RESTORE"
    mkdir -p "$outdir" || exit 1
    if [ "${STUB_RESTORE_FAIL:-0}" = "1" ]; then
      echo '{"ok": false, "error": "stub"}'; echo "RESTORE FAIL"; exit 1
    fi
    cp "$STUB_BAK_DIR/public_fund.db" "$outdir/public_fund_${STUB_DB_DATE}.db" || exit 1
    echo '{"ok": true}'
    echo "RESTORE PASS"
    echo "$outdir/public_fund_${STUB_DB_DATE}.db"
    exit 0
    ;;
  notify.py)
    printf '%s\n' "$@" >> "$STUB_NOTIFY_LOG"
    echo "[stub notify] $*"
    exit 0
    ;;
esac
echo "STUB: 未识别的调用 $*" >&2
exit 98
"""

STUB_DATE = r"""#!/bin/bash
if [ "$1" = "+%u" ]; then echo "$STUB_DOW"; exit 0; fi
if [ "$1" = "+%Y%m%d" ]; then echo "$STUB_TODAY"; exit 0; fi
exec /bin/date "$@"
"""

STUB_SLEEP = r"""#!/bin/bash
printf '%s\n' "$*" >> "$STUB_SLEEP_LOG"
exit 0
"""

STUB_DF = r"""#!/bin/bash
# df -Pk → 固定可用空间(KiB)，用例不依赖本机磁盘余量（否则某台机器剩得少就红）
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "/dev/stub 99999999 0 ${STUB_AVAIL_KB:-99999999} 0% /"
"""


def _mkdb(path: Path, tables, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        for t in tables:
            con.execute(f'CREATE TABLE "{t}" (x INTEGER)')
            con.executemany(f'INSERT INTO "{t}" VALUES (?)', [(i,) for i in range(rows)])
        con.commit()
    finally:
        con.close()


def _write_exec(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Drill:
    """一套完整的测试沙箱：假 REPO + 替身 python + 假 date/sleep。"""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.repo = tmp_path / "repo"
        self.bak = tmp_path / "bak"
        self.lists = tmp_path / "lists"
        self.bin = tmp_path / "bin"
        self.notify_log = tmp_path / "notify.log"
        self.sleep_log = tmp_path / "sleep.log"
        self.restore_mark = tmp_path / "restore.called"
        for d in (self.repo / "data", self.bak, self.lists, self.bin):
            d.mkdir(parents=True, exist_ok=True)
        # 日期全部取自运行时 today（不写死日期字面量，防 L51 跨天红）；运行日可通过
        # STUB_TODAY 注入，用于验证"隔天仍绿"。
        self.base_date = datetime.date.today()
        self.today = self.base_date.strftime("%Y%m%d")
        self.stub_db_date = self.today
        # 本地活库 + 备份库（默认行数一致 ⇒ 通过）
        for name, tables in ALL_TABLES.items():
            _mkdb(self.repo / "data" / f"{name}.db", tables, 100)
            _mkdb(self.bak / f"{name}.db", tables, 100)
            self.set_list_keys(name, [self.stub_db_date])
        _write_exec(self.repo / ".venv" / "bin" / "python", STUB_PY)
        (self.repo / "scripts").mkdir(parents=True, exist_ok=True)
        (self.repo / "scripts" / "upload_r2.py").write_text("# stub（被替身 python 拦截，永不执行）\n")
        (self.repo / "scripts" / "notify.py").write_text("# stub（被替身 python 拦截，永不真发）\n")
        _write_exec(self.bin / "date", STUB_DATE)
        _write_exec(self.bin / "sleep", STUB_SLEEP)
        _write_exec(self.bin / "df", STUB_DF)

    def set_list_keys(self, name: str, dates) -> None:
        keys = "".join(f"<Key>backup/{name}_{d}.db.gz</Key>" for d in dates)
        body = f"<ListBucketResult>{keys}</ListBucketResult>" if keys else "<ListBucketResult></ListBucketResult>"
        (self.lists / f"{name}.xml").write_text(body)

    def set_ledger(self, *, date: str, gz_size: int, key: str | None = None) -> None:
        """写 public_fund 上传台账（复刻 upload_r2.py:3304-3310 的字段形状）。"""
        (self.repo / "data" / ".r2_db_backup_state.json").write_text(json.dumps({
            "public_fund.db": {
                "size": 1, "mtime_ns": 2, "date": date,
                "key": key or f"backup/public_fund_{date}.db.gz",
                "gz_size": gz_size,
            }
        }))

    def set_rows(self, name: str, *, local: int | None = None, backup: int | None = None) -> None:
        if local is not None:
            _mkdb(self.repo / "data" / f"{name}.db", ALL_TABLES[name], local)
        if backup is not None:
            _mkdb(self.bak / f"{name}.db", ALL_TABLES[name], backup)

    def run(self, *, dow: int = 7, mode: str = "auto", min_kb: str = "1",
            script: Path | None = None, extra_env: dict | None = None):
        env = {
            "PATH": f"{self.bin}:{os.environ.get('PATH', '')}",
            "HOME": os.environ.get("HOME", str(self.root)),
            "TMPDIR": str(self.root / "tmp"),
            "REPO": str(self.repo),
            "GIT_REPO": str(REPO_ROOT),
            "REAL_PY": os.sys.executable,
            "STUB_BAK_DIR": str(self.bak),
            "STUB_LIST_DIR": str(self.lists),
            "STUB_DB_DATE": self.stub_db_date,
            "STUB_TODAY": self.today,
            "STUB_DOW": str(dow),
            "STUB_MARK_RESTORE": str(self.restore_mark),
            "STUB_NOTIFY_LOG": str(self.notify_log),
            "STUB_SLEEP_LOG": str(self.sleep_log),
            "STUB_RESTORE_FAIL": "0",
            "STUB_HEAD_STATUS": "200",
            "STUB_HEAD_LEN": "0",
            "STUB_AVAIL_KB": "99999999",
            "VERIFY_PUBLIC_FUND": mode,
            "VERIFY_PUBLIC_FUND_MIN_KB": min_kb,
            "VERIFY_NOTIFY_DRY_RUN": "1",
        }
        if extra_env:
            env.update(extra_env)
        (self.root / "tmp").mkdir(exist_ok=True)
        r = subprocess.run(
            ["bash", str(script or SCRIPT)], env=env,
            capture_output=True, text=True, timeout=120,
        )
        return r

    @property
    def notified(self) -> str:
        return self.notify_log.read_text() if self.notify_log.exists() else ""

    @property
    def restore_called(self) -> bool:
        return self.restore_mark.exists()


# ---------------------------------------------------------------- 1. 源码形状
def test_source_shape_declares_stock_daily_and_public_fund_drill():
    src = SCRIPT.read_text()
    # A1 stock_daily 走 download-db，且下载前有存在性预判（#338）
    assert "download-db stock_daily" in src
    assert "r2_latest_backup_date stock_daily" in src
    # 无 key 不许永久静默：过首备日仍无 key ⇒ FAIL（日期闸，TODAY 由 date 注入，不写死今天）
    assert '"$TODAY" -ge 20261030' in src
    assert "FAIL(无 stock_daily 备份,已过首备日)" in src
    # 非数字空间门限不许 fail-open
    assert "*[!0-9]*" in src and "回落默认 4718592" in src
    # 存在性预判必须查备份桶（upload_r2.py list 子命令默认 signal-data，查错桶=假 SKIP）
    assert "._list_keys(" in src and "BACKUP_BUCKET" in src
    assert '"status=200"' not in src
    # A5 public_fund 走流式还原脚本 + 6 线程 + 显式 REPO/GIT_REPO
    assert "restore_r2_db_backup.py" in src
    assert "--name public_fund" in src
    assert "--threads 6" in src
    assert 'REPO="$REPO" GIT_REPO="$GIT_REPO"' in src
    # trap 清理 public_fund 输出目录（restore 脚本不自动删输出）
    assert 'trap \'rm -rf "$PF_DIR" "$TMPDIR"\' EXIT' in src
    # A 断言④：台账 ↔ HEAD Content-Length 对账（public_fund）
    assert ".r2_db_backup_state.json" in src
    assert "s3_head(" in src
    assert "with_len=True" in src
    # 三态结论：跳过项必须点名、首行 VERIFY_OK 语义不变
    assert "跳过: " in src
    assert 'print(f"VERIFY_OK={overall_ok}")' in src


# ---------------------------------------------------------------- 2. stock_daily SKIP
def test_stock_daily_absent_skips_without_severe(tmp_path):
    drill = Drill(tmp_path)
    drill.set_list_keys("stock_daily", [])          # R2 上零对象（2026-10-28 现实状态）
    # 冻结到首备日之前（L51：不许靠"跑的那天恰好还没到阈值"才绿，否则 10-30 起定红）
    r = drill.run(dow=3, extra_env={"STUB_TODAY": BEFORE_FIRST_BACKUP})  # 非周日：public_fund 也 SKIP
    assert r.returncode == 0, f"SKIP 不该失败: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "SKIP(尚无 stock_daily 备份)" in r.stdout
    assert "跳过" in r.stdout and "stock_daily=" in r.stdout
    assert "✗ 下载失败" not in r.stdout
    assert drill.notified == "", f"设计内 SKIP 不许告警，实际发了:\n{drill.notified}"


# ---------------------------------------------------------------- 3. 空间不足 SKIP + severe
def test_stock_daily_list_failure_is_fail_not_skip(tmp_path):
    """LIST 失败 ≠ 没有备份：不许把"看不见"当成设计内 SKIP（假绿）。"""
    drill = Drill(tmp_path)
    r = drill.run(dow=3, extra_env={"STUB_LIST_FAIL": "1"})
    assert r.returncode == 1, f"LIST 失败必须 FAIL: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "✗ stock_daily R2 LIST 失败" in r.stdout
    assert "SKIP(尚无 stock_daily 备份)" not in r.stdout
    assert "--severe" in drill.notified


def test_stock_daily_absent_after_deadline_fails_with_severe(tmp_path):
    """首备日之后仍无 key ⇒ FAIL + severe（否则"永久缺失"会一路静默 rc=0）。"""
    drill = Drill(tmp_path)
    drill.set_list_keys("stock_daily", [])
    r = drill.run(dow=3, extra_env={"STUB_TODAY": FIRST_BACKUP_DEADLINE})
    assert r.returncode == 1, f"过首备日无备份必须 FAIL: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "FAIL(无 stock_daily 备份,已过首备日)" in r.stdout
    assert "✗ 失败" in r.stdout                  # 结论行翻成失败
    assert "--severe" in drill.notified


def test_stock_daily_date_gate_is_not_today_hardcoded(tmp_path):
    """运行日往后平移一天：有 key 时仍绿（门槛只惩罚"过了首备日还一个 key 都没有"）。"""
    drill = Drill(tmp_path)                       # 默认各库都有 key
    tomorrow = (drill.base_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
    r = drill.run(dow=3, extra_env={"STUB_TODAY": tomorrow})
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "FAIL(无 stock_daily 备份" not in r.stdout
    assert "stock_daily: 最新备份" in r.stdout     # 新鲜度行仍参与且为 OK


def test_pf_space_insufficient_skips_and_notifies_severe(tmp_path):
    drill = Drill(tmp_path)
    r = drill.run(dow=7, mode="1", min_kb=str(10 ** 12))   # 门限 1e12KiB：必然"空间不足"
    assert r.returncode == 0, f"空间不足是 SKIP 不是 FAIL: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "SKIP(空间不足" in r.stdout
    assert not drill.restore_called, "空间不足时不该启动大库还原"
    assert "--severe" in drill.notified, f"空间不足必须发 severe（安全网被关）:\n{drill.notified}"


def test_invalid_min_kb_falls_back_to_default(tmp_path):
    """非数字门限会让 [ -lt ] 报错后判 false ⇒ 门开(fail-open)。必须显式回落默认值。"""
    drill = Drill(tmp_path)
    r = drill.run(dow=7, mode="1", min_kb="abc")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "VERIFY_PUBLIC_FUND_MIN_KB='abc' 非法(需整数 KiB)，回落默认 4718592" in r.stderr
    assert drill.restore_called, "回落默认值后应按空间正常放行（不是直接关掉演练）"


# ---------------------------------------------------------------- 4. 周日门控
def test_sunday_gate_enters_drill(tmp_path):
    drill = Drill(tmp_path)
    r = drill.run(dow=7, mode="auto")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert drill.restore_called, "周日(auto)必须进入 public_fund 演练"
    assert "已覆盖: sentiment,etf_national_team,stock_daily,public_fund" in r.stdout


def test_non_sunday_gate_skips_drill(tmp_path):
    drill = Drill(tmp_path)
    r = drill.run(dow=5, mode="auto")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert not drill.restore_called, "非周日(auto)不许拉起 2.76GiB 大库还原"
    assert "SKIP(周频未到:非周日)" in r.stdout
    assert "public_fund=SKIP(周频未到:非周日)" in r.stdout


def test_public_fund_gate_can_be_disabled(tmp_path):
    drill = Drill(tmp_path)
    r = drill.run(dow=7, mode="0")
    assert r.returncode == 0
    assert not drill.restore_called
    assert "SKIP(已关闭 VERIFY_PUBLIC_FUND=0)" in r.stdout


# ---------------------------------------------------------------- 5. 行数三态
def test_rowcount_backup_empty_fails(tmp_path):
    drill = Drill(tmp_path)
    drill.set_rows("stock_daily", backup=0)          # 本地 100 > 0
    r = drill.run(dow=3)
    assert r.returncode == 1, f"{r.stdout}\n{r.stderr}"
    assert "✗FAIL 备份空" in r.stdout
    assert "--severe" in drill.notified


def test_rowcount_backup_gt_local_fails(tmp_path):
    drill = Drill(tmp_path)
    drill.set_rows("stock_daily", backup=120)        # 备份 > 本地 = 本地丢数据
    r = drill.run(dow=3)
    assert r.returncode == 1, f"{r.stdout}\n{r.stderr}"
    assert "✗FAIL 本地丢数据" in r.stdout
    assert "--severe" in drill.notified


def test_public_fund_below_ratio_fails(tmp_path):
    drill = Drill(tmp_path)
    drill.set_rows("public_fund", backup=90)         # 90 < 100×0.95 ⇒ 备份过旧/被截断
    r = drill.run(dow=7, mode="1")
    assert r.returncode == 1, f"{r.stdout}\n{r.stderr}"
    assert "✗FAIL 备份过旧/被截断" in r.stdout
    assert "--severe" in drill.notified


def test_public_fund_within_ratio_passes(tmp_path):
    drill = Drill(tmp_path)
    drill.set_rows("public_fund", backup=96)         # 96 ≥ 100×0.95 ⇒ 日增容忍范围内通过
    r = drill.run(dow=7, mode="1")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "✗FAIL" not in r.stdout
    assert drill.notified == ""


def test_public_fund_ratio_boundary_exactly_095_passes(tmp_path):
    drill = Drill(tmp_path)
    drill.set_rows("public_fund", backup=95)         # 恰好 95% ⇒ 不 <本地×0.95 ⇒ 通过
    r = drill.run(dow=7, mode="1")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "✗FAIL" not in r.stdout


def test_restore_failure_is_fail_with_severe(tmp_path):
    drill = Drill(tmp_path)
    r = drill.run(dow=7, mode="1", extra_env={"STUB_RESTORE_FAIL": "1"})
    assert r.returncode == 1, f"restore 失败必须 FAIL: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "✗ public_fund: restore_r2_db_backup.py 失败" in r.stdout
    assert "public_fund=FAIL(restore rc=1)" in r.stdout
    assert "--severe" in drill.notified


# ------------------------------------------------- 5d. 台账 ↔ HEAD 长度对账（断言④）
def test_ledger_head_length_matches_passes(tmp_path):
    drill = Drill(tmp_path)
    drill.set_ledger(date=drill.today, gz_size=123456)
    r = drill.run(dow=7, mode="1", extra_env={"STUB_HEAD_LEN": "123456"})
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "台账 HEAD 对账: OK(" in r.stdout
    assert "长度 123456 == 台账 gz_size" in r.stdout


def test_ledger_head_length_mismatch_fails(tmp_path):
    drill = Drill(tmp_path)
    drill.set_ledger(date=drill.today, gz_size=123456)
    r = drill.run(dow=7, mode="1", extra_env={"STUB_HEAD_LEN": "999"})
    assert r.returncode == 1, f"长度不一致必须 FAIL: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "FAIL(HEAD 长度 999 != 台账 gz_size 123456)" in r.stdout
    assert "public_fund=FAIL(台账 HEAD 对账" in r.stdout
    assert "--severe" in drill.notified


def test_ledger_date_mismatch_skips_and_names_it(tmp_path):
    drill = Drill(tmp_path)
    old = (drill.base_date - datetime.timedelta(days=1)).strftime("%Y%m%d")
    drill.set_ledger(date=old, gz_size=123456)
    r = drill.run(dow=7, mode="1", extra_env={"STUB_HEAD_LEN": "123456"})
    assert r.returncode == 0, f"前提不成立是 SKIP 不是 FAIL: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert f"SKIP(台账日期 {old} != 最新 key 日期 {drill.today})" in r.stdout
    assert f"public_fund_ledger=SKIP(台账日期 {old}" in r.stdout   # 结论行点名，不留假绿


def test_ledger_head_http_error_fails(tmp_path):
    drill = Drill(tmp_path)
    drill.set_ledger(date=drill.today, gz_size=123456)
    r = drill.run(dow=7, mode="1",
                  extra_env={"STUB_HEAD_STATUS": "500", "STUB_HEAD_LEN": "123456"})
    assert r.returncode == 1, f"HEAD 失败不许当通过: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "FAIL(HEAD backup/public_fund_" in r.stdout and "status=500" in r.stdout


# ---------------------------------------------------------------- 6. 三态结论行
def test_conclusion_names_skips_and_keeps_verify_ok(tmp_path):
    drill = Drill(tmp_path)
    drill.set_list_keys("stock_daily", [])
    # 本用例要的是「stock_daily 无 key ⇒ SKIP」这一态，而该态只在首备日之前成立；
    # 不冻结运行日的话，2026-10-30 起日期闸会把 SKIP 翻成 FAIL，用例随真实日历翻红（L51）。
    # 这里不能靠"补一份 stock_daily 备份"来脱敏——那会直接消灭被测的 SKIP 项。
    r = drill.run(dow=3, extra_env={"STUB_TODAY": BEFORE_FIRST_BACKUP})
    lines = r.stdout.splitlines()
    ok_lines = [ln for ln in lines if ln.startswith("VERIFY_OK=")]
    assert ok_lines == ["VERIFY_OK=1"], f"SKIP 不该把 VERIFY_OK 置 0: {ok_lines}\n{r.stdout}"
    concl = [ln for ln in r.stdout.splitlines() if "=== 结论" in ln]
    assert len(concl) == 1, r.stdout
    assert "跳过: " in concl[0], f"结论行必须点名跳过项(防 L49 假绿): {concl[0]}"
    assert "stock_daily=SKIP(尚无 stock_daily 备份)" in concl[0]
    assert "public_fund=SKIP(周频未到:非周日)" in concl[0]
    assert "全 ok" not in concl[0]


# ---------------------------------------------------------------- 7. 新鲜度
def test_stale_backup_date_fails(tmp_path):
    drill = Drill(tmp_path)
    stale = (datetime.date.today() - datetime.timedelta(days=3)).strftime("%Y%m%d")
    drill.stub_db_date = stale
    drill.set_list_keys("stock_daily", [stale])
    r = drill.run(dow=3)
    assert r.returncode == 1, f"备份落后 3 天必须 FAIL: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "✗FAIL 备份过旧" in r.stdout
    assert "--severe" in drill.notified


def test_freshness_day_shift_still_green(tmp_path):
    """隔天仍绿（L51）：把"运行日"推到明天、备份仍停在今天（落后 1 天）⇒ 必须 PASS。

    证明新鲜度门与整条链路不依赖"今天"这个字面量：明天跑同一份昨天的备份不会假红。
    """
    drill = Drill(tmp_path)
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y%m%d")
    r = drill.run(dow=3, extra_env={"STUB_TODAY": tomorrow})
    assert r.returncode == 0, f"隔天跑昨天的备份不该红: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "✗FAIL" not in r.stdout, r.stdout
    assert drill.notified == ""
    # 反向对照：再老一天（落后 2 天）必须 FAIL，证边界不是恒绿
    drill2 = Drill(tmp_path / "d2")
    r2 = drill2.run(dow=3, extra_env={
        "STUB_TODAY": (datetime.date.today() + datetime.timedelta(days=2)).strftime("%Y%m%d")})
    assert r2.returncode == 1, f"落后 2 天必须 FAIL:\n{r2.stdout}"
    assert "✗FAIL 备份过旧" in r2.stdout


# ---------------------------------------------------------------- 8. 变异测试
def _mutated_script(tmp_path: Path) -> Path:
    """把脚本复制到临时树（带 lib/repo_paths.sh），供变异用例改写。"""
    dst = tmp_path / "mut" / "scripts"
    (dst / "lib").mkdir(parents=True, exist_ok=True)
    (dst / "verify_backup.sh").write_text(SCRIPT.read_text())
    (dst / "lib" / "repo_paths.sh").write_text(REPO_PATHS_LIB.read_text())
    return dst / "verify_backup.sh"


def test_mutation_without_presence_check_turns_case2_red(tmp_path):
    """变异①：去掉 stock_daily 存在性预判 ⇒ 用例 2（无备份应 SKIP 不告警）必红。"""
    mut = _mutated_script(tmp_path)
    src = mut.read_text()
    start = src.index("  # stock_daily（#338）：先判存在性")
    end = src.index("  return $rc\n}", start)
    src = src[:start] + (
        '  if ! STOCK_BACKUP=$("$PY" "$REPO/scripts/upload_r2.py" download-db stock_daily "$TMPDIR" 2>>"$LOG"); then\n'
        '    echo "✗ stock_daily 下载失败" | tee -a "$LOG"\n'
        '    STOCK_BACKUP=""\n    rc=1\n  fi\n'
    ) + src[end:]
    mut.write_text(src)

    drill = Drill(tmp_path / "run")
    drill.set_list_keys("stock_daily", [])
    r = drill.run(dow=3, script=mut)
    # 原始用例断言（rc==0 且不告警）在变异版本上必然不成立
    assert not (r.returncode == 0 and drill.notified == ""), (
        "变异版本居然仍满足用例 2 ⇒ 该用例没有判别力")
    assert r.returncode != 0 or drill.notified.strip()


def test_mutation_space_gate_disabled_turns_case3_red(tmp_path):
    """变异②：把空间门分支改成永不触发 ⇒ 用例 3（空间不足应 SKIP+severe）必红。"""
    mut = _mutated_script(tmp_path)
    src = mut.read_text()
    old = ('  if [ -z "${avail_kb:-}" ] || [ "$avail_kb" -lt "$PF_MIN_KB" ]; then')
    assert old in src
    mut.write_text(src.replace(old, "  if false; then", 1))

    drill = Drill(tmp_path / "run")
    r = drill.run(dow=7, mode="1", min_kb=str(10 ** 12), script=mut)
    assert "SKIP(空间不足" not in r.stdout, (
        "变异后仍输出空间不足 SKIP ⇒ 用例 3 没有判别力")
    assert drill.restore_called, "变异后应直接进入还原（门失效）"


def test_mutation_stock_gate_removed_turns_deadline_case_red(tmp_path):
    """变异③：去掉「过首备日仍无 key 就 FAIL」的日期闸 ⇒ 新用例（过首备日 FAIL+severe）必红。"""
    mut = _mutated_script(tmp_path)
    old = 'if [ "$TODAY" -ge 20261030 ]; then'
    src = mut.read_text()
    assert old in src
    mut.write_text(src.replace(old, "if false; then", 1))

    drill = Drill(tmp_path / "run")
    drill.set_list_keys("stock_daily", [])
    r = drill.run(dow=3, script=mut, extra_env={"STUB_TODAY": FIRST_BACKUP_DEADLINE})
    assert not (r.returncode == 1 and "--severe" in drill.notified), (
        "变异后过首备日仍判失败 ⇒ 该用例没有判别力")


def test_mutation_stock_gate_inverted_turns_before_case_red(tmp_path):
    """变异④：把日期闸反向（首备日前就 FAIL）⇒ 用例（首备日前应 SKIP 不告警）必红。"""
    mut = _mutated_script(tmp_path)
    old = 'if [ "$TODAY" -ge 20261030 ]; then'
    src = mut.read_text()
    assert old in src
    mut.write_text(src.replace(old, 'if [ "$TODAY" -lt 20261030 ]; then', 1))

    drill = Drill(tmp_path / "run")
    drill.set_list_keys("stock_daily", [])
    r = drill.run(dow=3, script=mut, extra_env={"STUB_TODAY": BEFORE_FIRST_BACKUP})
    assert r.returncode != 0 or drill.notified.strip(), (
        "变异后首备日前也应绿 ⇒ 该用例没有判别力")


def test_no_real_network_or_notify_by_construction(tmp_path):
    """沙箱自证：全程只碰临时目录里的替身，真 notify / R2 / restore 一次都没跑。"""
    drill = Drill(tmp_path)
    r = drill.run(dow=7, mode="1")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "STUB: 未识别的调用" not in r.stderr
    assert "resolve_repo: REPO=%s" % drill.repo in r.stderr
    # 替身 python 若未被拦截，会因找不到真实 upload_r2.py 逻辑而报 STUB 未识别
    assert drill.restore_called
    assert drill.notified == ""