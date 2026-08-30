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
import bisect
import json
import sqlite3
import sys
from pathlib import Path

import akshare as ak
import numpy as np

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))
from app.collector.fetchers import load_config
from app.collector.overlap_fetcher import match_overlap as _overlap_match
from app.collector.overlap_fetcher import match_holdings_overlap as _holdings_match

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
    "sw_801730": ["电力设备"],  # 路B-D组: 同步TRACK_INDEX_KW精简, 删宽泛子行业词(电池/光伏/风电/储能/新能源)避免KW兜底纳入跨族ETF(中证电池主题属csi_931719/中证光伏产业属csi_931151)
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
    # ---- 宽基/红利指数（宽基全量改造 2026-08-08）----
    # 精确 KW 避免"上证"命中上证50/180/380、"深成"命中深成长等误匹配
    # 港股(hsi/hstech/hscei)不加KW：KW命中EXCLUDE("恒生/港股")无效，靠track_index匹配
    "sh":       ["上证指数", "上证综指"],
    "sz":       ["深成", "深证成指"],  # exclude 在 TRACK_INDEX_KW 过滤"深成长/深证100"
    "hs300":    ["沪深300"],           # exclude 在 TRACK_INDEX_KW 过滤"成长/价值"
    "sz50":     ["上证50"],            # 含"上证500"防御性排除在 TRACK_INDEX_KW
    "csi500":   ["中证500"],           # exclude A500 在 TRACK_INDEX_KW
    "csi1000":  ["中证1000"],
    "cyb":      ["创业板ETF", "创业板增强"],  # 精确避免命中"创业板50/创业板综"
    "kc50":     ["科创50"],
    "bj50":     ["北证50"],
    "csi_div":  ["中证红利"],          # exclude 低波/50/100/300/800 在 TRACK_INDEX_KW
    "div_lowvol": ["红利低波"],        # exclude 50/100/300/800/恒生/港股 在 TRACK_INDEX_KW
    # sz_div 不加KW：名"红利ETF工银"无"深"字KW不命中，已有 manual_fallback
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
    "sw_801010": {"include": ["农业", "农牧", "养殖", "渔业", "牧渔"], "exclude": ["畜牧养殖"]},  # Bug6: 排除"中证畜牧养殖指数"ETF(属csi_931946)
    "sw_801030": {"include": ["化工"], "exclude": ["细分化工", "易盛", "郑商所"]},  # 方案2: 加"易盛/郑商所"排除159981能源化工ETF(跟踪"易盛郑商所能源化工指数A"=郑商所商品期货指数,非化工行业股票指数)
    "sw_801040": {"include": ["钢铁"], "exclude": ["国证钢铁"]},
    "sw_801050": {"include": ["有色金属"], "exclude": ["国证有色", "中证稀有金属", "中证工业有色", "中证有色矿业"]},
    "sw_801080": {"include": ["电子"], "exclude": ["消费电子", "中证申万电子"]},  # 申万电子 vs 消费电子/中证申万电子行业
    "sw_801880": {"include": ["汽车"], "exclude": ["新能源汽车", "智能汽车", "新能源车", "中证新能源汽车"]},
    "sw_801110": {"include": ["家电", "家用电器"], "exclude": []},  # 方案2: 加"家用电器"命中159996(跟踪"中证全指家用电器指数","家电"非"家用电器"子串故原遗漏)
    "sw_801120": {"include": ["食品", "酒", "饮料"], "exclude": ["国证食品饮料", "国证粮食"]},
    "sw_801130": {"include": ["纺织", "服装", "服饰"], "exclude": []},
    "sw_801140": {"include": ["轻工", "家居", "造纸", "文娱"], "exclude": ["传媒", "智能家居"]},  # Bug7: 加"智能家居"排除"中证智能家居指数"ETF(属csi_399996)
    "sw_801150": {"include": ["医药", "医疗", "生物", "创新药", "中药"], "exclude": ["中证医疗", "互联网医疗"]},  # Bug3: 加"互联网医疗"排除"中证互联网医疗主题指数"
    "sw_801160": {"include": ["公用事业"], "exclude": ["电力公用事业", "中证环境治理"]},  # Bug1: "电力公用事业"通用匹配"中证全指电力公用事业指数"(原"中证电力公用事业"漏匹配"全指")
    "sw_801170": {"include": ["交通", "运输"], "exclude": []},
    "sw_801180": {"include": ["房地产", "地产"], "exclude": []},
    "sw_801200": {"include": ["商贸", "零售", "商业", "百货"], "exclude": []},
    "sw_801210": {"include": ["旅游", "社服"], "exclude": []},
    "sw_801780": {"include": ["银行"], "exclude": ["中证银行", "国证银行"]},
    "sw_801790": {"include": ["证券", "保险", "非银"], "exclude": ["中证全指证券公司", "中证申万证券", "中证证券公司"]},  # Bug2: 加"中证证券公司"排除"中证证券公司30/先锋策略"
    "sw_801710": {"include": ["建筑材料", "建材"], "exclude": []},
    "sw_801720": {"include": ["建筑", "基建"], "exclude": ["建筑材料", "建材", "中证基建工程"]},
    "sw_801730": {"include": ["电力设备"],  # 路B-D组: 删宽泛"光伏/风电/储能/电池/新能源"(命中创业板/国证/科创板新能源跨族; 中证电池主题属csi_931719, 中证光伏产业属csi_931151); 只留"电力设备"(无ETF精准跟踪则留空,159387创业板新能源不再错配)
                  "exclude": ["新能源汽车", "新能源车", "中证新能源", "中证电池", "中证光伏", "创业板", "国证", "科创板"]},  # 追加"创业板/国证/科创板"防御性排除跨指数族(旧exclude保留)
    "sw_801890": {"include": ["机械", "工程机械", "机床"], "exclude": ["中证工程机械"]},
    "sw_801740": {"include": ["军工", "国防"], "exclude": ["中证军工", "国证军工"]},
    "sw_801750": {"include": ["计算机", "软件", "信息技术"], "exclude": ["中证信息技术", "中证TMT", "中证云计算", "中证人工智能", "中证金融科技", "中证移动互联网", "中证信息安全"]},
    "sw_801760": {"include": ["传媒", "游戏", "动漫"], "exclude": ["中证传媒"]},
    "sw_801770": {"include": ["通信"], "exclude": ["中证移动互联网"]},
    "sw_801950": {"include": ["煤炭"], "exclude": ["中证煤炭"]},
    "sw_801960": {"include": ["石油", "石化"], "exclude": ["国证油气"]},
    "sw_801970": {"include": ["环保"], "exclude": ["中证环保"]},
    "sw_801980": {"include": ["美容", "护理", "化妆品"], "exclude": []},
    "sw_801230": {"include": [], "exclude": []},  # 综合行业无 ETF，留空
    # ---- 同花顺概念 ----
    "thsc_300816": {"include": ["机器人"], "exclude": []},
    "thsc_309119": {"include": ["机器人"], "exclude": []},
    "thsc_308700": {"include": ["半导体", "芯片", "碳化硅", "氮化镓", "宽禁带"], "exclude": ["科创板芯片"]},  # E组: 排除科创芯片ETF(属 sse_000685)
    "thsc_309049": {"include": ["光通信", "光模块", "CPO", "光子"], "exclude": []},
    "thsc_301085": {"include": ["芯片", "半导体"], "exclude": ["科创板芯片"]},  # E组: 排除"上证科创板芯片指数/设计主题指数"ETF(588200/588780, 属 sse_000685)
    "thsc_307940": {"include": ["存储芯片", "存储"], "exclude": []},
    "thsc_302035": {"include": ["人工智能"], "exclude": ["创业板人工智能"]},  # E组: 排除"创业板人工智能指数"ETF(159242等, 属 csi_970070)
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
    # ---- 国证指数（2c 新增）----
    # gz_399417 国证新能源汽车指数：160225 国泰国证新能源汽车LOF 跟踪"国证新能源汽车指数"
    # 用"国证新能源汽车"精准命中（排除"中证新能源汽车"的515030等ETF），160225 vs gz_399417 max_err<1%=excellent
    "gz_399417": {"include": ["国证新能源汽车"], "exclude": []},
    # ===== 路B新增 62 个国证/中证行业主题指数（2026-08-07）=====
    # include 用指数名关键词，让跟踪该指数的ETF/LOF精准命中。
    # ─ A组 国证指数(7个) ─
    "gz_399368": {"include": ["国证军工"], "exclude": []},
    "gz_399395": {"include": ["国证有色"], "exclude": []},
    "gz_399396": {"include": ["国证食品饮料"], "exclude": []},
    "gz_399431": {"include": ["国证银行"], "exclude": []},
    "gz_399439": {"include": ["国证油气"], "exclude": []},
    "gz_399440": {"include": ["国证钢铁"], "exclude": []},
    "gz_399365": {"include": ["国证粮食"], "exclude": []},
    # ─ B组 中证-深交所(18个) ─
    "csi_399975": {"include": ["中证全指证券公司"], "exclude": []},  # Bug2: 去掉宽泛"证券公司",只精准匹配"中证全指证券公司指数"ETF
    "csi_399986": {"include": ["中证银行"], "exclude": []},
    "csi_399989": {"include": ["中证医疗"], "exclude": []},
    "csi_399976": {"include": ["中证新能源汽车"], "exclude": []},
    "csi_399967": {"include": ["中证军工"], "exclude": []},
    "csi_399971": {"include": ["中证传媒"], "exclude": []},
    "csi_399998": {"include": ["中证煤炭"], "exclude": []},
    "csi_399808": {"include": ["中证新能源"], "exclude": ["中证新能源汽车"]},
    "csi_399803": {"include": ["中证工业4.0", "工业4.0"], "exclude": []},
    "csi_399806": {"include": ["中证环境治理", "环境治理"], "exclude": []},
    "csi_399807": {"include": ["中证高铁产业", "高铁产业"], "exclude": []},
    "csi_399970": {"include": ["中证移动互联网", "移动互联网"], "exclude": []},
    "csi_399991": {"include": ["中证一带一路", "一带一路"], "exclude": []},
    "csi_399994": {"include": ["中证信息安全", "信息安全"], "exclude": []},
    "csi_399995": {"include": ["中证基建工程", "基建工程"], "exclude": []},
    "csi_399996": {"include": ["中证智能家居", "智能家居"], "exclude": []},
    "csi_399707": {"include": ["中证申万证券行业", "申万证券"], "exclude": []},
    "csi_399811": {"include": ["中证申万电子行业", "申万电子"], "exclude": []},
    # ─ C组 中证-上交所/深交所(15个) ─
    "csi_000510": {"include": ["中证A500", "A500"], "exclude": []},
    "csi_000903": {"include": ["中证A100", "A100"], "exclude": []},
    "csi_000827": {"include": ["中证环保"], "exclude": []},
    "csi_000935": {"include": ["中证信息技术"], "exclude": []},
    "csi_000998": {"include": ["中证TMT", "TMT"], "exclude": []},
    "csi_000961": {"include": ["中证上游资源", "上游资源"], "exclude": []},
    "csi_000805": {"include": ["A股资源", "中证资源"], "exclude": []},
    "csi_000813": {"include": ["细分化工"], "exclude": []},
    "csi_000010": {"include": ["上证180"], "exclude": []},
    "csi_000330": {"include": ["深证100"], "exclude": []},
    "csi_000673": {"include": ["创业板50"], "exclude": []},
    "csi_000102": {"include": ["创业板综"], "exclude": []},
    "csi_000680": {"include": ["科创综合", "科创综指"], "exclude": []},
    "csi_000698": {"include": ["科创100"], "exclude": []},
    "csi_000699": {"include": ["科创200"], "exclude": []},
    # ─ D组 中证指数公司(22个) ─
    "csi_931151": {"include": ["中证光伏产业", "光伏产业"], "exclude": []},
    "csi_930050": {"include": ["中证A50", "A50"], "exclude": []},
    "csi_932000": {"include": ["中证2000"], "exclude": []},
    "csi_930986": {"include": ["中证金融科技", "金融科技"], "exclude": []},
    "csi_H30590": {"include": ["中证机器人", "机器人"], "exclude": []},
    "csi_931643": {"include": ["中证科创创业50", "科创创业50"], "exclude": []},
    "csi_931719": {"include": ["中证电池主题", "电池主题"], "exclude": []},
    "csi_930632": {"include": ["中证稀有金属", "稀有金属"], "exclude": []},
    "csi_931892": {"include": ["中证有色矿业", "有色矿业"], "exclude": []},
    "csi_930713": {"include": ["中证人工智能"], "exclude": ["产业"]},  # 路B-D组: 删宽泛"人工智能"(命中上证科创板/创业板/科创创业/沪港深AI跨族); 只留"中证人工智能"命中主题指数(excellent本行业)+产业指数; exclude"产业"排除"中证人工智能产业指数"(sim=0.15 warn max_err=84%跨族严重错配)
    "csi_930721": {"include": ["中证智能汽车", "智能汽车"], "exclude": []},
    "csi_930851": {"include": ["中证云计算", "云计算"], "exclude": []},
    "csi_932365": {"include": ["中证自由现金流"], "exclude": []},  # 路B-D组: 删宽泛"自由现金流"(命中国证/沪深300/中证800/中证全指/中证500/富时自由现金流跨族); 只留"中证自由现金流"(无ETF精准跟踪则留空,159201国证自由现金流不再错配)
    "csi_932315": {"include": ["中证红利质量", "红利质量"], "exclude": []},
    "csi_931752": {"include": ["中证工程机械"], "exclude": []},
    "csi_931946": {"include": ["中证畜牧养殖", "畜牧养殖"], "exclude": []},
    "csi_H11059": {"include": ["中证工业有色", "工业有色"], "exclude": []},
    "csi_932456": {"include": ["中证科创创业AI", "科创创业AI"], "exclude": []},
    "csi_930820": {"include": ["中证高端制造", "高端制造"], "exclude": []},
    "csi_930997": {"include": ["中证新能源汽车产业", "新能源汽车产业"], "exclude": []},
    "csi_H30535": {"include": ["中证互联网", "互联网"], "exclude": []},
    "csi_H30199": {"include": ["中证电力公用事业", "电力公用事业"], "exclude": []},
    # ─ E组 ETF跟踪指数补采（上证科创板主题指数） ─
    "sse_000685": {"include": ["科创板芯片指数"], "exclude": []},  # "科创板芯片指数"精准命中track_index"上证科创板芯片指数"(588200等11只), 不命中"上证科创板芯片设计主题指数"(588780等, 属另一指数)
    "csi_970070": {"include": ["创业板人工智能"], "exclude": []},  # "创业板人工智能"精准命中track_index"创业板人工智能指数"(159242等), 不命中"中证人工智能指数"(属csi_930713)/"上证科创板人工智能指数"(未查到代码)
    # ---- 宽基/红利/港股指数（宽基全量改造 2026-08-08）----
    # track_index_name 关键词匹配，用于 Layer 1(_match_by_track_index) + Layer 3 KW exclude 过滤
    # include 匹配 ETF 的 track_index_name（fundf10 抓取），exclude 过滤同前缀不同指数
    "sh":       {"include": ["上证综合", "上证综指"], "exclude": ["上证50", "上证180", "上证380", "上证580", "上证中盘"]},
    "sz":       {"include": ["深证成份"], "exclude": ["深成长", "深证100", "深证50", "深证主板"]},
    "hs300":    {"include": ["沪深300"], "exclude": ["成长", "价值", "中证智选", "ESG", "红利", "等权重", "非银行", "质量", "医药", "现金流"]},
    "sz50":     {"include": ["上证50"], "exclude": ["上证500", "AH"]},
    "csi500":   {"include": ["中证500"], "exclude": ["A500", "质量", "信息技术"]},
    "csi1000":  {"include": ["中证1000"], "exclude": []},
    "cyb":      {"include": ["创业板指"], "exclude": ["创业板50", "创业板综", "创精选"]},
    "kc50":     {"include": ["科创板50", "科创50"], "exclude": []},  # track_index_name="上证科创板50成份指数"含"科创板50"非"科创50"
    # bj50: 已在 universe_rules.yaml excluded_categories.空数组 mode: empty_array(2026-08-25 用户拍板)。
    # 从 TRACK_INDEX_KW 移除，防止 KW 名称匹配层被误匹配；holdings/sum_pct 层也跳过(见 EXCLUDE_FROM_HOLDINGS)
    "csi_div":  {"include": ["中证红利"], "exclude": ["低波", "50", "100", "300", "800", "价值", "质量"]},
    "div_lowvol": {"include": ["红利低波"], "exclude": ["50", "100", "300", "800", "恒生", "港股"]},
    "sz_div":   {"include": ["深证红利"], "exclude": []},
    # 港股 track_index_name 匹配（不经过 EXCLUDE，可匹配"恒生"ETF的 track_index_name）
    "hsi":      {"include": ["恒生指数"], "exclude": ["恒生科技", "恒生中国企业", "恒生国企", "恒生互联", "恒生医疗", "恒生生物", "恒生消费", "恒生红利"]},
    "hstech":   {"include": ["恒生科技"], "exclude": []},
    "hscei":    {"include": ["恒生中国企业", "恒生国企"], "exclude": []},
}

