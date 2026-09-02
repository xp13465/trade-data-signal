# S06 快照「基座未识别」生产事故根治报告(2026-09-02)

## 现象(用户报告)
lab 凯利回测 S06 模式出现 **3972 笔 trades 无法读取快照数据**(快照行缺失 / snapshot not ready / 长度不足),收益与「完整过滤」口径明显不一致。

## 诊断(数据说话,不靠猜测)
- 真实 trades 去重唯一笔(`_kellyBaseKey` = signal_date|index_id|signal|buy_date|etf_code)= **7584**。
- 覆盖范围内缺行交易日清单:不存在覆盖期内缺行(现网快照覆盖 2014-11-14 起,逐日有行)。
- 3972 笔构成 = 触发 `bad_mode` 的交易日信号:那些日子快照 `effective_mode` 不是前端接受的 a9/new14。
- 生成器为何从 20141114 开始:`gen_kelly_mode_s06_state.py` 的 coverage_start = csi1000∩hs300 在 ret20 下的首个交集日(csi1000 数据自 2014-10-17 起,ret20 后首个有效日 = 2014-11-14)。csi1000 在 20141114 前无有效 ret20,非数据丢失。

## 根因(单句)
**错配窗口**:用户报告时线上是「换基座前的旧快照(effective_mode='new15')+ 新前端(只验证 a9/new14)」——旧快照的 new15 行对前端属「基座未识别(bad_mode)」,旧前端对 bad_mode 一律 fail-open 裸放行 → 该日全部信号不过滤进池,3972 笔收益口径虚高且与完整过滤不一致。

## 修复方案(根因修,非逐文件补丁)
单一事实源在 **common.js `_tdsS06BaseForDate`**:bad_mode 不再 fail-open,改为
- 快照记录的 legacy 基座(如 new15)在 `_KELLY_FADE_MODE_PRESETS` 有预设 → 返回 `{ok:true, base:legacy, reason:"bad_mode_fallback"}` 按该基座键集真过滤;
- 无预设 → 返回 `{ok:true, base:off_base, reason:"bad_mode_fallback"}` 按快照兜底基座过滤。

所有消费点只认 `ok:false`(not_loaded/load_err/no_row)才 fail-open,`bad_mode_fallback` 与 `out_of_range_fallback` 同待遇=真过滤+轻标注计数。

## 验证数据(脚本:scripts/s06-badmode-verify.mjs,切片真实 common.js + 真实 trades 全量)
| 场景 | Open(fail-open) | bad_mode | out_of_range | normal |
|---|---|---|---|---|
| 现网快照(new14) | 0 | 0 | 110 | 7474 |
| 旧快照(new15)+修复前语义 | **3972** | 3972 | 110 | 3502 |
| 旧快照(new15)+修复后语义 | **0** | 3972 | 110 | 3502 |

- ① 复现 3972:PASS(旧快照+旧语义 Open=3972,与用户报告逐位一致)
- ② 修复后 Open 归零:PASS
- 修复后 FallbackSet 轻标注 = 4082(3972 bad_mode + 110 out_of_range)
- **现网快照下 bad_mode=0 → 修复对现网零影响**(现网快照本就是 new14)

## 收益影响(同一旧快照 new15 下,修复前 bad_mode→fail-open vs 修复后 bad_mode→真过滤,全周期 all,净利元)
| mode | 修复前 | 修复后 | Δ |
|---|---|---|---|
| A | 105,455 | 159,003 | +53,548 |
| B | 42,828 | 91,018 | +48,190 |
| C | 61,483 | 111,250 | +49,767 |
| D | 80,112 | 129,235 | +49,123 |
| E | 46,358 | 73,274 | +26,916 |
| F | 121,570 | 193,822 | +72,252 |
| J | 164,536 | 227,953 | +63,417 |
| **G** | 484,137 | 350,957 | **-133,180** |
| **I** | 386,961 | 341,182 | **-45,779** |
| H | 174,791 | 204,809 | +30,018 |

- 短线模式(A-F/J)净利普遍大幅提升:修复前 3972 笔错配单 fail-open 把大量亏损单放进池,修复后按 legacy 键集正确过滤。
- **G/I 下降是「错配单被正确过滤」的必然结果,非 bug(诚实标注)**:修复前 G 484k / I 387k 含 3972 笔错配单的虚高成分(部分错配单在信号卖出模式下净贡献为正),修复后口径才可信。
- 对照:new14 / a9 两基座在修复前后**逐位相同(Δ=0)**——修复只作用于 S06 的 bad_mode 路径,静态基座零影响。

