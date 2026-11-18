-- admin/ops 每日告警量走势（2026-11-18，方案 B；依据 docs/ops 内部需求单 + 调研报告
-- /tmp/ops-alert-trend-research.md）。纯新增表，不改任何既有表/触发器/内容谓词。
--
-- 权威源 = 云上外发台账 data/alerts/alert_ledger.jsonl（group=alert，scripts/notify.py
-- 每次实际外发追加一行）。本表只是最近 90 天的**派生历史**，供管理员只读端点
-- GET /api/ops/alert-daily 画图，不参与任何告警判定或投递。
--
-- 写入端（POST /api/ops/alert-daily，只认 ingest bearer）约定：
--   * 逐日行由 scripts/schedule_monitor.sh 每轮调用 `alert_meter.py --trend` 重算后推送，
--     内容与本表一致 ⇒ 不写（96 轮/天 × 90 行必须挡住，D1 免费层写配额）。
--   * 内容不变时只对**最新一天**的行做 computed_ms 心跳（每次推送最多 1 行写），
--     故 computed_ms 的语义 = 最近一次成功重算时刻，不是每行各自的计算时刻。
--     前端据此判定数据新鲜度（>2h 标「数据可能滞后」），不显示假 0。
--   * by_tier 是规范化 JSON 文本（键排序后序列化），用于逐位比对与展示。
--
-- 保留 180 天：清理挂在既有的 */15 保留清理里（worker/ops.js opsScheduled 的 db.batch）。
-- 缺失日不落行 —— 端点向前合成连续日期并标 no_data，前端画灰柱，严禁补 0 冒充「零告警」。
--
-- 部署顺序：**先应用本迁移，再部署 worker/ops.js**。本表纯新增、旧 worker 完全不引用，
-- 先迁移是安全的；反过来（先 worker）会让 opsScheduled 的保留清理 batch 因缺表整批失败，
-- 连带 ops_watchdog 的状态推进一起停摆。回滚：先回滚 worker（旧 worker 不引用本表），
-- 再 DROP TABLE 即可，无数据迁移、无回填。
CREATE TABLE IF NOT EXISTS ops_alert_daily (
  date TEXT PRIMARY KEY,
  total INTEGER NOT NULL,
  real INTEGER NOT NULL,
  noise INTEGER NOT NULL,
  escalation INTEGER NOT NULL,
  by_tier TEXT NOT NULL,
  computed_ms INTEGER NOT NULL
);
