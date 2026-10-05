#!/usr/bin/env python3
"""check_r2_consistency.py - R2 产物多源一致性审计（P2-2）

比对 local static-site/data/ 与远端各到达路径（R2 直链 / CF r2-proxy / 主站同源）
关键数据产物指纹，防 159335 类多版本不一致事故（§22 数据一致性铁律）。

非 deploy 前置（需网络），作定期监控任务跑（2026-10-05 #160 起由云上
trade-r2-consistency.timer 每日拉取，经 scripts/check_r2_consistency.sh 包装）。

用法:
  python scripts/check_r2_consistency.py              # 全量比对
  python scripts/check_r2_consistency.py --quiet      # 仅告警输出

退出码: 0=各源一致, 1=有不一致或网络错误
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import ssl
import sys
import time
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
TIMEOUT = 25
# 传输用 Accept-Encoding: gzip(2026-10-05 #160 接线实测):云上(阿里云境内)→ CF 边缘
# 未压缩下载极慢(concepts 32.3MB 需 95s;identity 下行 ~0.34MB/s),全量四源裸跑 >12min。
# gzip 后同文件 7.6MB / 7s(CF 对 application/json 自动压缩),全量降到 ~1-2min。
# TIMEOUT=25:境内首包 TTFB 抖动可达 12-14s(实测),socket 级超时留余量。
# track_score 跨源容差（同 build 产物应完全一致，留 0.01 防 JSON float repr 误差）
FLOAT_TOLERANCE = 0.01

# 受检文件: (显示名, 本地相对路径, [(源标签, URL), ...])
# 源标签 = 三站展示面的三条到达路径(§22「用户在 N 个展示位看到的数据必须统一」):
#   R2   = R2 直链      ssd.fx8.store/data/…      (origin, R2 自定义域, 全站数据源)
#   CF   = CF r2-proxy  ss.fx8.store/r2/data/…    (前端 _R2_DATA_BASE, 备站+主站回退读法)
#   MAIN = 主站同源     ss.fx8.store/data/…       (CF Workers rewrite→R2, 主站用户实际 fetch
#          的 ./data/ 面; 2026-10-05 #160 补——此前只查 R2 直链+/r2/ 代理, 主站 rewrite 路径零校验)
# 备站 sss.sugas.site(gh-pages)/ s.sugas.site 不直接服务 /data/(2026-10-05 实测均 404),
#   前端走 _R2_DATA_BASE 与主站回退面取数 → 无需独立腿, 由 CF/MAIN 两腿覆盖;
#   主站 rewrite 断链(历史 deploy.sh:168「R2 已上线但 CF 没拿到」类)由 MAIN 腿抓。
FILES = [
    (
        "overview",
        "overview.json",
        [
            ("R2", "https://ssd.fx8.store/data/overview.json"),
            ("CF", "https://ss.fx8.store/r2/data/overview.json"),
            ("MAIN", "https://ss.fx8.store/data/overview.json"),
        ],
    ),
    (
        "board_etf_map",
        "board_etf_map.json",
        [
            ("R2", "https://ssd.fx8.store/data/board_etf_map.json"),
            ("CF", "https://ss.fx8.store/r2/data/board_etf_map.json"),
            ("MAIN", "https://ss.fx8.store/data/board_etf_map.json"),
        ],
    ),
    (
        "concepts",
        "industry-all-concepts.json",
        # 只有 R2 直链 + CF /r2/ 两腿: 前端 concepts 读 ss.fx8.store/r2/industry/
        #   (app.js:25457 fetchJSON(_R2_DATA_BASE 系) 同一路径), worker 无 /industry/ rewrite
        #   (headers.js 只截 /data/* 与 /r2/*), 主站 /industry/ 面真实 404 → 无 MAIN 腿。
        #   2026-10-05 云上实测: 误加 MAIN 腿会报 concepts 404 假阳,已按实测路由移除。
        [
            ("R2", "https://ssd.fx8.store/industry/industry-all-concepts.json"),
            ("CF", "https://ss.fx8.store/r2/industry/industry-all-concepts.json"),
        ],
    ),
    # overfit_monitor 主+ext(2026-08-25 监控盲区收尾批补入): 首页 AI 监控卡盘后核心产物,
    # 2026-08-24 B拆分起走 R2 /data/ 前缀(upload_r2 _OVERFIT_FORCE), 此前审计不查
    # 本地 vs R2 一致性=盲区。指纹=generated_at+综合风险分三件套(主)/键集(ext)。
    (
        "overfit_monitor",
        "overfit_monitor.json",
        [
            ("R2", "https://ssd.fx8.store/data/overfit_monitor.json"),
            ("CF", "https://ss.fx8.store/r2/data/overfit_monitor.json"),
            ("MAIN", "https://ss.fx8.store/data/overfit_monitor.json"),
        ],
    ),
    (
        "overfit_monitor_ext",
        "overfit_monitor_ext.json",
        [
            ("R2", "https://ssd.fx8.store/data/overfit_monitor_ext.json"),
            ("CF", "https://ss.fx8.store/r2/data/overfit_monitor_ext.json"),
            ("MAIN", "https://ss.fx8.store/data/overfit_monitor_ext.json"),
        ],
    ),
    # 次日买入计划(PRD 阶段一, 2026-09-10 F1 补入): 盘后 nextday_plan_generator.py →
    # upload_r2 upload-data-files 上传 /data/ 前缀。指纹=date+|empty/plan 首条 etf_code+buy_date
    # (空计划 {date, empty:true} 合法, 指纹含 empty 标志同态比对; 三版本不一致=CDN/容器滞留旧计划)。
    (
        "nextday_plan",
        "nextday_plan.json",
        [
            ("R2", "https://ssd.fx8.store/data/nextday_plan.json"),
            ("CF", "https://ss.fx8.store/r2/data/nextday_plan.json"),
            ("MAIN", "https://ss.fx8.store/data/nextday_plan.json"),
        ],
    ),
    # auto_trade_steps(PRD 阶段一执行链, 2026-09-11 #98 F1b 补入): 与 nextday_plan 同批生成,
    # 仅在 steps 有变更时随 upload-data-files 上传 /data/ 前缀。指纹=schema_version+steps 条数+
    # 最新执行日(date)+首条 etf_code(条数/日期变即指纹变, 定位 CDN 滞留旧执行链)。
    (
        "auto_trade_steps",
        "auto_trade_steps.json",
        [
            ("R2", "https://ssd.fx8.store/data/auto_trade_steps.json"),
            ("CF", "https://ss.fx8.store/r2/data/auto_trade_steps.json"),
            ("MAIN", "https://ss.fx8.store/data/auto_trade_steps.json"),
        ],
    ),
    # signal_kelly_day_snapshot(首页历史信号冻结快照, 2026-09-23 信号漂移根治 commit 9a546256f 新增,
    # P2-F2 reviewer 补入): 与 nextday_plan 同批由 nextday_plan_generator.py 生成,
    # 无条件随 upload-data-files 上传 /data/ 前缀。指纹=schema_version+days 天数+最新固化日+
    # 最新日条目数+首条 index_id/signal/etf_code/track_score(快照固化即定格, 天数/最新日/首条
    # 任一漂移=版本错位或重算覆盖固化, 定位 CDN/容器滞留旧快照)。
    (
        "signal_kelly_day_snapshot",
        "signal_kelly_day_snapshot.json",
        [
            ("R2", "https://ssd.fx8.store/data/signal_kelly_day_snapshot.json"),
            ("CF", "https://ss.fx8.store/r2/data/signal_kelly_day_snapshot.json"),
            ("MAIN", "https://ss.fx8.store/data/signal_kelly_day_snapshot.json"),
        ],
    ),
    # accum_nav_map 全量(凯利 G/H/I 强平日真实净值, 2026-09-17 懒加载保留全量作回测源+对账对象+
    # 回退兜底): 走 data-large(data/ 前缀)。三版本一致性指纹=n_codes+首/中/末 code 抽样
    # (同日生成逐位一致, 任一版本滞留=报)。
    (
        "accum_nav_map",
        "accum_nav_map.json",
        [
            ("R2", "https://ssd.fx8.store/data/accum_nav_map.json"),
            ("CF", "https://ss.fx8.store/r2/data/accum_nav_map.json"),
            ("MAIN", "https://ss.fx8.store/data/accum_nav_map.json"),
        ],
    ),
]


def _fetch_json(url: str) -> tuple[object, str | None]:
    """HTTP 拉 JSON，返回 (data, error)。用 certifi 证书（macOS Python 自带 SSL 证书不全）。

    transient 网络错误(CF 边缘冷回源偶发 >12s, 2026-10-05 实测 signal_kelly CF 腿
    12s 超时一次)重试 2 次再判失败——网络抖动不升级为「拉取失败」假警(§123 降噪),
    真故障(持续不可达)重试后仍报, 判别维度不丢。
    """
    last = ""
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "check_r2_consistency/1.0", "Accept-Encoding": "gzip"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL_CTX) as resp:
                raw = resp.read()
                if (resp.headers.get("Content-Encoding", "") or "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8")), None
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if attempt == 0:
                time.sleep(2)
    return None, last


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
    elif kind == "nextday_plan":
        # 次日买入计划(2026-09-10 F1): 指纹=date + empty/plan 首条 etf_code+buy_date。
        # 空计划 {date, empty:true} 合法, 指纹含 empty 标志同态比对; 非空取首条足够定位
        # CDN/容器滞留旧计划(plan 内容错位=date 或 empty 至少一个变, 空→非空/非空→空必现)。
        fp["date"] = data.get("date")
        fp["empty"] = data.get("empty")
        plan = data.get("plan")
        if isinstance(plan, list) and plan and isinstance(plan[0], dict):
            fp["p0_code"] = plan[0].get("etf_code")
            fp["p0_buy"] = plan[0].get("buy_date")
    elif kind == "auto_trade_steps":
        # 执行链(2026-09-11 #98 F1b): 指纹=schema_version + steps 条数 + 最新执行日 + 首条 etf_code。
        # steps 条数/日期任一变即指纹变(追加链/回填/迁移都会改变), 定位 CDN 滞留旧执行链。
        fp["schema_version"] = data.get("schema_version")
        steps = data.get("steps")
        if isinstance(steps, list):
            fp["steps_n"] = len(steps)
            dates = [s.get("date") for s in steps if isinstance(s, dict) and s.get("date")]
            if dates:
                fp["latest_date"] = max(dates)
            if steps and isinstance(steps[0], dict):
                fp["p0_code"] = steps[0].get("etf_code")
    elif kind == "signal_kelly_day_snapshot":
        # 首页历史信号冻结快照(2026-09-23 信号漂移根治 9a546256f 新增): 结构
        # {schema_version, days: {YYYYMMDD: [{index_id, signal, etf_code, etf_name,
        # track_score, rating, bk_ts, late, source}, ...]}}。快照固化即定格(已固化日期不覆盖),
        # 三版本一致性指纹=schema_version + days 天数 + 最新固化日 + 最新日条目数 +
        # 最新日首条(index_id/signal/etf_code/track_score)。任一漂移=版本错位或重算覆盖固化,
        # 定位 CDN/容器滞留旧快照或生成器重写已固化日。
        fp["schema_version"] = data.get("schema_version")
        days = data.get("days")
        if isinstance(days, dict):
            dates = sorted(str(k) for k in days.keys() if isinstance(k, (str, int)))
            fp["days_n"] = len(dates)
            if dates:
                fp["latest_date"] = dates[-1]
                # 当日(最新日)可能为空数组(固化当日无入样买信号, 合法态); p0 取最新非空日
                # 首条, 保证指纹总能探到实际内容漂移(CDN/容器滞留旧快照定位)。
                last_recs = days.get(dates[-1])
                if isinstance(last_recs, list):
                    fp["latest_n"] = len(last_recs)
                src_recs = last_recs if (isinstance(last_recs, list) and last_recs) else None
                if not src_recs:
                    for _d in reversed(dates):
                        _r = days.get(_d)
                        if isinstance(_r, list) and _r:
                            src_recs = _r
                            break
                if src_recs and isinstance(src_recs[0], dict):
                    r0 = src_recs[0]
                    fp["p0_index"] = r0.get("index_id")
                    fp["p0_signal"] = r0.get("signal")
                    fp["p0_code"] = r0.get("etf_code")
                    fp["p0_score"] = r0.get("track_score")
    elif kind == "accum_nav_map":
        # accum_nav_map.json {etf_code: {YYYYMMDD: accum_nav}}(凯利 G/H/I 强平日真实净值全量,
        # 2026-09-17 懒加载保留全量作回测源+对账对象+回退兜底)。三版本一致性指纹:
        # n_codes + 确定性抽样(首/中/末 code)日期数+最新日净值, 追三版本漂移(CDN/容器滞留旧 map)。
        # 同 etf/nav_bucket 拆分 dir 不同: 这是顶层 data/ 前缀单文件, 走三版本 spot-check(拆分 dir 由
        # check_data_integrity.check_accum_nav_split_consistency + upload_r2 verify-r2 _R2_CHANNELS 覆盖)。
        codes = sorted(data.keys()) if isinstance(data, dict) else []
        fp["n_codes"] = len(codes)
        if codes:
            for i in sorted({0, len(codes) // 2, len(codes) - 1}):
                c = codes[i]
                inner = data.get(c)
                if isinstance(inner, dict) and inner:
                    dates = sorted(inner.keys())
                    fp[f"{c}_ndates"] = len(dates)
                    fp[f"{c}_last"] = f"{dates[-1]}={inner[dates[-1]]}"
                else:
                    fp[f"{c}_empty"] = True
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


def check_file(kind: str, local_rel: str, remotes: list[tuple[str, str]], quiet: bool) -> tuple[list[str], list[str]]:
    """比对单文件多源指纹，返回 (问题行, WARN 行)。

    remotes = [(源标签, URL), ...]（R2 直链 / CF r2-proxy / 主站同源，见 FILES 头注释）。
    各远端网络错误单独报；local 候选与远端指纹逐项比对（_mismatches）。
    WARN(P1-b review 2026-08-25): 「primary 权威树滞后、后续候选与远端一致」判据仍 PASS
    (正常打点窗口合法滞后不误伤), 但该形态=2026-08-19 R2 被渠道树旧库覆盖的事故同款,
    唯一探针不可静默——独立 WARN 行+汇总段重复计数, 不进 problems 不阻断。
    """
    problems: list[str] = []
    remote_fps: dict[str, dict[str, object]] = {}
    for sname, url in remotes:
        data, err = _fetch_json(url)
        if err:
            problems.append(f"[{kind}] {sname} 拉取失败: {err}")
        elif data is not None:
            remote_fps[sname] = _fingerprint(data, kind)

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
            mismatch_report = f"[{kind}] 各源 track_score/top1 不一致: {'; '.join(mm[:5])} (local={cand})"

    warnings: list[str] = []
    if passed is not None:
        n_keys, cand = passed
        line = f"  ✓ {kind}: 各源一致 ({n_keys} 项指纹)"
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
        print("=== R2 产物多源一致性审计 ===")
        print(f"  local: {LOCAL_DATA}")
        print(f"  R2:    ssd.fx8.store/data")
        print(f"  CF:    ss.fx8.store/r2/data")
        print(f"  MAIN:  ss.fx8.store/data")
        print()

    all_problems: list[str] = []
    all_warnings: list[str] = []
    for kind, local_rel, remotes in FILES:
        probs, warns = check_file(kind, local_rel, remotes, args.quiet)
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
        print("=== 各源一致 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
