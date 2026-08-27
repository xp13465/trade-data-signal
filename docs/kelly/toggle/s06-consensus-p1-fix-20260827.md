# S06 共识票 P1 双修(#95 mode_votes/fallback 契约统一 + #96 X 表 fail-closed 兜底)

日期:2026-08-27 | 分支:feat/p1-audit-s06-fix | 实施者:implementer agent | 来源:v1.1.7 审计(pending-index #95/#96,用户已拍板修)

## 一、修了什么

### #95 Y 票双路径契约统一(fail-open 单一实现)
**现象**:app.js `_consensusVotesOf` 中 `mode_votes` 路径与 fallback 求交路径是两套独立实现的降亏表决器;Y 票第 8 票(S06)语义靠两条 if 链分别手写,**结构性漂移风险**(任何一边改动即产生同信号不同票数)。node 四象限实测证实现状票数逐位一致(15/15 组),但实现分叉本身即为隐患。

**修法**:新增前端表决器 `_consensusFrontVotesOf`(与后端 `app/queries.py _ai_macro_mode_votes` 同构:preset 键集求交 + bullAuxBackupStop 特判走 `_isBullStopHit` 前端 tier 补判);`_consensusVotesOf` 收敛为「mv 单源优先,缺失调表决器」,S06 第 8 票单一谓词:`!r6 || !r6.ok || mv[r6.base]` 时计 1 票(base 未知一律 fail-open=保守放行)。

### #96 X 固化表 s06 行 fail-closed 静态兜底
**现象**:旧代码 `const base = r6 && r6.ok ? r6.base : "new15"; // fail-open = new15` 注释谎称 fail-open,实际快照未就绪/加载失败/日期超覆盖期时拿 new15 静态键集过滤——filters∩new15 命中的信号被错误拦掉出 top1 候选,违反 common.js L903 降级契约(fail-open 该笔不拦)与 CONS_TIP/purpose-notes 已公示的「S06 快照不可用时该票按保留计」。无可见提示。

**修法**:删硬编码兜底,`r6.ok` 时才按当日基座票拦,base 未知该笔照常进当日候选参与排序取 top1;hoverpop 认可度行在 `_tdsS06Status().err` 非空时追加可见降级小字「· S06快照不可用(...),该票按保留计」(仅真实加载失败显示;加载中/超覆盖期为数据常态不打扰)。

### 同根因顺带根治:X 表静态行 fallback 漏 bull 特判
X 表构建的 fallback 分支(mv 缺失旧数据)`fx.some(...)` 只求交,**漏掉 bullAuxBackupStop 特判**(p9/a9/b9/c9 带 bull 键)。统一进表决器后自动补齐,旧数据下 buy_aux/buy_backup × 牛市·主升的 X kept 集从「4 键 preset 全漏拦」修正为与后端单源一致。

## 二、同类错误面清单(S06 快照消费点全家族盘点)
| 消费点 | 位置 | base-unknown 行为 | 结论 |
|---|---|---|---|
| overview 弹窗聚合 memberSetForRow | app.js ~L2019 | null=该行不拦+s6Open 可见计数 | 契约合规 |
| 首页判定链 _isAiFadeHit | app.js L4680-4682 | 不拦+_homeS06FailOpen++ 计数 | 合规(标杆) |
| 凯利模拟 per-date fade | app.js ~L3927 | f6=null 不拦+_openCnt 红字 | 合规 |
| Y 票 S06 第 8 票 | app.js(原 L4829/L4843) | 两分支均 fail-open 但双实现 | 本次统一(#95) |
| **X 表 s06 行** | app.js(原 L4893) | **new15 静态键集拦截=fail-closed** | 本次修(#96) |
| **X 表静态行 fallback** | app.js(原 L4883) | 求交但漏 bull 特判 | 本次顺带修 |
| 灰标 _hitOn 键判 | app.js L5051-5053 | f=null 不灰(放行) | 合规 |

lab.js 各消费点(L8222/L8257 等)f6/base 为 null 时均放行,合规,不在本任务文件所有权内亦无需动。

## 三、自测结果
脚本 `/tmp/test_p1s06_final.js`(node,旧实现=HEAD cecf8e6b7 逐字复刻,新实现=修复版逐字复刻):
- PASS=54:modes(ok-a9/ok-new15/out_of_range/not_loaded)× 信号形态(mv 正常/mv 缺键/旧数据×2/bull 场景)× Y+X 静态+X-s06,**非修复目标场景新旧逐位等价**(含覆盖期内 s06 行为、mode_votes 缺键 falsy=拦语义保持)。
- BUGFIX=4(预期差异,全部命中修复点):X-s06 out_of_range/not_loaded 下旧拦新放(#96 主修);X 静态 bull 场景 mv 缺失时新正确拦 p9/a9/b9/c9(bull 补齐)。
- FAIL=0。
- 另跑第一轮四象限对拍 `/tmp/test_p1s06_voting.js`:Y 两路径现状票数一致(15/15)。
- `node --check static-site/app.js` 语法 PASS。

## 四、发版建议(§5.4⑥)
S06 已是 v1.1.7 整站默认模式,本修会改变「快照加载失败/日期超覆盖期时」的 X/Y 展示计数(方向=向已公示的 fail-open 契约对齐),正常快照覆盖期内零变化,不动 AI 推荐/降亏默认组合与开关值。属 bug 修复(§23.7④),建议作为 v1.1.7 序列内修复随 merge 上线即可;若主控认为需版本标记可计 v1.1.7.x,不必新开中间版本(未动基准组合本身,测试基准定义不变)。

## 五、其他核查项
- §21 公示:CONS_TIP(app.js)与 purpose-notes.js 认可度段均已写有「S06 快照不可用时该票按保留计(fail-open)」——本次修复正是让实现符合既有公示,文案零改动;lab.js 无认可度统计展示。
- README:bug 修复、无新功能/开源引用,README 无需变更。
- 文件所有权:仅改 static-site/app.js(+本文档);common.js/lab.js 后端零改动。
- §23.11:全程无 merge/冲突事件,基于 worktree 基线 cecf8e6b7(base-fresh 已验)。

## 复现
- 脚本:/tmp/test_p1s06_final.js(依赖 node ≥18;含旧/新双实现复刻与场景矩阵;旧实现来源=git show cecf8e6b7:static-site/app.js 对应段)
- 重跑命令:`node /tmp/test_p1s06_final.js`
- 输入依赖:无外部数据(preset 键集拷贝自 common.js `_KELLY_FADE_MODE_PRESETS` 对应 7 预设/app queries.py `_AI_CONSENSUS_PRESETS`,二者同源)
- 关键口径一句话:S06 第 8 票/X-s06 行 base 未知(未加载/加载失败/超覆盖期)=fail-open 保留;base 可知=当日生效基座(a9/new15)票判定;正常快照路径行为与修复前逐位一致。
