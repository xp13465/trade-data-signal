# 邮件告警处理:deploy 数据校验自锁(alert.json R2 停留 09-30)— 2026-10-08

**结论一句话**:告警确认 = `deploy.sh` 的 `check_data_integrity` FAIL(读线上 R2 且 R2 唯一上传通道是 deploy ⇒ 自锁);
本次唯一授权写 = 补传 `alert.json` + 70 个 `alert_analyze_*.json` 到 R2;补传后 check **0 fail / EXIT=0 闸门放行**。

## 一、告警原文(最近一封,`data/alerts/latest.md` L302)

```
## [severe] 2026-10-08 16:39:14 · [告警] deploy 数据产物校验失败
- **级别**: severe
- **来源**: notify.py
- **通道**: email=OK feishu=OK
- **摘要**: deploy.sh check_data_integrity FAIL(rc=1), 已终止部署(4 类事故拦截)。
  日志: /home/ubuntu/code/trade-data/data/logs/deploy_20261008_1632.log
```

同日 02:16:02 同款一封(`deploy_20261008_0206.log`)。

## 二、发出时间 + 判据

- 最近真实外发:**2026-10-08 16:39:14**(email=OK feishu=OK),此后 18:28 / 21:45 两轮 deploy 均被去重抑制:
  `[notify][dedup] suppress key=deploy_check_data_integrity_fail last_alerted=2026-10-08 16:39:14 ... < window=21600s`
  ⇒ 16:39:14 + 6h = **22:39:14** 窗口到期,之前任意 deploy 失败都会重发。
- 判据链:`deploy.sh` L323-324 跑 `check_data_integrity.py --deploy-mode --data-dir $REPO/static-site/data` → exit 1
  → L329 `notify.py ... --severe --dedup-key deploy_check_data_integrity_fail --dedup-window 21600`。
- 19:38 那轮 4 项 fail(update_all_20261008_1750.log L1251+):
  - `✗ alert: alert.json date=20260930 滞后 8 天 > 7 天` ← **本告警主角**
  - `✗ accum_nav_map_fresh` / `✗ trade_sim_indices` / `✗ s06_state`
  - 21:45 那轮只剩 1 fail(仅 alert)。
- **是否 deploy 自锁:是**。`check_alert` 读的是线上 R2(`_fetch_r2_json("alert.json")`),而 R2 上该文件停在 09-30 内容版;
  本 check 又是 deploy 的前置闸门 ⇒ 唯一自动上传通道被自己拦住 = 永久死锁。

## 三、实际执行命令(以代码实现为准;`--help` 用法行未列此子命令)

- 核对:`REPO=/home/ubuntu/code/trade-data .venv/bin/python scripts/upload_r2.py --help`
  —— 用法行**没有** `upload-data-files`,但代码 L4033 分发存在:注释 `upload-data-files <file1> [file2] ... 上传指定文件到 R2 data/ 前缀 + purge`(参数=相对 `static-site/data/` 的文件名)。
- 闸门要求:该命令不在 `_A_CLASS` / `_TRADE_FALLBACK_OK` 白名单,**必须显式带 `REPO=`,否则 `guard_repo_default` exit 3 拒绝**。
- 唯一授权写(实际跑的命令,比任务原命令多一个 `REPO=`):

```bash
cd /home/ubuntu/code/trade-data && REPO=/home/ubuntu/code/trade-data timeout 300 \
  .venv/bin/python scripts/upload_r2.py upload-data-files alert.json \
  $(cd static-site/data && ls alert_analyze_*.json)
```

结果:`共上传 71/71 -> https://ssd.fx8.store/data/` + `Cache purge 3 批全成功 purged=71/71`。

## 四、解锁前后对照

| 对象 | 解锁前 | 解锁后 |
|---|---|---|
| R2 `data/alert.json` | date=20260930, generated_at 09-30 18:37:24 | **date=20261008**, generated_at 10-08 19:29:45 |
| R2 `data/alert_analyze_510300.json` | alert.date=20260930 | **alert.date=20261008** |
| check 判据 | `✗ alert ... 滞后 8 天 > 7 天` | `✓ alert: date=20261008 (滞后 0 天)` |

## 五、闸门复核(check 单跑,只读)

只读性判定:云上 grep 确认 `check_data_integrity.py` 写操作 0 / 无 notify 外发 / 无 HTTP 写方法
(匹配到的 4 处 PUT/POST 实为注释里 `MUST_RECOMPUTE` 子串);唯一网络活动 = `_fetch_r2_json` GET;
`subprocess` 仅调 `check_s06_state.py`(静态 grep 无写)。

- 第一次:`... check_data_integrity.py --deploy-mode --data-dir .../static-site/data` → `=== 汇总: 38 ok / 4 warn / 0 fail ===`
- 第二次(带 `REPO=` 核 exit code):`EXIT=0`,`✗` 计数 0,`=== 汇总: 40 ok / 2 warn / 0 fail ===`
- 残留 2 warn(不阻断,`--deploy-mode` 仅 fail 阻断):`fapi_mutex`(观察期正常时序)、`etf_since_return 93.2% < 95%`
- ⇒ **闸门放行**

## 六、一致性校验(md5 三处逐位一致,§22)

| 文件 | ss.fx8.store | ssd.fx8.store | 云上源侧 |
|---|---|---|---|
| alert.json | 65c60ad5378e4179a40bfacb69c08352 | 同左 | 同左 |
| alert_analyze_hs300.json | 3d495923b03347f972445eff8cd71f62 | 同左 | 同左 |
| alert_analyze_us_spx.json | 3f0e9a324f0b18a7162157ad9f004c91 | 同左 | 同左 |
| alert_analyze_510300.json | dcda59fbe77aa7b0ff85637dacffe8a3 | 同左 | 同左 |

## 七、观察项(诚实标注)

1. 另 3 项 fail **非本次修复**:19:38 时 4 fail → 21:45 时仅 1 fail,由其它链在 19:45-21:51 更新
   (`accum_nav_map.json` mtime 21:51、`trade_sim_indices.json` mtime 19:45、s06 快照 20:35 链)。
2. purge 生效延迟:补传后**首次**抽查 hs300 曾拿到旧值(alert.date=20260930),复取即新值
   ⇒ CF purge 异步生效,非持续不一致;当前四文件 × 三处逐位一致。
3. 22:39:14 去重窗口到期后,若 deploy 仍失败会重发邮件;现 check 已 0 fail ⇒ 该告警不会再触发。

## 八、未测项 / 硬约束遵守

- **未跑 deploy 全链**(未授权);**零真实邮件/飞书/告警外发**;除补传那次外**零其他 R2 写**。
- `check_s06_state.py` 仅静态 grep 无写,未逐行审计;其余 67/70 个 analyze 未逐一线验(整批 71/71 上传成功 + 抽 3 个 md5 逐位一致)。
- 证据:`/tmp/ci_rerun.txt`(第二次 check 完整输出);日志 `deploy_20261008_1632.log` / `_2145.log` / `update_all_20261008_1750.log`。