# ETF track_index 缓存路径（fundf10 抓取，scripts/fetch_etf_track_index.py 生成）
ETF_TRACK_INDEX_PATH = ROOT / "data" / "etf_track_index.json"

# LOF track_index 缓存路径（fundf10 抓取，scripts/fetch_lof_track_index.py 生成）
# LOF（上市开放式基金）如 160225 国泰国证新能源汽车LOF，fund_etf_spot_em 不含，
# 需独立采集 fundf10 跟踪标的 + fund_open_fund_rank_em 预筛，纳入候选池
LOF_TRACK_INDEX_PATH = ROOT / "data" / "lof_track_index.json"

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


# ───────────────────────────────────────────────────────────────────
# 全球指数 -> 跨境 ETF 候选（KW 名称匹配 + cross_border 绕过 EXCLUDE）
# 2026-08-09 走势图问题2：给全球指数走势卡挂相关 ETF。
#
# 跨境 ETF（纳指/标普/日经/德国/法国/道琼斯）track_index_code 全空（status=no_track），
# 无法用 INDEX_TRACK_MAP 的 track_index_code 反向映射；改用 ETF 名称关键词匹配。
# 这些关键词命中 EXCLUDE（"美国/日本/德国/法国/纳斯达克/纳指/标普/日经"），需 cross_border 绕过。
#
# approx=True：跨境 ETF 跟踪海外指数，含汇率/时差偏差，统一标近似
# （us_ixic 纳指综合无精准 ETF，纳指 ETF 实跟踪纳指100，更是近似）。
# 无跨境 ETF 的指数（ftse100/kospi/cgb_*）留空，前端显示"无ETF"。
# ───────────────────────────────────────────────────────────────────
GLOBAL_INDEX_KW: dict[str, dict] = {
    "us_dji":    {"include": ["道琼斯"], "exclude": []},                # 513400 道琼斯ETF鹏华(跟踪道琼斯工业平均指数)
    "us_spx":    {"include": ["标普500"], "exclude": []},               # 513500等(名称含"500"，自动排除"标普消费/油气/红利"等)
    "us_ndx":    {"include": ["纳斯达克100", "纳指100"], "exclude": []}, # 159513/159659/513390等(名称含"100"，精准跟踪纳斯达克100)
    "us_ixic":   {"include": ["纳指ETF", "纳斯达克ETF"], "exclude": ["100"]},  # 纳指综合(.IXIC)无精准ETF，纳指ETF实跟踪纳指100，approx
    "nikkei225": {"include": ["日经"], "exclude": []},                  # 513520/513880/513000/159866等(所有日经ETF跟踪日经225)
    "dax":       {"include": ["德国"], "exclude": []},                  # 513030/159561(德国ETF跟踪DAX30)
    "cac40":     {"include": ["法国"], "exclude": []},                  # 513080(法国ETF跟踪CAC40)
    "ftse100":   {"include": ["富时100"], "exclude": ["A50"]},          # 大概率无ETF留空(富时A50是A股，非富时100)
    "kospi":     {"include": ["韩国"], "exclude": []},                  # 大概率无ETF留空
    # cgb_idx/cgb_10y_etf/cgb_10y_future 国债类：无精准跨境ETF，不列入（留空）
}


