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
import os
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

# overfit 条目 local 双树探测的默认树序(B件 #57, 2026-08-25; 权威树优先):
#   权威树=trade-data(overfit_monitor.sh REPO 打点后即时 upload_r2 上传源);
#   git 渠道树=trade(deploy.sh rsync 兜底副本, 相对新打点滞后 ~20h 属常态非异常)。
OVERFIT_LOCAL_TREES = [
    "/Users/linhuichen/code/trade-data",
    "/Users/linhuichen/code/trade",
]
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


def _local_candidates(kind: str, local_rel: str) -> list[Path]:
    """local 校验候选路径(有序, 权威优先)。

    病灶(#57 P2-B): overfit 产物权威树=trade-data(打点后即时 upload_r2, 不经 deploy.sh
    rsync 同步到 git 渠道树 trade), 固定单树口径(resolve 到脚本所在树=trade 渠道树)在每天
    21:40 打点后 ~20h 必假阳(local 旧 vs R2 新)。
    选型=双树任一与远端一致即 PASS(方案①强化), 不选「砍 local 只比 R2/CF」(方案②):
    「local 权威树 vs R2」是抓 R2 被旧库覆盖事故的唯一探针(2026-08-19 手动忘带 REPO 致
    R2 被 trade 侧旧库整体覆盖), 砍掉 local=把刚补上的盲区再挖开。
    树序: REPO env > GIT_REPO env > 默认权威树 > 默认渠道树(env 缺省回落现值, 行为不变)。
    非 overfit 条目维持单树旧行为(走 deploy 链, local 与 R2 同批快照无此病灶)。
    """
    if not kind.startswith("overfit"):
        return [LOCAL_DATA / local_rel]
    seen: set[Path] = set()
    out: list[Path] = []
    for tree in (
        os.environ.get("REPO"),
        os.environ.get("GIT_REPO"),
        *OVERFIT_LOCAL_TREES,
    ):
        if not tree:
            continue
        cand = (Path(tree) / "static-site" / "data" / local_rel).resolve()
        if cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out or [LOCAL_DATA / local_rel]


def _mismatches(fps: dict[str, dict[str, object]]) -> tuple[list[str], int]:
    """跨源指纹 union key 逐项比对，返回 (不一致描述行, 参比指纹项数)。空列表=一致。"""
    all_keys: set[str] = set()
    for fp in fps.values():
        all_keys.update(fp.keys())
    mismatches: list[str] = []
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
    return mismatches, len(all_keys)


def check_file(kind: str, local_rel: str, r2_url: str, cf_url: str, quiet: bool) -> tuple[list[str], list[str]]:
    """比对单文件多版本指纹，返回 (问题行, WARN 行)。

    WARN(P1-b review 2026-08-25): 「primary 权威树滞后、后续候选与远端一致」判据仍 PASS
    (正常打点窗口合法滞后不误伤), 但该形态=2026-08-19 R2 被渠道树旧库覆盖的事故同款,
    唯一探针不可静默——独立 WARN 行+汇总段重复计数, 不进 problems 不阻断。
    """
    problems: list[str] = []
    r2_data, r2err = _fetch_json(r2_url)
    cf_data, cferr = _fetch_json(cf_url)
    # 远端网络错误单独报
    for sname, e in (("R2", r2err), ("CF", cferr)):
        if e:
            problems.append(f"[{kind}] {sname} 拉取失败: {e}")
    remote_fps = {
        sname: _fingerprint(d, kind)
        for sname, d in (("R2", r2_data), ("CF", cf_data))
        if d is not None
    }

    loaded: list[tuple[Path, object, str | None]] = [
        (cand, *_load_local(cand)) for cand in _local_candidates(kind, local_rel)
    ]
    # local 全候选不可读: 单独报(保留 local 维度审计), 远端仍照比(与旧版行为一致)
    if loaded and all(err for _, _, err in loaded):
        for cand, _, err in loaded:
            problems.append(f"[{kind}] local({cand}) 拉取失败: {err}")

    passed: tuple[int, Path] | None = None      # (指纹项数, 命中路径)
    lagged_primary: Path | None = None          # 先于命中路径出现的不一致候选(滞后树)
    mismatch_report: str | None = None          # 全候选不一致时的首个报告
    for cand, data, err in loaded:
        if err:
            continue
        fps = dict(remote_fps)
        fps["local"] = _fingerprint(data, kind)
        if len(fps) < 2:
            continue  # 可用源 <2 无从比对(网络问题已单独报)
        mm, n_keys = _mismatches(fps)
        if not mm:
            passed = (n_keys, cand)
            break
        if lagged_primary is None:
            lagged_primary = cand
            mismatch_report = f"[{kind}] 三版本 track_score/top1 不一致: {'; '.join(mm[:5])} (local={cand})"

    warnings: list[str] = []
    if passed is not None:
        n_keys, cand = passed
        line = f"  ✓ {kind}: 三版本一致 ({n_keys} 项指纹)"
        if lagged_primary is not None:
            line += f" [primary({lagged_primary}) 滞后, 以 {cand} 为 local 权威源]"
            warnings.append(
                f"[{kind}] primary({lagged_primary}) 滞后于远端(local 权威={cand})"
                "——若非刚打点窗口期(21:40 后短窗口属合法滞后), 请人工核查是否渠道树旧库覆盖事故"
            )
            if not quiet:
                print(line)
                print(
                    f"  ⚠️ WARN {kind}: primary 树滞后于远端, 若非刚打点窗口期"
                    "请人工核查是否覆盖事故(判据仍 PASS, 汇总段有计数)"
                )
        else:
            if len(loaded) > 1 and not quiet:
                line += f" [local={cand}]"
            if not quiet:
                print(line)
    elif mismatch_report is not None:
        problems.append(mismatch_report)
        if not quiet:
            print(f"  ✗ {kind}: local 候选均与远端不一致")
    elif not quiet:
        print(f"  ~ {kind}: 可用源不足，跳过比对")

    return problems, warnings


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
    all_warnings: list[str] = []
    for kind, local_rel, r2_url, cf_url in FILES:
        probs, warns = check_file(kind, local_rel, r2_url, cf_url, args.quiet)
        all_problems.extend(probs)
        all_warnings.extend(warns)

    # P1-b: WARN 汇总段重复计数(「primary 滞后靠后续候选救回」不阻断但必须醒目可见,
    # 防 8-19 R2 被渠道树覆盖类事故在唯一探针处静默滑过)
    if all_warnings:
        print()
        print(f"=== {len(all_warnings)} 条 WARN(primary 树滞后, 判据仍 PASS) ===")
        for w in all_warnings:
            print(f"  ⚠️ {w}")

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
