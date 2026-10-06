# #219 治本(方案 P1):parts 元数据撤出 — 两把尺子合流,消除每轮「假补传」

> 日期:2026-10-06 | 角色:implementer | 分支:feat(worktree-agent-acc5e86f57441c0ac)
> 前置根因报告:`docs/ops/219-verify-r2-backfill-rootcause-20261006.md`(定性 = 甲噪音 + 丙口径错位)
> 结论一句话:**分片产物撤出 `generated_at`/`period_cutoffs`/`buy_amount`(每轮必变的生成器元数据)⇒ 整文件 md5 ≡ B 档指纹 ⇒ 上传链(跳过判据)与 verify-r2(整文件对账)两把尺子合流;本体不变则 0 补传,本体真变/R2 破坏或丢失则两处都照旧发现(判别力零损失)。**

---

## 1. 第一步:穷举(§23.3 举一反三)+ 结论门控

三字段的**全部生产方 / 判定方 / 对账方 / 消费方**逐一列全(不只改生成端):

| 角色 | 位置 | 说明 |
|---|---|---|
| **生产** | `scripts/signal_kelly_backtest.py:_export_trades_parts._dump`(L2148-2267 区内)、main() L2402 调用 | 每个 quadrants 分片(NDO/SDC 双口径,由 trades 文件名派生,同一 `_dump`)写入三字段 |
| 生产(旁路) | `_export_unique_parts`(unique_recent/unique_t*.json,KELLY_UNIQUE_EXPORT=1 才生成) | 产出 = `_build_unique_tables` 结果 `{fields,variant_fields,base_key_fields,qk_groups,n_base,base,variants}` — **本就不含三字段**,已是纯本体,无需改 |
| **判定** | `scripts/upload_r2.py:_kelly_parts_md5` L1017-1036(B 档:pop 三键后 sort_keys 序列化 md5) | 被 `cmd_upload_kelly_parts`(L1815)/`cmd_upload_kelly_parts_sdc`(L1832)绑定 |
| **对账** | `scripts/upload_r2.py:cmd_verify_r2._check` L3493-3510 | 小文件分支 `ok = etag.strip('"') == _file_md5(f)`(**整文件字节 md5**) |
| **状态** | `.r2_kelly_parts_state.json` / `.r2_kelly_sdc_state.json`(staticdata 仓 data/) | 存 B 档指纹;实测 `changed=[]`(上传链判"零待传") |
| **消费(前端)** | `static-site/app.js:3775 _simParseTrades`、`static-site/lab.js:8699 _labKellyParseTrades` | **只取 `tr.fields` / `tr.quadrants`**,返回 `{fields,fIdx,quadrants}`;三字段零读 |
| 消费(前端) | lab.js:8970/10646/13112 `td.buy_amount` | `td`=解析产物(无 buy_amount ⇒ 恒 undefined)⇒ 一律回退 `data.config.buy_amount`(= **backtest.json** 的 config) |
| 消费(前端) | lab.js:8971 / 12959 `period_cutoffs` | 读 `data.config.period_cutoffs` = **signal_kelly_backtest.json** 的 config(非 parts) |
| 消费(APP) | app.js:15938/29078 `generated_at` | 读的是 summary/snapshot/tb,**非 parts** |
| 消费(脚本) | `scripts/sync_dev_from_r2.sh` META_KEYS | 目标通道仅 `{index,industry,data-large}`,**不含 kelly-parts**;即便覆盖,pop 不存在键 = no-op |
| 消费(脚本) | `docs/kelly/**` 分析/复现脚本的 `period_cutoffs`/`buy_amount` | 读的是 **backtest.json config** 或**全量 trades 文件**(见下),非 parts |
| 消费(告警) | `check_data_gap_alerts.py` `generated_at` | 读全量 `signal_kelly_trades.json`(**非 parts**),不受影响 |

**门控结论:穷举后未发现报告结论之外、从 parts 读三字段的真消费方 ⇒ 不触发"停下上报",按方案 P1 实施。**

