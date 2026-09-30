# #144 过拟合监控风险分图停更修复 — 独立复审报告

- 日期: 2026-09-30
- 被测: feat 分支 `worktree-agent-a7cbb8af4e8d8d9f0`, commit `8ab0b5f31` (5 文件 398+/21-)
- 结论: **有条件 PASS**(必改项: app.js merge 冲突需按本文档口径处理 + 一处措辞语义需拍板)

## 复现段(独立于实施者验收脚本, 全部实测)

### 1. 核心结论独立复现(必查项1)
命令: 自写 `/tmp/overfit144_repro.py` + 云上真实输入(09-29 21:40 产物 accuracy.rolling win60)在本机跑 OLD vs NEW `_derive_daily_series` 逐行 diff。
实测:
- 输入: 回测 200 点末 20260922 / 实盘 200 点末 20260928
- OLD 序列 200 点末点 **20260922**; NEW 序列 209 点末点 **20260928**(末点推进 6 天)
- 共有日期逐位漂移 **0**; OLD 侧被丢日期 **0**(老点零漂移)
- NEW 独有 9 日(20251120/20251209/20260102/20260122/20260218/20260501/20260504/20260619/20260928)全部 risk_score/level/win_rate=null, 非 40/0/NaN — 「缺失侧留空不造假」成立
- 「回测有、实盘缺 -> 中性 40」老口径: 真实输入 9 日, 与 OLD 逐位一致

### 2. 前后端第二份实现对账(必查项2, §5.4⑦)
命令: 同一输入(/tmp/parity_real_input.json)分别喂 后端 `_derive_daily_series`(feat 版) 与 前端 `_ovDeriveDaily`(节点逐字复刻, 含 half-even 舍入), 逐位对账。
实测: **backend len=209 = frontend len=209, 漂移数=0**
- 注: 前端 `_ovDeriveDaily` 的 btMap 不过滤 win_rate=null 而后端 btw_map 跳过 — 理论漂移点, 但 rolling_win_rates 分桶 n=0 即 continue, 实际永不产出 null win_rate, 零实际影响(已核实 L1124 continue 分支)。
- `check_overfit_recent_parity.mjs` 部署校验链从 app.js 源码 sliceDecl 动态提取 `_ovDeriveDaily`(非第二份硬编码), 自动跟随新逻辑; F 抽查期望值 [60,22,30,85,10,40] 与 #144 逻辑兼容(act 缺->40 老口径未动)。PASS

### 3. §23.7 冻结范围(必查项3)
实测: 上述对账即冻结证明 —「有回测对照」的 200 老点数值逐位不变; 仅「实盘有、回测缺」9 日新增 null 记录。边界未越。

### 4. 生效链路(必查项4)
- `overfit_monitor.py` 由 `overfit_monitor.sh` 包装, 云上 timer `trade-overfit-monitor.timer` **交易日 Mon-Fri 21:40**(已 ssh 云上核实, 下次 2026-09-30 21:40)
- 产物写 `${REPO}/static-site/data/overfit_monitor.json` + ext(云上 /home/ubuntu/code/trade-data, scripts 为 symlink -> trade-data-signal git 树)
- 上传: deploy.sh 链 upload-data-large(R2, overfit_monitor 前缀) → CF
- **merge 后生效时点**: main-merge.sh push main 后**自动 ssh 云上 git pull**(机制 10, L443-463)→ 云上代码即新; **下一个交易日 21:40 timer 自动重算产物**; 前端 app.js 版本串由 main-merge.sh 统一 bump + build_min, 随 deploy 上线
- **结论: 用户最快在 merge 后下一个交易日 21:40 后看到末点推进**(若当日晚 22:00 前有 deploy 链; 无则次日 deploy)
- 实施者「产物只在 /tmp, 未碰线上」已核实: diff 5 文件无产物文件; 云上产物 09-29 21:40 未变

### 5. §21 公示(必查项5)
- diff 证明公式段(dev 分段映射 max(10,25-..)/35-.. /55-.. / min(95,70+..)、40 中性、30/60 level 阈值)在 diff 中**零 +/- 行** — 公式一行未动 PASS
- 新增尾注「末端N日无回测对照, 风险分不适用」与 help 弹窗既有措辞(L1683/1693/1698「无回测对照、风险分不适用」「仅实盘实际、无回测对照」)同款, 不冲突 PASS

