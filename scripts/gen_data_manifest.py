#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 data/manifest.json —— 开源完整化：全量 JSON 数据产物索引清单。

每个文件项含:path(相对 static-site/data/)、url(R2 公开桶直链)、size、sha256。
R2 URL 前缀映射与 scripts/upload_r2.py 的上传前缀保持一致(§8.1):
  - data/  前缀: 顶层 *.json(data/xxx.json) —— upload-data-large / upload-all-data / upload-etf-score
  - industry/  前缀: industry-* (industry-{all,5y,3y}-indices/ 子目录 + industry-*.json 扁平)
  - public_fund/ 前缀: public_fund*.json
  - offshore_fund/ 前缀: offshore_fund*.json
  - fund_score/ 前缀: fund_score*.json
  - index/ 前缀: index/*.json
  - lab/ 前缀: lab/*.json
  - trade_sim_data/ 前缀: trade_sim/*.json (避开 trade_sim/ HTML 前缀)

用法:
  python3 scripts/gen_data_manifest.py            # 生成 data/manifest.json
  python3 scripts/gen_data_manifest.py --verify   # 生成后对每个 URL 发 HEAD 抽查(慢,可选)

导出数据更新后重跑本脚本即可刷新 sha256/url(可复用,export 后调用)。
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "static-site" / "data"
OUT = ROOT / "data" / "manifest.json"

# R2 公开桶域名(与 .env R2_PUBLIC_DOMAIN 一致,公开非敏感)
R2_BASE = "https://ssd.fx8.store"

# DB Release 归档(待用户手动上传 GitHub Release,manifest 预留 URL 结构)
# Release tag 用日期,资产名固定。URL = https://github.com/{repo}/releases/download/{tag}/{asset}
# 本地打包产物在 data/release/{name}(gitignore,不进 git);scripts/release_db.sh 上传后用实际 sha256。
REPO = "xp13465/trade-data-signal"
DB_RELEASE_TAG = "db-archive"  # 实际发布时建议用 db-archive-YYYY-MM-DD
RELEASE_DIR = ROOT / "data" / "release"
DB_FILES = [
    # (name, 打包产物路径, 说明)
    ("sentiment.db.tar.gz", "sentiment.db.tar.gz", "情绪/信号/期货持仓 主库"),
    ("etf_national_team.db.tar.gz", "etf_national_team.db.tar.gz", "国家队 ETF 资金动向库"),
    ("stock_daily.db.tar.gz", "stock_daily.db.tar.gz", "个股日线原始库"),
    ("public_fund.db.tar.gz", "public_fund.db.tar.gz", "公募基金全量库(压缩后约578MB)"),
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def r2_key_for(rel: str) -> str:
    """把相对 static-site/data/ 的路径映射成 R2 key(与 upload_r2.py 前缀规则一致)。"""
    if rel.startswith("industry-"):
        return f"industry/{rel}"
    if rel.startswith("public_fund"):
        return f"public_fund/{Path(rel).name}"
    if rel.startswith("offshore_fund"):
        return f"offshore_fund/{Path(rel).name}"
    if rel.startswith("fund_score"):
        return f"fund_score/{Path(rel).name}"
    if rel.startswith("index/"):
        return f"index/{Path(rel).name}"
    if rel.startswith("lab/"):
        return f"lab/{Path(rel).name}"
    if rel.startswith("trade_sim/"):
        return f"trade_sim_data/{Path(rel).name}"
    return f"data/{rel}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="生成后对 URL 抽查 HTTP 状态(慢)")
    args = ap.parse_args()

    if not DATA_DIR.is_dir():
        sys.exit(f"数据目录不存在: {DATA_DIR}")

    files = sorted(p for p in DATA_DIR.rglob("*.json") if p.is_file())
    if not files:
        sys.exit("无 .json 文件")

    entries = []
    total_size = 0
    for p in files:
        rel = p.relative_to(DATA_DIR).as_posix()
        size = p.stat().st_size
        total_size += size
        entries.append({
            "path": rel,
            "url": f"{R2_BASE}/{r2_key_for(rel)}",
            "size": size,
            "sha256": sha256_of(p),
        })

    # DB 归档条目(Release 资产,上传后可用;未上传时 url 为规划地址)
    databases = []
    for name, archive_name, desc in DB_FILES:
        ap = RELEASE_DIR / archive_name
        db_entry = {
            "name": name,
            "description": desc,
            "url": f"https://github.com/{REPO}/releases/download/{DB_RELEASE_TAG}/{name}",
            "size": ap.stat().st_size if ap.exists() else None,
            "sha256": sha256_of(ap) if ap.exists() else None,
            "uploaded": False,  # scripts/release_db.sh 上传后置 True
        }
        databases.append(db_entry)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": "tdsignal 全量 JSON 数据产物索引。path 相对 static-site/data/;"
                       "url 为 R2 公开桶直链;sha256 用于完整性校验。"
                       "获取: git clone 后 bash fetch_data.sh 一键下载。",
        "data_license": "CC BY 4.0",
        "third_party_notice": "NOTICE",
        "r2_base": R2_BASE,
        "file_count": len(entries),
        "total_size": total_size,
        "files": entries,
        "databases": databases,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(manifest, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✓ manifest 写入 {OUT}: {len(entries)} 文件, 共 {total_size / 1024 / 1024:.1f}MB, "
          f"+ {len(databases)} 个 DB Release 条目")

    if args.verify:
        _verify(entries)


def _verify(entries):
    import urllib.request
    import random
    sample = random.sample(entries, min(20, len(entries)))
    bad = 0
    for e in sample:
        try:
            req = urllib.request.Request(e["url"], method="HEAD")
            with urllib.request.urlopen(req, timeout=15) as r:
                ok = r.status == 200
        except Exception:
            ok = False
        if not ok:
            bad += 1
            print(f"  ✗ {e['url']}")
        else:
            print(f"  ✓ {e['path']}")
    print(f"抽查 {len(sample)} 个 URL, 失败 {bad} 个" + (" ⚠️" if bad else " ✓"))


if __name__ == "__main__":
    main()
