# FAPI 日线采集 P0 落地实现报告

- 日期:2026-09-02
- 实施:implementer(role-implementer skill)
- 分支:research/fapi-h-k1(纯新增试点,不碰生产链)
- 上游方案:docs/fapi/fapi-integration-plan-20260901.md §2(P0 日线 T+1→T+0 落地设计)+ §7.4 改动范围

---

## 0. 结论速览(TL;DR)

| 项 | 结论 |
|---|---|
| 采集脚本 | `app/collector/fapi_daily.py` 已落地并真实跑通 |
| 新表 | `data/stock_daily.db:fapi_daily_raw`(建表,主键 (thscode,date_ms)) |
| 实测数据 | 10 交易日窗口 20260819-20260901,**55448 行 / 5553 只 / 主键零重复**,最新交易日=20260901(T+0 成立) |
| 与 mootdx 逐位一致 | 20260901 重叠 5169 只,close/amount 不一致均为 **0**;茅台 600519 close=1299.56 与 mootdx 逐位一致 |
| 补漏价值 | fapi 有而 mootdx 无 377 只(20260901),含北交所 339 + 断片补漏 |
| launchd 模板 | `docs/fapi/launchd/fapi-daily.plist`(18:10,只写模板不挂生产) |
| 上线状态 | 仅落 research/fapi-h-k1,未 bump/未 deploy/未 push main(§23.7 只增不改) |

## 1. 落地内容

### 1.1 采集脚本 app/collector/fapi_daily.py

- **流程(3 步)**:① `GET /api/dump/market-dumps/daily-k-10d/download-url`(X-api-key 头)→ ② 立即下载 Parquet(预签名 ≤5 分钟过期)→ ③ pyarrow 读 → 字段映射 → UPSERT 写 `fapi_daily_raw`。
- **字段映射**(FAPI dump → 表,物理交换命名坑):
  | FAPI dump | fapi_daily_raw | 处理 |
  |---|---|---|
  | thscode `600519.SH` | code=600519 / thscode 原样 | 去 `.SH/.SZ/.BJ` 后缀 |
  | date_ms(int64 毫秒) | date=20260901 | Asia/Shanghai 零点 |
  | open/high/low/close_price | open/high/low/close | 直接 |
  | volume | volume | 股 |
  | turnover | **amount** | ⚠️ FAPI turnover=成交额(元)非换手率,命名交换到 amount |
  | (无) | pct_change | 自算 close/prev_close-1,与 mootdx 同口径 |
  | (无) | turnover | 换手率恒 NULL(现有腾讯/快照链补) |
- **命名坑机检**:入库前断言 `(turnover>volume) 占比 ≥90%`,否则拒绝映射(防换手率/成交额错位)。
- **增量策略**:常规 daily-k-10d(10 交易日窗口);库内最新日期落后 ≥8 自然日 → 自动切 daily-k(10 年全量)一次跑完,防缺口;`--full` 强制全量。
- **幂等/重试**:UPSERT 按主键天然幂等(实测重跑行数不变 55448);下载重试 ≤3 次指数退避;预签名 URL 只打 host 不打 querystring。
- **安全**:API key 只从 .env 读(`HITHINK_FINANCE_API_KEY`),不打印/不入日志/不入 git;脚本内无 key 明文。

### 1.2 新表 fapi_daily_raw(只建新表,不动任何现有表)

DDL 见 `app/collector/fapi_daily.py` SCHEMA 常量。要点:
- **唯一键 = PRIMARY KEY (thscode, date_ms)**(dump 天然唯一,实测重复 0)
- 列:thscode/date_ms/code/date/open/high/low/close/volume/amount/pct_change/turnover
- 索引:idx_fapi_daily_code、idx_fapi_daily_date
- 与 mootdx_daily_raw 语义对齐(code/date/open/…/amount/pct_change),下游 width 链未来可无缝消费

### 1.3 launchd 模板 docs/fapi/launchd/fapi-daily.plist

- StartCalendarInterval=**18:10**(避开盘后 15:35/16:00/17:50/20:35/22:00 与 update_all 17:50,7 分钟余量,§14)
- WorkingDirectory=trade-data,日志指 trade-data/data/logs(参照 com.trade.*.plist 惯例)
- **只写模板,不 launchctl load、不挂生产**(观察期双写)

## 2. 实测数据(2026-09-02 深夜,真实写库 trade-data/data/stock_daily.db 生产侧)

| 指标 | 实测值 |
|---|---|
| 总行数 | 55448 |
| code 覆盖 | 5553 只(含北交所 339) |
| 日期范围 | 20260819 ~ 20260901(10 交易日) |
| 最新交易日 | 20260901(**T+0 成立,当晚数据在位**) |
| 主键 (thscode,date_ms) 重复 | 0 |
| 20260901 行数 | 5546(7 只停牌缺席,正常) |
| 重跑幂等 | 行数不变 55448 ✓ |

### 2.1 与 mootdx_daily_raw 逐位对照(20260901)

| 对照项 | 值 |
|---|---|
| 重叠 code | 5169 |
| close 不一致(>0.0001) | **0** |
| amount 不一致(>0.01) | **0** |
| fapi 有 mootdx 无(补漏) | 377(北交所 339 + 断片补漏) |

**茅台 600519@20260901 逐位一致**(fapi vs mootdx):
```
close=1299.56  open=1295.0  high=1307.99  low=1286.1  volume=3266402  amount=4242440861.1  pct_change=0.0031
```

**补漏演示**:000001(平安银行)mootdx 停在 20260824(断 6 交易日,方案 §1.3 痛点实例),fapi_daily_raw 有 20260901 close=11.92 —— 断片缺口由 FAPI 补上。

