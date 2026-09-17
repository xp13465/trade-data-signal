# 云上 deploy 链 ov-parity FAIL 根因调研(2026-09-16)

> 调研 agent 只读产出。现象:云上 09-16 17:05 public-fund-daily 跑 deploy 时 ov-parity I1/I2 FAIL 终止部署;
> 09-15 21:42 overfit-monitor 与 09-15 21:30 etf-national-team 两个 service exit=1;18:19 手动 deploy all 又成功。

## 结论速览

1. **recent.gr 空的根因(代码行级)= `scripts/overfit_monitor.py` 硬编码 FIELD 26 列与 trades.json 实际 27 列漂移**
   —— rating 读到 index 25 的 market_tier_cyb 中文字符串,`build_recent_block` L731 守卫
   `t.get("rating") in ("high","mid","low")` 不满足 → gr 恒 None → ov-parity I1「合法=0 非法=0」/I2 桶空。
   修复 commit = dc1f1c785(09-16 06:30,补 real_buy_date 对齐 27 列),已在 main。
2. **坏产物留场跨天**:09-15 21:42 打点产出的坏 overfit_monitor.json 未被修复前一直躺在
   static-site/data/,09-16 17:05 任何走 deploy.sh 的任务(public-fund-daily)的 1.2.3 校验都读到它 → FAIL 终止。
   17:31 手动重跑 overfit_monitor.sh(代码已含修复)→ 产物恢复 → 18:19 deploy all PASS。
3. **sdc rc=1 与 ov-parity FAIL 无因果**(sdc 失败不写 signal_kelly_trades.json,见 export.py L1240-1264;
   且 09-15 21:00 sdc 成功时坏产物照样存在)。sdc 失败是 09-16 16:35 起独立的持续性问题,根因待补(见 §5)。
4. **09-15 晚间连环失败 = 三件事两个根因,非同源**:
   - 21:15 turnover exit=143:systemd TimeoutStartSec=300 杀掉(采集 4.8min 仅 200/5200)
   - 21:07/21:27 deploy 版本一致性 FAIL(app.min.js 工作区脏/min 过期)——瞬时自愈
   - 21:30 etf_nt + 21:42 overfit-monitor exit=1:同一根因(FIELD 漂移坏产物)

## §1 recent.gr 空的确切根因(代码行级)

