# 公募基金日更 内外层成对预算（止血）RCA — 2026-10-29（#352）

> **性质**：止血——只把「超时预算」改对，不治本（export 提速另开待办）。
> **结论**：外层 `TimeoutStartSec` 900 → 1860s；内层按阶段给预算（采集 300 / export 600 / nav_bucket 300 既有）；`deploy.sh` 的 `EXPORT_TIMEOUT` 默认 0（不限时），只有公募日更这条调用链给 600s，其它调用方（17:50 全量链等）行为逐位不变。

## 1. 现象（实测）

`trade-public-fund-daily.service`（OnCalendar 16:20 / 17:00，同一个 service）最近 10 个交易日每次运行时长：

| 档位 | 实测区间 | 说明 |
|---|---|---|
| 16:20 档 | **845–890s** | 今天 2026-10-29 实测 **890.1s**，外层上限 900s ⇒ **只剩约 9.9s 余量** |
| 17:00 档 | 750–803s | 同 service，同样贴着上限跑 |

历史上该 unit 已被 systemd 杀掉过 **8 次**（`journalctl` 里失败样本时长≈900s=撞上限）。

## 2. 890s 花在哪（阶段拆解，今天 16:20 档）

| 阶段 | 耗时 | 占比 |
|---|---|---|
| `deploy.sh` 内 `export.py --incremental` | **463s** | **52%** |
| 采集 pipeline（`app.collector.public_fund daily`） | 161.6s | 18% |
| deploy 段 1 其余（R2 上传 / rsync / 校验） | ~181s | 20% |
| nav_bucket 净值桶刷新（既有 300s 预算） | ~70s | 8% |
| 其余（段 2 git 等） | ~15s | 2% |

⇒ **主因不是网络，是 export 慢**。事故面 = 外层 systemd 单点兜底 900s，内层各阶段无预算（除 nav_bucket）。
⇒ 今天 890.1s vs 900s：只要再慢 10s 就会被杀，且**被杀时脚本自己的「结束」行/告警都发不出**（整进程被杀）。

## 3. 根因（可复核锚点）

- 增量失效判据读的是**源文件 mtime 指纹** + 表日期/manifest：
  - `static-site/export.py:913`（`_code_fingerprint`，其中 `:920` 取 `Path(_p).stat().st_mtime`）
  - `static-site/export.py:1143-1145`（增量模式：指纹变了 ⇒ 本次强制全量重算）
- 「部署中途 cp/同步数据文件」会把源文件 mtime 顶新 ⇒ 指纹变化 ⇒ 下一次 `--incremental` 退化成全量重算（463s 的主要来源）。**治本 = export 提速 / 指纹口径改稳定内容哈希，另开任务。**

## 4. 更正上一轮的错误结论（统计被污染，问题被搁置 7 天）

`docs/ops/timeout-startsec-plan-20261022.md:233-234` 曾判「成功样本 P99 仅 1.1s，调大只会让它卡更久，先查锁竞争」。
**该结论错误**：那 4 个「成功样本」是**周末/非交易日跳过**（同款实测 2.3–2.9s / 日志 228 字节），被误当成正常路径样本，污染了统计 ⇒ 真实工作日是 845–890s 的正常慢，不是「卡住等锁」。
⇒ 已在原文档追加更正批注（不改原文）。

## 5. 本次改动（预算表 + 四副本）

**预算表（内外层成对，L55）**

| 层 / 段 | 值 | 依据 |
|---|---|---|
| 外层 `TimeoutStartSec` | **1860s** | 实测 max 900.2s × 2 = 1800.4 → 向上取 60 倍数 = 1860 |
| 内层 采集 pipeline | **300s** | 实测 161.6s / 24.4s，余量约 2x |
| 内层 export（`export.py --incremental`） | **600s** | 实测 463s，余量约 1.3x（只对公募日更调用链生效） |
| 内层 nav_bucket 刷新 | 300s（既有） | #278 既有预算，本次不动 |
| 等 deploy 锁（调用侧） | 420s | 只覆盖公募日更这一次；`deploy.sh` 全局默认 3600 不动 |

