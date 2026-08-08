# 主功能快速全量回归 Smoke 清单

> **目的**:拦截"老功能突然坏了/文件丢了"事故(全部无ETF/成交额昨日值/KPI角标停/预估爆炸)。大阶段结束/上线前必行,不等用户发现再修。
> **触发时机**:当天开发功能多后 / 大阶段结束 / 上线前 / 改动数据产物生成脚本后。
> **执行者**:task-reviewer 子 agent(不占主控上下文),按本清单逐项 curl 验证。
> **模型约束**:只文本禁图片,验证用 curl JSON 数据层 + 关键交互文字描述 + 让用户确认显示 三层。
> **落档**:本文件进 git,reviewer agent 读取执行。CLAUDE.md §15 三层机制③。

---

## Part 1: 数据产物完整性校验规则（拦截"文件丢了/空了"）

> 对应 CLAUDE.md §15 ①。脚本设计见 Part 2，超标 fail 不让 deploy。

### 校验项表

| # | 文件 | 位置 | 校验规则 | 阈值 | 严重 | 生成脚本 | 失败现象(历史事故) |
|---|------|------|----------|------|------|----------|---------------------|
| C1 | `board_etf_map.json` | `data/` | 空数组 key 占比 | <30% | **fail** | `scripts/build_board_etf_map.py` | 全部无ETF(27/73=37%) |
| C2 | `index_etf_map.json` | `data/` | 文件存在 | 存在 | **fail** | fund_etf_spot_em 前序 | "etf_index_map.json丢了" |
| C3 | `overview.json` | `static-site/data/` | `date`==今日或最近交易日 | == | **fail** | `static-site/export.py` | KPI显示昨日 |
| C4 | `overview.json` | 同上 | `collected_at` 含今日 | 含 | **fail** | 同上 | 数据不更新 |
| C5 | `overview.json` | 同上 | `today.scores` 9 key 非空 | 9/9 | **fail** | 同上 | 情绪分缺失 |
| C6 | `overview.json` | 同上 | `industry_heatmap` len | ==31 | warn | 同上 | 行业热力图缺 |
| C7 | `overview.json` | 同上 | `indices_sparkline` 含 sh/sz/hs300/sz50/cyb | 5/5 | warn | 同上 | 指数sparkline缺 |
| C8 | `intraday_snapshot.json` | `static-site/data/` | `collected_at` 含今日 | 含 | **fail** | `app/collector/intraday_snapshot.py` | 分时图无数据 |
| C9 | `intraday_snapshot.json` | 同上 | `indices` len | >=17 | **fail** | 同上 | 指数实时缺 |
| C10 | `intraday_snapshot.json` | 同上 | `industries` len | ==31 | warn | 同上 | 行业实时缺 |
| C11 | `intraday_snapshot.json` | 同上 | 盘中(`is_closed==false`)`amount_forecast` 非空 | 非空 | **fail** | 同上 | 预估成交额缺失 |
| C12 | `intraday_snapshot.json` | 同上 | `amount_forecast` < 50000 (亿) | <50000 | **fail** | 同上 | 预估9.52万亿爆炸 |
| C13 | `boot.json` | `static-site/data/` | `overview.date`==今日或最近交易日(盘中更新后) | == | **fail** | `intraday_snapshot.py` | 成交额显示昨日值 |
| C14 | `boot.json` | 同上 | `_meta.missing` == [] | 空 | **fail** | 同上 | 首屏包缺文件 |
| C15 | `boot.json` | 同上 | `_meta.files` 含 11 个 | ==11 | warn | 同上 | 首屏包不完整 |
| C16 | `alert.json` | `static-site/data/` | `date`==今日(盘后)或昨日(盘中) | 匹配 | **fail** | `app/alert_score.py` | 信号不更新 |
| C17 | `alert.json` | 同上 | `high.score` 非 null | 非 null | **fail** | 同上 | 信号评分缺失 |
| C18 | `alert.json` | 同上 | `history` len | >=1 | warn | 同上 | 信号历史缺 |
| C19 | `notifications.json` | `static-site/data/` | `date`==今日 | == | **fail** | `scripts/export_notifications.py` | 通知不更新 |
| C20 | `notifications.json` | 同上 | `signals` 是数组 | list | warn | 同上 | 通知面板空 |
| C21 | `schedule_stats.json` | `static-site/data/` | list len | ==9 | warn | `scripts/gen_schedule_stats.py` | 任务监控缺 |
| C22 | `schedule_stats.json` | 同上 | 各 `last_exit` | 非 143/133/1 | **fail** | 同上 | 任务异常退出 |
| C23 | `fund_score_top.json` | `static-site/data/` | `date`==今日或昨日(日频) | 匹配 | warn | `scripts/export_fund_score.py` | 基金评分滞后 |
| C24 | `fund_score_top.json` | 同上 | `count`==100 且 `data` len==100 | ==100 | warn | 同上 | 基金评分缺 |
| C25 | `trade_sim_indices.json` | `static-site/data/` | list len | >=100 | warn | lab 相关 | 策略实验室入口空 |
| C26 | `index/{id}-all.json` | R2 `ssd.fx8.store/index/` | enabled 指数有文件 + `etfs` 字段非空 | 非空 | **fail** | `export.py` | 全部无ETF(根因) |
| C27 | `alert_analyze_{iid}.json` | `static-site/data/` | enabled 指数/行业有文件 + 含 `high`/`low` | 存在 | warn | `scripts/export_alert_analyze.py` | 信号走势弹窗空 |
| C28 | `ad_line.json` | `static-site/data/` | `data` list 非空 | 非空 | warn | `export.py` | 涨跌家数空 |
| C29 | `etf_score_list_{buy,sell,hold}.json` | R2 `ssd.fx8.store/data/` | 文件存在 + 非空 | 存在 | warn | lab 相关 | ETF评分列表空 |

