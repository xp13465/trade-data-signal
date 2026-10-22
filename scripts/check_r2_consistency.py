#!/usr/bin/env python3
"""check_r2_consistency.py - R2 产物多源一致性审计（P2-2）

**判定口径（2026-10-22 #279 用户拍板方案 A）**：两层分离
  - 判定层（决定退出码/告警等级）：三站两两互比 —— R2 直链 / CF r2-proxy / 主站同源。
    任两站不一致、或任一站 404/缺文件/读取失败 ⇒ FAIL（rc=1，真故障判别维度不丢）。
  - 提示层（不阻断）：local 源树 vs 三站差异，按方向分两种措辞（都不计 rc/不发告警）:
      · local 落后于三站 ⇒ `[INFO] local 落后于三站(部署可能未完成/被跳过)`
        （部署闸门跳过 rsync 时 local 滞后属常态症状）
      · local 领先三站 ⇒ `[WARN] local 领先三站(疑似上传漏传/滞后)`
        （local 有新版但三站还是旧版 = 上传链路漏传/传旧，方向相反必须明确提示）
      · 无可比时点字段或同时点内容漂移 ⇒ `[INFO] local 与三站不一致(方向不明)`，
        不硬扣「落后」帽子（旧口径对领先也报「未同步」，方向反且无提示，#279 nits）。
    每轮 `[SUMMARY]` 追加 `local方向=落后|领先|一致`（方向不可判定时 `不明`）供事后核对。
    local 是 deploy 段1 rsync 的目标；旧口径把 local 当第 4 源直接比 ⇒ 误报 severe 连续
    2 天（#279）。提示层仍有价值：local 与三站不一致=部署链被掐断的真实症状，需要人看
    但不该发告警。

非 deploy 前置（需网络），作定期监控任务跑（2026-10-05 #160 起由云上
trade-r2-consistency.timer 每日拉取，经 scripts/check_r2_consistency.sh 包装）。

用法:
  python scripts/check_r2_consistency.py              # 全量比对
  python scripts/check_r2_consistency.py --quiet      # 仅问题/提示/摘要输出

退出码: 0=三站一致（local 差异仅提示）, 1=三站不一致或某站不可读
"""
from __future__ import annotations

import argparse
import gzip
import itertools
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
# 未压缩下载极慢(concepts 32.3MB 需 95s;identity 下行 ~0.34MB/s),全量三站裸跑 >12min。
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


def _mismatches(fps: dict[str, dict[str, object]],
                strict_presence: bool = False) -> tuple[list[tuple[str, dict[str, object]]], int]:
    """跨源指纹 union key 逐项比对，返回 ([(key, {源: 值}) ...], 参比指纹项数)。空列表=一致。

    strict_presence=True（三站互比）: 某字段只在一站存在（另一站缺该键）也算不一致——
    三站本应完全一致，键集不对称=版本错位，不能当「版本差异字段」放过（#279 红线：
    不得吞真三站漂移）。local 差异对照保持宽松（键集不对称只进 INFO 提示层）。
    """
    all_keys: set[str] = set()
    for fp in fps.values():
        all_keys.update(fp.keys())
    mismatches: list[tuple[str, dict[str, object]]] = []
    for key in sorted(all_keys):
        vals = {sname: fp.get(key) for sname, fp in fps.items()}
        present = {s: v for s, v in vals.items() if v is not None}
        if len(present) < 2:
            if strict_presence and len(present) == 1:
                mismatches.append((key, present))
            continue
        ref_s, ref_v = next(iter(present.items()))
        for s, v in present.items():
            if not _values_equal(ref_v, v):
                mismatches.append((key, present))
                break
    return mismatches, len(all_keys)


def _fp_usable(fp: dict[str, object]) -> bool:
    """指纹是否有可判定值。全 None(如空壳 {} 只剩 date=None)= 产物结构不可用,
    不能参与「一致」判定(否则空壳会被当成与任何版本一致而静默放过)。"""
    return any(v is not None for v in fp.values())


