# CORRECTIONS.md — ack_revision 2 证据订正记录

> 本文件记录 `claude-ack-20261104-recent-issues-v1.json` 由 rev1 → rev2 的两条证据订正。
> 订正性质:证据措辞收窄(推断当必然 → 实测口径 + 理论触发路径定性说明),不改变结论与任务派发。
> 订正依据:用户转述 Codex 的证据订正要求(2026-11-04)。
> 订正人:Claude 实施 agent(分支 `feat/codex-evidence-fix-20261104`)。
> 时间:2026-11-04。

## 订正 1 — F05 evidence(必然性断言收窄为实测口径)

- **文件**:`claude-ack-20261104-recent-issues-v1.json` F05 条目 `evidence` 字段。
- **原措辞**:「生产必走此路径:浏览器默认 br,CF 对 lab_sim_sh_full.json / lab_sim_sh_fusion_full.json 回 brotli 且剥掉 Content-Length ⇒ total=0」。
- **问题**:把推断当成必然(「生产必走此路径」「剥掉 Content-Length」均为推断,未实测覆盖)。
- **新措辞**:「Codex 提供一次真实响应头实测:URL https://ss.fx8.store/r2/lab/lab_sim_sh_full.json,2026-11-04 06:50:39 GMT,HTTP/2 200,content-encoding: gzip,该次实测无 Content-Length;不能据此推断 CF 必然使用 br 并剥掉该头,线上正文实际卡死尚未观测。理论触发路径=浏览器默认 br + CF 剥 Content-Length 时 total=0」。
- **依据**:用户转述 Codex 提供的实测响应头(单次样本,不能推广为必然行为)。

## 订正 2 — #331 证据(无效证据换为代码行号锚点)

- **文件**:`docs/pending-features-index.md` #331 行「已完成」证据段。
- **原措辞**:「第二份公式已收敛,`scripts/backfill_fund_nav_null_days_252.py` 已不存在」。
- **问题**:文件不存在不能证明公式已统一(逻辑不成立)。
- **新措辞**:「`scripts/backfill_fund_nav_null_days_251.py:197` 已调用 `calc_pct(...)`(import 在 `:47`),第二份 pct 公式已收敛到统一实现」。
- **依据**:用户转述 Codex 的证据订正要求;真实锚点为代码行号(import + 调用点)。

## 同批顺带收窄(非 rev2 新增订正,同一口径)

- `docs/pending-features-index.md` #369 行「现象」段原写「生产 CF br 必剥 Content-Length ⇒ total=0」,同步收窄为「该次实测无 Content-Length(2026-11-04 06:50:39 GMT,HTTP/2 200,gzip),据此不能推断 CF 必然剥该头;线上正文卡死未观测。理论触发路径=浏览器默认 br + CF 剥 Content-Length 时 total=0」。与订正 1 同口径、同依据。

## 未改动项

- `README.md` F05 摘要行不含「必然剥 / 生产必走」措辞,无需收窄。
- ack JSON 其余字段(含 S03 evidence 的 #331 引用)一律不动(用户明确「不扩大修复范围」)。