### 校验命令模板（reviewer agent 逐项 curl）

```bash
# 今日日期(YYYYMMDD 无连字符,与 overview.date 格式一致)
TODAY=$(date +%Y%m%d)
# 最近交易日(周末取周五;法定假日仍需人工判断,非交易日 overview.date=最近交易日不算FAIL)
DOW=$(date +%u)  # 6=周六 7=周日
if [ "$DOW" = "6" ]; then LAST_TRADING_DAY=$(date -v-1d +%Y%m%d); \
elif [ "$DOW" = "7" ]; then LAST_TRADING_DAY=$(date -v-2d +%Y%m%d); \
else LAST_TRADING_DAY=$TODAY; fi
# 周末/盘前判断: alert.json 盘后才更新,盘中 date 可能是昨日(正常)
IS_WEEKEND=$(date +%u)  # 6=周六 7=周日

# C1: board_etf_map 空占比 (在 data/ 非 static-site/data/)
python3 -c "
import json; d=json.load(open('data/board_etf_map.json'))
keys=list(d.keys()) if isinstance(d,dict) else []
empty=[k for k in keys if not d.get(k)]
pct=len(empty)/len(keys)*100 if keys else 100
print(f'C1 board_etf_map: {len(empty)}/{len(keys)}={pct:.1f}% empty', 'FAIL' if pct>=30 else 'OK')
"

# C3/C5: overview date + scores
python3 -c "
import json; d=json.load(open('static-site/data/overview.json'))
print('C3 overview.date:', d.get('date'), 'FAIL' if d.get('date') not in ('$TODAY','$LAST_TRADING_DAY') else 'OK')
s=d.get('today',{}).get('scores',{})
miss=[k for k in ['a_sentiment','cross_market','fear_greed','sentiment_csi1000','sentiment_csi500','sentiment_cyb','sentiment_hs300','sentiment_kc50','sentiment_sz50'] if not s.get(k)]
print('C5 scores missing:', miss, 'FAIL' if miss else 'OK')
"

# C8/C9/C11/C12: intraday_snapshot
python3 -c "
import json; d=json.load(open('static-site/data/intraday_snapshot.json'))
ca=d.get('collected_at','')
print('C8 collected_at:', ca, 'FAIL' if '$TODAY' not in ca.replace('-','') else 'OK')
print('C9 indices len:', len(d.get('indices',[])), 'FAIL' if len(d.get('indices',[]))<17 else 'OK')
af=d.get('amount_forecast')
print('C11 amount_forecast:', af, 'FAIL' if af is None else 'OK')
print('C12 amount_forecast<50000:', af, 'FAIL' if af is not None and af>=50000 else 'OK')
"

# C13/C14: boot.json overview.date==今日(盘中更新后) + missing
python3 -c "
import json; d=json.load(open('static-site/data/boot.json'))
ov=d.get('overview',{})
print('C13 boot.overview.date:', ov.get('date'), 'FAIL' if ov.get('date') not in ('$TODAY','$LAST_TRADING_DAY') else 'OK')
m=d.get('_meta',{}).get('missing',[])
print('C14 boot._meta.missing:', m, 'FAIL' if m else 'OK')
"

# C26: index/{id}-all.json etfs 非空 (R2, 抽查 sh/hs300/cyb)
for id in sh hs300 cyb sz50 csi1000; do
  curl -s "https://ssd.fx8.store/index/${id}-all.json" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin); e=d.get('etfs',[])
  print('C26 $id etfs len:', len(e) if isinstance(e,list) else e, 'FAIL' if not e else 'OK')
except: print('C26 $id: parse error FAIL')
"
done
```

---

## Part 2: check_data_integrity.py（已实施）

> 对应 CLAUDE.md §15 ①。**已实施**: `scripts/check_data_integrity.py`(commit f00978545,12 校验函数),已接入 `scripts/deploy.sh` L122-123(`--deploy-mode` fail 则 exit 阻断 deploy)。校验规则见 Part 1 表。
>
> 运行: `python3 scripts/check_data_integrity.py [--deploy-mode] [--strict]`
>
> 以下为设计参考(与已实施脚本一致,保留作阈值依据文档):

### 脚本设计（设计参考,已实施于 scripts/check_data_integrity.py）

