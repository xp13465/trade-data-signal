# 冰点认可度 sh_* 旁路字段上线收口:线上 overview.json 数据落地验证(2026-10-02)

## 一、结论摘要
- 线上 `https://ss.fx8.store/data/overview.json` 的 `sentiment_calendar` **24/24 天已带 sh_* 旁路字段**,命中日 `sh_freeze==true`、四因子 `name/key/value/threshold/hit` 四要素齐全、`consensus.x/y` 合理。
- 本机生成版与线上版 **md5 逐位一致**:`d3fb7d7a955d87eebf0cd94f2232c18b`。
- 前端展示层(app.min.js 含 sh_* 逻辑,版本串 `20261002-a629`)已上线;唯一消费 sh_* 字段的展示位 = 情绪日历(sh 格/图例/下钻弹窗/公示)。
- 云上代码已同步至含 sh_* 的 main(HEAD=`ac5f8539d`,queries.py 实测含 sh_freeze),**云上下一次任意 deploy(含今天 17:50 非交易日「仅 deploy 补推」分支)会自动重生成并推送带 sh_* 的 overview.json**(本环节验证链见 §三),本轮为即时生效,云上 17:50 为幂等覆盖不回退。

## 二、问题背景
- 代码已合 main(`ac5f8539d`):`app/queries.py` `overview()` 对 `sentiment_calendar` 每一天注入旁路字段 `sh_freeze` / `sh_factors`(四因子)/ `sh_hits` / `sh_level` / `consensus`。
- 问题:线上 `overview.json` 的 `sentiment_calendar` 曾 **0/24** 天带这些字段 ⇒ 前端虽已上线,用户看不到 sh 格(静默空转)。
- 根因 = 数据产物未重跑/未同步,非代码未合。

## 三、数据链路调研(结论:云上下次 deploy 自动带,含代码证据)

`overview.json` 本机/云上生成链路一致:

1. **update_all.sh 触发 deploy**:云上 systemd timer 17:50 跑 `update_all.sh`;非交易日分支(2026-10-02 国庆假期)执行 `bash "$REPO/scripts/deploy.sh"`(`update_all.sh` L76-79),交易日 O1 分支执行 `bash "$REPO/scripts/deploy.sh" all`(L106-107)。
2. **deploy.sh 段1 跑 export.py**:`EXPORT="$REPO/static-site/export.py"`(`deploy.sh` L34),L283 `"$PY" "$EXPORT" --incremental`。deploy.sh 的参数 `all` 仅标识用,无/有参行为一致(内部只按 `force` 判断时段闸门)。
3. **export.py 必重写 overview.json**:`overview.json` 在必更白名单「main 必更白名单首件」(`static-site/export.py` L756),`--incremental` 也强制全量重算;L1127 `counts["overview.json"] = write_json(DATA_DIR/"overview.json", export_overview(conn, cfg))`。
4. **export_overview → queries.overview()**:注入 sh_* 的逻辑在 `app/queries.py` L1567-1606(旁路字段,纯新增不动老字段)。
5. **R2 上传**:export.py 末尾自动 R2 上传(`EXPORT_SKIP_R2 != 1` 时),清单含 `upload-data-large`(L1422-1426),env 显式 `REPO=str(ROOT)`(ROOT=`__file__` 上两级,在 trade-data 跑即读真实主库目录,无 §3.1 事故);`upload-data-large` 上传 data/ 顶层 `>=1MB` 的 .json(`upload_r2.py` L1490-1518),overview.json 1.3MB ≥1MB ⇒ 覆盖;上传后 `purge_cache` 清 CF 边缘缓存。
6. **云上代码验证(只读)**:`ssh ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal && git log --oneline -1 && grep -c sh_freeze app/queries.py'` → HEAD=`ac5f8539d`,grep=2。云上即含 sh_* 逻辑,17:50 重导出为幂等覆盖。

**结论**:云上下一次任意 deploy 都会自动重新生成并推送带 sh_* 的 overview.json;本轮手动执行 = 立即生效,云上 17:50 = 幂等重跑。

## 四、执行记录(§22 三步)

1. **重跑数据产物**:在 `/Users/linhuichen/code/trade-data`(真实主库 `data/sentiment.db` 所在仓)执行
   `/Users/linhuichen/code/trade/.venv/bin/python static-site/export.py --incremental`
   → 357 JSON 生成,`overview.json` 重算,`boot.json`(合并 11 首屏)同步重算;末尾自动 R2 上传全部 rc=0(含 upload-data-large → overview/boot 覆盖 R2 `data/` 前缀 + purge)。
2. **static-site/data 同步**:生成后 `cp` 到主仓镜像 `/Users/linhuichen/code/trade/static-site/data/{overview,boot}.json`(该目录 gitignored,纯本机数据层对齐,不产生 commit)。
3. **R2/CF 同步**:由 export.py 自动上传段完成(upload-data-large rc=0 + purge);线上 md5 与本地逐位一致 = R2+CF 已生效。

