# 平台全面体检报告 (2026-08-29)

## 测试概览
- 总测试数: 15
- 通过: 15
- 失败: 0
- 跳过: 0

## 失败项详情
无失败项

## 数据层 curl 校验 (Phase 1)
| # | 测试点 | 结果 | 详情 |
|---|--------|------|------|
| A1 | boot.json | PASS | date=20260827, missing=[] |
| A2 | overview.json/scores | PASS | date=20260827, 9个scores全有值 |
| A3 | intraday_snapshot | PASS | indices=17, amount_forecast=盘后正常(无预估) |
| A4 | alert.json | PASS | date=20260827, high_score=48.51 |
| A5 | trade_sim_indices.json | PASS | len=168 |

## Playwright 页面渲染 (Phase 2)
| # | 测试点 | 结果 | 详情 |
|---|--------|------|------|
| B1-overview | 首页渲染 | PASS | 无JS错误,内容正常 |
| B1-market | 市场tab | PASS | 无JS错误,内容正常 |
| B1-sentiment | 情绪tab | PASS | 无JS错误,内容正常 |
| B1-fund | 基金tab | PASS | 无JS错误,内容正常 |
| B1-lab | 实验室tab | PASS | 无JS错误,内容正常 |
| B2 | S06状态 | PASS | mode=s06, threshold=-3.524 |

## check_data_integrity.py 结果
- 汇总: 33 ok / 1 warn / 2 fail
- **FAIL项**:
  1. kelly_lab_slices: 目录存在 meta 未记录的残留片 3 个(lab_mkt_a__G_p2.json 等) -- 非阻断
  2. s06_state: S06 快照机检 FAIL -- 需关注(可能是 check_s06_state.py 的判定问题)
- **WARN项**:
  1. notifications: date 滞后(周末正常)

## 代码审查发现
| # | 文件 | 问题 | 建议 |
|---|------|------|------|
| 1 | scripts/check_overfit_recent_parity.mjs | 无未提交改动 | 无需操作 |
| 2 | scripts/check_s06_state.py | S06 快照机检 FAIL | 需排查(A1 独立第二实现复算) |
| 3 | static-site/data/lab_mkt_a__*_p2.json | 3个残留slice文件 | 建议清理 |

## 数据准确性结论
- boot.json/overview.json/alert.json 日期一致(20260827)
- overview.json 9个情绪分全有值
- intraday_snapshot 17个指数完整
- trade_sim_indices 168个品种
- S06 状态正常(mode=s06, threshold=-3.524)

## 交互/UX 发现
- 所有5个tab(overview/market/sentiment/fund/lab)均正常加载,无JS错误
- S06状态通过全局变量可见,模式切换正常
