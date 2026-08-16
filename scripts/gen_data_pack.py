#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_data_pack.py - 历史数据包生成器（知识商店数字资产，2026-08-17 新增，B 级新功能）。

为 UUMit 平台「历史数据包」知识商店数字资产：核心衍生数据全史打包，
带版本号 + 包级 README + SHA256 校验和，可上架知识商店。

打包清单（只含自研衍生数据，绝不打包第三方原始行情）：
  sentiment-all.json         恐贪/情绪/跨市场全史
  etf_national_team-all.json 国家队 ETF 持仓
  etf_score_list.json        ETF 评分
  signal_freq.json           买卖信号频率
  rotation.json              板块轮动速度
  ma_alignment.json          均线多空排列家数
  volume_ratio.json          全市场量能
  new_high_low.json          新高新低家数
  futures.json               期货机构多空持仓
  overview.json              每日综合评分/信号灯
  a-stock-3m.json            [只取 metrics 宽度指标部分；indices 原始行情剔除]

合规硬约束：
  - 绝不打包 global/hk/industry/a-stock 的 indices（原始第三方行情）。
  - a-stock-3m.json 只打包 metrics 部分，剥离 indices。
  - 包内 README 附合规声明：衍生加工数据，原始行情不包含。

输出到 data_packs/<YYYYMMDD>/：
  financial-data-pack-<YYYYMMDD>.zip   （内含各 JSON + README.md）
  SHA256SUMS                            （每个文件 sha256）
  包级 README.md                        （版本号/生成日期/数据截止日期/字段说明/数据口径/合规声明）

支持：
  --date YYYYMMDD  重打包指定日（默认今天）
  --list           列历史包
  --out <dir>      输出根目录（默认 data_packs/）
每次跑输出新目录，不覆盖旧包（同日重复跑追加 -2/-3 后缀或覆盖提示）。

用法：
  python3 scripts/gen_data_pack.py            # 打包今天
  python3 scripts/gen_data_pack.py --date 20260814
  python3 scripts/gen_data_pack.py --list
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).absolute().parent.parent
DATA_DIR = REPO / "static-site" / "data"
PACK_ROOT = REPO / "data_packs"

# 打包清单：文件名 -> (包内文件名, 是否裁剪)
# 裁剪 = 从 JSON 对象里只保留指定键（如 a-stock-3m 只留 metrics）
PACK_FILES = {
    "sentiment-all.json": ("sentiment-all.json", None),
    "etf_national_team-all.json": ("etf_national_team-all.json", None),
    "etf_score_list.json": ("etf_score_list.json", None),
    "signal_freq.json": ("signal_freq.json", None),
    "rotation.json": ("rotation.json", None),
    "ma_alignment.json": ("ma_alignment.json", None),
    "volume_ratio.json": ("volume_ratio.json", None),
    "new_high_low.json": ("new_high_low.json", None),
    "futures.json": ("futures.json", None),
    "overview.json": ("overview.json", None),
    # a-stock-3m：只取 metrics 宽度指标（上涨家数/涨停等），剥离 indices 原始行情（合规红线）
    "a-stock-3m.json": ("a-stock-3m_metrics.json", {"keep": ["metrics"]}),
}

PACK_VERSION = "1.0.0"  # 数据包版本号（独立于站点版本，动打包清单/口径时递增）


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def trim_json(data: dict, trim: dict | None) -> dict:
    """按 trim 规则裁剪：keep 键列表。None = 原样。"""
    if not trim:
        return data
    keep = trim.get("keep") or []
    return {k: data.get(k) for k in keep if k in data}


def read_source(name: str) -> tuple[dict, Path]:
    """读源文件，返回 (json 对象, 源路径)。"""
    src = DATA_DIR / name
    if not src.exists():
        raise FileNotFoundError(f"源文件缺失: {src}")
    return json.loads(src.read_text(encoding="utf-8")), src


def data_cutoff_date() -> str:
    """数据截止日期 = 各源文件最新日期（取 overview.date 为权威主源）。"""
    try:
        ov, _ = read_source("overview.json")
        d = str(ov.get("date") or "")
        if d:
            return d
    except Exception:
        pass
    return datetime.now().strftime("%Y%m%d")


