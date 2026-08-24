#!/usr/bin/env python3
"""check_r2_consistency.py - R2 产物三版本一致性审计（P2-2）

比对 local static-site/data/ vs R2(ssd.fx8.store) vs CF r2 proxy(ss.fx8.store/r2)
关键数据产物的 track_score/top1 字段，防 159335 类三版本不一致事故（§22 数据一致性铁律）。

非 deploy 前置（需网络），作定期监控任务跑。

用法:
  python scripts/check_r2_consistency.py              # 全量比对
  python scripts/check_r2_consistency.py --quiet      # 仅告警输出

退出码: 0=三版本一致, 1=有不一致或网络错误
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.request
from pathlib import Path

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()  # 兜底：系统证书

LOCAL_DATA = Path(__file__).resolve().parent.parent / "static-site" / "data"
TIMEOUT = 12
# track_score 跨源容差（同 build 产物应完全一致，留 0.01 防 JSON float repr 误差）
FLOAT_TOLERANCE = 0.01

# 受检文件: (显示名, 本地相对路径, R2 URL, CF r2-proxy URL)
FILES = [
    (
        "overview",
        "overview.json",
        "https://ssd.fx8.store/data/overview.json",
        "https://ss.fx8.store/r2/data/overview.json",
    ),
    (
        "board_etf_map",
        "board_etf_map.json",
        "https://ssd.fx8.store/data/board_etf_map.json",
        "https://ss.fx8.store/r2/data/board_etf_map.json",
    ),
    (
        "concepts",
        "industry-all-concepts.json",
        "https://ssd.fx8.store/industry/industry-all-concepts.json",
        "https://ss.fx8.store/r2/industry/industry-all-concepts.json",
    ),
    # overfit_monitor 主+ext(2026-08-25 监控盲区收尾批补入): 首页 AI 监控卡盘后核心产物,
    # 2026-08-24 B拆分起走 R2 /data/ 前缀(upload_r2 _OVERFIT_FORCE), 此前审计不查
    # 本地 vs R2 一致性=盲区。指纹=generated_at+综合风险分三件套(主)/键集(ext)。
    (
        "overfit_monitor",
        "overfit_monitor.json",
        "https://ssd.fx8.store/data/overfit_monitor.json",
        "https://ss.fx8.store/r2/data/overfit_monitor.json",
    ),
    (
        "overfit_monitor_ext",
        "overfit_monitor_ext.json",
        "https://ssd.fx8.store/data/overfit_monitor_ext.json",
        "https://ss.fx8.store/r2/data/overfit_monitor_ext.json",
    ),
]


def _fetch_json(url: str) -> tuple[object, str | None]:
    """HTTP 拉 JSON，返回 (data, error)。用 certifi 证书（macOS Python 自带 SSL 证书不全）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "check_r2_consistency/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _load_local(path: Path) -> tuple[object, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _fingerprint(data: object, kind: str) -> dict[str, object]:
    """提取关键字段指纹（track_score/top1）。跨源比对用。"""
    fp: dict[str, object] = {}
    if not isinstance(data, dict):
        return fp
    if kind == "overview":
        fp["date"] = data.get("date")
        for s in (data.get("signals_today") or [])[:30]:
            if not isinstance(s, dict):
                continue
            etfs = s.get("etfs")
            if isinstance(etfs, list) and etfs and isinstance(etfs[0], dict):
                code, ts = etfs[0].get("code"), etfs[0].get("track_score")
                if code and ts is not None:
                    fp[f"sig_{code}"] = ts
    elif kind == "board_etf_map":
        for idx in ("sh", "sz", "hs300", "sz50", "csi500"):
            etfs = data.get(idx)
            if isinstance(etfs, list) and etfs and isinstance(etfs[0], dict):
                code, ts = etfs[0].get("code"), etfs[0].get("track_score")
                if code and ts is not None:
                    fp[f"{idx}_{code}"] = ts
    elif kind == "concepts":
        concepts = data.get("concepts")
        if isinstance(concepts, dict):
            for cid in list(concepts.keys())[:5]:
                cv = concepts[cid]
                etfs = cv.get("etfs") if isinstance(cv, dict) else None
                if isinstance(etfs, list) and etfs and isinstance(etfs[0], dict):
                    code, ts = etfs[0].get("code"), etfs[0].get("track_score")
                    if code and ts is not None:
                        fp[f"{cid}_{code}"] = ts
    elif kind == "overfit_monitor":
        # 指纹=generated_at(同次打点必一致, 旧版滞留即报)+综合风险分三件套
        # (overfit.current: date/d1-d4 加权前的分维度值+risk_score 总分)。
        fp["generated_at"] = data.get("generated_at")
        ov = data.get("overfit")
        cur = (ov.get("current") or {}) if isinstance(ov, dict) else {}
        fp["of_date"] = cur.get("date")
        fp["risk_score"] = cur.get("risk_score")
        for dkey in ("d1", "d2", "d3", "d4"):
            fp[dkey] = cur.get(dkey)
    elif kind == "overfit_monitor_ext":
        # ext 拆分产物(2026-08-24 B拆分): 指纹=generated_at+by_k/filtered_by_k 键集
        # (K档位缺失=拆分病灶复发, filtered 键丢失同款; 值体量大取键集足够定位版本错位)。
        fp["generated_at"] = data.get("generated_at")
        by_k = data.get("by_k")
        if isinstance(by_k, dict):
            fp["by_k_keys"] = ",".join(sorted(by_k.keys()))
        fbk = data.get("filtered_by_k")
        if isinstance(fbk, dict):
            fp["filtered_by_k_keys"] = ",".join(sorted(fbk.keys()))
    return fp