## §23.2 同类错误面清单(全站 S06 消费点逐项核对 bad_mode 处理)
| 消费点 | 位置 | bad_mode 处理 | 状态 |
|---|---|---|---|
| 单源解析层 | common.js `_tdsS06BaseForDate` | 根因修复:bad_mode→legacy 预设/off_base 真过滤 | ✅ 根因点 |
| 过滤构造 | common.js `_tdsS06FiltersForDate`/`_tdsS06KeysForDate` | bad_mode 走 legacy 预设键集 | ✅ 自动受益 |
| 状态/警示 | common.js `_tdsS06Status` | 返回 onBaseId/offBaseId | ✅ |
| 凯利主谓词 | lab.js `passesFade` | bad_mode→FallbackSet+真过滤 | ✅ 根因点 |
| 凯利 NoBull 谓词 | lab.js `passesFadeNoBull` | bad_mode→FallbackSet+真过滤 | ✅ 根因点 |
| 凯利警示文案 | lab.js `_s6warn` | 已含「基座未识别」+准确兜底描述 | ✅ 本次同步 |
| 凯利公示 | lab.js `fadeModeTitle` | 已同步「快照记录基座键集/防守兜底 NEW14」 | ✅ 本次同步 |
| 弹窗 NoBull 分支 | lab.js `_pcFadeFn`(s06NoBull) | b2.ok=true→legacy 过滤,仅 ok:false fail-open | ✅ 自动受益 |
| 弹窗普通分支 | lab.js `_pcFadeFn`(普通) | f6 非空→legacy 过滤 | ✅ 自动受益 |
| overfit 链 | app.js `memberSetForRow` | bad_mode→从预设直取 legacy 组集 | ✅ |
| 模拟回测弹窗 | app.js `_fbCnt` | bad_mode 也计轻标注(原只计 out_of_range) | ✅ 本次同步 |
| 首页 AI 降亏 | app.js `_isAiFadeHit`+`_mountHomeS06State` | bad_mode 计 fallback+警示含「基座未知」 | ✅ |
| 首页 `_aiOnS06` | app.js | 基于 `_tdsS06Status` on/offBaseId | ✅ |
| 首页共识表决器 | app.js `_consensusVotesFor`/`_fixedKeptMapByMode["s06"]` | bad_mode→`mv[legacy]=falsy`→第 8 票拦(**fail-closed 保守方向,与事故 fail-open 相反,非同源**);首页共识 top1 已发布冻结(§23.7),不改 | ⚠️ 差异说明,不动 |

## §21 算法公示同步清单
- common.js `_tdsS06Tooltip`:讲 S06 机制本身,不涉降级语义,确认无需改
- lab.js warning 文案 + lab.js `fadeModeTitle`:已同步「快照记录基座键集/防守兜底 NEW14」准确表述
- app.js 首页警示 + AI降亏下拉 tooltip:已含「超覆盖期/基座未识别→真过滤」
- purpose-notes.js `lab.sigkelly` 公示:已补「基座未识别(如换基座前旧快照)按基座预设键集或 off_base 真过滤」

## 复现
- 计数验证脚本:`docs/kelly/analysis/scripts/s06-badmode-verify.mjs`
  - 输入依赖:`static-site/data/signal_kelly_trades.json` + `static-site/data/kelly_mode_s06_state.json` + `static-site/common.js`(切片真实逻辑)
  - 重跑命令:`node docs/kelly/analysis/scripts/s06-badmode-verify.mjs`
  - 口径:对全部真实 trades 去重唯一笔,用切片 `_tdsS06BaseForDate` 判定每笔 Open/fail-open/bad_mode/out_of_range 归属;旧快照模拟 = 现网快照 `effective_mode` new14→new15 + off_base→new15;旧语义模拟 = bad_mode→ok:false(触发消费点 fail-open)。
- 收益对比复现:`/tmp/repro-sim-old.mjs`(trade-method-final-repro.mjs 的 SIM_OLD 变体,临时验证用)
  - `SIM_OLD=1` = 旧快照+旧语义(修复前);`SIM_NEW_ON_OLD=1` = 旧快照+新语义(修复后,同快照纯语义对比);默认(无 env)= 现网快照+新语义。
  - 数据截止:2026-09-02(现网快照 v1.1.7 S06 off_base=new14)。
  - 关键口径:每笔 1 万、费后、GIH 按 G=P@10万/H=A@5万/I=P@9万,全周期 all 净利。