```python
#!/usr/bin/env python3
"""数据产物完整性校验。超标返非0,接入 deploy.sh 前置阻断坏数据上线。
用法: python3 scripts/check_data_integrity.py [--deploy-mode] [--file <path>] [--strict]
  --deploy-mode: deploy 前置调用,fail 则 exit 1 阻断
  --file <path>: 单文件校验
  --strict: warn 也当 fail(默认只 fail 阻断)
"""
import json, os, sys, datetime, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SS_DATA = os.path.join(ROOT, "static-site", "data")
DATA = os.path.join(ROOT, "data")
TODAY = datetime.date.today().strftime("%Y%m%d")
TODAY_ISO = datetime.date.today().isoformat()
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y%m%d")
# 最近交易日(周末取周五;法定假日仍需人工判断,非交易日 overview.date=最近交易日不算FAIL)
_td = datetime.date.today()
if _td.weekday() == 5:      # 周六 -> 周五
    LAST_TRADING_DAY = (_td - datetime.timedelta(days=1)).strftime("%Y%m%d")
elif _td.weekday() == 6:    # 周日 -> 周五
    LAST_TRADING_DAY = (_td - datetime.timedelta(days=2)).strftime("%Y%m%d")
else:
    LAST_TRADING_DAY = TODAY

def _load(path):
    try:
        with open(path) as f: return json.load(f), None
    except Exception as e: return None, str(e)

def _date_ok(val, allow_yesterday=False):
    if not val: return False
    val = str(val).replace("-", "")
    if TODAY in val: return True
    if allow_yesterday and YESTERDAY in val: return True
    return False

# --- C1: board_etf_map 空占比 ---
def check_board_etf_map():
    d, err = _load(os.path.join(DATA, "board_etf_map.json"))
    if err: return "fail", f"board_etf_map.json 读取失败: {err}"
    keys = list(d.keys()) if isinstance(d, dict) else []
    empty = [k for k in keys if not d.get(k)]
    pct = len(empty) / len(keys) * 100 if keys else 100
    if pct >= 30:
        return "fail", f"board_etf_map 空数组 {len(empty)}/{len(keys)}={pct:.1f}% >=30% (全部无ETF根因)"
    return "ok", f"board_etf_map 空占比 {pct:.1f}%"

# --- C2: index_etf_map.json 存在 ---
def check_index_etf_map_exists():
    p = os.path.join(DATA, "index_etf_map.json")
    if not os.path.exists(p):
        return "fail", "index_etf_map.json 不存在 (etf_index_map.json 丢了)"
    return "ok", "index_etf_map.json 存在"

# --- C3-C7: overview.json ---
def check_overview():
    d, err = _load(os.path.join(SS_DATA, "overview.json"))
    if err: return "fail", f"overview.json 读取失败: {err}"
    fails = []
    warns = []
    if d.get("date") not in (TODAY, LAST_TRADING_DAY):
        fails.append(f"date={d.get('date')} 非今日/最近交易日({TODAY}/{LAST_TRADING_DAY})")
    ca = str(d.get("collected_at", ""))
    if TODAY not in ca.replace("-", ""):
        fails.append(f"collected_at={ca} 不含今日")
    s = d.get("today", {}).get("scores", {})
    need = ["a_sentiment","cross_market","fear_greed","sentiment_csi1000","sentiment_csi500",
            "sentiment_cyb","sentiment_hs300","sentiment_kc50","sentiment_sz50"]
    miss = [k for k in need if not s.get(k)]
    if miss: fails.append(f"scores 缺 {miss}")
    ih = d.get("industry_heatmap")
    if not isinstance(ih, list) or len(ih) != 31:
        warns.append(f"industry_heatmap len={len(ih) if isinstance(ih,list) else 'N/A'} !=31")
    isp = d.get("indices_sparkline", {})
    if isinstance(isp, dict):
        miss_sp = [k for k in ["sh","sz","hs300","sz50","cyb"] if k not in isp]
        if miss_sp: warns.append(f"indices_sparkline 缺 {miss_sp}")
    level = "fail" if fails else ("warn" if warns else "ok")
    msg = "; ".join(fails + warns) if (fails or warns) else "overview OK"
    return level, msg

# --- C8-C12: intraday_snapshot.json ---
def check_intraday_snapshot():
    d, err = _load(os.path.join(SS_DATA, "intraday_snapshot.json"))
    if err: return "fail", f"intraday_snapshot.json 读取失败: {err}"
    fails = []; warns = []
    ca = str(d.get("collected_at", ""))
    if TODAY not in ca.replace("-", ""):
        fails.append(f"collected_at={ca} 不含今日")
    idx = d.get("indices", [])
    if not isinstance(idx, list) or len(idx) < 17:
        fails.append(f"indices len={len(idx) if isinstance(idx,list) else 'N/A'} <17")
    ind = d.get("industries", [])
    if not isinstance(ind, list) or len(ind) != 31:
        warns.append(f"industries len={len(ind) if isinstance(ind,list) else 'N/A'} !=31")
    af = d.get("amount_forecast")
    is_closed = d.get("is_closed")
    if is_closed is False and af is None:  # 盘中必须有
        fails.append("盘中 amount_forecast 为空")
    if af is not None and af >= 50000:  # 50000亿,A股历史最高约3万亿
        fails.append(f"amount_forecast={af} >=50000亿 (爆炸)")
    level = "fail" if fails else ("warn" if warns else "ok")
    msg = "; ".join(fails + warns) if (fails or warns) else "intraday OK"
    return level, msg

# --- C13-C15: boot.json ---
def check_boot():
    d, err = _load(os.path.join(SS_DATA, "boot.json"))
    if err: return "fail", f"boot.json 读取失败: {err}"
    fails = []; warns = []
    ov = d.get("overview", {})
    if isinstance(ov, dict) and ov.get("date") not in (TODAY, LAST_TRADING_DAY):
        # 盘中 boot 会更新,若仍是昨日=成交额显示昨日值 bug
        fails.append(f"boot.overview.date={ov.get('date')} 非今日/最近交易日({TODAY}/{LAST_TRADING_DAY}) (成交额昨日值)")
    meta = d.get("_meta", {})
    missing = meta.get("missing", [])
    if missing:
        fails.append(f"boot._meta.missing={missing} (首屏包缺文件)")
    files = meta.get("files", [])
    if len(files) != 11:
        warns.append(f"boot._meta.files len={len(files)} !=11")
    level = "fail" if fails else ("warn" if warns else "ok")
    msg = "; ".join(fails + warns) if (fails or warns) else "boot OK"
    return level, msg

# --- C16-C18: alert.json ---
def check_alert():
    d, err = _load(os.path.join(SS_DATA, "alert.json"))
    if err: return "fail", f"alert.json 读取失败: {err}"
    fails = []; warns = []
    # 盘后更新,盘中可能昨日(正常)
    if not _date_ok(d.get("date"), allow_yesterday=True):
        fails.append(f"date={d.get('date')} 非今日/昨日")
    h = d.get("high", {})
    if h.get("score") is None:
        fails.append("high.score 为 null")
    if len(d.get("history", [])) < 1:
        warns.append("history 为空")
    level = "fail" if fails else ("warn" if warns else "ok")
    msg = "; ".join(fails + warns) if (fails or warns) else "alert OK"
    return level, msg

# --- C19-C20: notifications.json ---
def check_notifications():
    d, err = _load(os.path.join(SS_DATA, "notifications.json"))
    if err: return "fail", f"notifications.json 读取失败: {err}"
    fails = []; warns = []
    if d.get("date") != TODAY:
        fails.append(f"date={d.get('date')} != 今日{TODAY}")
    if not isinstance(d.get("signals"), list):
        warns.append("signals 非数组")
    level = "fail" if fails else ("warn" if warns else "ok")
    msg = "; ".join(fails + warns) if (fails or warns) else "notifications OK"
    return level, msg

# --- C21-C22: schedule_stats.json ---
def check_schedule_stats():
    d, err = _load(os.path.join(SS_DATA, "schedule_stats.json"))
    if err: return "fail", f"schedule_stats.json 读取失败: {err}"
    fails = []; warns = []
    if not isinstance(d, list) or len(d) != 9:
        warns.append(f"len={len(d) if isinstance(d,list) else 'N/A'} !=9")
    if isinstance(d, list):
        bad = [x.get("task") for x in d if x.get("last_exit") in (143, 133, 1)]
        if bad: fails.append(f"任务异常退出 last_exit in(143,133,1): {bad}")
    level = "fail" if fails else ("warn" if warns else "ok")
    msg = "; ".join(fails + warns) if (fails or warns) else "schedule_stats OK"
    return level, msg

# --- C23-C24: fund_score_top.json ---
def check_fund_score_top():
    d, err = _load(os.path.join(SS_DATA, "fund_score_top.json"))
    if err: return "fail", f"fund_score_top.json 读取失败: {err}"
    warns = []
    if not _date_ok(d.get("date"), allow_yesterday=True):
        warns.append(f"date={d.get('date')} 非今日/昨日(日频)")
    if d.get("count") != 100 or len(d.get("data", [])) != 100:
        warns.append(f"count={d.get('count')} data_len={len(d.get('data',[]))} !=100")
    return "warn" if warns else "ok", "; ".join(warns) if warns else "fund_score_top OK"

# --- C25: trade_sim_indices.json ---
def check_trade_sim_indices():
    d, err = _load(os.path.join(SS_DATA, "trade_sim_indices.json"))
    if err: return "fail", f"trade_sim_indices.json 读取失败: {err}"
    if not isinstance(d, list) or len(d) < 100:
        return "warn", f"len={len(d) if isinstance(d,list) else 'N/A'} <100"
    return "ok", f"trade_sim_indices len={len(d)}"

CHECKS = [
    ("C1", check_board_etf_map),
    ("C2", check_index_etf_map_exists),
    ("C3-C7", check_overview),
    ("C8-C12", check_intraday_snapshot),
    ("C13-C15", check_boot),
    ("C16-C18", check_alert),
    ("C19-C20", check_notifications),
    ("C21-C22", check_schedule_stats),
    ("C23-C24", check_fund_score_top),
    ("C25", check_trade_sim_indices),
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy-mode", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    fails = []; warns = []
    for cid, fn in CHECKS:
        try:
            level, msg = fn()
        except Exception as e:
            level, msg = "fail", f"{cid} 异常: {e}"
        icon = "OK" if level == "ok" else ("WARN" if level == "warn" else "FAIL")
        print(f"[{icon}] {cid}: {msg}")
        if level == "fail": fails.append(cid)
        elif level == "warn": warns.append(cid)
    print(f"\n汇总: {len(fails)} FAIL, {len(warns)} WARN")
    if fails:
        print("阻断 deploy: " + ", ".join(fails))
        sys.exit(1)
    if warns and (args.strict or args.deploy_mode):
        print("warn 在 --strict/--deploy-mode 下也阻断: " + ", ".join(warns))
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
```

