# A+B 提速方案反思报告:为什么没预见 `_now` bug + 后续待办风险评估

> 调研日期:2026-08-15 | researcher 产出,只读调研 | 触发:#90 采集异常根因(`_now` NameError)追因

## 一句话结论

`_now` bug 是**流程缺失**,不是单纯遗漏:A+B 是"reviewer FAIL 整改 commit",implementer 注意力全在 FAIL 项上,重构 runner.py 时**误删了无关的 `_now` 定义**(与新增 `_notify` 名字相近),且验收环节只做 py_compile/import/单测——**Python 函数体内名字调用时才解析,import 阶段根本不查**,所以影响 17 项指标的运行时错误漏到线上。

## 一、A+B 方案落档位置 + 改动范围 + 后续未执行清单

**诚实标注:方案无独立 md 落档**,只存在于 3 个 commit message(git show 可溯源):
- `113c05acb`(8/14 19:12)feat(update_all提速A第一步+B)——方案A(10001011黑名单 re-login)+ 方案B改动1(runner覆盖率<95%告警跳过写偏样本)+ 改动2(rebackfill按日回补)
- `be3da2c94`(8/14 19:44)fix(update_all提速A+B)——reviewer FAIL P1/P2/P3 整改,**此 commit 删 `_now`**
- `10ae54271`(8/14 20:02)merge

改动 5 文件:`baostock_daily.py`(rebackfill命令+日期归一)/ `baostock_worker.py`(10001011熔断)/ `cleanup_d3d2.py`(覆盖率拦截下沉)/ `runner.py`(覆盖率检查+_notify+**删_now**)/ `scripts/fix_turnover_partial_20260814.sh`。

**后续未执行项**:#37降并发+#38 core采集提速+#39 deploy增量导出——**在 docs/git 均无落档**(pending-features-index 的 #37/38/39 是别的内容),来源是 8/14 实时会话 TASKS 未入库保留。基于描述+代码现状已评估(见第三节)。

## 二、反思 1:为什么没预见 `_now` bug(证据链)

1. **误删**:`be3da2c94` diff 中 `_now` 定义紧邻新增 `_notify`,名字相近被顺手删
2. **两处调用没同步**:`runner.py:91`(upsert_metric)/`:106`(upsert_metrics_many)
3. **自验盲区**:commit message 写"单元测试通过+4模块import通过",但 import/单测都抓不到——函数体内名字调用时才解析,import 不查;单测只测 P1/P2/P3 新增逻辑,没测 metrics 写入路径
4. **真实采集才触发**:调用点在 metrics step 4 个分支(collect_direct/tencent/series/snapshot),一跑 update_all 全炸 → 17 项异常

## 三、后续未执行项风险评估

| 待办 | 涉及文件 | 同类风险(与 `_now` 同坑) | 防法 |
|---|---|---|---|
| #37 降并发+A熔断 | baostock_worker/parallel/runner | 改共享状态(circuit_open字段)读写两方不同步;worker日志格式正则解析不匹配 | 改共享状态前 grep 读写双方;加字段后跑真实并行采集核对统计 |
| #38 core采集提速 | pipeline.sh/indicators.yaml/fetchers | 改采集返回结构未同步调用方(upsert_index_rows);改config key未同步读取方;删sw指数波及board_etf_map/凯利回测/首页(§22/§23.6) | 改后跑 `--steps indices` 验证;删前 grep 全站引用 |
| #39 deploy增量导出 | deploy.sh/export.py | 增量判定静默用旧数据(带日期文件跳过=8-14偏样本同类);R2与static-site不同步(§22);并发deploy撞锁 | 建"必更白名单";改后跑完整update_all;§22三查 |

## 四、同类隐患扫描(pyflakes 全 app)

- **0 个 undefined name**(`_now` 是唯一,修复未 commit 时存在;pyflakes 可直接抓)
- 模块属性级交叉调用全部对齐(runner↔fetchers/baostock_*,签名 `run_update_parallel(codes, n_workers=4)` 一致)
- 大量 **imported-but-unused** import 残留(baostock_worker 3个/baostock_daily os/.base/runner os重定义等)——当前不炸,未来重构会误导,建议顺手清理

## 防再犯(已落 memory `refactor-delete-keep-callers-synced` 强化款)
1. 删函数定义前必 grep 调用点
2. 改核心采集模块验收必含「跑最小真实链路」(`--steps metrics`),不只 py_compile/import/单测
3. pyflakes 纳入 lint(直接抓 undefined name)
4. commit message 自验清单加"已跑真实采集链路(step名)"

## 复现
- **证据**:`git show be3da2c94 -- app/collector/runner.py`(看 `_now` 删除 + `_notify` 新增同位置)
- **扫描**:`pyflakes app/collector/`(抓 undefined name/未使用 import)
- **触发路径**:`python -m app.collector.runner --steps metrics`(真实采集,`_now` 修复前会炸 NameError)
- **日志铁证**:`data/logs/backfill_20260815_1635.log`(`runner.py:102 upsert_metrics_many → NameError: name '_now' is not defined`)
- 数据截止:2026-08-15 | 关键口径:import 不执行函数体,函数内名字调用时才解析
