# review FAIL 修复:腾讯补名部分缺失静默截断 → fail-closed(2026-09-24)

> 针对 `docs/ops/board-etf-map-sina-fallback-20260924-review.md` 第 2 项 FAIL + 3 跟进项的修复记录。
> review base=origin/main@125faef75,feat=worktree-agent-a299c2abc473eee4c。本报告由修复后独立自测支撑,不采信 review 转述。

## 结论速览

| 项 | 结论 | 修复 |
|---|---|---|
| 必改:腾讯部分缺失静默截断名 | **已修** | 代码集合 fail-closed + 缺失批次重试一次 + 错误信息含缺失代码 |
| 跟进①:deploy.sh 告警文案 | 已修 | "三源全挂"文案 |
| 跟进②:_meta.source 兜底日标注 | 已修 | 先查无消费方 → 加标注 |
| 跟进③:r.text 显式 GBK 解码 | 已修 | `r.content.decode("gbk", errors="replace")` |

## 必改项修复详情

### 根因
`_sina_etf_spot_df` 的腾讯补名 `.fillna(df["名称"])` 对腾讯没返回的代码**静默回落新浪简称**,`(df["名称"]=="")` 守卫永假(Q: 新浪 name 永非空串)。腾讯部分缺失(如某批被 WAF 风控挑掉)时,截断名("创业板EF"/"创业板")流入匹配链 → gen 的 cyb 规则 include=["创业板ETF","创业板增强"] 不命中 → 标 no_track;build 的 14 宽基校验只查板块非空,兜不住。"名字全错但板块非空" = 2026-08-06 空数组事故的变种新通道(§23.11)。

### 修法(四步)
1. `_tencent_fetch_names` 改为返回 `(names, missing)`:逐批记录"请求了但腾讯没返回"的代码(`batch_got` 集合差),**不静默**。空串名(`fields[1].strip()` 为空)同样记缺失,不记录空名。
2. 按**代码集合**比对(非仅 len):`missing = codes - batch_got`,长度相等但代码错位同样被拦(因为错位代码不在 batch_got)。
3. 缺失时**重试一次缺失批次**(`_tencent_fetch_names(missing)`),瞬时抖动能救不整轮 fail;重试后仍缺 → `RuntimeError`,错误信息含缺失代码清单。
4. 删除永假守卫 `if (df["名称"]=="").any()`。

### 同类错误面审计(§23.2③,全模块静默降级点清单)

