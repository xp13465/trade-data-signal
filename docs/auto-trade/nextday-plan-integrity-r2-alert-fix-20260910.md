# 次日买入计划 机检链收编 + R2/通知失败告警 修复报告(F1/F2)

日期:2026-09-10
分支:feat/prd-plan-fix98(基于 origin/main fb7e94687)
相关 PRD:docs/auto-trade/next-day-buy-prd-20260910.md、nextday-plan-backend-implement-20260910.md

## 背景

nextday_plan(次日买入计划,PRD 阶段一产物)上线后,reviewer 提出两个非阻塞项:

- **F1(80分)**:新产物 nextday_plan/auto_trade_steps 未接入既有机检链 —— check_data_integrity /
  check_r2_consistency / schedule_monitor.sh / gen_schedule_stats.py 均无该任务登记,漏跑/过期/结构损坏无告警出口。
- **F2(75分)**:nextday_plan_generator.py 的 R2 上传失败、关键通知失败是静默的 —— 计划生成/写盘/上传失败对生产是致命的
  (用户看到错数据),必须走 notify.py --severe 告警 + 最终退出码非 0。

## F1 改动清单

| 文件 | 改动 |
|---|---|
| `scripts/check_data_integrity.py` | 新增 `check_nextday_plan(data_dir)` 检查,注册进 run_all_checks(s06_state 之后)。校验:①文件存在 ②date 字段为 YYYYMMDD ③date 合法性(允许=最近交易日/当前交易日/下一交易日,交易日历不可用时退化>7天即 FAIL) ④空计划 `{date, empty:true}` 为合法 ⑤非空 plan 逐条校验 etf_code/etf_name/prev_close/amount/signal/buy_date 字段 ⑥`auto_trade_steps.json` 若存在则校验 schema_version==v1 + steps 为数组 |
| `scripts/check_r2_consistency.py` | FILES 元组新增 `("nextday_plan", "nextday_plan.json", r2_url, cf_url)`;`_fingerprint` 新增 nextday_plan 分支(date/empty/plan[0].etf_code/plan[0].buy_date 指纹) |
| `scripts/schedule_monitor.sh` | TASKS 表新增 nextday_plan 行(schedule 20:55, trading_day_only=True, log=nextday_plan_launchd.log);DUR_THRESHOLDS 新增 `"nextday_plan": 900`(15min 超时告警) |
| `scripts/gen_schedule_stats.py` | TASKS 表新增 nextday_plan 行(名称"次日买入计划", schedule 20:55, standard 模式);LABEL_MAP 新增 `"nextday_plan": "com.trade.nextday-plan"` |

## F2 改动清单

`scripts/nextday_plan_generator.py`:

- 新增 `_severe_alert(subject, body)` helper:调 notify.py `--severe --from-prefix [告警] --alert-issue --alert-log --dedup-key nextday_plan_gen_fail --dedup-window 3600`(1 小时内同主题不重复轰炸)。
- R2 上传块:`r2_rc = 0` 初始化;returncode != 0 → 记日志 + `_severe_alert` + `r2_rc = 1`;TimeoutExpired/异常同样 r2_rc=1。
- 通知块:`notify_rc = 0`;notify.py returncode != 0 → 记日志 + notify_rc=1(不内部再发 severe —— nextday_plan.sh 包装层已有 dedup-key nextday_plan_fail 的 --severe 兜底,避免重复轰炸)。
- 最终 `return 1 if (r2_rc or notify_rc) else 0`。

不误报原则:只对「计划生成失败/写盘失败/上传失败」这类真正卡住生产的主链路失败告警;通知通道的偶发抖动
(如 notify 单次失败)只影响退出码、不触发内部二次 severe(由包装层 dedup 兜底),避免通道抖动引发告警风暴。

## 自测结果

| 验收项 | 结果 |
|---|---|
| 语法检查(python3 ast.parse ×4 + bash -n) | PASS |
| check_data_integrity.py 实跑(venv, 生产 data-dir) | 42 ok / 1 warn(etf_since_return 既有) / 0 fail;nextday_plan 行显示 "空计划(empty:true) date=20260910" PASS |
| check_data_integrity 正/负用例(check_nextday_plan 单独构造 8 组) | 全 PASS(date 非法/plan 非数组/空数组无 empty/字段缺失/steps v2/steps 非数组 → FAIL;空计划/正常计划 → OK) |
| check_r2_consistency 指纹对账(local trade-data vs ssd R2 vs ss CF r2) | 三方 date/empty 指纹逐位一致 PASS |
| schedule_monitor 漏跑模拟(沙箱, 昨天日志 + 今天 20:55 无运行) | SEVERE: nextday_plan 漏跑 计划<20:55> 正确触发 |
| schedule_monitor 无误报(沙箱, 今天 20:55 运行已写入) | 无 nextday_plan 漏跑告警 |
| gen_schedule_stats 沙箱实跑 | schedule_stats.json 14 tasks 含 nextday_plan(次日买入计划 20:55) |
| F2 正常路径(--no-r2 --no-notify) | exit=0, 无 severe 误报 |
| F2 白盒:R2 上传 rc=1 模拟 | _severe_alert 被调(含 rc + 明细)+ r2_rc=1 → 最终退出码非 0 PASS |
| F2 白盒:notify rc=1 模拟 | notify_rc=1 → 退出码非 0;内部不重复发 severe(交包装层) PASS |

## 复现

- 改动文件:`scripts/check_data_integrity.py`、`scripts/check_r2_consistency.py`、`scripts/schedule_monitor.sh`、
  `scripts/gen_schedule_stats.py`、`scripts/nextday_plan_generator.py`(本报告 + 上 5 文件同 commit)。
- 输入依赖:`data/nextday_plan.json`(生成器产物,当前 `{"date":"20260910","empty":true}`)、
  `static-site/data/schedule_stats.json`、`data/trade_dates.txt`、`data/logs/nextday_plan_launchd.log`。
- 重跑命令:
  - 机检:`REPO=/Users/linhuichen/code/trade-data /Users/linhuichen/code/trade-data/.venv/bin/python scripts/check_data_integrity.py --deploy-mode --data-dir /Users/linhuichen/code/trade-data/static-site/data`
  - R2 一致性:`REPO=/Users/linhuichen/code/trade-data python3 scripts/check_r2_consistency.py`
  - 监控漏跑(沙箱冻结 NOW):复制 schedule_monitor.sh 到沙箱,`NOW = datetime(2026,9,10,21,10,0)`,`REPO=<沙箱>` 带昨天日志 → 期望 SEVERE nextday_plan 漏跑
  - 生成器正常:`REPO=/Users/linhuichen/code/trade-data /Users/linhuichen/code/trade-data/.venv/bin/python scripts/nextday_plan_generator.py --no-r2 --no-notify`
- 数据截止:2026-09-10(nextday_plan.json date=20260910)。
- 关键口径一句话:nextday_plan date 允许=最近交易日/当前交易日/下一交易日(覆盖周一 17:50 deploy 场景:生成器 20:55 跑,文件仍持上周五 date);空计划 `{date,empty:true}` 为合法;R2 上传/写盘失败走 notify.py --severe 且退出码非 0。
