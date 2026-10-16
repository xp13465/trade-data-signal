# #252 冻结表孤儿买事件「定向补账」上线台账(2026-10-16 夜,A1 + A4 包)

## 0. 拍板与范围(用户 2026-10-16 拍板)

| 项 | 内容 |
|---|---|
| **A1** | 一次性**定向**补账孤儿买事件(入账侧白名单), **不动全局入账源**(T2 `SIGNAL_KELLY_FREEZE_UNION` 默认仍关闭) |
| **A4** | 打开孤儿观测(云上 `SIGNAL_KELLY_FREEZE_ORPHAN_ALERT=1`)+ 登记告警四元组 |
| **T2 翻默认** | **不翻**(依据:564/880 格变差;日后要翻须走 §5.4⑥ 版本升级全流程) |

依据: `scripts/trades_orphan_backfill.py`(只读候选生成器)· `scripts/signal_kelly_backtest.py` L397-520(T2 冻结表优先/孤儿检测)· `docs/ops/trades-wipe-rootfix-20261014.md`(根因 A 包)。

**干跑实测与派单基准不符(如实标注)**: 任务书基准 = 36 条 / no_price=0(取自 10-14 台账);2026-10-16 深夜**云上生产库**只读扫描实测 = **orphan=49 / 有价候选=43 / no_price=6**(多出的 13 条 = 10-14 的 5 条 + 10-15 的 2 条 + 10-16 当日的 6 条, 同一损伤类, 非新故障)。按 §23.3 举一反三**全量纳入**(只补点名那 36 条 = 只做点名处, 且 6 条当日孤儿之后不会再有任何机制回头补它们)。

## 1. 机制(为什么必须是「引擎读侧 + git 登记表」)

- `signal_daily` 每天全表 DELETE+重算, 上游 `index_daily` 被整段 UPSERT 重写 ⇒ 历史 buy 行凭空消失; 冻结表 `data/signal_kelly_etf_freeze.json` 是「事件曾存在」的唯一固化证据。
- **绝不往 signal_daily 插行**(下一次重算又抹掉, 治标不治本且造假日账)。
- 产出物(交易档)由三条链各自从零重算(17:50 export 链 / 02:00·16:35·21:00 backfill_metrics / 09:40 盘中增量), **任何手工改产物几小时后必然被打回** ⇒ 补账必须落在**引擎入账侧**, 且可 git 追溯、可一键回滚。
- 实现 = `config/signal_kelly_freeze_orphan_backfill.json`(白名单, git 跟踪)+ 引擎两个读侧钩子:
  ① `_union_freeze_backfill_rows()`: 只补**登记键** ∩ **冻结表仍在** ∩ **(date,index_id) 整行仍缺失**的买事件(第三道护栏 = 与 T2 全局 union 的区别: 信号类型漂移的事件行还在、读侧 `_freeze_fallback` 已接住, 再补一次就是**重复计数**);
  ② `_split_registered_orphans()` + `_alert_freeze_orphans(handled_n=)`: 已登记的孤儿不再计入告警(孤儿本体不会因补账而从 DB 消失, 不拆就会天天报同一批), **未登记的新孤儿照常告警**(真故障判别维度保留)。
- 应用点两处(§22 多展示位一致): 全量档(主产物)+ 盘中增量档(**只补「信号日 == T」的登记键**, 保持盘中档「零历史、只含 T 日交易」的结构不变量)。
- **fail-safe**: 登记表缺失/损坏/形状不对(`keys` 非 list)一律当空集 = 改动前现行为(不补账、不吞告警, 绝不静默造账)。单元测试锁死(`scripts/tests/test_252_freeze_orphan_backfill.py`, 14 例)。

## 2. 生成 / 重生成(单一格式来源, 防第二份实现漂移 §5.4⑦)

```
# 云上(只读扫生产库; 不写任何 DB)
python3 scripts/trades_orphan_backfill.py \
    --registry-out config/signal_kelly_freeze_orphan_backfill.json
```
- 本批登记表 = 2026-10-16 23:33 云上只读扫描结果(候选 JSON 留档 `/tmp/orphan_candidates_252.json`, 云上 `/tmp/orphan_candidates_252.json`), 由 `build_registry()` 统一转格式。
- `keys` 取**全部孤儿**(有价 43 + 无次日行情 6):「无次日行情」只是价还没到(正常 T+1 时点), 事件本体仍是真孤儿; **何时补得上交给引擎**按当时的 `etf_daily` 决定, 登记表不预判。
- 新孤儿出现时(告警会报)→ 重跑本命令重生成登记表, 追加即补。

## 3. 回滚(§25 可逆)

| 回滚对象 | 操作 |
|---|---|
| 补账机制 | 删 `config/signal_kelly_freeze_orphan_backfill.json`(或置 `keys: []`)⇒ 引擎回到改动前行为(不补账); 代码钩子空集即 no-op, 无需回退代码 |
| A4 观测开关 | 云上 `cp -p /home/ubuntu/backup-252-20261016/env.bak-20261016 /home/ubuntu/code/trade-data/.env`(systemd `EnvironmentFile` 每次启动读取, 不需 daemon-reload) |
| 产物回滚 | `cp -p /home/ubuntu/backup-252-20261016/data/<文件名> /home/ubuntu/code/trade-data/static-site/data/<文件名>` |