### deploy.sh 接入（L122-123,已实现）

```bash
# scripts/deploy.sh L105 附近(export.py 完成后),插入:
echo "[deploy] 数据产物完整性校验..."
if ! python3 scripts/check_data_integrity.py --deploy-mode; then
  echo "[deploy] 数据校验失败,阻断 deploy。修复后重试。"
  exit 1
fi
```

### 阈值依据

| 阈值 | 依据 |
|------|------|
| board_etf_map 空占比 30% | 历史正常<10%,事故时27/73=37%明显异常,30%为安全线 |
| amount_forecast <50000 亿 | A股历史最高成交约3万亿(30000亿),9.52万亿超3倍,50000留余量 |
| indices len>=17 | 快照含17核心指数(sh/sz/hs300/sz50/cyb/kc50/csi1000/csi500 等) |
| industries len==31 | 申万一级行业31个 |
| schedule last_exit 非143/133/1 | 143=SIGTERM/133=内存超限/1=通用错误,均为异常退出 |
| fund_score count==100 | top100 基金评分 |

---

## Part 3: P0 核心功能 Smoke 清单（拦截"上线后才发现"）

> 对应 CLAUDE.md §15 ③。每项给 curl 数据层验证 + 关键交互文字描述 + 关联文件。reviewer agent 上线前必跑。

