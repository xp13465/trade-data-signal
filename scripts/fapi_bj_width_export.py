#!/usr/bin/env python3
"""fapi_bj_width_export.py — 北交所宽度产物最小 export + R2 上传(#101 F4 时序修复, 2026-09-06)。

背景: FAPI 日线 18:10 采集(fapi_daily_syn.sh)完成后, 北交所宽度 a_bj_* 当天数据已入 daily_metric;
     但 17:50 update_all 宽度 pipeline 用的还是昨日 FAPI 数据(采集时点晚于它), 北交所宽度卡因此差一天。
     F4 拍板: 链式里补一步 export, 当天数据 18:10 采完即上 R2, 当天可见(不等次日 17:50)。

产物(最小范围: 只重导北交所宽度相关, 不重算无关产物, 不与 17:50 既有产物互扰):
  - data/overview.json                     北交所宽度卡当前值(today.metrics.a_bj_*) + a_bj_*_6m sparkline
  - data/a-stock-{3m,6m,1y,3y,5y,all}.json 历史走势(metrics.a_bj_width_*, 前端 KPI 详情弹窗 range)

通道(复用既有, 不新造):
  - export: 复用 static-site/export.py 的 export_overview/export_a_stock/write_json(与 deploy.sh 同源查询逻辑)
  - R2: 复用 scripts/upload_r2.py 的 upload-data-files 命令 —— 精准传指定文件到 R2 data/ 前缀 +
        自动 purge CF edge cache(static-site/data/ 已整体 gitignore 移出 git, 线上主站/备站
        /data/ rewrite 与 R2 大range直链均读 R2; 18:10 时点内不做 git push, §14 该时点无 deploy,
        R2 上传即完成数据上线)。

失败语义: 与 bj_width 同(新增指标缺供不影响既有功能)—— 产物生成任一步失败仅打印告警,
    不上传 R2(防旧产物覆盖), exit 1 让链式 wrapper 的 || 兜底 WARN 不阻断。

CLI:
  python scripts/fapi_bj_width_export.py           # 导出 + 上传 R2(链式调用)
  python scripts/fapi_bj_width_export.py --no-upload  # 只导出不上传(本地自测/排查)

依赖:
  REPO env(默认 /Users/linhuichen/code/trade-data)决定读主库 DB 与写 static-site/data 的位置。
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("REPO", "/Users/linhuichen/code/trade-data"))
PY = REPO / ".venv" / "bin" / "python"

# ── 复用 static-site/export.py(与 deploy.sh 同源查询逻辑)───────────────────────
# 必须经 trade-data 路径 import(不 resolve symlink), 使 export.ROOT=trade-data →
# app.db.DB_PATH=trade-data/data/sentiment.db 主库(§9 cwd trade-data 方案, 防读滞后镜像)。
sys.path.insert(0, str(REPO / "static-site"))
sys.path.insert(0, str(REPO))
import export as exp  # noqa: E402


def _export_products(conn, cfg) -> bool:
    """只重导出北交所宽度相关产物。任一步失败返回 False(整体不上传)。"""
    ok = True
    # 1) overview.json(北交所宽度卡当前值 + a_bj_*_6m sparkline)
    try:
        exp.write_json(exp.DATA_DIR / "overview.json", exp.export_overview(conn, cfg))
        print(f"  ✓ overview.json", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ overview.json 导出失败: {e}", flush=True)
        ok = False
    # 2) a-stock-{3m,6m,1y,3y,5y,all}.json(北交所宽度历史走势, 前端 range 弹窗)
    for rng in exp.EXPORT_RANGES:
        fname = f"a-stock-{rng}.json"
        try:
            exp.write_json(exp.DATA_DIR / fname, exp.export_a_stock(conn, cfg, rng))
            print(f"  ✓ {fname}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {fname} 导出失败: {e}", flush=True)
            ok = False
    return ok


def _upload_r2(files) -> bool:
    """复用 upload_r2.py upload-data-files 精准上传 R2 data/ 前缀(自动 purge edge cache)。"""
    cmd = [str(PY), str(REPO / "scripts" / "upload_r2.py"), "upload-data-files", *files]
    env = {**os.environ, "REPO": str(REPO)}
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        if r.returncode != 0:
            print(f"  ✗ upload-data-files 退出码 {r.returncode}", flush=True)
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  ✗ upload-data-files 超时(600s)", flush=True)
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ upload-data-files 异常: {e}", flush=True)
        return False


def _now() -> str:
    return dt.datetime.now().strftime("%F %T")


def main() -> int:
    no_upload = "--no-upload" in sys.argv
    files = ["overview.json"] + [f"a-stock-{rng}.json" for rng in exp.EXPORT_RANGES]
    print(f"=== [fapi-bj-width-export] {_now()} start (REPO={REPO}) ===", flush=True)

    cfg = exp.load_config()
    conn = exp.get_conn()

    if not _export_products(conn, cfg):
        print("[fapi-bj-width-export] ERROR: 产物导出失败, 不上传 R2(防旧产物覆盖)", flush=True)
        return 1

    if no_upload:
        print("[fapi-bj-width-export] --no-upload: 仅导出未上传(自测模式)", flush=True)
        return 0

    if not _upload_r2(files):
        print("[fapi-bj-width-export] ERROR: R2 上传失败(次日 17:50 runner 会重导重传)", flush=True)
        return 1

    print(f"=== [fapi-bj-width-export] {_now()} done (上传 {len(files)} 文件到 R2 data/) ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