### 6. 举一反三穷举(必查项6)
- accuracy 图 `_overfitAccSeries` 已一并改(并集+null) ✓
- 全仓 grep: daily 序列唯一生产端=`_derive_daily_series`(调用点 L1519/1617/1620/1626/1635), 唯一消费端=前端 `_overfitRiskSeries`/`_ovDeriveDaily`(+部署校验 mjs 动态提取); `_overfitAccSeries` 唯一调用 `_renderOverfitAcc`; docs/ops/verify_r2skip_fix.py 仅日志语义引用
- 同款「单侧驱动」: #139 reviewer 已标情绪分叠加指数(9061)/`_overfitRiskSeries`; #144 修了后者, 9061 是**历史图单序列**非双序列对照, 非同类根因, 不适用本次修法(已核实 9061 区域为 tier 四档图单序列)
- **遗漏一处: main 上 #139(a8ec330e0) 已修 `_overfitAccSeries` 前端读法(并集+null), #144 又改同一函数** — 两边语义等价但 merge 冲突(见必查项9)

### 7. 回归三组维度(必查项7)
命令: 云上 by_signal 6 种 + by_grade 3 种 rolling win60 各跑 OLD vs NEW 逐位对账。
实测: **9 维度总漂移 = 0**; 各维度末点均推进(buy 09-18→09-22, buy_aux 09-22→09-28, buy_special 09-08→09-28, grade/low 09-22→09-28 等); sell/sell_stop_loss 回测空 -> 空序列(保持「无回测对照」空态语义); grade/high 从 66 点扩到 208(并集新增实盘独有日)且老点不变。

### 8. §0.2/§15 常规(必查项8)
- 改动面 5 文件与自述一致, 无越界(未碰 pick_repo/guard_deploy_source_tree/REPO; #138 地盘零 diff)
- `bash -n overfit_monitor.sh` PASS; `python3 -m py_compile overfit_monitor.py` PASS; 多字节(中文注释)正常 UTF-8
- commit trailer 合规(Co-Authored-By + 详细根因/自验)
- 前端未自行 bump(由 main-merge.sh 机制 C 统一处理) ✓

### 9. 合并风险(必查项9)
实测(临时 detached worktree, 未动任何分支):
```
merge-base main 8ab0b5f31 = 4e99c2d6d
git merge-tree --write-tree main 8ab0b5f31  → exit=1
CONFLICT (content): static-site/app.js
```
- 唯一冲突文件 = **static-site/app.js**(`_overfitAccSeries` 函数, 约 L1767-1815); overfit_monitor.py 自动合并无冲突
- **冲突根因**: main 已含 #139 的 a8ec330e0(09-30 14:55, 前端读法修 accuracy 图并集+null 桥接), #144 分支基于更早 base(4e99c2d6d, 不含 a8ec330e0)且又改了同一函数
- **两边语义等价**(均为并集+缺失侧 null; btEmpty 时 #139 backtest 全 null 数组 vs #144 backtest 空数组, 渲染 hasBt=false 均单曲线) — 冲突解决取任一边均可,**但必须保留并集+null 语义**, 禁止退回旧的单侧驱动/整体丢弃; 若取 #144 版需保留 `connectNulls` 桥接行为
- 另注意: #144 版 `_overfitAccSeries` 的 btEmpty 分支(单曲线)与 #139 版行为差异: #139 btEmpty 时 backtest 数组=全 null(长度与 dates 相同)而 #144 为 [] — 前端 `_renderOverfitAcc` 的 `hasBt = !btEmpty && backtest.length > 0` 两者均为 false, 渲染等价

## 低分项(<80)已滤
- 2 项: 前后端 null-win_rate btMap 理论漂移(实际不可达); 9061 情绪分叠加指数疑似同款(实为非同类单序列图)

## 必改项
1. **app.js merge 冲突**(§23.11 不静默): 主控 merge 前人工解决 `_overfitAccSeries`, 保留并集+null 语义, 取 #139 或 #144 版皆可; 解决后必须跑 build_min + §24⑤ 哈希校验
2. **一处措辞语义冗余(非阻断, 建议拍板)**: `_renderOverfitRisk` 全 null 分支 `isSell ? "无回测对照..." : "无回测对照..."` 三元两侧完全相同(isSell 已无区分度), 建议简化为单文案; 行为无 bug 但代码冗余(over_engineering: action=simplify, saves_lines≈2)