## 4. 实测证据(2026-10-16 深夜, 云上, **零生产写**)

**§25 备份先行(完成于任何写之前, 且实测可恢复)**
- 目录 `/home/ubuntu/backup-252-20261016/`: `env.bak-20261016` + `data/{signal_kelly_trades.json, signal_kelly_backtest.json, signal_kelly_trades_sdc.json, signal_kelly_backtest_sdc.json, signal_kelly_trades_intraday.json}` + `MANIFEST.md5`。
- 恢复验证 = 5/5 文件 md5 与源**逐位相同**(集合比对 `MD5_SET_IDENTICAL`); `.env` md5 `d658951f42ae391a48f5ba7c1e19731d` 一致。

**A4 观测开关到位(生产路径实证, 非只看配置)**
- 云上 `.env` 追加 `SIGNAL_KELLY_FREEZE_ORPHAN_ALERT=1`(第 42 行; 追加前备份同目录)。
- 三个相关 unit(`trade-update-all` / `trade-backfill-evening` / `trade-kelly-intraday-rerun`)均 `EnvironmentFile=/home/ubuntu/code/trade-data/.env`, 且 `update_all.sh` 内 signal_kelly_backtest 调用为直呼子进程(唯一 `sudo -n systemd-run` 只用于 fund-nav 上传, 与本链无关)。
- **实证**: `sudo -n systemd-run --property=EnvironmentFile=... --property=User=ubuntu /bin/bash -c 'echo $SIGNAL_KELLY_FREEZE_ORPHAN_ALERT'` → `PROOF=1`(真按 unit 同款环境跑出来的值, 不是读配置文件推断)。

**引擎干跑 A/B(登记表生效验证; 只写 /tmp, 生产文件 mtime 保持 10-16 23:18/23:19 未变 = 零生产写)**
- 搭法: `/tmp/252gen/` = `scripts`(真实文件 + 兄弟模块软链)/`config`(含登记表)/`data`(冻结表**真副本**、DB 软链)⇒ ROOT 落临时区, 任何写入不外溢; `notify.py` 换成**打桩**(只记日志不外发, §18 L48)。
- 日志: `[#252 定向补账] 冻结表补入登记表内未成账买事件 49 条` / `冻结表孤儿买事件: 共 49 条, 全在 #252 补账登记表内(已处置, 不告警)`。
- 产物 A/B(同一份 DB, 同一晚):

| | 总笔 | 命中登记键 (date,index) 成交行 | 覆盖有价候选 | 覆盖登记键 |
|---|---|---|---|---|
| 生产主档(无登记表) | 341,000 | 0 | 0/43 | 0/49 |
| 干跑(有登记表) | **342,848** | 1,848 | **42/43** | 42/49 |

- 未立即成账的 7 条 = **等有效行情日, 非缺陷**: 6 条 10-16 当日孤儿(次日 10-19 开盘还没到)+ 1 条 `20261015|csi_000102|buy`(次日 10-16 行 `accum_nav` 为 NULL 未回填 ⇒ 引擎按设计跳过, 待回填后自动成账)。
- **候选清单与引擎成账口径的差(如实标注)**: 候选生成器判「次日有行情」只看 `open` 非空, 引擎另需 `accum_nav` 就绪 ⇒ 候选清单是**上界**, 实际成账由引擎定, 不保证 100% 立即成账。
- 打桩拦截记录: 本次干跑触发了 1 条既有小缺口告警(`冻结表缺失历史信号事件 6 个`, 24h dedup 的 WARN 路径, **与本次改动无关**), 被桩拦住**零外发**。

**回归**: 本机全量 `pytest -q scripts/tests/` = **989 passed, 2 skipped**(新增 14 例在内), 无回归。

## 5. 边界 / 未覆盖(必读, 不许当"全好了")

1. **历史行不会回来**: 补账只修「入账侧」。`signal_daily` 里消失的行、以及由此受影响的**信号列表类展示位**, 本次不动(源头治本见 A 包装 `docs/ops/trades-wipe-rootfix-20261014.md`)。⇒ kelly 交易档与当日信号列表对同一事件可能一处有一处无, 属**损伤残留**, 不是新增不一致。
2. **盘中档只补 T 日**: 盘中增量档结构上「零历史」, 只补登记表里 `信号日 == T` 的键(保证同一事件在主档与盘中档口径一致)。
3. **登记表是时点快照**: 新孤儿须重跑 §2 命令重生成; A4 告警只报**未登记**的新孤儿 —— 报了就说明有新增损伤待处置。
4. **§21 算法公示未改**: 本次不改任何算法/评分/权重/匹配规则(纯数据完整性补账), 故 `purpose-notes.js`/前端公示无对应改动。
5. **§5.4⑥ 版本标记**: 交易档数字(总笔 341,000 → 342,848 及派生收益率)会变, 但默认组合/算法未动; 是否要为凯利页数字发一次中间版本标记 = **待主控/用户拍板**(本包未发)。

## 6. 生效链

代码与登记表在 feat 分支 → **主控 `scripts/main-merge.sh` 合并入 main** → 云上 `git pull`(deploy 链/self_heal)→ 下一次产物重算(17:50 全量 / 02:00·16:35·21:00 / 09:40 盘中)自动带上补账。**本次未在云上写任何生产文件**(证据见 §4), 真正落地靠合并后的生产链自动生效。