### P0-01 首页 KPI 角标（19 卡）
- **数据层 curl**: `curl -s https://ss.fx8.store/data/overview.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('date:',d['date']);s=d['today']['scores'];print('scores:',{k:s.get(k) is not None for k in ['a_sentiment','cross_market','fear_greed','sentiment_csi1000','sentiment_csi500','sentiment_cyb','sentiment_hs300','sentiment_kc50','sentiment_sz50']})"`
- **期望**: date==今日;9 scores 全 True
- **文字验证**: 首页19张KPI卡(涨停数/跌停数/成交额/换手率/量比/恐贪指数/情绪分/跨市场等),角标显示今日日期非昨日,数值非null
- **关联**: `app.js renderOverview L8460+` / `overview.json` / `boot.json`(首屏包含overview)
- **历史事故**: KPI角标停8-5(炸板池竞价空窗误判)

### P0-02 KPI 卡 hover 6m 分位 tooltip
- **数据层 curl**: `curl -s https://ss.fx8.store/data/overview.json | python3 -c "import sys,json;d=json.load(sys.stdin);print({k:len(d.get(k,[])) for k in ['a_sentiment_6m','cross_market_6m','fear_greed_6m','a_amount_6m','a_volume_ratio_6m']})"`
- **期望**: 各 _6m 数组 len>0
- **文字验证**: hover KPI卡显示tooltip(当前值+6m分位偏热/偏冷/中性+6m最高/最低/均值)
- **关联**: `app.js L8486+ _KPI_6M_TOOLTIP_IDS` / `overview.json {id}_6m`

### P0-03 恐贪指数卡
- **数据层 curl**: `curl -s https://ss.fx8.store/data/overview.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('fear_greed:',d['today']['scores'].get('fear_greed'))"`
- **期望**: fear_greed 非 null,0-100
- **文字验证**: 恐贪指数卡显示数值+配色(红=贪婪/绿=恐惧),hover显示进度条tooltip
- **关联**: `app.js L8462 fearGreedColor/fearGreedLabel` / `overview.json today.scores.fear_greed`

### P0-04 情绪分卡分项构成（hover 条形图）
- **数据层 curl**: `curl -s https://ss.fx8.store/data/overview.json | python3 -c "import sys,json;d=json.load(sys.stdin);s=d['today']['scores'].get('a_sentiment',{});print('a_sentiment:',s);print('components:',s.get('components') if isinstance(s,dict) else None)"`
- **期望**: a_sentiment 含 components(6维子分值)
- **文字验证**: hover情绪分卡显示分项构成条形图(ratio/zt/zhaban/lianban/amount/north 6维)
- **关联**: `app.js L8516+ 分项构成条形图` / `overview.json today.scores.a_sentiment.components`

### P0-05 分时图
- **数据层 curl**: `curl -s https://ss.fx8.store/data/intraday_snapshot.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('collected_at:',d['collected_at']);print('indices:',len(d.get('indices',[])));print('is_closed:',d.get('is_closed'))"`
- **期望**: collected_at 含今日;indices len>=17;is_closed 字段存在
- **文字验证**: 指数分时图有当日时间点数据点(非空),hover显示时间+数值
- **关联**: `app.js L4718 fetchJSON intraday_snapshot` / `intraday_snapshot.json`

### P0-06 盘中状态横幅
- **数据层 curl**: 同 P0-05
- **期望**: is_closed==false(盘中)显示"盘中实时",==true(盘后)显示"已收盘"
- **文字验证**: 页面顶部横幅显示盘中/午休/收盘状态
- **关联**: `app.js updateMarketStatusBanner` / `intraday_snapshot.json is_closed`

### P0-07 KPI 时间角标三色（绿/黄/红）
- **数据层 curl**: `curl -s https://ss.fx8.store/data/intraday_snapshot.json | python3 -c "import sys,json;d=json.load(sys.stdin);sh=[i for i in d.get('indices',[]) if i.get('code')=='sh000001'];print('sh000001:',sh)"`
- **期望**: indices 含 sh000001(上证,基准源)
- **文字验证**: KPI卡角标绿色=最新/黄色=滞后/红色=异常,非全红
- **关联**: `app.js getCardTimeBadge L4740+` / `intraday_snapshot.json indices`

### P0-08 指数表现 ETF（全部无ETF拦截）
- **数据层 curl**: `for id in sh hs300 cyb sz50 csi1000; do curl -s "https://ssd.fx8.store/index/${id}-all.json" | python3 -c "import sys,json;d=json.load(sys.stdin);e=d.get('etfs',[]);print('$id etfs:',len(e) if isinstance(e,list) else e,'FAIL' if not e else 'OK')"; done`
- **期望**: 各指数 etfs 字段非空(len>0)
- **文字验证**: 指数表现区每个指数卡显示相关ETF列表(非"全部无ETF")
- **关联**: `app.js renderIndicesSection L10602+` / `index/{id}-all.json etfs` / `data/board_etf_map.json`(根因)
- **历史事故**: 全部无ETF(board_etf_map 27/73空数组,etf_index_map.json)

### P0-09 指数 K 线 + 信号 pin
- **数据层 curl**: `curl -s https://ssd.fx8.store/index/sh-all.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('ohlc:',len(d.get('ohlc',[])),'signals:',len(d.get('signals',[])))"`
- **期望**: ohlc 非空;signals 数组存在
- **文字验证**: 指数K线图有蜡烛数据,信号pin标记在K线上(买/卖点)
- **关联**: `app.js renderIndicesSection L10602` / `index/{id}-all.json ohlc/signals`

### P0-10 信号网格（4维筛选）
- **数据层 curl**: `curl -s https://ss.fx8.store/data/alert.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('date:',d['date'],'high:',d.get('high',{}).get('score'),'history:',len(d.get('history',[])))"`
- **期望**: date 今日/昨日;high.score 非 null;history len>=1
- **文字验证**: 信号网格显示当日信号(评级/置信度/维度),4维筛选可切换
- **关联**: `app.js _renderSignalGrid` / `alert.json`

