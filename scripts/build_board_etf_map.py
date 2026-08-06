#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 data/board_etf_map.json：行业/概念 -> 相关 ETF 候选列表（按成交额降序）。

设计原则（对齐用户诉求）：
  - 匹配到多个就全列出来，按成交额（流动性）降序，让用户在前端自选；
  - 匹配不到就留空数组（不再硬塞"代理"ETF，避免名称对不上误导用户）；
  - 关键词尽量精准（避免"消费"误匹配消费电子、"设备"误匹配半导体设备）；
  - 排除跨境/债券/商品/货币等非行业主题 ETF。

数据源：akshare fund_etf_spot_em()（A 股场内 ETF 实时行情，含成交额/流通市值）。
可重复跑：python scripts/build_board_etf_map.py，覆盖 data/board_etf_map.json。
"""
import json
import sqlite3
import sys
from pathlib import Path

import akshare as ak

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))
from app.collector.fetchers import load_config
from app.collector.overlap_fetcher import match_overlap as _overlap_match

OUT = ROOT / "data" / "board_etf_map.json"

# 每个板块的匹配关键词（同义词，ETF 名称命中任一即候选；空列表 = 主动留空）
KW: dict[str, list[str]] = {
    # ---- 申万一级行业 ----
    "sw_801010": ["农林", "农牧", "养殖", "农业", "牧渔"],
    "sw_801030": ["化工"],
    "sw_801040": ["钢铁"],
    "sw_801050": ["有色"],
    "sw_801080": ["电子"],
    "sw_801880": ["汽车", "新能源车"],
    "sw_801110": ["家电"],
    "sw_801120": ["食品", "酒", "饮料"],
    "sw_801130": ["纺织", "服装", "服饰"],
    "sw_801140": ["轻工", "造纸", "家居", "文娱"],
    "sw_801150": ["医药", "医疗", "生物", "创新药", "中药"],
    "sw_801160": ["公用事业"],
    "sw_801170": ["交通", "运输"],
    "sw_801180": ["房地产", "地产"],
    "sw_801200": ["商贸", "零售", "百货", "商业"],
    "sw_801210": ["旅游", "社服"],
    "sw_801780": ["银行"],
    "sw_801790": ["证券", "保险", "非银"],
    "sw_801230": [],  # 综合行业无专门 ETF，主动留空
    "sw_801710": ["建材"],
    "sw_801720": ["建筑", "基建", "装饰"],
    "sw_801730": ["电力设备", "电池", "光伏", "风电", "储能", "新能源"],
    "sw_801890": ["机械", "工程机械", "机床"],
    "sw_801740": ["军工", "国防"],
    "sw_801750": ["计算机", "软件", "信息技术"],
    "sw_801760": ["传媒", "媒体", "游戏"],
    "sw_801770": ["通信"],
    "sw_801950": ["煤炭"],
    "sw_801960": ["石油", "石化"],
    "sw_801970": ["环保"],
    "sw_801980": ["美容", "护理", "化妆品"],
    # ---- 同花顺概念 ----
    "thsc_300816": ["机器人"],
    "thsc_309119": ["机器人"],
    "thsc_308700": ["碳化硅", "氮化镓", "宽禁带", "第三代"],  # 收紧：无专门ETF则留空
    "thsc_309049": ["CPO", "光通信", "光模块", "光子"],
    "thsc_301085": ["芯片", "半导体"],
    "thsc_307940": ["存储芯片", "存储"],
    "thsc_302035": ["人工智能", "AI"],
    "thsc_309068": ["算力", "数据中心", "IDC"],
    "thsc_308828": ["算力", "数据中心", "IDC"],
    "thsc_309020": ["信创", "信息技术应用"],
    "thsc_309060": ["数据"],
    "thsc_300008": ["新能源车", "汽车"],  # 收紧：去掉"新能源"(命中创业板新能源/科创新能源等非汽车主题，误差大)；保留"新能源车"(515030等直接新能源车ETF)+"汽车"(159565汽车零部件等贴合走势)
    "thsc_301079": ["光伏"],
    "thsc_300733": ["电池", "锂电"],
    "thsc_306380": ["储能"],
    "thsc_308294": ["固态", "电池"],
    "thsc_309115": ["低空", "通用航空", "eVTOL"],
    "thsc_308014": ["创新药", "医药"],
    "thsc_300082": ["军工", "国防"],
    "thsc_300830": ["量子"],
    "thsc_308725": ["汽车芯片", "车芯片"],  # 收紧：无专门ETF则留空
    "thsc_308300": ["MCU", "单片机"],       # 收紧：无专门ETF则留空
    "thsc_309113": ["eVTOL", "飞行汽车", "通用航空"],
    "thsc_308491": ["氢能", "氢"],
    "thsc_308870": ["数字经济"],
    "thsc_308752": ["元宇宙", "虚拟现实", "VR", "增强现实", "AR", "游戏"],  # 加"游戏"：159869游戏ETF华夏(8.13亿)归申万传媒(sw_801760)但贴合元宇宙走势，误差0.08%；不加"传媒"避免命中泛传媒ETF
    "thsc_309128": ["军工", "国防", "信息化"],
}

# ───────────────────────────────────────────────────────────────────
# track_index_name 关键词匹配（fundf10 抓取的 ETF 跟踪指数名，比 ETF 名称更精准）。
# 优先级：track_index_name > overlap 成分股 > KW 名称子串。
# 行业/概念匹配均标 approx=true（ETF 跟踪中证/国证指数，非申万一级/同花顺概念精准跟踪）。
#
# track_index_name 例：515880 track_index="中证全指通信设备指数"，比 ETF 名"通信ETF国泰"
# 更精准（暴露实际跟踪的中证全指指数，非申万通信 sw_801770）。
#
# include：track_index_name 命中任一即候选；
# exclude：命中任一排除（精度过滤，如 sw_801880 汽车 排除"新能源汽车/智能汽车"）。
# ───────────────────────────────────────────────────────────────────
TRACK_INDEX_KW: dict[str, dict] = {
    # ---- 申万一级行业 ----
    "sw_801010": {"include": ["农业", "农牧", "养殖", "渔业", "牧渔"], "exclude": []},
    "sw_801030": {"include": ["化工"], "exclude": []},
    "sw_801040": {"include": ["钢铁"], "exclude": []},
    "sw_801050": {"include": ["有色金属"], "exclude": []},
    "sw_801080": {"include": ["电子"], "exclude": ["消费电子"]},  # 申万电子 vs 消费电子
    "sw_801880": {"include": ["汽车"], "exclude": ["新能源汽车", "智能汽车", "新能源车"]},
    "sw_801110": {"include": ["家电"], "exclude": []},
    "sw_801120": {"include": ["食品", "酒", "饮料"], "exclude": []},
    "sw_801130": {"include": ["纺织", "服装", "服饰"], "exclude": []},
    "sw_801140": {"include": ["轻工", "家居", "造纸", "文娱"], "exclude": ["传媒"]},  # 排除传媒(516190 中证文娱传媒指数误匹配)
    "sw_801150": {"include": ["医药", "医疗", "生物", "创新药", "中药"], "exclude": []},
    "sw_801160": {"include": ["公用事业"], "exclude": []},
    "sw_801170": {"include": ["交通", "运输"], "exclude": []},
    "sw_801180": {"include": ["房地产", "地产"], "exclude": []},
    "sw_801200": {"include": ["商贸", "零售", "商业", "百货"], "exclude": []},
    "sw_801210": {"include": ["旅游", "社服"], "exclude": []},
    "sw_801780": {"include": ["银行"], "exclude": []},
    "sw_801790": {"include": ["证券", "保险", "非银"], "exclude": []},
    "sw_801710": {"include": ["建筑材料", "建材"], "exclude": []},
    "sw_801720": {"include": ["建筑", "基建"], "exclude": ["建筑材料", "建材"]},
    "sw_801730": {"include": ["电力设备", "光伏", "风电", "储能", "电池", "新能源"],
                  "exclude": ["新能源汽车", "新能源车"]},
    "sw_801890": {"include": ["机械", "工程机械", "机床"], "exclude": []},
    "sw_801740": {"include": ["军工", "国防"], "exclude": []},
    "sw_801750": {"include": ["计算机", "软件", "信息技术"], "exclude": []},
    "sw_801760": {"include": ["传媒", "游戏", "动漫"], "exclude": []},
    "sw_801770": {"include": ["通信"], "exclude": []},
    "sw_801950": {"include": ["煤炭"], "exclude": []},
    "sw_801960": {"include": ["石油", "石化"], "exclude": []},
    "sw_801970": {"include": ["环保"], "exclude": []},
    "sw_801980": {"include": ["美容", "护理", "化妆品"], "exclude": []},
    "sw_801230": {"include": [], "exclude": []},  # 综合行业无 ETF，留空
    # ---- 同花顺概念 ----
    "thsc_300816": {"include": ["机器人"], "exclude": []},
    "thsc_309119": {"include": ["机器人"], "exclude": []},
    "thsc_308700": {"include": ["半导体", "芯片", "碳化硅", "氮化镓", "宽禁带"], "exclude": []},
    "thsc_309049": {"include": ["光通信", "光模块", "CPO", "光子"], "exclude": []},
    "thsc_301085": {"include": ["芯片", "半导体"], "exclude": []},
    "thsc_307940": {"include": ["存储芯片", "存储"], "exclude": []},
    "thsc_302035": {"include": ["人工智能"], "exclude": []},
    "thsc_309068": {"include": ["算力", "云计算", "数据中心"], "exclude": []},
    "thsc_308828": {"include": ["算力", "云计算", "数据中心"], "exclude": []},
    "thsc_309020": {"include": ["信创", "信息技术创新"], "exclude": []},
    "thsc_309060": {"include": ["数据", "大数据"], "exclude": []},
    "thsc_300008": {"include": ["新能源汽车"], "exclude": []},
    "thsc_301079": {"include": ["光伏"], "exclude": []},
    "thsc_300733": {"include": ["电池", "锂电"], "exclude": []},
    "thsc_306380": {"include": ["储能"], "exclude": []},
    "thsc_308294": {"include": ["固态电池", "电池"], "exclude": []},
    "thsc_309115": {"include": ["低空", "通用航空", "eVTOL"], "exclude": []},
    "thsc_308014": {"include": ["创新药", "医药"], "exclude": []},
    "thsc_300082": {"include": ["军工", "国防"], "exclude": []},
    "thsc_300830": {"include": ["量子"], "exclude": []},  # 大概率无 ETF，fallback overlap
    "thsc_308725": {"include": ["汽车芯片"], "exclude": []},
    "thsc_308300": {"include": ["MCU", "单片机"], "exclude": []},
    "thsc_309113": {"include": ["eVTOL", "飞行汽车", "通用航空"], "exclude": []},
    "thsc_308491": {"include": ["氢能", "氢"], "exclude": []},
    "thsc_308870": {"include": ["数字经济"], "exclude": []},
    "thsc_308752": {"include": ["元宇宙", "虚拟现实", "动漫游戏", "游戏"], "exclude": []},
    "thsc_309128": {"include": ["军工", "国防"], "exclude": []},
}

# ETF track_index 缓存路径（fundf10 抓取，scripts/fetch_etf_track_index.py 生成）
ETF_TRACK_INDEX_PATH = ROOT / "data" / "etf_track_index.json"

# 排除词：跨境/债券/商品/货币等非 A 股行业主题 ETF
EXCLUDE = ["债", "货币", "黄金", "白银", "原油", "海外", "美国", "日本", "德国",
           "法国", "英国", "韩国", "中韩", "亚太", "纳斯达克", "纳指", "标普", "日经",
           "恒生", "港股", "香港", "QDII", "商品", "豆粕", "REIT", "可转债",
           "国债", "信用", "MOM", "FOF"]

# P2-新-G ETF 联动推荐：宽基/红利/综合/港股指数 -> 跟踪 ETF 候选清单。
# 2026-07-28 方案D第二阶段：用 data/etf_index_map.json 自动采集替代原硬编码 INDEX_ETF_MAP。
#
# 数据源 data/etf_index_map.json（1555只ETF，ok=1228有track_index_code）：
#   结构 {etf_code: {name, track_index_name, track_index_code, track_index_ths_code, amount, status}}
#   建反向映射 {track_index_code: [etf_info列表]}，按指数ID->track_index_code 自动匹配 ETF 候选。
#
# 覆盖 14 个指数（bj50 北证50 无活跃跟踪ETF，留空，前端 _etf_for 返空数组不渲染 tag）：
#   A股宽基 8: sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50
#   红利指数 3: csi_div/div_lowvol/sz_div
#   港股指数 3: hsi/hstech/hscei（跨境ETF，cross_border=True 绕过 EXCLUDE 防御）
#
# 修正原硬编码 bug（2026-07-28）：
#   - hscei 原 513900 实跟踪"中华港股通精选100港元指数"（track_index_code 为空），非 HSCEI！
#     自动采集修正为 510900（恒生中国企业ETF易方达 1.16亿居首）。
#   - hsi 原 513600（0.86亿）非首位，自动采集首位 159920（恒生ETF华夏 4.83亿）。
#   - sz 原 159943（0.81亿）非首位，自动采集首位 159903（深成ETF南方 1.70亿）。
#
# 数据源污染过滤（name_eq 规则）：
#   - csi_div=000922 被"中证红利低波动100指数/中证红利价值指数/中证红利质量指数"共用 track_index_code，
#     需 track_index_name=="中证红利指数" 过滤（排除红利低波100等）。
#   - div_lowvol=930955 被"标普中国A股大盘红利低波50指数/国证港股通红利低波动率指数"共用，
#     需 track_index_name=="中证红利低波动指数" 过滤。
#
# approx 判定：ETF name 含"增强" -> True（增强型ETF，非纯被动跟踪）；否则 False（纯被动精准跟踪）。
# cross_border 判定：港股指数（HSI/HSTECH/HSCEI）-> True，name 含"恒生/港股"会命中 EXCLUDE，需绕过防御。
#
# 候选结构：list[dict]，每项 {"code": str, "name": str, "amount": float, "approx": bool}
#   name/amount 优先用 akshare fund_etf_spot_em() 实时值（df_by_code），查不到用 etf_index_map.json 的 amount。
#   按 amount 降序排（成交额大的居首，流动性最好）。
ETF_INDEX_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "etf_index_map.json"
# resolve() 解析 symlink：从 trade-data 跑时 scripts/ 是 symlink 指向 trade/scripts/，
# resolve() 后读 trade/data/etf_index_map.json（真实路径，前序任务生成在此）。


def _get_etf_db_path() -> Path:
    """ETF DB 路径：优先 trade-data/data/etf_national_team.db（主库，launchd 写），
    回退 trade/data/etf_national_team.db（镜像，deploy.sh rsync 同步）。
    与 simulate_trade.py _get_etf_db_path 策略一致。"""
    base = Path(__file__).resolve().parent.parent  # trade/
    main = base.parent / "trade-data" / "data" / "etf_national_team.db"
    if main.exists():
        return main
    return base / "data" / "etf_national_team.db"


# 指数ID -> {code: track_index_code, name_eq?: 过滤规则, cross_border?: bool} 映射
# code: 该指数跟踪的标准指数代码（etf_index_map.json 的 track_index_code 字段）
# name_eq: 可选，track_index_name 必须精确等于此值（过滤数据源污染）
# cross_border: 可选，True=港股跨境ETF（绕过 EXCLUDE 防御）
INDEX_TRACK_MAP: dict[str, dict] = {
    # ── A股宽基（track_index_code 无污染，直接匹配）──
    "sh":       {"code": "000001"},   # 上证综合指数（8个精准ETF，510210首位14.13亿）
    "sz":       {"code": "399001"},   # 深证成份指数（159903首位1.70亿/159943 0.81亿）
    "hs300":    {"code": "000300"},   # 沪深300（510300首位78.32亿）
    "sz50":     {"code": "000016"},   # 上证50（510050首位23.11亿）
    "csi500":   {"code": "000905"},   # 中证500（510500首位60.44亿）
    "csi1000":  {"code": "000852"},   # 中证1000（512100首位53.03亿）
    "cyb":      {"code": "399006"},   # 创业板指（159915首位127.93亿）
    "kc50":     {"code": "000688"},   # 科创50（588000首位109.59亿）
    # bj50: 899050 北证50，etf_index_map.json 无活跃跟踪ETF，不加入（留空）
    # ── 红利指数（track_index_code 有数据源污染，需 name_eq 过滤）──
    "csi_div":    {"code": "000922", "name_eq": "中证红利指数"},        # 中证红利（515180首位3.77亿）
    "div_lowvol": {"code": "930955", "name_eq": "中证红利低波动指数"},  # 红利低波（512890首位7.75亿）
    "sz_div":     {"code": "399324"},   # 深证红利（159905首位0.69亿，无污染）
    # ── 港股指数（跨境ETF，cross_border=True 绕过 EXCLUDE 防御）──
    "hsi":     {"code": "HSI", "cross_border": True},     # 恒生指数（159920首位4.83亿）
    "hstech":  {"code": "HSTECH", "cross_border": True},  # 恒生科技（513130首位31.24亿）
    "hscei":   {"code": "HSCEI", "cross_border": True},   # 恒生中国企业（510900首位1.16亿，修正原513900 bug）
}


def _load_etf_index_map_reverse() -> dict[str, list[dict]]:
    """读 data/etf_index_map.json，建反向映射 {track_index_code: [etf_info列表]}。

    返回 {track_index_code: [{code, name, amount, track_index_name}, ...]}（只含 status=ok 的 ETF）。
    resolve() 解析 symlink：从 trade-data 跑时读 trade/data/etf_index_map.json（真实路径）。

    读不到返回空 dict（非静默失败：调用方 main() 会走 _akshare_name_fallback 名称匹配兜底；
    若 akshare 也失败则 main() 末尾 14 宽基校验 exit 1，不静默覆盖空数组）。
    etf_index_map.json 由 scripts/gen_etf_index_map.py 生成，deploy.sh 前置调用刷新。
    """
    if not ETF_INDEX_MAP_PATH.exists():
        print(f"⚠ etf_index_map.json 不存在: {ETF_INDEX_MAP_PATH}，走 akshare 名称匹配兜底")
        return {}
    try:
        with open(ETF_INDEX_MAP_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"⚠ etf_index_map.json 读取失败: {e}，走 akshare 名称匹配兜底")
        return {}
    rev: dict[str, list[dict]] = {}
    for etf_code, info in d.items():
        if etf_code.startswith("_") or not isinstance(info, dict):
            continue
        tic = info.get("track_index_code") or ""
        if not tic:
            continue
        if info.get("status", "") != "ok":
            continue  # 跳过 parse_fail/no_track
        rev.setdefault(tic, []).append({
            "code": etf_code,
            "name": info.get("name", ""),
            "amount": info.get("amount", 0) or 0,
            "track_index_name": info.get("track_index_name", ""),
        })
    return rev


# akshare 名称匹配兜底规则（etf_index_map.json 缺失时用 fund_etf_spot_em 名称反推 track_index_code）。
# 与 gen_etf_index_map.py INDEX_NAME_RULES 同源，覆盖 14 指数（sz_div 主动留空）。
# akshare fund_etf_spot_em 不返回 track_index_code 字段，名称匹配是唯一反推方式。
_AKSHARE_NAME_RULES: dict[str, dict] = {
    "sh":        {"code": "000001", "include": ["上证指数", "上证综指", "上证综合"], "exclude": []},
    "sz":        {"code": "399001", "include": ["深成", "深证成指"], "exclude": ["深成长", "深成成长"]},
    "hs300":     {"code": "000300", "include": ["沪深300"], "exclude": []},
    "sz50":      {"code": "000016", "include": ["上证50"], "exclude": []},
    "csi500":    {"code": "000905", "include": ["中证500"], "exclude": ["A500"]},
    "csi1000":   {"code": "000852", "include": ["中证1000"], "exclude": []},
    "cyb":       {"code": "399006", "include": ["创业板ETF", "创业板增强"], "exclude": []},
    "kc50":      {"code": "000688", "include": ["科创50"], "exclude": []},
    "csi_div":    {"code": "000922", "include": ["中证红利"], "exclude": ["低波"]},
    "div_lowvol": {"code": "930955", "include": ["红利低波"],
                   "exclude": ["50", "100", "300", "800", "恒生", "港股"]},
    "sz_div":     {"code": "399324", "include": [], "exclude": []},  # 名称无法区分，留空
    "hsi":     {"code": "HSI", "include": ["恒生ETF", "恒生指数"],
                "exclude": ["科技", "中国企业", "互联", "医疗"]},
    "hstech":  {"code": "HSTECH", "include": ["恒生科技"], "exclude": []},
    "hscei":   {"code": "HSCEI", "include": ["恒生中国企业", "恒生国企"], "exclude": []},
}


def _akshare_name_fallback(df_by_code: dict) -> dict[str, list[dict]]:
    """akshare 名称匹配兜底：etf_index_map.json 缺失时，用 fund_etf_spot_em 名称反推 track_index_code。
    返回 {index_id: [{code, name, amount, approx}, ...]}（与 _build_index_etf_map_auto 输出同构）。
    df_by_code: {etf_code: row}（fund_etf_spot_em 行，含 名称/成交额）。
    """
    print("⚠ 走 akshare 名称匹配兜底（etf_index_map.json 缺失）")
    result: dict[str, list[dict]] = {}
    for iid, rule in _AKSHARE_NAME_RULES.items():
        inc = rule["include"]
        exc = rule["exclude"]
        if not inc:
            result[iid] = []
            continue
        etfs = []
        for code, r in df_by_code.items():
            try:
                rname = str(r["名称"])
            except (KeyError, TypeError):
                continue
            if any(k in rname for k in inc) and not any(k in rname for k in exc):
                try:
                    amount = round(float(r["成交额"]) / 1e8, 2)
                except (TypeError, ValueError, KeyError):
                    amount = 0.0
                etfs.append({"code": code, "name": rname, "amount": amount, "approx": "增强" in rname})
        etfs.sort(key=lambda x: x["amount"], reverse=True)
        result[iid] = etfs
    return result


def _load_etf_track_index() -> dict[str, dict]:
    """读 data/etf_track_index.json（fundf10 抓取的 ETF 跟踪指数名），返回 {etf_code: info}。

    info 结构：{name, track_index, amount, fetched_at, status?}（status='no_track' 表示页面无"跟踪标的"字段）。
    读不到返回空 dict（track_index 匹配 fallback 到 overlap/KW）。
    """
    if not ETF_TRACK_INDEX_PATH.exists():
        print(f"⚠ etf_track_index.json 不存在: {ETF_TRACK_INDEX_PATH}，track_index 匹配 fallback overlap/KW")
        return {}
    try:
        with open(ETF_TRACK_INDEX_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"⚠ etf_track_index.json 读取失败: {e}，track_index 匹配 fallback overlap/KW")
        return {}
    out: dict[str, dict] = {}
    for k, v in d.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        if not v.get("track_index"):
            continue  # 跳过 no_track
        out[k] = v
    return out


def _match_by_track_index(
    iid: str,
    track_idx_map: dict[str, dict],
    df_by_code: dict,
) -> list[dict]:
    """用 track_index_name 关键词匹配 ETF，返回候选列表。

    流程：对全量 ETF 的 track_index_name 做 include/exclude 关键词匹配，
    命中的 ETF 按成交额降序排，每个 ETF 携带 track_index_name 字段。

    返回 [{code, name, amount, approx, track_index_name, match_method}, ...]。
    """
    rule = TRACK_INDEX_KW.get(iid)
    if not rule or not rule.get("include"):
        return []  # 无 include 关键词（如 sw_801230 综合行业），返空
    inc = rule["include"]
    exc = rule.get("exclude", [])
    etfs = []
    for code, info in track_idx_map.items():
        tin = info.get("track_index", "") or ""
        if not tin:
            continue
        # include 任一命中 + exclude 都不命中
        if any(k in tin for k in inc) and not any(k in tin for k in exc):
            # ETF 名称优先用 akshare 实时值（df_by_code），查不到用 cache name
            r = df_by_code.get(code) if df_by_code else None
            if r is not None:
                try:
                    rname = str(r["名称"])
                    amount = round(float(r["成交额"]) / 1e8, 2)
                except (TypeError, ValueError, KeyError):
                    rname = info.get("name", code)
                    amount = round((info.get("amount", 0) or 0) / 1e8, 2)
            else:
                rname = info.get("name", code)
                amount = round((info.get("amount", 0) or 0) / 1e8, 2)
            etfs.append({
                "code": code,
                "name": rname,
                "amount": amount,
                "approx": True,  # 行业/概念 ETF 跟踪中证/国证指数，非申万/同花顺精准跟踪
                "track_index_name": tin,
                "match_method": "track_index",
            })
    etfs.sort(key=lambda x: x["amount"], reverse=True)
    return etfs


def _build_index_etf_map_auto(reverse_map: dict[str, list[dict]], df_by_code: dict) -> dict[str, list[dict]]:
    """自动采集生成指数->ETF候选映射: {index_id: [{code, name, amount, approx}, ...]}。

    - 从 reverse_map 按 track_index_code 拿 ETF 列表
    - 按 track_index_name 过滤（name_eq 规则，排除数据源污染）
    - 按 etf_index_map.json 的 amount 降序预排（akshare 实时 amount 后面填，顺序基本一致）
    - approx: ETF name 含"增强" -> True（增强型ETF），否则 False（纯被动）
    - cross_border: 港股指数 -> True（绕过 EXCLUDE 防御）
    - amount/name 优先用 akshare 实时值（df_by_code），查不到用 etf_index_map.json 的 amount
    - 代码复用绕过防御：非跨境ETF检查 akshare name 不含 EXCLUDE（2026-07-20 事故：159509复用为纳指科技）
    """
    result: dict[str, list[dict]] = {}
    for iid, rule in INDEX_TRACK_MAP.items():
        tic = rule["code"]
        name_eq = rule.get("name_eq")
        cross_border = rule.get("cross_border", False)
        cands = reverse_map.get(tic, [])
        if name_eq:
            cands = [c for c in cands if c["track_index_name"] == name_eq]
        cands_sorted = sorted(cands, key=lambda x: x["amount"], reverse=True)
        etfs = []
        for c in cands_sorted:
            code = c["code"]
            etf_name_src = c["name"]
            approx = "增强" in etf_name_src
            r = df_by_code.get(code) if df_by_code else None
            if r is not None:
                try:
                    rname = str(r["名称"])
                    if not cross_border and any(ex in rname for ex in EXCLUDE):
                        print(f"  [跳过] {iid} {code} {rname}（name 命中 EXCLUDE，代码复用绕过防御）")
                        continue
                    amount = round(float(r["成交额"]) / 1e8, 2)
                    etf_name = rname
                except (TypeError, ValueError, KeyError):
                    amount = round(c["amount"] / 1e8, 2)
                    etf_name = etf_name_src
            else:
                amount = round(c["amount"] / 1e8, 2)
                etf_name = etf_name_src
            etfs.append({"code": code, "name": etf_name, "amount": amount, "approx": approx})
        result[iid] = etfs
    return result


def main():
    cfg = load_config()
    name_by_id = {i["id"]: i["name"] for i in cfg.get("indices", [])}
    # 只为 industry/concept 生成
    board_ids = [i["id"] for i in cfg.get("indices", [])
                 if i.get("market") in ("industry", "concept") and i.get("enabled", True)]

    df = ak.fund_etf_spot_em()
    df["成交额"] = df["成交额"].fillna(0)
    names = df["名称"].astype(str)
    # 预计算排除掩码
    excl_mask = names.apply(lambda n: any(ex in n for ex in EXCLUDE))
    # P2-新-G: 按代码精确匹配宽基/红利指数 ETF（与行业关键词匹配同源，amount 取 fund_etf_spot_em 实时值）
    df_by_code = {}
    if "代码" in df.columns:
        for _, r in df.iterrows():
            df_by_code[str(r["代码"])] = r

    out: dict = {"_meta": {"source": "akshare fund_etf_spot_em + fundf10 track_index",
                           "sort_by": "成交额(亿元,降序)",
                           "match_priority": "track_index > overlap > kw_name",
                           "note": "匹配不到为空数组；前端按成交额排序展示，用户自选；"
                                   "行业/概念 ETF 跟踪中证/国证指数非申万/同花顺精准跟踪，approx=true"}}
    empty_boards = []
    # 加载 fundf10 抓取的 ETF track_index 缓存
    track_idx_map = _load_etf_track_index()
    if track_idx_map:
        print(f"\ntrack_index 匹配：加载 {len(track_idx_map)} 只 ETF 的 track_index 缓存")

    # ── 行业/概念匹配（优先级：track_index > overlap > KW 名称）──
    # 第1层：track_index_name 关键词匹配（fundf10 抓取的 ETF 跟踪指数名，最精准）
    track_matched = {}  # {iid: etfs} 记录 track_index 匹配结果（含空列表），避免后续 overlap/KW 覆盖
    for iid in board_ids:
        etfs = _match_by_track_index(iid, track_idx_map, df_by_code)
        track_matched[iid] = etfs
        if etfs:
            out[iid] = etfs
        else:
            out[iid] = []  # 占位，等下面 overlap/KW 兜底

    # 第2层：overlap 成分股匹配（track_index 未命中的 thsc 概念用成分股重叠补充）
    empty_thsc = [iid for iid in board_ids
                  if iid.startswith("thsc_") and not out.get(iid)]
    if empty_thsc:
        print(f"\n成分股重叠算法：{len(empty_thsc)} 个 track_index 未命中的 thsc 概念尝试重叠匹配")
        try:
            overlap_result = _overlap_match(df, df_by_code, excl_mask)
            for iid, etfs in overlap_result.items():
                if etfs and not out.get(iid):
                    # 给 overlap 匹配的 ETF 加 match_method + approx=true
                    for e in etfs:
                        e.setdefault("approx", True)
                        e["match_method"] = "overlap"
                    out[iid] = etfs
        except Exception as e:
            print(f"  [overlap] ⚠ 重叠算法异常,保留空数组: {e}")

    # 第3层：KW 名称子串匹配（track_index + overlap 都未命中的兜底）
    # KW 匹配是名称子串，精度最差，作为最后兜底（如 track_index 缓存缺失或 fundf10 抓取失败时）
    for iid in board_ids:
        if out.get(iid):
            continue  # 已有 track_index 或 overlap 匹配
        kws = KW.get(iid, [])
        if not kws:
            continue
        mask = ~excl_mask & names.apply(lambda n: any(k in n for k in kws))
        hit = df[mask].sort_values("成交额", ascending=False)
        etfs = []
        for _, r in hit.iterrows():
            # 尝试从 track_idx_map 拿 track_index_name
            tin = ""
            ti_info = track_idx_map.get(str(r["代码"]))
            if ti_info:
                tin = ti_info.get("track_index", "") or ""
            etfs.append({
                "code": str(r["代码"]),
                "name": str(r["名称"]),
                "amount": round(float(r["成交额"]) / 1e8, 2),
                "approx": True,  # KW 名称匹配兜底，approx=true
                "track_index_name": tin,
                "match_method": "kw",
            })
        if etfs:
            out[iid] = etfs

    # 记录留空板块
    for iid in board_ids:
        if not out.get(iid):
            empty_boards.append(f"{iid} {name_by_id.get(iid)}")

    # P2-新-G: 宽基/红利/综合/港股指数 -> 跟踪 ETF 候选（自动采集，按成交额降序）
    # 从 data/etf_index_map.json 自动采集替代原硬编码 INDEX_ETF_MAP（2026-07-28 方案D第二阶段）。
    # 覆盖 sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50/csi_div/div_lowvol/sz_div/hsi/hstech/hscei 14 个指数
    # （bj50 北证50 无活跃跟踪ETF，留空）。
    # 修正原硬编码 bug：hscei 原 513900 实跟踪"中华港股通精选100"非 HSCEI，自动采集修正为 510900 居首。
    reverse_map = _load_etf_index_map_reverse()
    if reverse_map:
        index_etf_map = _build_index_etf_map_auto(reverse_map, df_by_code)
    else:
        # etf_index_map.json 缺失 -> akshare 名称匹配兜底（防静默失败，不退化为全空）
        index_etf_map = _akshare_name_fallback(df_by_code)
    for iid, etfs in index_etf_map.items():
        out[iid] = etfs
        if not etfs:
            empty_boards.append(f"{iid} {name_by_id.get(iid, iid)}（宽基/红利/综合/港股）")

    # 写盘
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 防静默失败校验（§15 防复现）：14 宽基/红利/港股指数中，除 sz_div（名称无法区分，主动留空）
    # 和 bj50（无活跃跟踪ETF）外，其余 12 个必须非空。空则 exit 1，让 deploy.sh 捕获失败用旧 map，
    # 不静默覆盖线上 board_etf_map.json 为空数组（2026-08-06 事故根因：etf_index_map.json 缺失
    # 致 14 宽基全空，_load_etf_index_map_reverse 只 warning + exit 0 静默失败）。
    BROAD_MUST_NONEMPTY = ["sh", "sz", "hs300", "sz50", "csi500", "csi1000", "cyb", "kc50",
                           "csi_div", "div_lowvol", "hsi", "hstech", "hscei"]
    broad_empty_unexpected = [iid for iid in BROAD_MUST_NONEMPTY if not out.get(iid)]
    if broad_empty_unexpected:
        print(f"\n✗ 校验失败：宽基/红利/港股指数 ETF 全空 {broad_empty_unexpected}"
              f"（etf_index_map.json 缺失且 akshare 名称匹配兜底失败？），exit 1 不覆盖线上 map",
              file=sys.stderr)
        sys.exit(1)

    # 摘要
    total = len(board_ids)
    n_empty = len(empty_boards)
    dist = {"0": 0, "1": 0, "2-3": 0, "4+": 0}
    for iid in board_ids:
        n = len(out.get(iid, []))
        if n == 0:
            dist["0"] += 1
        elif n == 1:
            dist["1"] += 1
        elif n <= 3:
            dist["2-3"] += 1
        else:
            dist["4+"] += 1
    print(f"生成 {OUT.name}：{total} 板块 + {len(index_etf_map)} 宽基/红利/综合/港股指数（自动采集自 etf_index_map.json）")
    print(f"候选数分布(行业/概念): 0个={dist['0']}  1个={dist['1']}  2-3个={dist['2-3']}  4+个={dist['4+']}")
    print(f"\n宽基/红利/综合/港股指数 ETF 联动（{len(index_etf_map)} 个，自动采集）:")
    for iid in index_etf_map.keys():
        etfs = out.get(iid, [])
        if etfs:
            e = etfs[0]
            extra = f" +{len(etfs)-1}" if len(etfs) > 1 else ""
            approx_tag = " [approx]" if e.get("approx") else ""
            print(f"  {name_by_id.get(iid, iid):<10} {e['code']} {e['name']} ({e['amount']}亿){extra}{approx_tag}")
        else:
            print(f"  {name_by_id.get(iid, iid):<10} (无匹配ETF)")
    print(f"\n留空板块（{n_empty}，无相关ETF/主动留空）:")
    for b in empty_boards:
        print(f"  {b}")
    # 抽样展示 top1
    print("\n各板块 top1（成交额最大）抽样:")
    for iid in board_ids:
        etfs = out.get(iid, [])
        if etfs:
            e = etfs[0]
            extra = f" +{len(etfs)-1}" if len(etfs) > 1 else ""
            method = e.get("match_method", "?")
            tin = e.get("track_index_name", "")
            tin_tag = f" [{tin}]" if tin else ""
            print(f"  {name_by_id.get(iid, iid):<16} {e['code']} {e['name']} ({e['amount']}亿){extra} <{method}>{tin_tag}")

    # 匹配方式统计（行业/概念）
    method_cnt = {"track_index": 0, "overlap": 0, "kw": 0, "empty": 0}
    for iid in board_ids:
        etfs = out.get(iid, [])
        if not etfs:
            method_cnt["empty"] += 1
        else:
            m = etfs[0].get("match_method", "kw")
            method_cnt[m] = method_cnt.get(m, 0) + 1
    print(f"\n匹配方式统计（行业/概念 {total} 个）:")
    print(f"  track_index 精准: {method_cnt['track_index']}")
    print(f"  overlap 成分股: {method_cnt['overlap']}")
    print(f"  kw 名称兜底: {method_cnt['kw']}")
    print(f"  留空: {method_cnt['empty']}")


if __name__ == "__main__":
    main()