> 说明:本次不跑本机全链 `deploy.sh`(避免触发 git push/rsync 全量同步的额外副作用);数据生成用与 deploy 同款 export.py --incremental,产物与线上部署逻辑逐位同源。线上数据走 R2(static-site/data 全 gitignored,`upload-data-large` → R2 `data/` 前缀),无需 git commit 数据文件。

## 五、验证(硬证据)

| 项 | 结果 |
|---|---|
| 本机 trade-data 版 `sentiment_calendar` 带 sh_* 天数 | **24/24**(trade 主仓镜像 cp 后同 24/24) |
| 线上版带 sh_* 天数 | **24/24**(curl ss.fx8.store/data/overview.json) |
| 命中日 `sh_freeze==true` | 20260911(hard)/ 20260910(main);其余 false 正常(未命中) |
| 四因子四要素 | `[{name,key,value,threshold,hit}×4]` 每命中日均齐全 |
| `consensus` x/y | 样例 20260907: `{x:0,y:2}`、20260911: `{x:2,y:2}`、20260915: `{x:1,y:2}` —— **x 可为 0**(双口径当日均未命中),后端注释写 ∈{1,2} 不准确,非异常 |
| **md5 逐位对账** | 本机 trade-data 版 `d3fb7d7a955d87eebf0cd94f2232c18b` == 线上 `https://ss.fx8.store/data/overview.json` **逐位一致** |
| 前端展示层上线 | curl 线上 app.min.js 含 `sh_freeze|上海炒家`;index.html 版本串 `20261002-a629` |
| boot.json 一致性 | boot.overview.sentiment_calendar 24/24 带 sh_*(与 overview 同源) |
| 备站 data/overview.json | 404 为常态(备站 data 走 R2 fallback,memory cf-workers-large-json-404-r2-fallback),前端 fetchJSON 自动 R2 fallback 到 ssd.fx8.store,一致 |

### 缺项原因说明
某天无 sh_* 的正常场景:`app/compute/icepoint.py` `compute()` 对当日无上海炒家口径数据(四因子任一缺,如缺楼层数据)或 compute 抛异常(L1585 logger.exception)时,该日不注入 sh_*;前端 `_hasSh=false` 兜底不显示 sh 格(§5.3 不白屏)。当前 24 天全有 ⇒ 四因子数据全部可得。

## 六、§22 依赖产物清单核验

独立审查结论「角标/温度 tab/邮件均不涉 sh,唯一消费方=情绪日历」——**复核通过**:

| 展示位/产物 | 是否读 sentiment_calendar | 是否读 sh_* 字段 | 结论 |
|---|---|---|---|
| 情绪日历(sh 格/图例/下钻弹窗/公示) | 是(app.js L7226-7344) | **是(唯一消费方)** | 已同步(overview.json 24/24) |
| 卡片时间角标(data-badge-freeze) | 读 `sentiment_calendar[0]` 的 date/freeze | 否(不读 sh_* 字段,app.js L11962-11982) | 依赖 sentiment_calendar 数据,已同步;新增字段不影响其渲染 |
| 市场温度 tab | 否(读 scores/signal_daily s.*) | 否 | 无需同步 |
| 邮件(check_signals.py) | 否(无 sh_* 引用) | 否 | 无需同步 |
| boot.json(boot.overview) | 含 sentiment_calendar 快照 | 旁路同源 | 已同步(export 同跑) |
| /api/overview(动态 API) | 由同款 queries.overview() 动态计算 | 天然带 sh_* | 无需同步(动态实时) |

## 七、复现段
```bash
# 1. 重生成(读真实主库 trade-data/data/sentiment.db)
cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/python static-site/export.py --incremental
# 2. 同步主仓镜像
cp /Users/linhuichen/code/trade-data/static-site/data/overview.json /Users/linhuichen/code/trade/static-site/data/overview.json
cp /Users/linhuichen/code/trade-data/static-site/data/boot.json /Users/linhuichen/code/trade/static-site/data/boot.json
# 3. R2 上传已由 export.py 自动段完成;校验:
md5 -q /Users/linhuichen/code/trade-data/static-site/data/overview.json
curl -sL -A "Mozilla/5.0" "https://ss.fx8.store/data/overview.json" -o /tmp/ov.json && md5 -q /tmp/ov.json
# 4. 统计 sh_* 覆盖
python3 -c "import json;d=json.load(open('/tmp/ov.json'));print(sum(1 for x in d['sentiment_calendar'] if isinstance(x,dict) and 'sh_freeze' in x), '/', len(d['sentiment_calendar']))"
# 5. 云上代码确认(只读)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal && git log --oneline -1 && grep -c sh_freeze app/queries.py'
```

## 八、时点与风险
- 2026-10-02 国庆假期非交易日,本次执行时点 16:35-17:00,未撞云上 17:50 update_all(只读验证+本机操作);云上 17:50 将幂等重跑(deploy.sh 非交易日分支),产出与本轮一致,不回退。
- 全程未 push main(仅本地数据层 + R2 上传);未 add 根目录 data/;未写云上。