def _build_global_etf_map(
    df,
    df_by_code: dict,
    track_idx_map: dict[str, dict],
) -> dict[str, list[dict]]:
    """全球指数 -> 跨境 ETF 候选（KW 名称匹配 + cross_border 绕过 EXCLUDE）。

    跨境 ETF 的 track_index_code 全空（fundf10 抓取 status=no_track），无法用
    _build_index_etf_map_auto 的 track_index_code 反向映射；改用 ETF 名称关键词匹配。
    GLOBAL_INDEX_KW 的关键词命中 EXCLUDE（纳指/标普/日经/德国/法国），这里不走 excl_mask，
    直接按 include/exclude 子串匹配（cross_border 语义）。

    track_index_name 优先从 track_idx_map（fundf10 缓存）取，取不到留空。
    返回 {index_id: [{code, name, amount, approx, track_index_name, match_method, fund_type}, ...]}，
    按成交额降序（后续 _enrich_with_tracking_score 会改按 track_score 排）。
    """
    result: dict[str, list[dict]] = {}
    for iid, rule in GLOBAL_INDEX_KW.items():
        inc = rule["include"]
        exc = rule.get("exclude", [])
        if not inc:
            result[iid] = []
            continue
        etfs = []
        for code, r in df_by_code.items():
            try:
                rname = str(r["名称"])
            except (KeyError, TypeError):
                continue
            # include 任一命中 + exclude 都不命中（cross_border 绕过 EXCLUDE 防御）
            if any(k in rname for k in inc) and not any(k in rname for k in exc):
                try:
                    amount = round(float(r["成交额"]) / 1e8, 2)
                except (TypeError, ValueError, KeyError):
                    amount = 0.0
                # track_index_name 从 fundf10 缓存取（如 513400 道琼斯="道琼斯工业平均指数"）
                tin = ""
                ti_info = track_idx_map.get(code)
                if ti_info:
                    tin = ti_info.get("track_index", "") or ""
                etfs.append({
                    "code": code,
                    "name": rname,
                    "amount": amount,
                    "approx": True,  # 跨境ETF含汇率/时差偏差，统一标近似
                    "track_index_name": tin,
                    "match_method": "kw_global",
                    "fund_type": "etf",
                })
        etfs.sort(key=lambda x: x["amount"], reverse=True)
        result[iid] = etfs
    return result


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


def _etf_index_map_amount(etf_code: str) -> float:
    """从 etf_index_map.json 直接读指定 ETF 的 amount（元），转亿元。
    reverse_map 跳过 status!="ok" 的 ETF（如 159905 sz_div 主动留空 status="no_track"），
    本函数不过滤 status，直接按 code 查（用于 manual fallback 取 amount）。
    读不到返回 0.0。
    """
    if not ETF_INDEX_MAP_PATH.exists():
        return 0.0
    try:
        with open(ETF_INDEX_MAP_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return 0.0
    info = d.get(etf_code)
    if not isinstance(info, dict):
        return 0.0
    return round((info.get("amount", 0) or 0) / 1e8, 2)


def _fallback_159905_amount(reverse_map: dict[str, list[dict]]) -> float:
    """159905 amount 兜底：df_by_code 无时用 etf_index_map.json 直读（reverse_map
    因 159905 status="no_track" 无 399324 条目，故不走 reverse_map）。"""
    amt = _etf_index_map_amount("159905")
    if amt > 0:
        return amt
    # etf_index_map.json 也无，reverse_map 399324 条目最后兜底（理论上不会有）
    cands = reverse_map.get("399324", []) if reverse_map else []
    if cands:
        return round((cands[0].get("amount", 0) or 0) / 1e8, 2)
    return 0.0


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
        v.setdefault("fund_type", "etf")  # ETF 默认 fund_type=etf
        out[k] = v
    return out


def _load_lof_track_index() -> dict[str, dict]:
    """读 data/lof_track_index.json（fundf10 抓取的 LOF 跟踪指数），返回 {lof_code: info}。

    info 结构：{name, fullname, track_index, fund_type='lof', fund_subtype, amount, fetched_at, status?}。
    只保留 fund_type='lof' 且 track_index 非空的条目（status=no_track/not_lof 跳过）。
    读不到返回空 dict（LOF 不纳入候选，fallback 到 ETF 三层匹配）。
    """
    if not LOF_TRACK_INDEX_PATH.exists():
        print(f"⚠ lof_track_index.json 不存在: {LOF_TRACK_INDEX_PATH}，LOF 不纳入候选（跑 scripts/fetch_lof_track_index.py 生成）")
        return {}
    try:
        with open(LOF_TRACK_INDEX_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"⚠ lof_track_index.json 读取失败: {e}，LOF 不纳入候选")
        return {}
    out: dict[str, dict] = {}
    for k, v in d.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        if v.get("fund_type") != "lof":
            continue  # 只取 fund_type=lof
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
                "fund_type": info.get("fund_type", "etf"),  # etf 或 lof
            })
    etfs.sort(key=lambda x: x["amount"], reverse=True)
    return etfs


# ───────────────────────────────────────────────────────────────────
# 路 A-2b：实测相似度计算（涨跌幅 max_err 分级）
# 校验标准：max_err<1%=excellent(精准) / 1-5%=good(近似) / >5%=warn
# 数据源：index_daily(指数close) + etf_daily(ETF close) + fund_open_fund_info_em(LOF累计净值)
# 算法：5周期涨幅(ret_5d/20d/60d/ytd/1y) 日期对齐取交集，max_err=最大|候选涨幅-指数涨幅|
# ───────────────────────────────────────────────────────────────────
PERIODS = ["ret_5d", "ret_20d", "ret_60d", "ret_ytd", "ret_1y"]
# 涨幅回看交易日数（ret_ytd 单独按年份算）
PERIOD_NBACK = {"ret_5d": 5, "ret_20d": 20, "ret_60d": 60, "ret_1y": 252}


def _get_sent_db_path() -> Path:
    """sentiment.db 路径：优先 trade-data/data/sentiment.db（主库，launchd 写），
    回退 trade/data/sentiment.db（镜像）。与 _get_etf_db_path 策略一致。"""
    base = Path(__file__).resolve().parent.parent  # trade/
    main = base.parent / "trade-data" / "data" / "sentiment.db"
    if main.exists():
        return main
    return base / "data" / "sentiment.db"


def _load_index_close_series() -> dict[str, list[tuple]]:
    """批量读 index_daily，返回 {index_id: [(date, close), ...]} 按日期升序。
    用于相似度计算（指数 close 序列）。读不到返回空 dict。"""
    db = _get_sent_db_path()
    if not db.exists():
        print(f"⚠ sentiment.db 不存在: {db}，相似度计算将跳过")
        return {}
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT index_id, date, close FROM index_daily ORDER BY index_id, date")
    series: dict[str, list[tuple]] = {}
    for r in cur:
        if r["close"] is None:
            continue
        series.setdefault(r["index_id"], []).append((r["date"], r["close"]))
    conn.close()
    return series


def _load_etf_close_series() -> dict[str, list[tuple]]:
    """批量读 etf_daily 累计净值(accum_nav),返回 {etf_code: [(date, accum_nav), ...]} 按日期升序。
    用于相似度计算（ETF accum_nav 序列,已复权除权日不跳变）。读不到返回空 dict。
    accum_nav 缺失的QDII跨境ETF(48只)自动跳过(WHERE accum_nav IS NOT NULL)。
    """
    db = _get_etf_db_path()
    if not db.exists():
        print(f"⚠ etf_national_team.db 不存在: {db}，相似度计算将跳过")
        return {}
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT etf_code, date, accum_nav FROM etf_daily WHERE accum_nav IS NOT NULL ORDER BY etf_code, date")
    series: dict[str, list[tuple]] = {}
    for r in cur:
        series.setdefault(r["etf_code"], []).append((r["date"], r["accum_nav"]))
    conn.close()
    return series