def _fmt_station_diff(mm: list[tuple[str, dict[str, object]]], a: str, b: str) -> str:
    """把两站不一致明细格式化为「哪两站 + 哪个字段 + 两边值」。"""
    parts = []
    for key, vals in mm[:5]:
        parts.append(f"{key}: {a}={vals.get(a)!r} vs {b}={vals.get(b)!r}")
    return "; ".join(parts)


def _fmt_local_diff(mm: list[tuple[str, dict[str, object]]], ref: str,
                    ref_fp: dict[str, object]) -> str:
    """把 local 差异明细格式化（三站基准值 vs local 值），最多 5 项。"""
    parts = []
    for key, vals in mm[:5]:
        parts.append(f"{key}: 三站({ref})={ref_fp.get(key)!r} vs local={vals.get('local')!r}")
    return "; ".join(parts)


# local 差异方向判定（#279 nits）: 只读指纹里已有的「时点字段」，不改指纹函数口径。
# 无可比时点字段的产物（board_etf_map/concepts/accum_nav_map 指纹只有 code→track_score）
# 方向不可判定 ⇒ 诚实报「方向不明」，不硬扣「落后」帽子。
_RECENCY_KEYS: dict[str, tuple[str, ...]] = {
    "overview": ("date",),
    "overfit_monitor": ("generated_at",),
    "overfit_monitor_ext": ("generated_at",),
    "nextday_plan": ("date",),
    "auto_trade_steps": ("latest_date",),
    "signal_kelly_day_snapshot": ("latest_date",),
}


def _recency(kind: str, fp: dict[str, object]) -> int | None:
    """取指纹内时点字段的可比较值（抽数字比较，兼容 20261021 / 2026-10-21T21:40:00）。"""
    for key in _RECENCY_KEYS.get(kind, ()):
        val = fp.get(key)
        if val is None:
            continue
        digits = "".join(ch for ch in str(val) if ch.isdigit())
        if digits:
            return int(digits)
    return None


def _local_direction(kind: str, ref_fp: dict[str, object],
                     local_fp: dict[str, object]) -> str:
    """local 相对三站的方向: lag(落后) / lead(领先) / unknown(不可判定)。"""
    ref, loc = _recency(kind, ref_fp), _recency(kind, local_fp)
    if ref is None or loc is None or ref == loc:
        return "unknown"
    return "lead" if loc > ref else "lag"