> 交叉印证:生成侧**全量** trades 文件(`signal_kelly_trades.json` / `_sdc.json`,走 data-large 通道)**保留**三字段(其 generated_at 被告警链消费);本次只动 **parts 分片**家族,全量文件一字不改。

## 2. 第二步:方式选择(撤出 vs 稳定化)—— 选「撤出」

- **依据**:
  1. 三字段**零消费**(上表逐一 grep 证据)。
  2. 三者语义都是"生成器元数据"而非数据本体:`generated_at`=生成时刻;`period_cutoffs`=**滚动日期切点(每天本就该变)**;`buy_amount`=常量(前端恒回退 config)。
  3. **稳定化(b)不可行/更复杂**:`period_cutoffs` 语义上就该随日期滚动,无法"稳定化到本体";`generated_at` 若"数据变才更新"需引入 body-hash 条件更新逻辑 + 新失败面(7 级阶梯:删优先于加)。
  4. parts 的 `period_cutoffs` 只是 **backtest.json config 的冗余副本**(前端读的是后者,后者照旧产出)⇒ 撤出不损语义。
- **实现**(`signal_kelly_backtest.py:_dump`):
  - `shard` 由 `{generated_at,buy_amount,period_cutoffs,fields,quadrants}` → **`{fields,quadrants}`**;
  - 序列化加 `sort_keys=True`,令**文件字节规范化,与 `_kelly_parts_md5` 的 sort_keys 序列化逐字节一致**(file_md5 ≡ B 档指纹,杜绝"内容同但键序不同"的残余代差)。
- **过渡行为**:`_kelly_parts_md5` 保留(对现产物 pop 变 no-op)⇒ ①旧 R2/旧状态里仍含三字段的产物照旧按 B 档判定,**B 档指纹连续(新==旧)⇒ 上传链不会"全变"重传**;②防御未来生成端回流元数据。

## 3. 第三步:实施 + 自测

### 3.1 改动文件
- `scripts/signal_kelly_backtest.py`:`_dump` 撤三字段 + `sort_keys=True`;`_export_trades_parts` docstring 同步。
- `scripts/upload_r2.py`:`_kelly_parts_md5` docstring 补 #219 说明(逻辑零改动)。
- `scripts/tests/test_219_parts_metadata.py`(新增,6 用例)。
- 前端源码 **未动**(无需 bump 版本串 / 无需发中间版本,见 §5)。

### 3.2 自测结果(逐条对应任务三条硬要求)
命令:`REPO=/Users/linhuichen/code/trade-data .venv/bin/python3 -m pytest scripts/tests/test_219_parts_metadata.py -v -s`

| 要求 | 用例 | 结果 |
|---|---|---|
| ① 连续两次生成 md5 稳定 | `test_c1_two_rounds_stable`(两轮 gen/period_cutoffs 不同、本体不变) | PASS:全部片跨两轮整文件 md5 **逐位一致** |
| 形态/合流/状态连续 | `test_c2` | PASS:顶层键 == {fields,quadrants};`file_md5 == B 档`;旧(含三字段)与新(仅本体)的 **B 档相等** |
| ② 负控-内容真变 | `test_c3a` | PASS:改 profit ⇒ **B 档变(上传须传)且整文件 md5 变(verify 须补传)** |
| ② 负控-R2 真丢/破坏 | `test_c3b` | PASS:`etag=None`(404)/`etag≠本地`/近大小异内容 ⇒ 判据全 False(照旧补传) |
| ③ 前端解析逐字段不变 | `test_c3c`(node 抽取 app.js/lab.js **真实函数源码**在旧/新文件上运行) | PASS:两函数解析结果 canonical-stringify **完全一致**;结果键 == `fIdx,fields,quadrants` 无元数据泄漏 |
| 登记点守护 | `test_c4` | PASS:verify 判据仍 `_file_md5`+ETag、B 档仍剔三字段、生成端不再写三键 |