# LOF 累计净值序列缓存（同一次运行内避免重复取 akshare）
_LOF_NAV_CACHE: dict[str, list[tuple]] = {}


def _fetch_lof_nav_series(lof_code: str) -> list[tuple]:
    """从 akshare fund_open_fund_info_em 取 LOF 累计净值序列（稳定，0.7s/只）。
    返回 [(date_yyyymmdd, nav), ...] 按日期升序。fund_lof_spot_em/stock_zh_a_hist 不稳定已弃用。
    缓存避免重复取；失败重试1次，仍失败返空列表（该 LOF similarity=None）。
    """
    if lof_code in _LOF_NAV_CACHE:
        return _LOF_NAV_CACHE[lof_code]
    series: list[tuple] = []
    for attempt in range(2):  # 重试1次
        try:
            df = ak.fund_open_fund_info_em(symbol=lof_code, indicator="累计净值走势")
            for _, row in df.iterrows():
                dt = str(row["净值日期"]).replace("-", "")  # YYYY-MM-DD -> YYYYMMDD
                nav = float(row["累计净值"])
                series.append((dt, nav))
            series.sort(key=lambda x: x[0])
            break
        except Exception as e:
            if attempt == 0:
                continue  # 重试
            print(f"  [LOF净值] ⚠ {lof_code} 取失败: {e}")
    _LOF_NAV_CACHE[lof_code] = series
    return series


def _calc_returns(series: list[tuple]) -> dict:
    """算5周期涨幅%。series: [(date, close), ...] 按日期升序（已日期对齐）。
    返回 {ret_5d: x, ret_20d: y, ret_60d: z, ret_ytd: w, ret_1y: v}，数据不足的周期为 None。
    复用 /tmp/etf_full_audit.py 算法：用交易日倒数第N个到最新涨跌幅。
    """
    if not series or len(series) < 2:
        return {}
    latest_date, latest_close = series[-1]
    if latest_close is None or latest_close <= 0:
        return {}
    results = {}
    for period, n_back in PERIOD_NBACK.items():
        if len(series) > n_back:
            start_close = series[-(n_back + 1)][1]
            if start_close and start_close > 0:
                results[period] = (latest_close - start_close) / start_close * 100
            else:
                results[period] = None
        else:
            # 不够 N 天，取最早可得
            start_close = series[0][1]
            if start_close and start_close > 0 and len(series) > 1:
                results[period] = (latest_close - start_close) / start_close * 100
            else:
                results[period] = None
    # YTD：2026年第一个交易日到最新
    ytd_start = None
    for dt, cl in series:
        if dt.startswith("2026"):
            ytd_start = cl
            break
    if ytd_start and ytd_start > 0:
        results["ret_ytd"] = (latest_close - ytd_start) / ytd_start * 100
    else:
        results["ret_ytd"] = None
    return results


def _calc_similarity(
    idx_id: str,
    cand_code: str,
    fund_type: str,
    idx_series_all: dict[str, list[tuple]],
    etf_series_all: dict[str, list[tuple]],
) -> dict | None:
    """算候选 vs 指数的相似度。

    日期对齐：取 index 和候选的共同日期交集，按日期升序，再算5周期涨幅。
    （比审计脚本"各自倒数第N个"更准确，消除交易日历差异）
    返回 {similarity, max_err, max_err_period, grade, direction_mismatch} 或 None（数据不足）。

    分级（用户标准）：
      max_err < 1%  -> excellent（精准跟踪）
      max_err < 5%  -> good（近似跟踪）
      max_err >= 5% -> warn（误差大）
    similarity = 1 - max_err/100（近似跟踪度%）
    """
    idx_series = idx_series_all.get(idx_id, [])
    if fund_type == "lof":
        cand_series = _fetch_lof_nav_series(cand_code)
    else:
        cand_series = etf_series_all.get(cand_code, [])
    if not idx_series or not cand_series:
        return None
    # 日期对齐：取交集（消除交易日历差异）
    idx_map = {d: c for d, c in idx_series}
    cand_map = {d: c for d, c in cand_series}
    common_dates = sorted(set(idx_map.keys()) & set(cand_map.keys()))
    if len(common_dates) < 10:  # 至少10个共同交易日，否则数据不足
        return None
    aligned_idx = [(d, idx_map[d]) for d in common_dates]
    aligned_cand = [(d, cand_map[d]) for d in common_dates]
    idx_ret = _calc_returns(aligned_idx)
    cand_ret = _calc_returns(aligned_cand)
    if not idx_ret or not cand_ret:
        return None
    max_err = 0.0
    max_err_period = None
    direction_mismatch = False
    has_any = False
    for p in PERIODS:
        ir = idx_ret.get(p)
        cr = cand_ret.get(p)
        if ir is None or cr is None:
            continue
        has_any = True
        err = abs(cr - ir)
        # 方向：同涨同跌为 consistent，否则 mismatch
        if (ir > 0 and cr > 0) or (ir < 0 and cr < 0) or (abs(ir) < 0.01 and abs(cr) < 0.01):
            pass
        else:
            direction_mismatch = True
        if err > max_err:
            max_err = err
            max_err_period = p
    if not has_any:
        return None
    # 分级
    if max_err < 1:
        grade = "excellent"
    elif max_err < 5:
        grade = "good"
    else:
        grade = "warn"
    return {
        "similarity": round(1 - max_err / 100, 4),
        "max_err": round(max_err, 4),
        "max_err_period": max_err_period,
        "grade": grade,
        "direction_mismatch": direction_mismatch,
    }


def _enrich_with_similarity(
    out: dict,
    idx_series_all: dict[str, list[tuple]],
    etf_series_all: dict[str, list[tuple]],
) -> tuple[int, int, int]:
    """对所有指数的候选列表加 similarity/max_err/grade 字段，并按 max_err 升序排序。
    返回 (sim_ok, sim_fail, lof_fetched) 统计数。
    """
    sim_ok = 0
    sim_fail = 0
    lof_fetched = 0
    for iid in list(out.keys()):
        if iid == "_meta":
            continue
        cands = out.get(iid, [])
        if not cands:
            continue
        for c in cands:
            code = c.get("code", "")
            ft = c.get("fund_type", "etf")  # 宽基candidates无fund_type，默认etf
            c.setdefault("fund_type", ft)
            if ft == "lof" and code not in _LOF_NAV_CACHE:
                lof_fetched += 1
            sim = _calc_similarity(iid, code, ft, idx_series_all, etf_series_all)
            if sim:
                c.update(sim)
                sim_ok += 1
            else:
                c["similarity"] = None
                c["max_err"] = None
                c["max_err_period"] = None
                c["grade"] = "n/a"
                c["direction_mismatch"] = None
                sim_fail += 1
        # 按 max_err 升序排（最相似在前）；None 排最后
        cands.sort(
            key=lambda x: (
                x.get("max_err") is None,
                x.get("max_err") if x.get("max_err") is not None else float("inf"),
            )
        )
    return sim_ok, sim_fail, lof_fetched


# ───────────────────────────────────────────────────────────────────
# 路 D1：ETF跟踪5维度评分（日收益率序列，捕捉全路径偏离）
# 弥补 _calc_similarity 只看起点终点的缺陷：V型尖刺(159536)在累计里抵消骗过旧算法，
# 新算法用日收益率 diff 捕捉全路径偏离，roll_std/TE 抓出尖刺。
#
# 5项指标（日收益率序列 r = diff(close)/close[:-1]，accum_nav 复权除权日不跳）：
#   1. avg_dev  日均跟踪偏离度 mean(|r_etf - r_idx|) × 100        越低越好
#   2. TE       年化跟踪误差 std(diff, ddof=1) × sqrt(252) × 100   越低越好
#   3. IR       信息比率 mean(diff)×252/(std(diff)×sqrt(252))       |IR|越接近0越好
#   4. R²       决定系数 corr(r_etf, r_idx)²                        越高越好
#   5. roll_std 30交易日滚动TE序列的std(ddof=1)                      越低越好
#
# 归一化：4项百分位rank（防min-max异常值拉伸，如跨境ETF TE=40%拉大range），
#         IR用分段函数（正负不同惩罚：正>0.5斜率80，负<-0.5斜率200）
# 权重：TE30%/R²25%/avg_dev15%/roll_std15%/IR15%
# 阈值：≥80 strong / 70-79 related / 50-69 approx / <50或None none
# ───────────────────────────────────────────────────────────────────
TRACK_WEIGHTS = {"te": 0.30, "r2": 0.25, "avg_dev": 0.15, "roll_std": 0.15, "ir": 0.15}
# 方案A(2026-08-09): 间接匹配ETF的IR权重分层
# 直接匹配(track_index)=ETF真正跟踪该指数,IR可信->用TRACK_WEIGHTS(IR15%原样)
# 间接匹配(overlap/kw/holdings_overlap/sum_pct/kw_global/manual_fallback)=通过成分股/持仓/名称
# 间接关联,IR可能反映其他指数跟踪质量(如516630跟踪云计算指数IR好但和量子科技概念无关)
# ->IR权重0%,重分配到R²(+9%->34%)和TE(+6%->36%),avg_dev/roll_std不变
TRACK_WEIGHTS_INDIRECT = {"te": 0.36, "r2": 0.34, "avg_dev": 0.15, "roll_std": 0.15, "ir": 0.0}