def check_file(kind: str, local_rel: str, remotes: list[tuple[str, str]],
               quiet: bool) -> tuple[list[str], list[str], list[str], str]:
    """比对单文件指纹，返回 (problems, warnings, infos, local_state)。

    两层划分（#279 方案 A）:
      - problems（判定层，决定 rc/告警）: 三站两两互比不一致；任一站 404/缺文件/读取失败；
        站点可读但指纹为空（结构异常，等同不可用）。真故障判别维度不允许被降噪吞掉。
      - infos（提示层，不阻断）: local 落后于三站 / 方向不明 / local 读取失败或结构异常。
        部署链被闸门掐断跳过 rsync 时 local 滞后属常态症状，用户侧三站无损 ⇒ 只提示不发告警。
      - warnings（提示层强化，不阻断）: overfit 双树里 primary 滞后、后续候选与三站一致
        （2026-08-19 R2 被渠道树旧库覆盖事故同款形态的唯一探针，必须醒目可见）；
        local 领先三站（上传漏传/传旧，方向与「落后」相反，必须明确 WARN）。
      - local_state: 一致 / 落后 / 领先 / 不明（供 [SUMMARY] 汇总，不影响 rc）。

    remotes = [(源标签, URL), ...]（R2 直链 / CF r2-proxy / 主站同源，见 FILES 头注释）。
    """
    problems: list[str] = []
    infos: list[str] = []
    local_state = "一致"
    remote_fps: dict[str, dict[str, object]] = {}
    for sname, url in remotes:
        data, err = _fetch_json(url)
        if err:
            problems.append(f"[{kind}] {sname} 拉取失败: {err}")
            continue
        if data is None:
            # json.loads("null") 可成功返回 None —— 产物文件为空/不可用, 与读取失败同类对待
            problems.append(f"[{kind}] {sname} 读取失败: 内容为空(JSON null)")
            continue
        fp = _fingerprint(data, kind)
        if not _fp_usable(fp):
            # 可读但指纹无可判定值 = 数据结构不是预期产物(如空壳 {}), 不能当「一致」放过
            problems.append(f"[{kind}] {sname} 指纹为空(数据结构异常/产物为空)")
            continue
        remote_fps[sname] = fp

    # ── 判定层: 三站两两互比（R2 vs CF、R2 vs MAIN、CF vs MAIN）──
    station_names = [n for n, _ in remotes if n in remote_fps]
    for a, b in itertools.combinations(station_names, 2):
        mm, _ = _mismatches({a: remote_fps[a], b: remote_fps[b]}, strict_presence=True)
        if mm:
            problems.append(
                f"[{kind}] 三站不一致 {a}≠{b}: {_fmt_station_diff(mm, a, b)}"
            )

    # ── 提示层: local 源树 vs 三站（基准取首个可用站, FILES 顺序 R2 优先）──
    warnings: list[str] = []
    loaded: list[tuple[Path, object, str | None]] = [
        (cand, *_load_local(cand)) for cand in _local_candidates(kind, local_rel)
    ]
    readable = [(cand, data) for cand, data, err in loaded if err is None]
    usable: list[tuple[Path, dict[str, object]]] = []
    for cand, data in readable:
        fp = _fingerprint(data, kind)
        if not _fp_usable(fp):
            infos.append(f"[{kind}] local 结构异常(指纹为空, 不计入判定, 方向不明): {cand}")
            local_state = "不明"
            continue
        usable.append((cand, fp))
    if not readable:
        err_detail = next((err for _, _, err in loaded if err), "无候选路径")
        infos.append(f"[{kind}] local 读取失败(不计入判定, 方向不明): {err_detail}")
        local_state = "不明"
    elif remote_fps and usable:
        ref_name, ref_fp = next(iter(remote_fps.items()))
        matched: tuple[int, Path] | None = None   # (指纹项数, 命中路径)
        lagged_primary: Path | None = None        # 先于命中路径出现的不一致候选(滞后树)
        first_diff: tuple[list[tuple[str, dict[str, object]]], Path, dict[str, object]] | None = None
        for cand, lfp in usable:
            mm, n_keys = _mismatches({ref_name: ref_fp, "local": lfp})
            if not mm:
                matched = (n_keys, cand)
                break
            if lagged_primary is None:
                lagged_primary = cand
                first_diff = (mm, cand, lfp)
        if matched is not None:
            n_keys, cand = matched
            # 双树探测: 前一候选结构异常/滞后但后续候选与三站一致 ⇒ local 实际同步,
            # 方向回到「一致」(异常明细仍保留在 INFO/WARN 里供人看)
            local_state = "一致"
            if lagged_primary is not None:
                warnings.append(
                    f"[{kind}] primary({lagged_primary}) 滞后于三站(一致候选={cand})"
                    "——若非刚打点窗口期(21:40 后短窗口属合法滞后), 请人工核查是否渠道树旧库覆盖事故"
                )
            if not quiet:
                line = f"  ✓ {kind}: 三站一致 ({n_keys} 项指纹) [local 同步]"
                if len(usable) > 1:
                    line += f" [local={cand}]"
                print(line)
        else:
            assert first_diff is not None
            mm, cand, lfp = first_diff
            direction = _local_direction(kind, ref_fp, lfp)
            detail = f"{_fmt_local_diff(mm, ref_name, ref_fp)} (local={cand})"
            if direction == "lead":
                # local 有新版、三站还是旧版 = 上传漏传/传旧，与「落后」方向相反，必须明确 WARN
                warnings.append(
                    f"[WARN] [{kind}] local 领先三站(疑似上传漏传/滞后): {detail}"
                )
                local_state = "领先"
            elif direction == "lag":
                infos.append(
                    f"[{kind}] local 落后于三站(部署可能未完成/被跳过): {detail}"
                )
                local_state = "落后"
            else:
                # 无可比时点字段(board_etf_map/concepts/accum_nav_map)或同时点内容漂移:
                # 判不出先后就报「方向不明」，不硬扣「落后」帽子（#279 nits）
                infos.append(
                    f"[{kind}] local 与三站不一致(方向不明: 无可比时点字段或同时点内容漂移): {detail}"
                )
                local_state = "不明"

    if problems and not quiet:
        print(f"  ✗ {kind}: 三站不一致/不可读(详见问题段)")
    for info in infos:
        # 提示层始终输出（含 --quiet）：部署链症状需要日志可追溯, 但绝不进判定/告警
        print(f"[INFO] {info}")

    return problems, warnings, infos, local_state