## 3. 采集落点修正(2026-09-02 生产覆盖事故根治)

### 3.1 事故:表曾从镜像侧被 deploy 覆盖冲掉

| 时间线 | 事件 |
|---|---|
| 01:35-02:04 | implementer 在 **trade(镜像侧)** 写库 55448 行,fapi_daily_raw 表落地、幂等验证通过 |
| 02:07:28 | backfill-evening 内部 `index_backfill.main` 补到新数据 → 触发 `deploy.sh backfill`(证据 `data/logs/backfill_20260902_0200.log` L69) |
| 02:07:28+ | deploy 1.7 rsync 阶段 `rsync -a --exclude=logs/ $REPO/data/ $GIT_REPO/data/`(deploy.sh L296-321)把 **trade-data(生产权威侧)的 stock_daily.db(无 fapi 表)反向覆盖回 trade(镜像侧)**,inode 被替换、mtime 退回 09-01 19:23 |
| 02:20+ | 主控验收查询 → 表消失 |

**根因**:implementer 落点错误 + deploy 的单向覆盖机制。数据权威在 **trade-data**(launchd WorkingDirectory=trade-data),trade/ 是 rsync 镜像。写入镜像侧的数据会被下一次生产侧 deploy 覆盖(它本来就是`trade-data→trade` 只同步生产侧已有的东西)。

### 3.2 修正:生产侧落点 + 双副本一致

- **生产侧 venv 补依赖**:`/Users/linhuichen/code/trade-data/.venv` 装 `pyarrow 25.0.1`(与 trade venv 同版本)
- **从生产侧重跑采集**:`cd /Users/linhuichen/code/trade-data && ./.venv/bin/python -m app.collector.fapi_daily`(脚本 `__file__` 经 symlink 解析到 trade-data/data),落库 **55448 / 5553 / 主键零重复 / latest=20260901**,茅台 600519 close=1299.56 逐位正确
- **幂等重跑**:保持一致 55448 行(2 次确认)
- **镜像侧手动 rsync 追平**(与 deploy.sh 1.7 同机制):`rsync -a --exclude=logs/ trade-data/data/ trade/data/` → 双副本一致 55448/5553
- **自动清理增强**:`run()` upsert 后 `dest.unlink(missing_ok=True)` 清掉下载的 dump parquet(防 accumulate;失败不阻断)

**运维约束(未来必遵守)**:FAPI 采集必须**从 trade-data 跑**、落到 `trade-data/data/stock_daily.db`(生产权威侧)。launchd 模板 WorkingDirectory=trade-data 天然正确;禁止从 trade 侧直跑写镜像。

## 4. 下一步(观察期计划)

1. **双写互证 ≥1 周**(本次起每日 18:10 模板挂载后,fapi_daily_raw vs mootdx_daily_raw 每日对账,close 差异 >0.5% code 数告警)
2. **确认互证逐位一致后 → 评估转主**(把 fapi_daily_raw 接入宽度/行业宽度下游,替代 mootdx 断片源)
3. **北交所宽度口径需用户拍板**(方案 §2.4:fapi 含北交所后 width 总家数会变,是否纳入宽度宇宙由用户定,再动 width 下游)
4. **互证校验脚本**(§22:挂 deploy 前 check,与 check_universe_alignment 同链)——列为观察期待补
5. **全量 daily-k 路径**(10 年全量,~945 万行)仅兜底重建用,自动切换逻辑已实现,不每日拉

## 5. 风险与边界(诚实标注)

| 风险 | 等级 | 缓解 |
|---|---|---|
| FAPI 单一外部依赖(同花顺) | 中 | 只做兜底,主链不动;与 mootdx 异构双源互备 |
| dump 预签名 5 分钟过期 | 低 | 签名即下载,不跨时点(脚本已内联) |
| 4001 限流 | 低 | 1 天 1 次 dump,远低于限流;错误码 1xxx/2xxx 不重试、4001 指数退避 ≤3 次 |
| 全量 daily-k 未实测下载 | 低 | 仅自动切换兜底;10d 增量已实测;全量路径与 10d 同流程同校验 |
| Key 泄露 | 高 | key 仅 .env;脚本/日志/报告零明文;commit 前 grep 防呆 |

## 复现

**脚本路径**:`app/collector/fapi_daily.py`
**生成依赖**:`data/stock_daily.db`(建 fapi_daily_raw 表)、`.env`(`HITHINK_FINANCE_API_KEY`,trade 或 trade-data 侧均可)、`requests`+`pyarrow`(两侧 venv 均已装)
**重跑命令**(⚠️ **必须从 trade-data 跑**落生产权威侧;倒灌 dump 后自动清理,不残留 parquet):
```bash
cd /Users/linhuichen/code/trade-data
./.venv/bin/python -m app.collector.fapi_daily            # 常规增量 daily-k-10d(UPSERT 幂等)
./.venv/bin/python -m app.collector.fapi_daily --full     # 强制全量 daily-k 重建
./.venv/bin/python -m app.collector.fapi_daily --dry-run  # 只下载+映射验证,不写库
# 镜像侧手动追平(与 deploy.sh 1.7 同机制,平时 deploy 自动做):
rsync -a --exclude=logs/ /Users/linhuichen/code/trade-data/data/ /Users/linhuichen/code/trade/data/
```
**数据截止**:2026-09-02 深夜(dump 覆盖 20260819-20260901,20260901 为最新交易日)
**关键口径一句话**:dump 主键 `(thscode,date_ms)` UPSERT;FAPI `turnover`=成交额(元)→ amount 命名交换,换手率列恒 NULL;pct_change 自算 close/prev_close-1(与 mootdx 同口径)。