| # | 静默降级点 | 修复前行为 | 判定/修复 |
|---|---|---|---|
| 1 | 腾讯补名部分缺失 `.fillna(新浪简称)` | **静默截断名** | **fail-closed**(本次必改项) |
| 2 | 新浪翻页部分页失败 | `_sina_fetch_node` 空页 `break` → 静默只返回前 N 页 | 空页重试一次(attempt=2);仍空 break;**节点条数下限** fail-closed(etf≥1500/lof≥300,实测 1685/360 留 10% 余量) |
| 3 | 新浪返回条数与预期(2045)不符 | 无校验,多少收多少 | 同上,节点条数下限 fail-closed |
| 4 | 腾讯批量分片某一片挂掉(HTTP 错误) | `raise_for_status()` 抛错 → 整轮 fail | **可接受**:整轮 fail 如实报错,非静默 |
| 5 | 腾讯批量分片返回空(HTTP 200 但无 v_ 行) | 该片代码静默缺失 → 走 `.fillna` | 缺失集合 fail-closed(本次修复) |
| 6 | 腾讯返回名称空串 | `fields[1]` 空串被记入 names → map 后空名 | 空串计缺失,重试后仍缺 fail-closed |
| 7 | 成交额解析失败回落 0 | `pd.to_numeric(errors="coerce").fillna(0)` 静默 | 解析失败代码清单,≤50 只打 `⚠ [etf-fallback]` 日志回落 0(可接受,成交额仅用于排序非匹配);>50 只 fail-closed(源结构异常) |
| 8 | 新浪两节点全空 | `if not all_rows: raise` | **可接受**:本就 fail-closed |
| 9 | 新浪某节点空但另一节点正常 | 无校验,静默少半个宇宙 | 节点条数下限兜住(见 #3) |
| 10 | 主源成功路径 | try 分支直接 return,兜底零触发 | **可接受**:主源成功不用兜底(本就不静默) |

### 跟进项

- **① deploy.sh L1069 告警文案**:原"akshare 反爬兜底也失败"→ 改为"东财+新浪+腾讯行情源均失败",方向不再误导排障。
- **② `_meta.source` 兜底日标注**:先查消费方:前端 app.js/lab.js/common.js **无 `_meta` 消费**(lab.js 命中均为 fusion_meta/pair_meta 无关),`check_data_integrity.py check_board_etf_map` 仅按 `k.startswith("_")` 排除 `_meta` 作指数键、不校验其内格式;build/gen 内 `if iid=="_meta": continue` 全跳过。结论=**纯信息字段,无消费方 → 加标注**:`_etf_spot_fallback` 加 `was_fallback_used()` 模块标志,主源成功置 False、兜底成功置 True;build_board_etf_map `_meta.source` 按标志拼接"新浪+腾讯兜底(东财主源失败) + fundf10 track_index"。后端调试元数据,前端不展示,无格式破坏。
- **③ `r.text` → `r.content.decode("gbk", errors="replace")`**:腾讯 charset 头在位时两者等价;头缺失/被剥离时 `r.text` 按 ASCII 猜解乱码,显式解码更防御(与 signal_kelly_backtest `_fetch_intraday_open_via_http` 同口径)。

## 自测(独立复现 + 逐项证据)

### 自测①:修复前能复现(先 8-24 FAIL,后修复被拦)
```bash
# 修复前(reviewer 复现段):腾讯删 159948/159915 → 静默截断名
python -c "
import sys; sys.path.insert(0,'scripts')
import _etf_spot_fallback as m
orig = m._tencent_fetch_names
def partial(codes):
    d = orig(codes)
    for drop in ('159948','159915'): d.pop(drop, None)
    return d
m._tencent_fetch_names = partial
df = m._sina_etf_spot_df()
print(df[df['代码'].isin(['159948','159915'])]['名称'].tolist())"
# 修复前输出: ['创业板', '创业板EF']  ← 无异常返回,静默截断名(FAIL 复现成功)
```

### 自测②:修复后同一复现被拦(抛错 + 错误信息含缺失代码)
```bash
python /tmp/test_etf_fallback_fixed.py
# 输出: [etf-fallback] 腾讯补全称缺失 2 只(159915,159948)，重试一次缺失批次 ...
# PASS: 被拦截 RuntimeError = 腾讯补全称缺失 2 只代码(重试后仍缺)，fail-closed 拒用，缺失代码: 159915,159948
```

### 自测③:正常路径零回归(兜底 0 缺失出全量)
```bash
python /tmp/test_etf_fallback_normal.py  # 自测①里直接调 _sina_etf_spot_df()
# 输出: ①兜底正常路径: 2045 只, 列=['代码','名称','成交额','最新价']
#       159915 名=创业板ETF易方达 / 159948 名=创业板ETF南方 ← 全称补齐正常
```

### 自测④:主源成功路径零回归(monkeypatch 东财成功 → 兜底不触发)
```bash
python /tmp/test_etf_fallback_normal.py
# 输出: 主源成功路径: 兜底零触发, 原样返回东财 df ✓ / was_fallback_used=False ✓
```

### 自测⑤:两源全挂仍抛 RuntimeError
```bash
# test_etf_fallback_normal.py 内 ✓: ETF 实时行情两源均失败：东财(...)；新浪+腾讯兜底(...)
```

### 自测⑥:兜底路径 gen 全链路(独立复跑,对应 review 第 5/复现段 3)
```bash
python /tmp/test_etf_gen_fallback.py   # OUT 指向 /tmp,不写生产
# 2045 只: ok=200 / no_track=1845; 14 指数分布与修复前逐位一致; cyb=16 只
# 159948 ok(创业板ETF南方) / 159915 ok(创业板ETF易方达), track_index_name=创业板指数
# 13 指数(除 sz_div 主动留空)全命中: sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50/csi_div/div_lowvol/hsi/hstech/hscei
```

### 自测⑦:编码探测(跟进项③依据)
```bash
python /tmp/probe_encodings.py
# 新浪 Content-Type: application/json; charset=gbk(JSON 内中文 \u 转义,与编码无关)
# 腾讯 Content-Type: text/html; charset=GBK, 内容 GBK 明文 → 显式 decode("gbk") 正确
```

## 复现段
- 必改项最小复现:见自测①②;完整复现脚本 `/tmp/test_etf_fallback_fixed.py`
- gen 全链路复跑:见自测⑥;脚本 `/tmp/test_etf_gen_fallback.py`
- 全部测试脚本留存 /tmp(不写生产;gen OUT 重定向 /tmp 不碰 data/etf_index_map.json)

## 涉及文件
- `scripts/_etf_spot_fallback.py`(核心修复:nullable names/missing/重试/条数下限/成交额守卫/was_fallback_used)
- `scripts/build_board_etf_map.py`(_meta.source 动态标注)
- `scripts/deploy.sh`(告警文案三源全挂)
- `docs/ops/board-etf-map-sina-fallback-20260924-fix.md`(本报告)