def _calc_tracking_metrics(
    idx_id: str,
    cand_code: str,
    fund_type: str,
    idx_series_all: dict[str, list[tuple]],
    etf_series_all: dict[str, list[tuple]],
) -> dict | None:
    """算候选 vs 指数的5项跟踪指标（原始值，非归一化）。

    用日收益率序列（accum_nav/累计净值，非累计收益差），捕捉全路径偏离。
    日期对齐：取 ETF/LOF 与指数的共同交易日交集（同 _calc_similarity）。

    返回 {avg_dev, te, ir, r2, roll_std, n} 或 None（n<30 数据不足）。
    - n>=60：全5项可算（TE/IR/roll_std 需足够样本）
    - 30<=n<60：仅 avg_dev+R²，TE/IR/roll_std=None（sqrt(252) 放大噪声不可靠）
    - n<30：返回 None
    """
    idx_series = idx_series_all.get(idx_id, [])
    if fund_type == "lof":
        cand_series = _fetch_lof_nav_series(cand_code)
    else:
        cand_series = etf_series_all.get(cand_code, [])
    if not idx_series or not cand_series:
        return None
    # 日期对齐：取交集（消除交易日历差异）
    idx_map = {d: c for d, c in idx_series}
    cand_map = {d: c for d, c in cand_series}
    common_dates = sorted(set(idx_map.keys()) & set(cand_map.keys()))
    n = len(common_dates)
    if n < 30:
        return None  # 至少30天才能算 avg_dev+R²

    idx_close = np.array([idx_map[d] for d in common_dates], dtype=float)
    cand_close = np.array([cand_map[d] for d in common_dates], dtype=float)
    # 日收益率（对齐后序列做 diff，消除交易日历差异）
    r_idx = np.diff(idx_close) / idx_close[:-1]
    r_cand = np.diff(cand_close) / cand_close[:-1]
    diff = r_cand - r_idx
    n_ret = len(diff)  # n-1

    # 指标1: avg_dev 日均跟踪偏离度 %
    avg_dev = float(np.mean(np.abs(diff)) * 100)

    # 指标4: R² 决定系数（corr²）
    r2 = None
    if np.std(r_idx) >= 1e-8 and np.std(r_cand) >= 1e-8:
        corr = np.corrcoef(r_cand, r_idx)[0, 1]
        if not np.isnan(corr):
            r2 = float(corr ** 2)

    result: dict = {
        "avg_dev": round(avg_dev, 4),
        "r2": round(r2, 4) if r2 is not None else None,
        "te": None,
        "ir": None,
        "roll_std": None,
        "n": n,
    }

    # n<60（n_ret<59）：TE/IR/roll_std 不可靠，仅存 avg_dev+R²
    if n_ret < 59:
        return result

    # n>=60：全5项可算
    # 指标2: TE 年化跟踪误差 %
    te = float(np.std(diff, ddof=1) * np.sqrt(252) * 100)
    result["te"] = round(te, 4)

    # 指标3: IR 信息比率（带符号，cap ±5 防极端主导）
    if te < 0.01:  # TE<0.01% 防分母爆炸
        ir = 0.0
    else:
        ir = float(np.mean(diff) * 252 / (np.std(diff, ddof=1) * np.sqrt(252)))
        ir = max(-5.0, min(5.0, ir))
    result["ir"] = round(ir, 4)

    # 指标5: roll_std 30交易日滚动TE的标准差 %
    # 用 sliding_window_view 向量化（替代 Python for 循环，提速 ~5x）
    from numpy.lib.stride_tricks import sliding_window_view
    windows = sliding_window_view(diff, 30)  # shape (n_ret-29, 30)
    if len(windows) >= 2:
        rolling_te = np.std(windows, axis=1, ddof=1) * np.sqrt(252) * 100
        result["roll_std"] = round(float(np.std(rolling_te, ddof=1)), 4)

    return result


def _enrich_with_tracking_score(
    out: dict,
    idx_series_all: dict[str, list[tuple]],
    etf_series_all: dict[str, list[tuple]],
) -> tuple[int, int, int]:
    """对所有指数的候选列表加 track_score/track_tier + 5项指标字段。

    两轮计算：
    1. 收集所有 n>=60 对的5项原始指标（用于百分位rank基线）
    2. 百分位rank（4项）+ IR分段函数 -> 加权composite -> tier归类

    n>=60: 全5项可算，track_score=0-100，track_low_confidence=False
    30<=n<60: 降权分（A: avg_dev+R² 按原权重归一化重分配算 composite
              + B: composite * sqrt(n/60) 可信度折扣），track_low_confidence=True
              sqrt 折扣比线性 n/60 更温和（n=47 时降11.5% vs 降21.7%），
              避免上市不久但跟踪好的 ETF 被过度惩罚
    n<30: track_score=None（数据太少）

    返回 (score_ok, score_none, lof_fetched) 统计数。
    """
    # 第一轮：算所有对的原始指标
    metrics_by_pair: dict[tuple[str, str], dict] = {}
    lof_fetched = 0
    for iid in list(out.keys()):
        if iid == "_meta":
            continue
        for c in out.get(iid, []):
            code = c.get("code", "")
            ft = c.get("fund_type", "etf")
            if ft == "lof" and code not in _LOF_NAV_CACHE:
                lof_fetched += 1
            m = _calc_tracking_metrics(iid, code, ft, idx_series_all, etf_series_all)
            if m:
                metrics_by_pair[(iid, code)] = m

    # 收集每项指标的值列表（所有有该指标的 pair，用于百分位rank基线）
    # te/roll_std 仅 n>=60 有值；avg_dev/r2 在 n>=30 即有值（含降权pair，使降权ETF在更宽群体中排名）
    te_vals = sorted(m["te"] for m in metrics_by_pair.values() if m["te"] is not None)
    r2_vals = sorted(m["r2"] for m in metrics_by_pair.values() if m["r2"] is not None)
    avg_dev_vals = sorted(m["avg_dev"] for m in metrics_by_pair.values() if m["avg_dev"] is not None)
    roll_std_vals = sorted(m["roll_std"] for m in metrics_by_pair.values() if m["roll_std"] is not None)

    def _pct_score(sorted_vals: list, target: float, lower_better: bool) -> float:
        """百分位rank -> 0-100 score。lower_better=True 时越低分越高。
        ties 用 average rank（bisect_left+right 均值）。"""
        nv = len(sorted_vals)
        if nv == 0 or target is None:
            return 50.0
        left = bisect.bisect_left(sorted_vals, target)
        right = bisect.bisect_right(sorted_vals, target)
        pct = (left + right) / 2 / nv * 100
        return 100 - pct if lower_better else pct

    def _ir_score(ir: float) -> float:
        """IR分段函数：|IR|<=0.5满分；正>0.5斜率80（惩罚轻）；负<-0.5斜率200（惩罚重）。"""
        abs_ir = abs(ir)
        if abs_ir <= 0.5:
            return 100.0
        if ir > 0.5:
            return max(0.0, 100 - (ir - 0.5) * 80)
        return max(0.0, 100 - (abs_ir - 0.5) * 200)  # ir < -0.5

    # 第二轮：算 score + tier
    score_ok = 0
    score_none = 0
    for iid in list(out.keys()):
        if iid == "_meta":
            continue
        for c in out.get(iid, []):
            code = c.get("code", "")
            m = metrics_by_pair.get((iid, code))

            # n<30 (not m): 数据太少，track_score=None, track_tier=null(灰灭灯)
            if not m:
                c["track_score"] = None
                c["track_tier"] = None
                c["track_low_confidence"] = False
                c["track_avg_dev"] = None
                c["track_te"] = None
                c["track_ir"] = None
                c["track_r2"] = None
                c["track_roll_std"] = None
                c["track_n"] = 0
                score_none += 1
                continue

            # 30<=n<60: 降权分（A: 可算项归一化重分配 + B: n/60 可信度折扣）
            if m["n"] < 60:
                # A: 可算项(avg_dev, r2)按原权重归一化重分配，缺项权重给可算项
                avail = []  # [(score, weight)]
                if m["avg_dev"] is not None:
                    avail.append((_pct_score(avg_dev_vals, m["avg_dev"], lower_better=True),
                                  TRACK_WEIGHTS["avg_dev"]))
                if m["r2"] is not None:
                    avail.append((_pct_score(r2_vals, m["r2"], lower_better=False),
                                  TRACK_WEIGHTS["r2"]))
                total_w = sum(w for _, w in avail)
                if total_w > 0:
                    composite_a = sum(s * (w / total_w) for s, w in avail)
                else:
                    composite_a = 50.0
                # B: 可信度折扣 sqrt(n/60)（比线性 n/60 更温和，避免短期好ETF被过度惩罚）
                composite = composite_a * ((m["n"] / 60.0) ** 0.5)

                if composite >= 75:
                    tier = "strong"
                elif composite >= 60:
                    tier = "related"
                elif composite >= 50:
                    tier = "approx"
                elif composite >= 30:
                    tier = "none"
                else:
                    tier = None  # <30 灰灭灯

                c["track_score"] = round(composite, 1)
                c["track_tier"] = tier
                c["track_low_confidence"] = True
                c["track_avg_dev"] = m["avg_dev"]
                c["track_te"] = None
                c["track_ir"] = None
                c["track_r2"] = m["r2"]
                c["track_roll_std"] = None
                c["track_n"] = m["n"]
                score_ok += 1
                continue

            # n>=60: 全5项 percentile/分段 score
            te_score = _pct_score(te_vals, m["te"], lower_better=True)
            r2_score = _pct_score(r2_vals, m["r2"], lower_better=False)
            avg_dev_score = _pct_score(avg_dev_vals, m["avg_dev"], lower_better=True)
            roll_std_score = _pct_score(roll_std_vals, m["roll_std"], lower_better=True)
            ir_score = _ir_score(m["ir"])

            # 方案A(2026-08-09): IR权重按match_method分层
            # 直接匹配(track_index)用TRACK_WEIGHTS(IR15%); 间接匹配用TRACK_WEIGHTS_INDIRECT(IR0%)
            w = TRACK_WEIGHTS if c.get("match_method") == "track_index" else TRACK_WEIGHTS_INDIRECT
            composite = (te_score * w["te"] + r2_score * w["r2"]
                         + avg_dev_score * w["avg_dev"]
                         + roll_std_score * w["roll_std"]
                         + ir_score * w["ir"])

            if composite >= 75:
                tier = "strong"
            elif composite >= 60:
                tier = "related"
            elif composite >= 50:
                tier = "approx"
            elif composite >= 30:
                tier = "none"
            else:
                tier = None  # <30 灰灭灯

            c["track_score"] = round(composite, 1)
            c["track_tier"] = tier
            c["track_low_confidence"] = False
            c["track_avg_dev"] = m["avg_dev"]
            c["track_te"] = m["te"]
            c["track_ir"] = m["ir"]
            c["track_r2"] = m["r2"]
            c["track_roll_std"] = m["roll_std"]
            c["track_n"] = m["n"]
            score_ok += 1

    return score_ok, score_none, lof_fetched


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
            etfs.append({"code": code, "name": etf_name, "amount": amount, "approx": approx,
                         "fund_type": "etf", "track_index_name": c.get("track_index_name", ""),
                         "match_method": "track_index"})
        result[iid] = etfs
    return result


