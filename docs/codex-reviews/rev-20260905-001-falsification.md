# codex rev-20260905-001 报告 P1 证伪评估

> 主控按 §0 验收铁律(外部评审结论必须先证据核验再采信)对 codex 外审 rev-20260905-001
> 的 2×P1+1×P2 逐点核实,结论:**2 处 P1 全部不成立(误报),1 处 P2 属实但非 bug**。
> 本档记录证据链,供 codex 反查、防同类幻觉复发。原始报告:`/tmp/codex-reports/rev-20260905-001.json`
> (8/21 假跌修复批次 base 765504706..head 5b4d8085a 抽审,verdict=FAIL)。

## 逐点核实

### P1-1 commit 69e41d9cb 时 app.min.js 未 rebuild — 不成立 ❌
- **codex 声称**:`git diff 765504706..5b4d8085a -- static-site/app.min.js` 无差异、两 blob SHA 相同
  (761b3d579),「该 commit 边界 app.min.js 未同步 rebuild,会部署残缺版」。
- **证据(实测)**:
  - `git ls-tree 765504706 -- static-site/app.min.js` → **b9659707e**;`git ls-tree 5b4d8085a` → **761b3d579**;
    **两个 blob SHA 明显不同**(报告自己的 verifier 命令跑出来就是这个结果,观察栏却写「相同」);
  - head 5b4d8085a 的 app.min.js 内容含 `mvByCode`×3、`较前日 nav`、`卖出离场`、`留存持仓`(全量 key 命中);
    base 765504706 的 app.min.js **零命中**(无任何新逻辑)→ rebuild 确实执行了,新旧内容分得清清楚楚;
  - 磁盘当前文件 hash=761b3d579 = head blob = 3 站线上 curl 实测 hash §0 三查(线上 app.min.js 含「较前日 nav」「卖出离场」);
  - 版本串 v20260905-a540 在 main-merge commit 5b4d8085a 统一 bump(机制 C),min 的同 commit 重建已闭环。
- **判定**:app.min.js 已随 main-merge 正确 rebuild,线上正确。「未 rebuild」无事实依据。

### P1-2 净资产图 series「只剩 1 条红线,蓝虚线被移除,headEl title 误导」 — 不成立 ❌
- **codex 声称**:head series 数组只有 1 个元素,蓝虚线(持仓日涨跌)被完全移除,但 headEl title 仍写
  「副线=持仓市值」→ 语义混淆。
- **证据(实测)**:
  - head 净资产图 `series` 有 **2 个元素**:series[0]=红线总资产(L5339)+ series[1]=蓝虚线持仓市值
    mvSeries(L5349-5351,`color:"#409eff", dash:"4 4"`);headEl title(L5426)写「副线=持仓市值」,
    与 series[1] **名实相符**;
  - 「蓝虚线被移除」的对比参照 = base 765504706(v1.1.15 的「副线=持仓日涨跌%」)。这是 **2026-09-05 用户拍板
    方案 A 的设计变更**(TASKS 记录:「②蓝线曲线口径=方案A 改持仓市值(mv)口径(名实相符)」),
    不是缺陷;
  - **verifier 用 base 行号 L5265-5285 去 head 上 grep**(L5265 在 head 里早已是 tipFn 不同区域),
    行号漂移导致漏看 series[1],是典型「拿旧版行号匹配新 code」幻觉。
- **判定**:series=2 条、title 与副线一致,「移除/误导」无事实依据。

### P2-1 tooltip 市值精度(mv round 2 位 vs mvByCode 完整精度) — **属实,非 bug**
- **事实**:`_simNetassetCurve` push 的 `mv: Math.round(mv*100)/100`(展示值 round 到分),
  而 `mvByCode` 保留完整精度用于 navChg 加权计算;tooltip `_blueMain` 显示 p.mv(round 版)。
- **评估**:两值量级同源,极限差 ¥0.01,属「展示舍入 vs 计算精度」的常规设计取舍,不影响正确性。
  外审自己标注 linkage=uncertain、实务影响小。**不修**(如需严格同源可后续把 _blueMain 改用 numSum,排期外)。
- **判定**:属实但非缺陷,列为技术债不阻塞。

## 结论

| 项 | codex 结论 | 实际 | 判定 |
|---|---|---|---|
| P1-1 app.min.js 未 rebuild | FAIL | base b9659707e vs head 761b3d579 明显不同,head 含全部新逻辑,线上=磁盘=head | 误报 |
| P1-2 蓝虚线被移除/title 误导 | FAIL | series 有 2 条,title 与副线(持仓市值)一致,变更=用户 09-05 拍板方案 A | 误报 |
| P2-1 tooltip 精度 | PARTIAL | 展示 round 与计算全精度,极限差 ¥0.01,非 bug | 属实·技术债 |

**处置**:外审 FAIL 的 2 个 P1 全部误报(v1.1.15 批次净资产曲线修复 `5b4d8085a` 指向的
base 765504706..head 5b4d8085a 无需因外审返工),P2 技术债登记不阻塞。netasset UI 三处调整
(feat/netasset-modal-ui f3dfe818b,用户 09-05 口头需求)为外审 base 之后的**新批次**,走内审
reviewer + §0 三查后随 v1.1.16 tag 一并上线,不在本批次外审范围内。

**根因反思**:本次与 rev-20260903-002(3/3 误报)同病——codex 用**固定行号 grep 漂移**
(拿 base 行号匹配 head 代码)、verifier 命令实测结果与观察栏结论**自相矛盾**。
外部评审结论必须经主控逐条证据核验后才采信,不直接照单全收(§0 验收铁律 + §23.7⑤ 上报用户)。
连续两轮外审均出现 P1 级幻觉,后续外审报告消化时对"行号/文件内容/对比参照"类断言默认先验证据。