### P0-11 信号走势弹窗
- **数据层 curl**: `curl -s https://ss.fx8.store/data/alert_analyze_sh.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('keys:',list(d.keys())[:8]);print('high:',d.get('high'),'low:',d.get('low'))"`
- **期望**: 含 high/low 字段
- **文字验证**: 点击信号弹窗显示走势图+评级历史
- **关联**: `app.js L3401/L3442 fetchJSON alert_analyze_{iid}` / `alert_analyze_*.json`

### P0-12 通知面板
- **数据层 curl**: `curl -s https://ss.fx8.store/data/notifications.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('date:',d['date'],'signals:',len(d.get('signals',[])),'anomalies:',len(d.get('anomalies',[])))"`
- **期望**: date==今日;signals 是数组
- **文字验证**: 通知面板显示当日信号/异常/预警
- **关联**: `app.js L7149 fetchJSON notifications` / `notifications.json`

### P0-13 预估成交额（爆炸拦截）
- **数据层 curl**: `curl -s https://ss.fx8.store/data/intraday_snapshot.json | python3 -c "import sys,json;d=json.load(sys.stdin);af=d.get('amount_forecast');print('amount_forecast:',af,'FAIL' if af is None or af>=50000 else 'OK')"`
- **期望**: amount_forecast 非空且 <50000(亿)
- **文字验证**: 盘中KPI成交额卡显示预估角标(合理值,A股日常1-2.5万亿),非9.52万亿/15万亿
- **关联**: `app.js amount_forecast 角标` / `intraday_snapshot.json amount_forecast`
- **历史事故**: 预估9.52万亿/15万亿爆炸

### P0-14 成交额非昨日值（boot 时效拦截）
- **数据层 curl**: `curl -s https://ss.fx8.store/data/boot.json | python3 -c "import sys,json;d=json.load(sys.stdin);ov=d.get('overview',{});print('boot.overview.date:',ov.get('date'),'missing:',d.get('_meta',{}).get('missing'),'FAIL' if ov.get('date')!=$(date +%Y%m%d) or d.get('_meta',{}).get('missing') else 'OK')"`
- **期望**: boot.overview.date==今日;_meta.missing==[]
- **文字验证**: 首屏成交额显示今日值(非昨日),首屏包11文件齐全无缺失
- **关联**: `app.js L3187 fetchJSON boot` / `boot.json`
- **历史事故**: 成交额显示昨日值(boot.json盘中不更新)

### P0-15 涨跌家数 ad_line
- **数据层 curl**: `curl -s https://ss.fx8.store/data/ad_line.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('data len:',len(d.get('data',[])))"`
- **期望**: data list 非空
- **文字验证**: 涨跌家数图有数据
- **关联**: `app.js L9174 fetchJSON ad_line` / `ad_line.json`

### P0-16 市场温度 / 冰点过热热力图
- **数据层 curl**: `curl -s https://ss.fx8.store/data/overview.json | python3 -c "import sys,json;d=json.load(sys.stdin);s=d['today']['scores'];print('scores:',{k:s.get(k) is not None for k in ['a_sentiment','cross_market','fear_greed']})"`
- **期望**: 3 核心情绪分非 null
- **文字验证**: 市场温度计/冰点过热热力图显示各指数情绪分(非空)
- **关联**: `app.js renderSentiment/市场温度` / `overview.json today.scores`

### P0-17 策略实验室入口
- **数据层 curl**: `curl -s https://ss.fx8.store/data/trade_sim_indices.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('len:',len(d),'FAIL' if len(d)<100 else 'OK')"`
- **期望**: list len>=100
- **文字验证**: 策略实验室tab可进入,显示指数列表+备买chip三档(年化最高/最稳健/回撤最小)
- **关联**: `app.js L33 fetchJSON trade_sim_indices` / `lab.js` / `trade_sim_indices.json`

### P0-18 基金评分
- **数据层 curl**: `curl -s https://ss.fx8.store/data/fund_score_top.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('date:',d['date'],'count:',d.get('count'),'data_len:',len(d.get('data',[])))"`
- **期望**: count==100;data len==100
- **文字验证**: 基金评分列表显示top100基金
- **关联**: `app.js L16549 fetchJSON fund_score_top(R2)` / `fund_score_top.json`

### P0-19 定时任务监控
- **数据层 curl**: `curl -s https://ss.fx8.store/data/schedule_stats.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('len:',len(d),'tasks:',[x['task'] for x in d],'bad:',[x['task'] for x in d if x.get('last_exit') in (143,133,1)])"`
- **期望**: len==9;无 bad(异常退出)
- **文字验证**: 定时任务监控弹窗显示9任务状态(非异常退出)
- **关联**: `app.js L19154 fetchJSON schedule_stats` / `schedule_stats.json`

### P0-20 boot 首屏包完整性
- **数据层 curl**: `curl -s https://ss.fx8.store/data/boot.json | python3 -c "import sys,json;d=json.load(sys.stdin);m=d.get('_meta',{});print('files:',len(m.get('files',[])),'missing:',m.get('missing'))"`
- **期望**: files==11;missing==[]
- **文字验证**: 首屏快速加载(boot包11文件齐全),不 fallback 多次 fetch
- **关联**: `app.js L3187 fetchJSON boot` / `boot.json _meta`

---

## Part 4: P1 重要功能 Smoke 清单

### P1-01 策略实验室备买 chip 三档
- **curl**: `curl -s https://ssd.fx8.store/trade_sim_data/trade_sim_sh000001_stats.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('keys:',list(d.keys())[:10])"`
- **验证**: 备买chip显示年化最高/最稳健/回撤最小三档
- **关联**: `lab.js` / `trade_sim_data/trade_sim_{id}_stats.json`(R2)

