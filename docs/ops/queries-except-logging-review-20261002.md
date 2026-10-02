# app/queries.py 4 处静默 except 补日志 Review 报告(2026-10-02)

- reviewer:独立复验,未参与实施;只读审查,未改任何业务代码
- 审查对象:分支 `feat/queries-except-logging-20261002` @ `ae126cd72`(未合 main)
- base = `8723a64a2`(origin/main);worktree 独立验证,临时探针脚本跑完已删
- 方法:全 diff numstat + 逐行 diff + 独立 monkeypatch 实测 + merge-tree 模拟合并 + 前端消费点核对 + 复现段命令复跑

## 总体结论:PASS(9 项全过,2 低分项见末尾)

---

## ① 全 diff 无夹带 — PASS
- `git diff --numstat 8723a64a2..ae126cd72` = `app/queries.py 20 0` / `docs/ops/queries-except-audit-20261002.md 128 0`。
- **「仅 20 行纯增、0 删除」自述属实**,无其他文件改动。

## ② 4 处降级语义逐位未变 — PASS
- diff 每处均为 `except Exception:` 后**纯插入** `logger.exception(...)` + 原 `pass` 保留;无 return/continue/变量赋值/控制流改动。
- **独立 monkeypatch 实测**(worktree 内、跑完已删):patch `app.collector.etf_national_team.get_conn` 抛 RuntimeError → `_enrich_etfs_since_return`:
  - stderr 真实输出 `走势卡 ETF 至今盈亏计算失败(...)` 全文 + Traceback(指向 worktree `app/queries.py:420` `_etf_get_conn()`);
  - **函数尾部跑完未崩**,pass 降级语义保持。

## ③ logger 定义核实 + 两分支撞车分析 — PASS(重点项)
- base `8723a64a2` 的 `app/queries.py` **本来就有** `import logging`(:15)+ `logger = logging.getLogger(__name__)`(:30),实施「复用已有、未新增 import」属实。
- **冰点分支真相**:补丁 commit `9e7ec2893`(冰点日志留痕)基于**旧父版** `d8cbea1d7`(该版无 import),故其 diff 加了 `import logging` + `logger` 定义;但 `9e7ec2893` **已是 main 祖先**(`git merge-base --is-ancestor` YES),main `8723a64a2` 已含冰点 `logger.exception`(:1585)。
- 冰点分支 HEAD `101b521ab` 的 `app/queries.py` 与 main `8723a64a2` **零差异**(`git diff --stat` 空)= 冰点分支对 queries.py 已无未合并改动。
- `git merge-tree 8723a64a2 ae126cd72 101b521ab`:无 conflict 关键字;合并后 queries.py 仅 1 份 import logging/logger(worktree 当前文件 15/30 行唯一)。
- **结论:两分支在 queries.py 上无交集,合 main 不会冲突、不会重复 logger 定义。合并顺序无强约束**(冰点分支只改前端 app.js+冒烟脚本,本分支只改后端 queries.py,正交;任意顺序安全)。

## ④ 4 处「明确不动」未被误改 — PASS
- 新文件 9 处 except 位置 = `428 / 1074 / 1447 / 1593 / 1745 / 1824 / 1848 / 1866 / 1881`(各对应 base 的 `428/1069/1442/1583/1735/1814/1838/1856/1866`,偏移 = 本次插入行数)。
- 逐处确认仍为静默降级,未触碰:
  - :1074 T1 新键标注 — `except Exception: pass  # 新键标注失败不阻断...`(带注释声明)✓
  - :1745 `load_latest_snapshot` — `except Exception: pass` ✓
  - :1824 `maybe_override_heatmap` — `except Exception: pass` ✓
  - :1848 `etf_date MAX(date)` — `except Exception: pass`(有 `updated_at[:10]` fallback)✓