def write_pack_readme(out_dir: Path, date: str, cutoff: str, files: list[str]) -> Path:
    """写包级 README.md。"""
    readme = out_dir / "README.md"
    lines = [
        f"# 金融情绪衍生数据包 v{PACK_VERSION}（{date}）",
        "",
        "## 数据包内容",
        "本数据包为**自研衍生加工数据**，用于研究/教学/数据挖掘，**不包含任何第三方原始行情**。",
        "",
        "| 文件 | 内容 |",
        "|---|---|",
        "| sentiment-all.json | 恐贪/情绪/跨市场全史序列 |",
        "| etf_national_team-all.json | 国家队 ETF 持仓历史 |",
        "| etf_score_list.json | ETF 综合评分列表 |",
        "| signal_freq.json | 买卖信号频率聚合 |",
        "| rotation.json | 板块轮动速度 |",
        "| ma_alignment.json | 均线多空排列家数 |",
        "| volume_ratio.json | 全市场量能 |",
        "| new_high_low.json | 52周/20日新高新低家数 |",
        "| futures.json | 期货机构多空持仓/多空比 |",
        "| overview.json | 每日综合评分/信号灯/今日信号 |",
        "| a-stock-3m_metrics.json | A股宽度指标（上涨家数/涨停等，已剥离原始行情 indices） |",
        "",
        "## 元信息",
        f"- 数据包版本号：v{PACK_VERSION}",
        f"- 生成日期：{date}",
        f"- 数据截止日期：{cutoff}",
        "",
        "## 数据口径",
        "各文件字段口径与站点公开数据一致（详见 docs/data-pack.md 与各源文件生成脚本注释）。",
        "",
        "## 合规声明",
        "本数据包为**衍生加工数据**（情绪/评分/宽度指标等自研指标），**不包含第三方原始行情数据**",
        "（global/hk/industry/a-stock 的 indices 原始行情一律不打包）。使用请遵守原始数据源与平台条款。",
        "",
        "## 校验",
        "见 SHA256SUMS。可用 `sha256sum -c SHA256SUMS` 校验完整性。",
        "",
    ]
    readme.write_text("\n".join(lines), encoding="utf-8")
    return readme


def build_pack(date: str, out_root: Path) -> tuple[Path, list[str]]:
    """打包指定日，返回 (zip 路径, 成功文件列表)。"""
    out_dir = out_root / date
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"financial-data-pack-{date}.zip"

    cutoff = data_cutoff_date()

    success_files = []

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src_name, (inzip_name, trim) in PACK_FILES.items():
            src = DATA_DIR / src_name
            if not src.exists():
                print(f"[gen_data_pack] 跳过（源缺失）: {src}")
                continue
            if trim is None:
                # 未裁剪：源文件字节原样写入 zip，保证 zip 内字节 = 源文件字节（§22 sha256 逐位一致）
                zf.write(src, inzip_name)
            else:
                # 裁剪（a-stock metrics）：JSON 重序列化后写入，剥离原始行情 indices
                data = json.loads(src.read_text(encoding="utf-8"))
                trimmed = trim_json(data, trim)
                tmp = out_dir / (inzip_name + ".tmp")
                tmp.write_text(json.dumps(trimmed, ensure_ascii=False, indent=1), encoding="utf-8")
                zf.write(tmp, inzip_name)
                tmp.unlink()
            success_files.append(inzip_name)
            print(f"[gen_data_pack] + {inzip_name}")

        # 包级 README
        readme = write_pack_readme(out_dir, date, cutoff, success_files)
        zf.write(readme, "README.md")

    # 单独为每个文件算 sha256（与源文件逐位一致校验，§22/验收）：
    # 未裁剪文件 zip 内字节 = 源文件字节，sha256 直接与源比对；裁剪文件（a-stock metrics）
    # 对 zip 内裁剪后字节算 sha。
    sha_lines = []
    for src_name, (inzip_name, trim) in PACK_FILES.items():
        src = DATA_DIR / src_name
        if not src.exists():
            continue
        if trim is None:
            sha_lines.append(f"{file_sha256(src)}  {inzip_name}")
        else:
            sha_lines.append(f"{sha_of_zip_entry(zip_path, inzip_name)}  {inzip_name}")

    (out_dir / "SHA256SUMS").write_text("\n".join(sorted(sha_lines)) + "\n", encoding="utf-8")

    return zip_path, success_files


def sha_of_zip_entry(zip_path: Path, entry: str) -> str:
    """对 zip 内某个 entry 的字节算 sha256（裁剪文件用）。"""
    with zipfile.ZipFile(zip_path) as zf:
        data = zf.read(entry)
    return hashlib.sha256(data).hexdigest()


def list_packs(out_root: Path) -> None:
    if not out_root.exists():
        print("暂无历史数据包")
        return
    for d in sorted(out_root.iterdir()):
        if d.is_dir():
            zips = list(d.glob("financial-data-pack-*.zip"))
            if zips:
                print(f"{d.name}: {', '.join(z.name for z in zips)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", default=str(PACK_ROOT))
    args = ap.parse_args()

    out_root = Path(args.out)
    if args.list:
        list_packs(out_root)
        return 0

    zip_path, files = build_pack(args.date, out_root)
    print(f"\n[gen_data_pack] ✓ 数据包生成: {zip_path}")
    print(f"[gen_data_pack] 文件数: {len(files)}，校验: {zip_path.parent / 'SHA256SUMS'}")
    print(f"[gen_data_pack] 命令: sha256sum -c {zip_path.parent / 'SHA256SUMS'}")
    return 0


if __name__ == "__main__":
    main()