**真实生产分片实测**(用 trade-data 镜像的 18 NDO + 17 SDC = 35 个真产物,模拟"撤三字段+sort_keys"):
```
真实分片 35 个: 合流(file_md5==B档) 35/35; 状态连续(B档新==B档旧) 35/35
```
⇒ 真实数据尺度上:两把尺子合流、切换后状态连续(不会上传风暴)。

## 4. 上线步骤(由主控走统一入口)

1. 本 feat 分支 merge main(`scripts/main-merge.sh`;纯脚本+测试+文档,**无前端源码改动 ⇒ 无需 build_min/bump 版本串**)。
2. 云上 `git pull` 后,**下一轮 export**(15:35 后盘后链路)即产出新格式 parts。
3. 过渡:该轮上传链因 B 档连续**跳过**不 PUT,R2 仍持旧格式 ⇒ **verify-r2 该轮一次性回填 34 个**(与当前每轮成本同量级,**只此一次**)⇒ R2 收敛为新格式。
4. 次轮起:本体不变 ⇒ 上传跳过 + verify **0 补传**;期望日志从每轮 `发现 34~36 个不一致` 降为 `全部一致 ✓`。
5. 观测点:下一交易日各轮 verify-r2 的 parts 通道行(应 0);R2 对象 ETag 与本地 md5 一致。

## 5. 诚实标注 / 边界(未决或未动)

- **【§5.4⑥ 判断】不发中间版本、不动测试基准**:本次仅改 parts 分片的**传输/元数据**层,数据本体(fields+quadrants)逐字节不变,前端行为零变化,**未触及 AI 推荐/降亏过滤的默认组合或算法** ⇒ 无需版本升级/基准定义更新。
- **【§23.7 冻结契约】parts schema 结构变更**:已上线产物去掉了 3 个顶层键(前端零消费、行为不变)。已按派单授权实施,建议 **reviewer 复核消费方全量清单 + 键集审计**;若用户拍板"冻结 parts 结构",则退根因报告 P2。
- **【§21 算法公示】无算法改动** ⇒ 无需改 purpose-notes.js / app.js / lab.js 公示。
- **【§22 一致性】parts 仅单一消费路径**(首页模拟回测弹窗 + 实验室),无多展示位一致性问题;R2 过渡轮回填后即一致。
- **`recent2.json` 残留(未动)**:NDO parts 目录内有一枚 `recent2.json`(2026-08-29 旧残余,当前 `_dump` 不再生成该名)。它含旧格式三字段但**从不重写**⇒ B 档稳定、不产生每轮代差;非本任务范围。**是否清理需另立删除任务(§25 先备份后删)**。
- **全量 trades 走 data-large 通道(未动)**:`signal_kelly_trades.json`/`_sdc.json`(各 ~86MB)的 `generated_at` 每轮变 → 其 A 档整文件 md5 每轮变 → data-large 每轮真上传(≈173MB/轮)。这是**另一条独立通道**且其 generated_at 被告警链消费,口径不同,不在 #219 范围;如需省这份带宽须**另立任务**(会牵动告警新鲜度判定,风险高于本任务)。此处仅记录,未改。
- **未直连 R2 实测**:恪守"实施期禁真外发",未 HEAD/GET R2;合流与连续性均以本地 `_file_md5`/`_kelly_parts_md5` 对真实产物实测(35/35)。
- **`schedule_stats.json` 等浮动位**:属根因报告 §4.2/§4.3 的独立链产物(非 parts),本任务不涉及。

## 6. 证据锚点
- 代码:`signal_kelly_backtest.py:_export_trades_parts._dump`(改动点)/ `upload_r2.py:_kelly_parts_md5`(docstring)、`_file_md5` L1003、`cmd_verify_r2._check` L3493-3510、`_R2_CHANNELS` kelly-parts/-sdc L3302-3305。
- 测试:`scripts/tests/test_219_parts_metadata.py`(6 用例)。
- 真产物体检:NDO 18 + SDC 17 = 35 分片,合流 35/35 + 状态连续 35/35。
- 前置:`docs/ops/219-verify-r2-backfill-rootcause-20261006.md`。