# ── top1 稳定性：延迟纳入 + 3天滞回 ──
# 延迟纳入: track_n < MIN_TRACK_N 的 ETF 不参与 top1 候选（只展示不排 top1）。
#   阈值 90 = 60(算分最低要求) + 30(观察缓冲)，n>=90 才进候选 + 滞回 3 天。
# 滞回: 今日 eligible top1 != 昨日 stable_top1 时计 challenge count；
#   连续 HYSTERESIS_DAYS 天领先才切换 stable_top1，防小样本/临界点跳变。
# 标记: stable_top1 ETF 加 stable_top1=True 字段，前端 _topEtfByScore 优先用。
# 状态: _hysteresis 顶层 key 存 {index_id: {stable_top1, challenge}}，下次运行读取。
MIN_TRACK_N = 90
HYSTERESIS_DAYS = 3


def _apply_hysteresis(out: dict) -> None:
    """3天滞回 stable_top1：读昨日 OUT 的 _hysteresis，今日 eligible top1 连续3天领先才切换。

    延迟纳入: track_n<90 的 ETF 不参与 top1 候选（只展示不排 top1）。
    滞回: 今日 top1 != 昨日 stable_top1 时，计 challenge count；连续3天才切换。
    标记: stable_top1 ETF 加 stable_top1=True，前端 _topEtfByScore 优先用。
    """
    prev_hyst = {}
    if OUT.exists():
        try:
            prev_data = json.loads(OUT.read_text(encoding="utf-8"))
            prev_hyst = prev_data.get("_hysteresis", {})
        except (json.JSONDecodeError, OSError):
            pass

    hyst = {}
    for iid in list(out.keys()):
        if iid.startswith("_"):
            continue
        etfs = out.get(iid, [])
        if not etfs:
            continue

        # 清除旧标记（防上次标记残留）
        for e in etfs:
            e.pop("stable_top1", None)

        # 今日 eligible top1（候选挑战者）：track_n>=90 且 track_score 非 None
        eligible = [e for e in etfs
                    if e.get("track_n", 0) >= MIN_TRACK_N
                    and e.get("track_score") is not None]
        today_top1_code = max(eligible, key=lambda e: e["track_score"])["code"] if eligible else None

        # 昨日状态
        prev = prev_hyst.get(iid, {})
        prev_stable = prev.get("stable_top1")
        prev_chal = prev.get("challenge") or {}
        prev_chal_code = prev_chal.get("code")
        prev_count = prev_chal.get("count", 0)

        # prev_stable 已不在今日列表 -> 重置
        today_codes = {e["code"] for e in etfs}
        if prev_stable and prev_stable not in today_codes:
            prev_stable = None

        stable_top1 = None
        challenge = None

        if prev_stable is None:
            # 首次/重置：用今日 eligible top1（可能 None=无候选）
            stable_top1 = today_top1_code
        elif today_top1_code is None:
            # 无 eligible 挑战者，保持 prev_stable
            stable_top1 = prev_stable
        elif today_top1_code == prev_stable:
            # 今日 top1 与昨日 stable 一致，保持
            stable_top1 = prev_stable
        else:
            # 挑战者出现，计数
            count = prev_count + 1 if today_top1_code == prev_chal_code else 1
            if count >= HYSTERESIS_DAYS:
                # 连续3天领先，切换
                stable_top1 = today_top1_code
            else:
                # 保持昨日 stable，记录挑战
                stable_top1 = prev_stable
                challenge = {"code": today_top1_code, "count": count, "threshold": HYSTERESIS_DAYS}

        hyst[iid] = {"stable_top1": stable_top1, "challenge": challenge}

        # 标记 stable_top1 ETF
        if stable_top1:
            for e in etfs:
                if e["code"] == stable_top1:
                    e["stable_top1"] = True
                    break

    out["_hysteresis"] = hyst
    _stable = sum(1 for v in hyst.values() if v.get("stable_top1") and not v.get("challenge"))
    _challenging = sum(1 for v in hyst.values() if v.get("challenge"))
    _none = sum(1 for v in hyst.values() if not v.get("stable_top1"))
    print(f"\n=== 滞回 stable_top1（3天滞回 + 延迟纳入 track_n<{MIN_TRACK_N}）===")
    print(f"  {len(hyst)} 指数: {_stable} 稳定, {_challenging} 挑战中, {_none} 无候选")