## ⑤ 日志文案可用性 — PASS
4 条均含「展示位 + 退化成什么样 + 可能原因」三要素,且每条带「请检查 <具体文件/表>」,运维可一眼定位:
- 428 走势卡 ETF 盈亏 / etf-tag-pnl 不生成 / etf_national_team.db
- 1442 信号卡 ETF 盈亏 / 字段留空 / etf_national_team.db
- 1856 时效横幅 / 三 date 缺失退默认文案 / futures.json + sentiment.db index_daily
- 1866 汪汪队卡片 / 置 None 卡片空白 / etf_national_team.db

## ⑥ 实施自测可信度 — PASS(独立重跑)
- **symlink 事实成立**:`ls -ld /Users/linhuichen/code/trade-data/app` = `lrwxr-xr-x ... -> /Users/linhuichen/code/trade/app`(trade-data 与 trade 平级,非子目录;doc 描述属实)。
- 独立复跑(worktree cwd):`MODULE_FILE = .../agent-a705582e7ba802b26/app/queries.py`(非主 checkout)→ 命中正确路径,symlink 坑已被规避。
- py_compile PASS;monkeypatch 实测 428 处日志真实输出(见②)。

## ⑦ 落档报告核对 — PASS(1 低分项见末尾)
- 9 处审计总表**语义判定全对**(函数锚点与代码逐一对上):4 补 / 4 不动 / 1 已补(冰点)闭合。
- §复现段 grep 命令**可跑通**:数量 9 对,但**行号是 base(改前)版**,与改动后文件偏移 +5~+15(详见低分项 A)。
- §诚实标注把「实测 vs 推断」分清了(collect_log=0 实测 / 绿点覆盖不到=推断 / 前端行号未复验),可信。

## ⑧ §21 公示判断 — PASS
- 独立核实:diff 为纯 logger 插入,**不改任何返回值/变量/控制流**,overview JSON 输出与 base 逐字一致;前端对缺失字段的容忍是既有设计(`app.js:2658-2680` etf-tag-pnl 缺失即不生成、`:12346` extra_dates 兜底)。
- 本次未动算法/口径/评分/匹配规则 → §21 触发词不命中,**不需改 purpose-notes.js,判断成立**。

## ⑨ §23.2 同类错误面 — PASS
- 实施列出的「不动」7 处逐一核实,判定全站得住:
  - `collector/etf_national_team.py:984` PDF 清理失败(pdf.unlink)非 DB 故障 ✓
  - `:1597` 基金名解析失败,名字兜底保留 ✓
  - `:2161` ACCUM_NAV_SKIP_PATH 缓存写失败 ✓
  - `main.py:300` 订阅配置读失败 → 显式空列表 fallback ✓
  - `auth.py:111,117` token 解析/验签失败 → return None = **fail-closed(拒绝访问),安全路径应有** ✓
  - `calendar.py:45` 交易日历拉取失败 → 清缓存重读旧缓存 ✓
  - `alert_score.py:863` 波动率分段失败 → vol_score 外层默认 50.0(:846)✓
- **独立抽查**:queries.py 是唯一「前端展示数据层」主文件(9 处全审);`export.py`/`signals.py`/`sentiment_calendar.py` 无 `except Exception`+pass 同类点;`intraday_snapshot.py` 68 处 except 属采集器,前端消费函数已有 print/fallback。**未发现漏网的「DB 级故障静默吞且无察觉途径」点**。

---

## 低分项(<80 已滤,按 §10.2)

- **A(50 分)**:doc 审计总表/复现段标注的行号是 base(改前)版却写「改动后」,复现段期望 `428/1069/1442/1583/1735/1814/1838/1856/1866` 与改动后实际 `428/1074/1447/1593/1745/1824/1848/1866/1881` 偏移 +5~+15。数量 9 对、函数锚点全对,仅行号辅助锚点过时,建议实施后续更新(非阻断)。
- **B(25 分)**:1856 文案同时覆盖 futures.json 与 us_dji/csi_div 两源,无法从文案区分哪个失败(exception 堆栈可补,可接受)。

## 合并建议
两分支(本分支 vs `feat/icepoint-consensus-20261002`)在 queries.py 上零交集(冰点分支 queries.py 已全部在 main),合 main 不会冲突、不会重复 logger。合并顺序无强约束,主控按 main-merge.sh 任意顺序处理均安全。