### P1-02 ETF 评分列表
- **curl**: `for t in buy sell hold; do curl -s "https://ssd.fx8.store/data/etf_score_list_${t}.json" | python3 -c "import sys,json;d=json.load(sys.stdin);print('$t:',len(d) if isinstance(d,list) else 'dict')"; done`
- **验证**: ETF评分列表显示买/卖/持有建议
- **关联**: `app.js L15559/L16088/L16089` / R2 `etf_score_list_{buy,sell,hold}.json`

### P1-03 行业热力图
- **curl**: `curl -s https://ss.fx8.store/data/overview.json | python3 -c "import sys,json;d=json.load(sys.stdin);ih=d.get('industry_heatmap',[]);print('len:',len(ih),'FAIL' if len(ih)!=31 else 'OK')"`
- **验证**: 行业热力图31个行业全覆盖
- **关联**: `app.js` / `overview.json industry_heatmap`

### P1-04 期货/持仓
- **curl**: `curl -s https://ss.fx8.store/data/futures.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('keys:',list(d.keys())[:8])"`
- **验证**: 期货数据(螺纹/黄金/国债)+持仓趋势
- **关联**: `app.js L9388` / `futures.json` / `futures_acc_trend.json`

### P1-05 国家队 ETF
- **curl**: `curl -s https://ssd.fx8.store/data/etf_national_team-1m.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('keys:',list(d.keys())[:8])"`
- **验证**: 国家队ETF净流入数据
- **关联**: `app.js L9420` / `etf_national_team-{range}.json`

### P1-06 公募基金
- **curl**: `curl -s https://ssd.fx8.store/public_fund/public_fund_summary.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('keys:',list(d.keys())[:8])"`
- **验证**: 公募基金模块数据
- **关联**: `app.js L11112+` / R2 `public_fund_*.json`

### P1-07 量比/新高新低/均线排列
- **curl**: `for f in volume_ratio new_high_low ma_alignment position; do curl -s "https://ss.fx8.store/data/${f}.json" | python3 -c "import sys,json;d=json.load(sys.stdin);print('$f:',type(d).__name__)"; done`
- **验证**: 量比/新高新低/均线排列/仓位数据
- **关联**: `app.js L9100/L9134/L9174/L9176`

---

## Part 5: 改动影响面 grep 清单（reviewer agent push 前必跑）

> 对应 CLAUDE.md §15 ②。改了 X 文件 → grep 谁引用 X → 列出受影响老功能点 → 跑相关 P0/P1 smoke。

### grep 模板

```bash
# 改了 board_etf_map / index_etf_map 相关
grep -n "board_etf_map\|index_etf_map\|etfs" app.js lab.js
# 受影响: P0-08指数表现ETF / P0-09指数K线信号 / 信号网格相关ETF展示

# 改了 overview.json 结构(加/删字段)
grep -n "overview\.json\|today\.scores\|today\.metrics\|\.scores\[\|_6m" app.js lab.js
# 受影响: P0-01 KPI角标 / P0-02 6m分位 / P0-03恐贪 / P0-04分项构成 / P0-16市场温度

# 改了 intraday_snapshot 结构
grep -n "intraday_snapshot\|amount_forecast\|is_closed\|\.indices\b" app.js lab.js
# 受影响: P0-05分时图 / P0-06横幅 / P0-07角标 / P0-13预估成交额

# 改了 boot.json 结构
grep -n "boot\.json\|_bootData\|_meta\b" app.js lab.js
# 受影响: P0-14成交额非昨日 / P0-20首屏包 / 所有首屏加载功能

# 改了 alert.json 结构
grep -n "alert\.json\|\.high\b\|\.low\b\|\.history\b\|signals_today" app.js lab.js
# 受影响: P0-10信号网格 / P0-11信号走势弹窗

# 改了 export.py / 生成脚本
grep -n "fetchJSON.*\.json" app.js lab.js | grep -v "//"
# 受影响: 所有读 JSON 的功能(全量回归)

# 改了 fetchJSON / dataUrl / R2 URL 逻辑
grep -n "fetchJSON\|dataUrl\|ssd\.fx8\.store" app.js lab.js | head -30
# 受影响: 所有数据加载(全量回归)

# 改了 alert_analyze 生成
grep -n "alert_analyze" app.js lab.js
# 受影响: P0-11信号走势弹窗

# 改了 notifications 生成
grep -n "notifications\.json" app.js lab.js
# 受影响: P0-12通知面板

# 改了 fund_score / etf_score_list 生成
grep -n "fund_score\|etf_score_list" app.js lab.js
# 受影响: P0-18基金评分 / P1-02 ETF评分列表

# 改了 trade_sim 生成
grep -n "trade_sim\|trade_sim_data" app.js lab.js
# 受影响: P0-17策略实验室 / P1-01备买chip

# 改了 schedule_stats 生成
grep -n "schedule_stats" app.js lab.js
# 受影响: P0-19定时任务监控
```

### 影响面判断流程
1. `git diff --name-only main..HEAD` 列改动文件
2. 按上表 grep 改动文件名/关键字 → 命中哪些老功能
3. 跑命中的 P0/P1 smoke 项(curl 验证)
4. 任一失败 = 阻断 push,修复后重验

---

## Part 6: reviewer agent 执行指引

### 何时派
- 大改动 push 前(改了数据产物生成脚本 / 改了 app.js 多个函数 / 改了 JSON 结构)
- 大阶段结束(当天开发功能多后)
- 上线前最终确认