def main():
    cfg = load_config()
    name_by_id = {i["id"]: i["name"] for i in cfg.get("indices", [])}
    # 宽基全量改造：所有指数统一 a+b+c+d，不分层(宽基track_index单一/行业概念全量的分层取消)
    # board_ids 收行业+概念+宽基(market=a/hk)，全球指数(market=global)和港股行业(market=hk_industry)不收
    board_ids = [i["id"] for i in cfg.get("indices", [])
                 if i.get("market") in ("industry", "concept", "a", "hk") and i.get("enabled", True)]

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
                           "sort_by": "track_score(降序,跟踪分最高在前; None排最后); LOF净值取自fund_open_fund_info_em",
                           "match_method": "全量叠加: track_index_code(base) + track_index_name + overlap + kw + holdings_overlap(d) + sum_pct(e) 合并去重, 按track_score降序排",
                           "similarity_fields": "similarity(1-max_err/100) / max_err(5周期最大误差%) / grade(excellent<1%/good<5%/warn>=5%) / fund_type(etf|lof)",
                           "note": "宽基全量改造: 所有指数(行业/概念/宽基/红利/港股)统一 a+b+c+d+e 全量,不分层; "
                                   "e层=sum_pct概念暴露度(跨股持仓占比求和),和d层(max×count)独立排序各产Top12候选,"
                                   "候选列表含所有来源匹配ETF+LOF; 按track_score降序排序; "
                                   "行业/概念ETF跟踪中证/国证指数非申万/同花顺精准跟踪,grade=good/warn属正常"}}
    empty_boards = []
    # 加载 fundf10 抓取的 ETF track_index 缓存
    track_idx_map = _load_etf_track_index()
    if track_idx_map:
        print(f"\ntrack_index 匹配：加载 {len(track_idx_map)} 只 ETF 的 track_index 缓存")
    # 加载 LOF track_index 缓存（fundf10 抓取，含 160225 等 LOF，纳入候选池）
    lof_track_map = _load_lof_track_index()
    if lof_track_map:
        print(f"  + LOF track_index 缓存 {len(lof_track_map)} 只（fund_type=lof，纳入候选池）")
        track_idx_map.update(lof_track_map)  # 合并，LOF 已标 fund_type=lof

    # ── 宽基/红利/港股指数 base：track_index_code 精准匹配（移到 Layer 1 之前作宽基base）──
    # 宽基全量改造：_build_index_etf_map_auto 原在所有Layer后覆盖out[iid]，现移到Layer 1前
    # 作宽基base，Layers 1-4 在此基础上叠加(merge)，不再覆盖。
    # 覆盖 14 个指数(sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50/csi_div/div_lowvol/sz_div/hsi/hstech/hscei)。
    reverse_map = _load_etf_index_map_reverse()
    if reverse_map:
        index_etf_map = _build_index_etf_map_auto(reverse_map, df_by_code)
    else:
        # etf_index_map.json 缺失 -> akshare 名称匹配兜底（防静默失败，不退化为全空）
        index_etf_map = _akshare_name_fallback(df_by_code)
    for iid, etfs in index_etf_map.items():
        out[iid] = etfs  # 宽基base，后续Layers叠加
    print(f"\n宽基/红利/港股 base（track_index_code 精准匹配）：{len(index_etf_map)} 个指数")
    for iid_ in index_etf_map.keys():
        etfs_ = out.get(iid_, [])
        if etfs_:
            print(f"  {name_by_id.get(iid_, iid_):<10} {len(etfs_)} 只 ETF [base]")

    # ── 行业/概念/宽基匹配（全量多来源叠加：track_index + overlap + KW + holdings(d+e) 合并去重）──
    # 宽基全量改造：所有指数统一 a+b+c+d+e，不分层(宽基track_index单一/行业概念全量的分层取消)。
    # 五层来源（优先级递减，同一ETF多来源命中取最优来源标记）：
    #   0. track_index_code 精准匹配（宽基base，_build_index_etf_map_auto，已在上方注入）
    #   1. track_index_name 关键词匹配（fundf10 抓取的 ETF 跟踪指数名，最精准）
    #   2. overlap 成分股重叠（thsc 概念用东财BK成分股∩指数成分股Jaccard重叠度）
    #   3. KW 名称子串匹配（ETF名称关键词，精度最差，兜底补充）
    #   4. holdings_overlap ETF持仓重叠（d层: max_hold_pct×overlap_count 综合分排序）
    #   5. sum_pct 概念暴露度（e层: sum_hold_pct 跨股持仓占比求和，覆盖"分散持多只/合计高"的ETF）
    # 合并规则：后层只添加前层未匹配到的ETF（同code不覆盖），保留最优来源的match_method。

    # 第1层：track_index_name 关键词匹配（所有 board_id，merge 到宽基base上）
    # 宽基全量：宽基已有 _build_index_etf_map_auto 的 track_index_code base，此层补充 track_index_name 匹配
    for iid in board_ids:
        etfs = _match_by_track_index(iid, track_idx_map, df_by_code)
        if not etfs:
            out.setdefault(iid, [])
            continue
        existing_codes = {e["code"] for e in out.get(iid, [])}
        added = 0
        for e in etfs:
            if e["code"] not in existing_codes:
                out.setdefault(iid, []).append(e)
                existing_codes.add(e["code"])
                added += 1
        if added:
            print(f"  [track_index叠加] {iid}: 新增 {added} 只（已有 {len(out.get(iid, [])) - added}）")

    # 第2层：overlap 成分股匹配（全量叠加：对所有 thsc 概念，不只空概念）
    # overlap 模块覆盖 CONCEPT_BK_MAP 中 9 个 thsc 概念，合并去重（同 code 不覆盖 track_index 结果）
    thsc_ids = [iid for iid in board_ids if iid.startswith("thsc_")]
    if thsc_ids:
        print(f"\n成分股重叠算法：对 {len(thsc_ids)} 个 thsc 概念叠加匹配（全量叠加，非仅空概念）")
        try:
            overlap_result = _overlap_match(df, df_by_code, excl_mask)
            for iid, etfs in overlap_result.items():
                if not etfs:
                    continue
                existing_codes = {e["code"] for e in out.get(iid, [])}
                added = 0
                for e in etfs:
                    if e["code"] not in existing_codes:
                        e.setdefault("approx", True)
                        e["match_method"] = "overlap"
                        out.setdefault(iid, []).append(e)
                        existing_codes.add(e["code"])
                        added += 1
                if added:
                    print(f"  [overlap叠加] {iid}: 新增 {added} 只（track_index 已有 {len(out.get(iid, [])) - added}）")
        except Exception as e:
            print(f"  [overlap] ⚠ 重叠算法异常,保留 track_index 结果: {e}")

    # 第3层：KW 名称子串匹配（全量叠加：对所有 board_id，合并去重）
    # KW 匹配是名称子串，精度最差，作为补充来源（如 track_index 缓存缺失或 fundf10 抓取失败时）
    for iid in board_ids:
        kws = KW.get(iid, [])
        if not kws:
            continue
        existing_codes = {e["code"] for e in out.get(iid, [])}
        mask = ~excl_mask & names.apply(lambda n: any(k in n for k in kws))
        hit = df[mask].sort_values("成交额", ascending=False)
        added = 0
        # Bug4/Bug5: TRACK_INDEX_KW exclude 过滤防 kw 兜底纳入应属其他指数的 ETF
        # (如 515220 中证煤炭应属 csi_399998, 512580 中证环保应属 csi_000827)
        # 只影响有 exclude 的申万 board, thsc 概念 exclude=[] 不受影响
        exc_ti = TRACK_INDEX_KW.get(iid, {}).get("exclude", [])
        for _, r in hit.iterrows():
            code = str(r["代码"])
            if code in existing_codes:
                continue  # 已被 track_index/overlap 匹配，不覆盖
            # 尝试从 track_idx_map 拿 track_index_name
            tin = ""
            ti_info = track_idx_map.get(code)
            if ti_info:
                tin = ti_info.get("track_index", "") or ""
            # exclude 检查：track_index_name 或 ETF名称 命中 exclude 关键词则跳过
            if exc_ti:
                rname_tmp = str(r["名称"])
                if (tin and any(k in tin for k in exc_ti)) or any(k in rname_tmp for k in exc_ti):
                    continue
            # 宽基 KW 误匹配过滤（正验证）：宽基指数(在 INDEX_TRACK_MAP 中)的 KW 匹配，
            # 若 ETF 有 track_index_name 则必须匹配 TRACK_INDEX_KW include，否则过滤。
            # 防"上证"KW命中"上证50ETF"(track_index=上证50指数≠上证综合)、
            # "深成"KW命中"深成长ETF"(track_index=深证成长40≠深证成份)等同前缀不同指数误匹配。
            inc_ti = TRACK_INDEX_KW.get(iid, {}).get("include", [])
            if inc_ti and tin and not any(k in tin for k in inc_ti):
                continue  # track_index_name 不匹配预期指数，过滤
            out.setdefault(iid, []).append({
                "code": code,
                "name": str(r["名称"]),
                "amount": round(float(r["成交额"]) / 1e8, 2),
                "approx": True,  # KW 名称匹配兜底，approx=true
                "track_index_name": tin,
                "match_method": "kw",
            })
            existing_codes.add(code)
            added += 1
        if added:
            print(f"  [kw叠加] {iid}: 新增 {added} 只（已有 {len(out.get(iid, [])) - added}）")

    # 第4+5层：ETF持仓重叠匹配（d层 max×count + e层 sum_pct，跑1-3层<6只ETF的 board_id，含宽基）
    # 宽基全量改造：去掉 thsc_ 限制，宽基(sz/csi_div/sz_div/hscei等<6只ETF)也跑第4+5层。
    # thsc 概念用 CONCEPT_BK_MAP(东财BK成分股)，宽基用 BROAD_INDEX_CONST_MAP(index_stock_cons)。
    # d层: max_hold_pct×overlap_count 综合分排序 Top-12; e层: sum_hold_pct 概念暴露度排序 Top-12(>=15%)
    # 性能优化：已有足量ETF（>=6只）的指数跳过；宽基 sh(7)/hs300(40)/csi500(35)等跳过。
    # 首次跑宽基 sz(500股)~4min + csi_div(100股)~1min，7天缓存后~1-2min。
    # 禁入: universe_rules.yaml excluded_categories.空数组(mode=empty_array) 的指数，防止 空数组被 holdings/sum_pct 填满导致 §23.6 对称校验 FAIL
    _HOLDINGS_EXCLUDE = {"bj50", "bj_399", "csi_930820", "ftse100", "kospi"}
    holdings_candidates = [
        iid for iid in board_ids
        if iid not in _HOLDINGS_EXCLUDE and len(out.get(iid, [])) < 6
    ]
    if holdings_candidates:
        print(f"\n持仓重叠算法（第4层）：对 {len(holdings_candidates)} 个 1-3层<6只ETF 的指数叠加匹配（含宽基）")
        try:
            holdings_result = _holdings_match(holdings_candidates, df_by_code, track_idx_map)
            for iid, etfs in holdings_result.items():
                if not etfs:
                    continue
                existing_codes = {e["code"] for e in out.get(iid, [])}
                added = 0
                for e in etfs:
                    if e["code"] not in existing_codes:
                        e.setdefault("approx", True)
                        out.setdefault(iid, []).append(e)
                        existing_codes.add(e["code"])
                        added += 1
                if added:
                    print(f"  [holdings叠加] {iid}: 新增 {added} 只（已有 {len(out.get(iid, [])) - added}）")
        except Exception as e:
            print(f"  [holdings] ⚠ 持仓重叠算法异常,保留前3层结果: {e}")

    # 记录留空板块（含宽基，宽基已在 Layer 1 前由 _build_index_etf_map_auto 注入 base）
    for iid in board_ids:
        if not out.get(iid):
            empty_boards.append(f"{iid} {name_by_id.get(iid)}")

    # sz_div 深证红利 manual fallback（2026-08-07）：
    # ETF 159905"红利ETF工银"名无"深"字，gen_etf_index_map.py INDEX_NAME_RULES["sz_div"] include=[]
    # 主动留空 -> etf_index_map.json[159905].track_index_code="" status="no_track" -> reverse_map 无
    # 399324 -> _build_index_etf_map_auto 返空 -> Layers 1-4 也无新增 -> board_etf_map.json["sz_div"]=[]。
    # 手动注入 159905（eastmoney fundf10 jbgk_159905 验证：跟踪标的=深证红利指数，业绩比较基准=
    # 深证红利价格指数，指数代码 399324 经 eastmoney push2 f57=399324 f58=深证红利 确认）。
    if not out.get("sz_div"):
        _sz_code = "159905"
        _sz_name = "红利ETF工银"
        _r = df_by_code.get(_sz_code) if df_by_code else None
        if _r is not None:
            try:
                _sz_amt = round(float(_r["成交额"]) / 1e8, 2)
                _sz_name = str(_r["名称"])
            except (TypeError, ValueError, KeyError):
                _sz_amt = _fallback_159905_amount(reverse_map)
        else:
            _sz_amt = _fallback_159905_amount(reverse_map)
        out["sz_div"] = [{
            "code": _sz_code,
            "name": _sz_name,
            "amount": _sz_amt,
            "approx": False,
            "track_index_name": "深证红利指数",
            "track_index_code": "399324",
            "match_method": "manual_fallback",
            "fund_type": "etf",
        }]
        # 移除 sz_div 的留空标记（上方 L934 循环在注入前已 append，现在已非空）
        empty_boards = [b for b in empty_boards if not b.startswith("sz_div ")]
        print(f"  [sz_div fallback] 注入 {_sz_code} {_sz_name} ({_sz_amt}亿) [manual_fallback]")

    # ── 全球指数 -> 跨境 ETF 候选（KW 名称匹配 + cross_border 绕过 EXCLUDE）──
    # 2026-08-09 走势图问题2：us_dji/us_spx/us_ndx/us_ixic/nikkei225/dax/cac40/ftse100/kospi
    # 跨境 ETF track_index_code 全空，用 ETF 名称关键词匹配（纳指/标普/日经/德国/法国 命中 EXCLUDE，需绕过）。
    # 无跨境 ETF 的指数（ftse100/kospi）留空，前端显示"无ETF"；cgb_* 国债类不列入。
    global_etf_map = _build_global_etf_map(df, df_by_code, track_idx_map)
    for iid, etfs in global_etf_map.items():
        out[iid] = etfs
        if not etfs:
            empty_boards.append(f"{iid} {name_by_id.get(iid, iid)}（全球指数，无跨境ETF）")
    print(f"\n全球指数 ETF 联动（{len(global_etf_map)} 个，KW 名称匹配 + cross_border）:")
    for iid, etfs in global_etf_map.items():
        if etfs:
            e = etfs[0]
            extra = f" +{len(etfs)-1}" if len(etfs) > 1 else ""
            print(f"  {name_by_id.get(iid, iid):<12} {e['code']} {e['name']} ({e['amount']}亿){extra} [kw_global]")
        else:
            print(f"  {name_by_id.get(iid, iid):<12} (无跨境ETF)")

    # ── 路 A-2b：实测相似度计算 + 按相似度排序 ──
    # 每候选 vs 指数算多周期 max_err（5周期涨跌幅最大误差%），加 similarity/max_err/grade 字段
    # 排序改为按 max_err 升序（最相似在前），替代原 amount 降序
    print("\n=== 路 A-2b 相似度计算（实测涨跌幅 max_err 分级）===")
    idx_series_all = _load_index_close_series()
    etf_series_all = _load_etf_close_series()
    print(f"  index_daily: {len(idx_series_all)} 个指数, etf_daily: {len(etf_series_all)} 只 ETF")
    sim_ok, sim_fail, lof_fetched = _enrich_with_similarity(out, idx_series_all, etf_series_all)
    print(f"  相似度计算完成: {sim_ok} 成功, {sim_fail} 数据不足(grade=n/a), {lof_fetched} 只LOF净值实时取")

    # ── 路 D1：ETF跟踪5维度评分（日收益率5指标百分位加权）──
    # 弥补旧算法只看起点终点的缺陷，用日收益率序列捕捉全路径偏离（V型尖刺/roll_std）
    print("\n=== 路 D1 ETF跟踪5维度评分（日收益率5指标百分位加权）===")
    track_ok, track_none, track_lof = _enrich_with_tracking_score(out, idx_series_all, etf_series_all)
    print(f"  跟踪评分完成: {track_ok} 有分, {track_none} 数据不足(track_score=None), {track_lof} 只LOF净值实时取")

    # ── 方案0排序修复：最终按 track_score 降序排（None 排最后）──
    # _enrich_with_similarity 的 max_err 升序排是中间步骤（track_score 尚未计算），
    # 最终排序改为 track_score 降序（track_score 需 N>=30 天日收益率数据，5维度百分位加权，
    # 比 max_err 10天相似度更可靠）。避免 top1 是 track_score=None(N<30) 的 ETF 埋没高跟踪分 ETF。
    # 稳定排序：同 track_score 的条目保持 max_err 升序（前序排序结果作隐式 tiebreaker）。
    for iid in list(out.keys()):
        if iid == "_meta":
            continue
        cands = out.get(iid, [])
        if not cands:
            continue
        cands.sort(key=lambda x: (
            x.get("track_score") is None,  # False(0) 在前 True(1) 在后 -> None 排最后
            -(x.get("track_score") if x.get("track_score") is not None else 0),  # 降序
        ))

    # ── top1 稳定性：延迟纳入 + 3天滞回 stable_top1 ──
    # 读昨日 OUT 的 _hysteresis 状态，今日 eligible top1(track_n>=90) 连续3天领先才切换。
    # 标记 stable_top1 ETF 加 stable_top1=True，前端 _topEtfByScore 优先用。
    _apply_hysteresis(out)

    # 写盘（compact 格式减体积：加 track_* 8字段后 indent=2 771KB/indent=1 704KB 超 700KB，
    # compact ~615KB 达标。后端文件 json.loads 读取不受格式影响，debug 用 python -m json.tool 查看）
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 防静默失败校验（§15 防复现）：14 宽基/红利/港股指数中，除 sz_div（已有 manual_fallback 兜底注入 159905 红利ETF工银，靠兜底非正常匹配故不列入必填）
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

    # 摘要（宽基全量改造：board_ids 含行业/概念/宽基/红利/港股，统一统计）
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
    print(f"生成 {OUT.name}：{total} 指数（行业/概念/宽基/红利/港股，统一全量 a+b+c+d）")
    print(f"候选数分布: 0个={dist['0']}  1个={dist['1']}  2-3个={dist['2-3']}  4+个={dist['4+']}")
    print(f"\n宽基/红利/港股指数 ETF（{len(index_etf_map)} 个，track_index_code base + Layers叠加）:")
    for iid in index_etf_map.keys():
        etfs = out.get(iid, [])
        if etfs:
            e = etfs[0]
            extra = f" +{len(etfs)-1}" if len(etfs) > 1 else ""
            approx_tag = " [approx]" if e.get("approx") else ""
            method = e.get("match_method", "?")
            print(f"  {name_by_id.get(iid, iid):<10} {e['code']} {e['name']} ({e['amount']}亿){extra}{approx_tag} <{method}>")
        else:
            print(f"  {name_by_id.get(iid, iid):<10} (无匹配ETF)")
    print(f"\n留空板块（{n_empty}，无相关ETF/主动留空）:")
    for b in empty_boards:
        print(f"  {b}")
    # 抽样展示 top1（track_score 最高）
    print("\n各板块 top1（track_score最高）抽样:")
    for iid in board_ids:
        etfs = out.get(iid, [])
        if etfs:
            e = etfs[0]
            extra = f" +{len(etfs)-1}" if len(etfs) > 1 else ""
            method = e.get("match_method", "?")
            tin = e.get("track_index_name", "")
            tin_tag = f" [{tin}]" if tin else ""
            ts = e.get("track_score")
            tier = e.get("track_tier")
            ts_tag = f" <score={ts} {tier}>" if ts is not None else " <score=None>"
            ft = e.get("fund_type", "etf")
            print(f"  {name_by_id.get(iid, iid):<16} {e['code']} {e['name']} ({e['amount']}亿){extra} <{method}>{tin_tag}{ts_tag} [{ft}]")

    # 匹配方式统计（行业/概念/宽基统一）
    method_cnt = {"track_index": 0, "overlap": 0, "kw": 0, "holdings_overlap": 0, "sum_pct": 0, "manual_fallback": 0, "empty": 0}
    for iid in board_ids:
        etfs = out.get(iid, [])
        if not etfs:
            method_cnt["empty"] += 1
        else:
            m = etfs[0].get("match_method", "kw")
            method_cnt[m] = method_cnt.get(m, 0) + 1
    print(f"\n匹配方式统计（全部 {total} 个指数）:")
    print(f"  track_index 精准: {method_cnt['track_index']}")
    print(f"  overlap 成分股: {method_cnt['overlap']}")
    print(f"  kw 名称兜底: {method_cnt['kw']}")
    print(f"  holdings 持仓重叠(d层): {method_cnt.get('holdings_overlap', 0)}")
    print(f"  sum_pct 概念暴露度(e层): {method_cnt.get('sum_pct', 0)}")
    print(f"  manual_fallback: {method_cnt.get('manual_fallback', 0)}")
    print(f"  留空: {method_cnt['empty']}")


if __name__ == "__main__":
    main()