**最坏路径复算**：300 + 600 + 300 + 其余≈195 = **1395s < 1860s**（留 465s 梯度，外层恒大于内层，避免「外杀内层」）。

**代码改动**

- `scripts/deploy.sh`：新增 `run_with_budget`（与既有 `git_fetch_timeout` 同一套 background+sleep+kill 原生实现，mac 无 coreutils `timeout`）；
  export 处 `EXPORT_TIMEOUT` 默认 0 = 不限时 = 改动前逐位不变，>0 才包裹；超时返回 124，日志点明「超预算 Ns 被杀」，并**按失败终止**（不当成功）。
- `scripts/public_fund_daily.sh`：采集 `run_to 300`（云上即 `timeout 300`，与 `s06_snapshot.sh` 同惯用法）；deploy 调用处 `EXPORT_TIMEOUT=600 GIT_LOCK_TIMEOUT=420`。
- 测试：`scripts/tests/test_pf_budget_20261029.py`（默认零变化 / 2s 预算被杀 rc=124 / 接线值 / 全局默认 3600 不动，含变异判别力）。

**四副本同步（L55，改预算必须四处同批对齐）**

| # | 副本 | 路径 | 状态 |
|---|---|---|---|
| 1 | 代码 `.sh` | `scripts/public_fund_daily.sh` + `scripts/deploy.sh`（内层预算） | ✅ 本次已改 |
| 2 | unit 生成源 doc | `docs/deploy/systemd-units-20260912.md:1176-1177` | ✅ 本次已改 1860 |
| 3 | 云上快照 txt | `docs/deploy/systemd-units-cloud-snapshot.txt:537` | ⏳ **待云上 unit 改完后从云上重 dump 刷新**（该文件语义=云上真实状态固化快照，先改=文件撒谎 + 云上巡检 `--check-snapshot` 报漂移） |
| 4 | 云上真实 unit | `/etc/systemd/system/trade-public-fund-daily.service`（手动管理，git pull 不更新） | ⏳ 待执行（合并后另派） |

⚠ **已知冲突（须主控处置）**：`scripts/main-merge.sh` 第 7.8 步机检 `systemd_timeout_gradient_audit.py --check-doc` 比对「doc §2 == 云上快照」，副本 2 改了 1860、副本 3 仍是 900 ⇒ **该门会 FAIL 阻断 merge**。正确顺序：先在云上改 unit（+ dump 刷新快照）→ 再 merge；或由主控拍板「快照同批预改（接受云上巡检窗口内报一次漂移）」。

**核生效值**

- `systemctl show trade-public-fund-daily -p TimeoutStartUSec`（应 = 1860s，不是文件字面量）
- `python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc`（doc == 快照）
- 云上：`python3 scripts/systemd_timeout_gradient_audit.py --units-dir /etc/systemd/system --snapshot docs/deploy/systemd-units-cloud-snapshot.txt --check-snapshot`（快照 == 云上）

## 6. 时点影响（§14）

- 16:20 档最长到 **16:51**（早于 17:00 档 9min），17:00 档最长到 **17:31**（早于 17:50 全量链 19min）⇒ 调大预算不会让两次运行互相踩，也不会撞 17:50。
- 改云上 unit 需 `systemctl daemon-reload`；建议在当日两档跑完之后（17:35 后至次日 16:00 前）操作，不影响当天已在跑的那次。

## 7. 待办

1. **云上 unit 改 1860 + 刷新云上快照**（合并后另派，需 `daemon-reload`，按 §14 时点）。
2. **治本：export 提速**（463s/52%）——指纹口径（mtime → 稳定内容哈希）+ 增量粒度，另开调研。
3. 观察锚点：改动上线后看 16:20 / 17:00 两档的 `journalctl` 时长与退出码，连续 3 个交易日无 `timeout` 被杀即收口。