- 病灶起点:89c9f774b(2026-09-11 23:56,feat(batch-fix) #72)给 `signal_kelly_backtest.py` TRADE_FIELDS
  补 real_buy_date(schema 26→27 列,real_buy_date 落在 index 20),但 `overfit_monitor.py` 硬编码 FIELD 未同步
  (保持 0d95a667c 版 26 列:real_buy_price=19, real_current_price=20, …, rating=25)。
- 错位:`overfit_monitor.py` load_trades L374-379 FIELD 缺 real_buy_date → index20 起整体前移一格 →
  `t["rating"]`(IDX 25)实际读到 trades.json index25 = **market_tier_cyb 中文字符串**。
- 空化:`build_recent_block` L724-732 bt_map 构建中 `ent["gr"] = t.get("rating")` 仅在
  `rating in ("high","mid","low")` 时设置(L731),读到中文串/空串时 gr 保持 None。
- 结果:recent.rows 每行 gr=null → check_overfit_recent_parity.mjs L393-394 I1
  `grN>0 && grBad==0` FAIL(合法=0 非法=0)、L395-398 I2 by_grade 回测桶 0/0/0 FAIL。
- 为什么 09-15 才爆发:trades.json 每日由 update_all/backfill 的 export 重写,但 09-12(周六)/09-13(周日)
  无打点(非交易日闸门 overfit_monitor.sh L41-46),云上 05:00 美股任务只采美股不跑全量 export
  (us_stock_morning_20260915_0500.log 仅美股/美债采集)。09-14(周一)21:40 打点读到的还是 26 列旧
  trades.json(FIELD 26 与 schema 26 对齐)→ 产物好(I1 合法=2663)。09-15 17:50 update_all
  (exit=0 dur=2394s)成功重写 27 列 trades.json → 09-15 21:42 打点首次读错 → 坏产物 + 打点自检 FAIL exit=1。
- 修复:dc1f1c785(2026-09-16 06:30)FIELD 补 real_buy_date(26→27 列);09-16 17:31 重跑打点
  (代码已含修复)→ I1 合法=2627 PASS。


- 出现点:export.py L1248-1252 subprocess 跑 signal_kelly_backtest.py(KELLY_BUY_NEXTDAY=0,
  --output signal_kelly_backtest_sdc.json),L1262 打 stderr[:200] → 日志只留 Traceback 前 200 字符。
- 失败窗口:09-15 21:00 backfill sdc 成功(513427 B);09-16 00:07/02:00 backfill sdc 成功;
  **09-16 16:35 backfill 首次失败**,17:05 public_fund_daily、18:19 deploy 连续失败(stderr 前 200 字符一致)。
- 与 ov-parity 无关:sdc 失败只影响 signal_kelly_backtest_sdc.json/trades_sdc(对比档),不触碰
  signal_kelly_trades.json(主档在 sdc 之前已单独成功写出 78MB);check_data_integrity 对 sdc 是 WARN 级
  (check_data_integrity.py L618/L1708),读旧文件(05:02 版)所以校验 PASS。
- 与 09-16 当日数据相关(推测,待重跑验证):失败从 16:35(当日盘中数据入 DB 后)开始,02:00 前成功。

## §3 09-15 晚间连环失败:不同源

| 时点 | 任务 | exit | 根因 | 证据 |
|---|---|---|---|---|
| 21:07/21:27 | backfill deploy | 1 | 版本一致性校验3 FAIL: app.min.js 当前 3ed0ecf9 ≠ HEAD重建 90e5bed3(工作区源脏/min 过期) | deploy_20260915_2100.log L693-698 |
| 21:15 | turnover-backfill | 143 | systemd start timeout 300s 杀(SIGTERM;4.8min 仅采集 200/5200 codes) | journalctl -u trade-turnover-backfill 21:10-21:20「start operation timed out. Terminating」 |
| 21:30→21:44 | etf-national-team | 1 | deploy 链 1.2.3 ov-parity I1/I2 FAIL(21:38 deploy 与 21:40 打点竞态,读到打点刚写的坏产物 rows=6631;21:07 校验时旧产物 rows=6657 PASS) | etf_national_team_backfill_20260915_2130.log L651-672 |
| 21:40→21:42 | overfit-monitor | 1 | 打点自检 ov-parity FAIL(自家刚产出的坏产物,同 FIELD 漂移根因) | overfit_monitor.sh L75-85 + schedule_stats「过拟合监控 21:40 exit=1 dur=160s」 |

## §4 修复建议

- 主根因已修(dc1f1c785 已进 main,09-16 17:31 重跑打点验证 I1 合法=2627 PASS):**数据层恢复即可,无需新代码**。
- 数据层确认项(运维动作,已由 17:31 重跑完成):overfit_monitor.json 当前合法数 2627 > 0,ov-parity PASS。
- B 级建议(可选,防再犯,派 implementer):
  1. load_trades 的 FIELD 与 TRADE_FIELDS 漂移是第二次同款病灶(2026-08-23 曾因 21 列错位出过一次):
     建议 overfit_monitor.py 从 signal_kelly_backtest.py import TRADE_FIELDS(单源),或加
     len(tr)!=len(FIELD) 时硬 FAIL 的断言,不再静默 continue。
  2. check_overfit_recent_parity.mjs I1 断言对「gr 全 null」场景的诊断信息可加
     「gr 全空但 w 非空 → 疑似 rating 列错位」提示,加速下次定位。
  3. deploy.sh 1.2.3 校验在打点写入窗口(21:40-21:42)撞车读新产物的竞态(21:38 案例):
     可加产物 generated_at 稳定性检查或打点写 tmp+rename 原子替换。
  4. **sdc SDC 分支补 None 兜底(本次 §2 根因,建议修)**:signal_kelly_backtest.py L689-693 在 close 回退
     open 后仍缺时补与 NDO 对称的最终兜底 `if not real_buy or real_buy <= 0: return None`(整笔剔除,
     与 NDO 语义一致),防 QDII 净值晚发布日 sdc 崩。理由:160717 类 QDII 当日净值 T+1 发布是常态,不修则每个
     有 QDII 信号的交易日 sdc 必 rc=1(16:35/17:05/18:19 三连已现)。
  5. sdc 失败目前无独立告警(仅 export 日志一行 + 前端回退默认口径):建议 sdc 连续 N 次失败
     挂 check_data_integrity WARN 升级,或 deploy 链对 sdc 新鲜度加机检(可选)。
- A 级(数据层恢复,无需代码):160717 等 74 只当日 accum_nav=None 会在 09-17 00:07 backfill 批自动补齐
  (证据:09-16 00:07/02:00 批 sdc 已成功 = 当日净值凌晨已发布;160717 前 5 个交易日 accum_nav 全有值)。

## §5 复现段

```bash
# 本地复现 FIELD 错位(只读): 对 27 列 trades.json 分别用 26/27 列 FIELD 读 rating 列
python3 - <<'PYEOF'
import json
with open('static-site/data/signal_kelly_trades.json') as f:
    data = json.load(f)
OLD_FIELD = [..., "real_buy_price", "real_current_price", "market_state",
             "market_tier", "market_tier_all", "market_tier_cyb", "rating"]  # 26 列(dc1f1c785 前)
NEW_FIELD = [..., "real_buy_price", "real_buy_date", "real_current_price", "market_state",
             "market_tier", "market_tier_all", "market_tier_cyb", "rating"]  # 27 列
quad = data["quadrants"]
old_vals, new_vals = {}, {}
for q, modes in quad.items():
    for mode, arr in (modes.items() if isinstance(modes, dict) else []):
        if mode not in ("A", "F", "G"):
            continue
        for tr in arr:
            old_vals[tr[25]] = old_vals.get(tr[25], 0) + 1
            new_vals[tr[26]] = new_vals.get(tr[26], 0) + 1
print("旧26列 rating 位置实际值 top5:", sorted(old_vals.items(), key=lambda x: -x[1])[:5])
print("新27列 rating 位置实际值:", sorted(new_vals.items(), key=lambda x: -x[1]))
PYEOF
# 实测输出(2026-09-16 本机 static-site/data/signal_kelly_trades.json, 27 列):
#   旧26列: [('牛市·主升', 29004), ('熊市·主跌', 20880), ('上升期', 17640), ('下降期', 12576), ('', 11196)]
#            → gr 合法数 = 0(= I1「合法=0 非法=0」场景, gr 守卫不设值)
#   新27列: {'low': 72336, 'mid': 17928, 'high': 1032} → gr 合法数 = 91296
```

证据锚点(云上):
- 17:05 FAIL 日志:/home/ubuntu/code/trade-data/data/logs/public_fund_daily_20260916_1700.log L262-283(rows=6631, I1 合法=0 非法=0, I2 0/0/0)
- 17:31 重跑 PASS:/home/ubuntu/code/trade-data/data/logs/overfit_monitor_launchd.log 尾部(I1 合法=2627, 17:34:19 rc=0)
- 18:19 deploy PASS:/home/ubuntu/code/trade-data/data/logs/deploy_20260916_1819.log L573(43 ok/0 fail) + L673-676(ov-parity PASS 合法=2627)
- 09-15 21:07 PASS/21:38 FAIL 对照:/home/ubuntu/code/trade-data/data/logs/deploy_20260915_2100.log L651-671(rows=6657 PASS)、deploy_20260915_2138.log L651-672(rows=6631 FAIL)
- 09-15 21:15 turnover journal:journalctl -u trade-turnover-backfill --since '2026-09-15 21:10' --until '2026-09-15 21:20'(start operation timed out. Terminating, status=15/TERM)
- 修复 commit:dc1f1c785(云上 /home/ubuntu/code/trade-data-signal git log)
- sdc 失败窗口:backfill_20260916_0007/0200.log L128 成功 vs backfill_20260916_1635.log L156 首次失败
