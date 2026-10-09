#!/usr/bin/env python3
"""#238 黄金对账 fixture 生成器:从**改动前(#238 之前)的旧实现**产出期望输出。

用途(reviewer 建议 3):把「旧实现黄金输出」固化成仓内 fixture,给 `_map_group`
(流式与参照实现共用)一个**独立于当前生产代码**的锚点 —— 未来 `_map_group` 若漂移,
`test_streaming_equals_golden_fixture` 立刻红。

生成方式(可离线重复):
  1. `git show <LEGACY_REF>:app/collector/fapi_daily.py` 取出 **pre-#238 旧实现**
     (物化版 `map_frame`:pandas `map(_f)` + 内联逐行);
  2. 校验其 md5 == 下方 `LEGACY_MD5`(闸门:取错版本 ⇒ 中止,不产出假黄金);
  3. 在独立子进程里 import 该旧实现,对**真实 dump 切片**(fixtures/238/sample.parquet)
     跑 `map_frame`,输出 JSON 行数组 → 写 `fixtures/238/expected_rows.json`。

为什么用「固定输入 → 固定期望输出」黄金 fixture,而非每次 `git show` 现取旧版做 oracle:
  · **不依赖 git/网络**:CI 若浅克隆、或历史被 rewrite,`git show <ref>` 会失败 ⇒ 测试脆;
  · **不引入「第二份实现」常驻**:旧实现是一次性产物,冻结进 JSON 即止,不留活代码;
  · 黄金来源可审计:本脚本 + `LEGACY_REF`/`LEGACY_MD5` 记录来源(任何人可复算复核)。

用法:
    python3 scripts/tests/gen_fapi_golden_238.py [LEGACY_REF]
    python3 scripts/tests/gen_fapi_golden_238.py [LEGACY_REF] --check   # 只校验可复算
    # 默认 LEGACY_REF=43cb3e804(main 上 #238 之前的版本,md5 见 LEGACY_MD5)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "238"
SAMPLE = FIXTURES / "sample.parquet"
GOLDEN = FIXTURES / "expected_rows.json"

# pre-#238 旧实现锚点:43cb3e804 = main 上 #238 之前的版本,未含任何流式改动。
# md5 闸门同时锁定「取到的确实是那一版」(43cb3e804 / 33c6bace2 / origin/main 三处一致)。
LEGACY_REF = "43cb3e804"
LEGACY_MD5 = "682e6b588b82833d8f00ce825792ffaf"

_SUBPROC = r"""
import json, sys
sys.path.insert(0, sys.argv[3])          # scripts/tests(_ci_stubs 所在)
from _ci_stubs import install_missing_third_party_stubs
install_missing_third_party_stubs()      # CI 缺 requests: 补导入级 stub(与 pytest 进程同判据)
sys.path.insert(0, sys.argv[1])          # 旧实现所在目录
import fapi_daily as legacy              # noqa: E402
import pyarrow.parquet as pq             # noqa: E402
rows = legacy.map_frame(pq.read_table(sys.argv[2]).to_pandas())
json.dump(rows, sys.stdout)
"""


def _legacy_source(ref: str) -> bytes:
    out = subprocess.run(["git", "show", f"{ref}:app/collector/fapi_daily.py"],
                         cwd=ROOT, capture_output=True, timeout=60)
    if out.returncode != 0:
        raise SystemExit(f"git show {ref}:... 失败:{out.stderr.decode()[:300]}")
    return out.stdout


def compute_rows(ref: str) -> tuple[list, str]:
    """从 `ref` 的旧实现算出黄金行(md5 闸门校验)。返回 (rows, legacy_md5)。"""
    src = _legacy_source(ref)
    md5 = hashlib.md5(src).hexdigest()
    if md5 != LEGACY_MD5:
        raise SystemExit(
            f"旧实现 md5 不符(md5 闸门):期望 {LEGACY_MD5},实得 {md5}。"
            f"ref={ref} 不是 pre-#238 版本,拒绝生成(防产出假黄金)。")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "fapi_daily.py").write_bytes(src)
        out = subprocess.run(
            [sys.executable, "-c", _SUBPROC, td, str(SAMPLE), str(Path(__file__).parent)],
            cwd=ROOT, capture_output=True, timeout=300)
    if out.returncode != 0:
        raise SystemExit(f"旧实现跑 map_frame 失败:{out.stderr.decode()[-500:]}")
    return json.loads(out.stdout.decode()), md5


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ref", nargs="?", default=LEGACY_REF)
    ap.add_argument("--check", action="store_true",
                    help="只校验仓内 golden 可由旧实现复算(不改文件);不符则 exit 1")
    args = ap.parse_args(argv)

    rows, md5 = compute_rows(args.ref)

    if args.check:
        cur = json.loads(GOLDEN.read_text(encoding="utf-8"))
        if cur["rows"] != rows or cur["meta"]["legacy_md5"] != md5:
            print(f"MISMATCH: {GOLDEN} 与旧实现复算结果不符", file=sys.stderr)
            return 1
        print(f"OK: {GOLDEN} 可由 {args.ref} 旧实现复算(rows={len(rows)})")
        return 0

    golden = {
        "meta": {
            "source": f"git show {args.ref}:app/collector/fapi_daily.py",
            "legacy_md5": md5,
            "sample": "scripts/tests/fixtures/238/sample.parquet",
            "generator": "scripts/tests/gen_fapi_golden_238.py",
            "note": "pre-#238 物化版 map_frame 的输出;冻结作 _map_group 独立锚点",
        },
        "rows": rows,
    }
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    print(f"wrote {GOLDEN} rows={len(rows)} legacy_md5={md5}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))