def main() -> int:
    parser = argparse.ArgumentParser(description="R2 产物三站一致性审计")
    parser.add_argument("--quiet", action="store_true", help="仅输出问题/提示/摘要")
    args = parser.parse_args()

    if not args.quiet:
        print("=== R2 产物三站一致性审计(判定=三站互比, local 差异仅提示) ===")
        print(f"  local: {LOCAL_DATA}(提示层, 不参与判定)")
        print(f"  R2:    ssd.fx8.store/data")
        print(f"  CF:    ss.fx8.store/r2/data")
        print(f"  MAIN:  ss.fx8.store/data")
        print()

    all_problems: list[str] = []
    all_warnings: list[str] = []
    station_ok = 0
    local_diff = 0
    local_states: list[str] = []
    for kind, local_rel, remotes in FILES:
        probs, warns, infos, state = check_file(kind, local_rel, remotes, args.quiet)
        all_problems.extend(probs)
        all_warnings.extend(warns)
        local_states.append(state)
        if not probs:
            station_ok += 1
        if infos or state in ("领先", "落后"):
            local_diff += 1

    # P1-b: WARN 汇总段重复计数(「primary 滞后靠后续候选救回」不阻断但必须醒目可见,
    # 防 8-19 R2 被渠道树覆盖类事故在唯一探针处静默滑过；local 领先三站同属必须醒目项)
    if all_warnings:
        print()
        print(f"=== {len(all_warnings)} 条 WARN(local 领先 / primary 树滞后, 三站判据仍 PASS) ===")
        for w in all_warnings:
            # local 领先行自带 [WARN] 前缀(用户/日志检索锚点)，primary 滞后维持 ⚠️ 形式
            print(w if w.startswith("[WARN] ") else f"  ⚠️ {w}")

    # 每轮一行摘要(历史可追溯): 三站一致文件数 / local 差异文件数 / local 方向 / 结果。
    # 方向聚合优先级: 领先(WARN 级) > 落后 > 不明 > 一致。
    # 注意: 本脚本比对的是指纹字段而非整文件 md5(见 _fingerprint), 摘要口径与之一致。
    if "领先" in local_states:
        local_direction = "领先"
    elif "落后" in local_states:
        local_direction = "落后"
    elif "不明" in local_states:
        local_direction = "不明"
    else:
        local_direction = "一致"
    result = "FAIL" if all_problems else "PASS"
    print()
    print(f"[SUMMARY] 文件={len(FILES)} 三站一致={station_ok}/{len(FILES)} "
          f"local差异={local_diff} local方向={local_direction} 结果={result}")

    if all_problems:
        print()
        print(f"=== {len(all_problems)} 项问题 ===")
        for p in all_problems:
            print(f"  ✗ {p}")
        return 1
    if not args.quiet:
        print()
        print("=== 三站一致(local 差异仅提示) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