### 怎么派（主控 prompt 模板）
```
你是 task-reviewer 子 agent。任务:主功能回归 smoke 检查,不看新功能,专看"改动可能影响哪些老功能"。

步骤:
1. 读 docs/smoke-checklist.md
2. git diff --name-only main..HEAD 列改动文件
3. 按 Part 5 grep 模板,grep 改动文件 → 列受影响老功能点
4. 跑 Part 3 P0 全部 20 项 curl 验证(逐项 curl + python 解析 + 期望值比对)
5. 跑 Part 1 数据产物校验(python3 scripts/check_data_integrity.py,若已实施;否则按 Part 1 命令模板逐项 curl)
6. 跑命中的 P1 项(Part 4)
7. 输出回归报告:通过/失败项 + 失败根因 + 修复建议
8. 任一 P0 fail = 阻断 push,SendMessage to main 报告

约束:glm-5.2 只文本禁图片,验证用 curl JSON 数据层 + 关键交互文字描述,不看 UI 截图。
进度文件 /tmp/agent-progress-reviewer-<时间>.md。
```

### 输出格式（回归报告）
```
## 回归报告 <日期>
### 改动文件
<git diff --name-only>

### 影响面 grep 结果
- 改了 X → 影响 P0-XX / P1-XX

### P0 验证结果
- P0-01 KPI角标: OK (date=20260806, 9 scores 全 True)
- P0-08 指数表现ETF: FAIL (sh etfs=0, 全部无ETF)
- ...

### 数据产物校验
- C1 board_etf_map: FAIL (37% 空数组)
- ...

### 结论
- X 项 P0 fail,阻断 push
- 失败根因: <...>
- 修复建议: <...>
```

### 失败处理
- P0 fail = 阻断 push,修复后重派 reviewer 复验
- P1 fail = 警告,主控判断是否阻断(严重则阻断)
- 数据校验 fail = 阻断 deploy(check_data_integrity.py 自动拦截)

---

## 附录:线上 URL + 验证模板

### 3 域名（任一验证到新版即算上线）
- `https://ss.fx8.store/` (CF Workers 主站,server: cloudflare)
- `https://sss.sugas.site/` (GitHub Pages)
- `https://s.sugas.site/` (MaoziYun,300MB 限制)

### 数据 URL
- CF 小文件: `https://ss.fx8.store/data/{file}.json`
- R2 大文件/历史: `https://ssd.fx8.store/{prefix}/{file}.json`
  - index: `https://ssd.fx8.store/index/{id}-all.json`
  - trade_sim: `https://ssd.fx8.store/trade_sim_data/trade_sim_{id}_stats.json`
  - public_fund: `https://ssd.fx8.store/public_fund/{file}.json`
  - industry: `https://ssd.fx8.store/industry/industry-{range}.json`
  - data(大range): `https://ssd.fx8.store/data/{file}.json`

### 快速全量 P0 验证（一键脚本，reviewer 可直接跑）
```bash
TODAY=$(date +%Y%m%d)
DOW=$(date +%u); if [ "$DOW" = "6" ]; then LAST_TRADING_DAY=$(date -v-1d +%Y%m%d); elif [ "$DOW" = "7" ]; then LAST_TRADING_DAY=$(date -v-2d +%Y%m%d); else LAST_TRADING_DAY=$TODAY; fi
echo "=== P0 回归 $(date) ==="
# C1 board_etf_map
python3 -c "import json;d=json.load(open('data/board_etf_map.json'));k=list(d.keys());e=[x for x in k if not d[x]];print(f'C1 board_etf_map {len(e)}/{len(k)}={len(e)/len(k)*100:.0f}%', 'FAIL' if len(e)/len(k)*100>=30 else 'OK')"
# C3 overview date
python3 -c "import json;d=json.load(open('static-site/data/overview.json'));print('C3 overview.date',d['date'],'FAIL' if d['date'] not in ('$TODAY','$LAST_TRADING_DAY') else 'OK')"
# C8 intraday
python3 -c "import json;d=json.load(open('static-site/data/intraday_snapshot.json'));print('C8 intraday collected_at',d['collected_at'],'FAIL' if '$TODAY' not in d['collected_at'].replace('-','') else 'OK');print('C9 indices',len(d.get('indices',[])),'FAIL' if len(d.get('indices',[]))<17 else 'OK');af=d.get('amount_forecast');print('C12 amount_forecast',af,'FAIL' if af is None or af>=50000 else 'OK')"
# C13 boot
python3 -c "import json;d=json.load(open('static-site/data/boot.json'));ov=d.get('overview',{});print('C13 boot.overview.date',ov.get('date'),'FAIL' if ov.get('date') not in ('$TODAY','$LAST_TRADING_DAY') else 'OK');m=d.get('_meta',{}).get('missing',[]);print('C14 boot.missing',m,'FAIL' if m else 'OK')"
# C16 alert
python3 -c "import json;d=json.load(open('static-site/data/alert.json'));print('C16 alert.date',d['date'],'high.score',d.get('high',{}).get('score'))"
# C19 notifications
python3 -c "import json;d=json.load(open('static-site/data/notifications.json'));print('C19 notifications.date',d['date'],'FAIL' if d['date']!='$TODAY' else 'OK')"
# C26 index etfs (R2 抽查)
for id in sh hs300 cyb; do curl -s "https://ssd.fx8.store/index/${id}-all.json" | python3 -c "import sys,json;d=json.load(sys.stdin);e=d.get('etfs',[]);print('C26 $id etfs',len(e) if isinstance(e,list) else e,'FAIL' if not e else 'OK')" 2>/dev/null; done
```

### 验证三层（模型只文本不能看 UI）
1. **curl JSON 数据层**: 字段值/非空/日期==今日(本清单主体)
2. **关键交互文字描述**: 功能点该显示什么(文字,非截图)
3. **让用户确认显示**: 数据层+文字都过,让用户看页面确认显示正确