def _values_equal(a: object, b: object) -> bool:
    """比较两个值，float 容差 FLOAT_TOLERANCE。"""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= FLOAT_TOLERANCE
    return a == b


def check_file(kind: str, local_rel: str, r2_url: str, cf_url: str, quiet: bool) -> list[str]:
    """比对单文件三版本指纹，返回问题行列表。"""
    problems: list[str] = []
    local_data, lerr = _load_local(LOCAL_DATA / local_rel)
    r2_data, r2err = _fetch_json(r2_url)
    cf_data, cferr = _fetch_json(cf_url)

    sources = {"local": (local_data, lerr), "R2": (r2_data, r2err), "CF": (cf_data, cferr)}
    # 网络错误单独报
    for sname, (_, e) in sources.items():
        if e:
            problems.append(f"[{kind}] {sname} 拉取失败: {e}")

    fps = {sname: _fingerprint(d, kind) for sname, (d, e) in sources.items() if not e}
    if len(fps) < 2:
        if not quiet:
            print(f"  ~ {kind}: 可用源 {list(fps)} < 2，跳过比对")
        return problems

    # 比对所有 key（union）
    all_keys = set()
    for fp in fps.values():
        all_keys.update(fp.keys())
    mismatches = []
    for key in sorted(all_keys):
        vals = {sname: fp.get(key) for sname, fp in fps.items()}
        present = {s: v for s, v in vals.items() if v is not None}
        if len(present) < 2:
            continue  # 只有一处有值，不判（可能版本差异字段）
        ref_s, ref_v = next(iter(present.items()))
        for s, v in present.items():
            if not _values_equal(ref_v, v):
                mismatches.append(f"{key}: {dict(present)}")
                break

    if mismatches:
        problems.append(f"[{kind}] 三版本 track_score/top1 不一致: {'; '.join(mismatches[:5])}")
        if not quiet:
            print(f"  ✗ {kind}: {len(mismatches)} 项不一致")
    elif not quiet:
        print(f"  ✓ {kind}: 三版本一致 ({len(all_keys)} 项指纹)")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="R2 产物三版本一致性审计")
    parser.add_argument("--quiet", action="store_true", help="仅输出不一致项")
    args = parser.parse_args()

    if not args.quiet:
        print("=== R2 产物三版本一致性审计 ===")
        print(f"  local: {LOCAL_DATA}")
        print(f"  R2:    ssd.fx8.store")
        print(f"  CF:    ss.fx8.store/r2")
        print()

    all_problems: list[str] = []
    for kind, local_rel, r2_url, cf_url in FILES:
        all_problems.extend(check_file(kind, local_rel, r2_url, cf_url, args.quiet))

    if all_problems:
        print()
        print(f"=== {len(all_problems)} 项问题 ===")
        for p in all_problems:
            print(f"  ✗ {p}")
        return 1
    if not args.quiet:
        print()
        print("=== 三版本一致 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
