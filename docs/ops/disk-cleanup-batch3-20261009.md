# #234 收尾批(第三批)执行报告 —— stash @{0}/@{2} 备份后 drop + 109 html 再生路径核查

- 日期:2026-10-09;执行:role-tester agent;仓库 /Users/linhuichen/code/trade(分支 main,HEAD 16dfee5aa)
- 任务:① 备份后 drop 2 个过时 stash(用户已拍板 @{0}/@{2} 可弃,@{1} 保留)② 查清 109 个 `trade_sim_*.html` 的再生路径(只查不删)
- 纪律:全程未切分支 / 未 checkout / reset / commit / push;未 stash apply/pop/save;未触发任何真实告警/邮件/飞书/R2 写

---

## 一、① stash @{0}/@{2} —— 备份 → 验可恢复 → drop

### 1.1 动手前基线(实测)

| stash | 提交哈希 | message 摘要 | 文件 | 本轮处置 |
|---|---|---|---|---|
| `@{0}` | `f546f4f92981f0c60f916159fb261c67e13b2397` | WIP on main: 98470715b | 1:`docs/kelly/position/scripts/accum_nav_map.json` | **drop** |
| `@{1}` | `a2d9fa018328034a5c29cd231fcdc156e5aaace1` | 主worktree脏改动09-08早上(README 等 7 文件) | 7 | **保留(全程未碰)** |
| `@{2}` | `1cc5339d0fa73b15a436747ae4412861afe079b8` | WIP on main: 60185b511 | 2:`docs/pending-features-index.md`+`scripts/agent_inbox_watcher.py` | **drop** |

- 分支 main / HEAD 16dfee5aa / `git status --porcelain` 空;`git stash list` = 3 条(与 batch2 审阅一致)
- **三条 stash 均 2 父(无 untracked 第三父)** ⇒ `git stash show -p` 导出即无损(不存在被漏掉的 untracked 成分)

### 1.2 备份产物(/Users/linhuichen/.claude/backups/cleanup-234-20261009/)

| 文件 | 大小 / 行数 | md5 |
|---|---|---|
| `stash-0-20261009.patch` | 45,425,542 B / 9 行 | `49e54e4257f942ec67f366989b5faccc` |
| `stash-2-20261009.patch` | 7,255 B / 36 行 | `7282bfd25f394edcad68c3633eed3d69` |
| `stash-{0,2}-20261009.meta.txt` | 原 stash 提交哈希/日期/父提交/构成说明 | — |
| `verify-20261009.txt` | 本轮全部验证输出留痕(可反查) | — |

- **逐位对账**:两份 patch 的 md5 **均等于** `git diff stash@{n}^1 stash@{n}` 的 md5(49e54e42… / 7282bfd2…) ⇒ 导出内容与原始 diff 逐位相同,无遗漏
- 注:stash@{0} 的 patch 达 43MB,是因 accum_nav_map.json 为超长单行 JSON 的整行改写(1+/1−),非异常

### 1.3 可恢复性实测(§25②「不是应该有备份,而是实测可恢复」)

方法:临时 index 重放(`GIT_INDEX_FILE=/tmp/... git read-tree <stash 基点>` → `git apply --cached <patch>` → 比对 blob 哈希),**不触真 index / 工作区**:

| 项 | 重放结果 | 原 stash blob | 判定 |
|---|---|---|---|
| stash@{0} accum_nav_map.json | `66062277c219876e2461a03ac9eb37cfadb9d375` | `66062277c219876e2461a03ac9eb37cfadb9d375` | ✅ 逐位一致 |
| stash@{2} pending-features-index.md | `f1152ff0350fbf149ac3d4c519f9cf2541da84b5` | `f1152ff0350fbf149ac3d4c519f9cf2541da84b5` | ✅ 逐位一致 |
| stash@{2} agent_inbox_watcher.py(mode 100755 保留) | `0afd6aaafe363483b783dfb206307b5d7ee1a64e` | `0afd6aaafe363483b783dfb206307b5d7ee1a64e` | ✅ 逐位一致 |

- **尺子先验(§5.2)**:截断版 patch → `git apply --check` exit=128「corrupt patch at line 6」;改 context 行版 → exit=1「patch does not apply」⇒ 校验器能抓坏样本(尺子有效),上面的 PASS 才成立

### 1.4 drop 执行(先删大序号,每步复核)

1. 再确认 `@{2}`=1cc5339d 内容(stat=2 文件)→ `git stash drop stash@{2}` ✅ `Dropped stash@{2} (1cc5339d…)`
2. 复 list:`@{0}`=f546f4f9、`@{1}`=a2d9fa01 **编号未错位**(原 @{0}/{1} 未受影响)✅
3. 再复核原 `@{0}`(message 含 98470715b + stat=1 文件)→ `git stash drop stash@{0}` ✅ `Dropped stash@{0} (f546f4f9…)`
4. 终态:`git stash list` **仅剩 1 条 = a2d9fa01**(与基线逐位一致);7 文件 stat 完整(README 17±/TASKS 2±/accum_nav_map 2±/plist 40−/about·guide·privacy 各 4±)✅

### 1.5 恢复路径(§25④)

```bash
cd /Users/linhuichen/code/trade
git apply /Users/linhuichen/.claude/backups/cleanup-234-20261009/stash-2-20261009.patch
git apply /Users/linhuichen/.claude/backups/cleanup-234-20261009/stash-0-20261009.patch
```

- 恢复内容 = 当时工作区态的逐位还原(blob 已证);patch 为纯文本,可读性已核(首行/尾行/行数)
- 若目标文件上下文已漂移:`git apply --check` 预检 → 失败改 `patch -p1 < <patch>`(fuzz)或直接从 patch 文本取完整新旧行
- 备选(仅限 `git gc` 清理前):`git stash store f546f4f92981f0c60f916159fb261c67e13b2397` / `git stash store 1cc5339d0fa73b15a436747ae4412861afe079b8`

---

## 二、② 109 个 `trade_sim_*.html` 再生路径核查(只查不删)

### 2.1 结论(先给结论)

1. **再生路径存在**:生成脚本 `scripts/simulate_trade.py` **在 main**(git tracked;最近提交 2026-09-22 c5b06b3db;`ast.parse` 语法可解析)。重跑命令:
   - 全量:`python3 scripts/simulate_trade.py --all --html`
   - 单品种:`python3 scripts/simulate_trade.py --index <index_id> --html`
   - 输出:`<脚本所在树>/static-site/trade_sim_<index_id>.html`(经 trade-data 符号链接路径调用则落 `trade-data/static-site/`)
   - `--html` 为显式开关,help 原文「生成旧版静态 HTML(默认不生成,仅 JSON)」⇒ 日常管线只产 JSON,该族是按需生成形态
2. **但「可再生成」≠「可逐位复原」**:重跑产物 = 按当前数据重算的新版;07-29/08-02 原件内容无法逐位复原(数据已前进、脚本已演进)⇒ 若删,§25 应先 tar 归档
3. **该族不是纯死文件**(对 batch2 待删隐含前提的修正,见 2.4):
   - 线上 R2 `/r2/trade_sim/*.html` 实测 **200**,是 app.js「模拟回测」的兜底入口
   - 实测下载 R2 副本 vs 本机 TD 原件:**前 1,091,350 B 逐位一致**(尾部 938 B 为 CF 边缘注入 `window.__CF$cv$params`,非存储内容)⇒ R2 兜底页 = 本机这族内容
   - 每日 deploy 链存在 `upload-trade-sim` 通道(r2_upload_async.sh L202),其**源目录解析会优先取本地这族文件**
4. **建议**:不要无差别全删;若要删 → ①先 tar 归档(§25)②确认/处置 upload-trade-sim 通道 ③本体 `static-site/trade_sim.html`(tracked,2,547,478 B,08-21)**禁删**,删除须白名单模式 `trade_sim_*.html`(禁「根 html 通配」,会踩 25 个活跃 symlink)

### 2.2 怎么生成的(证据链)

- **生成脚本/CLI/输出约定**:`scripts/simulate_trade.py` L2264-2339(main)+ L2156/2230-2232(`_generate_one` 写 `out_dir_static/trade_sim_{id}.html`);`scripts/SIMULATION_CHECKLIST.md` L6/L86「输出文件:`static-site/trade_sim_{index_id}.html`」
- **html 内生成标记:全家族 109 个文件都含**「生成于 YYYY-MM-DD HH:MM」(实测 103/103 + 6/6;来源 = build_html L1757 `datetime.now()`);样本无 `fetch(` ⇒ 数据内嵌自包含
- mtime 两组一次性批量:TD 103 个全 = 2026-07-29 00:06(195.3 MiB);TR 6 个全 = 2026-08-02 23:11(5.2 MiB)
  - 异常如实标注:TR 侧 marker(08-02 **19:26**)≠ mtime(08-02 23:11),差异未深究
- **目录约定**:输出在 static-site 根;该模式被 **.gitignore L109 `static-site/trade_sim_*.html`** 设计性排除(git 不受管=设计意图,与「R2 阶段3 线上瘦身 2026-07-20」注释一致)
- 与「本体」区别:本体 `static-site/trade_sim.html`(全品种打包版,tracked 2.5MB)已停用(update_lab.sh L252-259「2026-08-21 清理,不再每日重生 + commit」;历史快照保留不删);109 个是 per-index 版
- ⚠ 数字对不上如实标注:增量设计文档 `docs/kelly/analysis/r2-incremental-upload-design-20260915.md` L15 记该通道「103 文件 / 5.3MB」,与实测不符(实测 TD=103 个/195.3 MiB、TR=6 个/5.2 MiB——文件数对 TD、体积对 TR),本轮未深究;R2 实测含 TD 独有文件(bj50=200)⇒ 上传源 = TD 侧成立

### 2.3 谁在用(删除风险面,逐项实测)

- **前端 app.js**:L8952 模拟回测按钮 href → `ss.fx8.store/r2/trade_sim/trade_sim_{id}.html`;L31862-31867 左键打开新弹窗、**中键仍新标签打开旧 HTML 兜底**;L30267 弹窗 JSON 加载失败时提示「可访问旧版:静态回测页」(同 URL,带登录特权 gating)
- **R2 侧**:4 例实测 200(bj50 / sh / cac40 / nikkei225;bj50 为 TD 侧独有)⇒ R2 `trade_sim/` 现有 TD 侧内容;对照 CF 根路径 bj50/cgb_idx 仍 404(复核 batch2 旧结论成立范围:仅根路径)
- **每日通道**:`scripts/r2_upload_async.sh` L202 `upload-trade-sim`(部署链固定步骤);源解析 `upload_r2.py` L1516-1522(STATIC_DIR 优先,**全空 → `sys.exit("无 trade_sim html")`**)
- **失败后果链**:R2_FAIL → 收尾 `verify-channels` 轻量对账 → 有缺口 → `notify.py "[告警] R2上传失败" --severe`(r2_upload_async.sh L229-247);该通道 #212(2026-10-07)已 loud 化(L1516-1517)
- **本机特有实况(实测)**:
  - 本机两树**均无** `.r2_trade_sim_html_state.json`(html 通道无状态文件;而 trade-data/data 下其他通道状态文件齐全,如 `.r2_trade_sim_json_state.json` 10-02)⇒ 本机跑该通道会走「无状态全量」→ 被 **export-guard L3 拦 + 告警 + exit 1**(upload_r2.py L1352-1379)⇒ 本机该通道**本已处于失败+告警态**(与本地文件是否删无关)
  - ⇒ 本机删 109 个的失败模式变化:从「L3 拦」提前到「L1522 sys.exit」,同为失败(非静默写坏)
- **爆炸半径**:本机这 109 个(200.5 MiB,均 untracked + gitignored)删除只影响本机;云上为独立副本(git 载不动 untracked 文件)⇒ 本机删除不触及云上——**云侧若要清理需在云上另行核实(源目录/状态文件/当日通道日志),本报告不给云侧结论(未实测,如实标注)**

### 2.4 ⚠ 与 batch2 依据的两点修正(独立复核发现)

| batch2 说法 | 本轮复核结果 |
|---|---|
| 「上传链路不含 static-site 根 html」(引 upload_r2.py L1546「仅传 `STATIC_DIR/data/trade_sim/*.json`」) | L1546 处是 **upload-trade-sim-json**(JSON 通道);HTML 有**专属通道 upload-trade-sim**(upload_r2.py L1506-1525,每日链 r2_upload_async.sh L202)⇒ 原说法不完整 |
| 「线上 404」⇒ 可删依据之一 | 仅 **CF 根路径** 404(复核确认);**R2 兜底路径 200**(4 例实测)⇒ 该族线上仍活着,不是死文件 |

### 2.5 若决定删:前置清单(供拍板)

1. **tar 归档**(§25;原件不可逐位再生,归档才能把不可逆变可逆)+ 归档后写恢复命令
2. **通道处置**(三选一,需拍板):①保留源文件不动 ②从 r2_upload_async.sh 移除/停用该通道 ③改源
3. 删前用**白名单模式** `trade_sim_*.html`,严禁通配根 html;**本体 trade_sim.html 禁删**
4. 数量/体积对账:TD 103(195.3 MiB)+ TR 6(5.2 MiB)= **109 个 / 200.5 MiB**

---

## 三、纪律合规声明(逐条实测)

- ① **零 git 写**:未切分支 / 未 checkout / 未 reset / 未 commit / 未 push;`git stash` 仅 `list` / `show` / 备份 / `drop`(drop 的是已备份且用户拍板的两条);未 apply / pop / save
- ② **未触发任何真实告警/邮件/飞书**;未写 R2(仅只读 GET 探测 + 下载 1 个样本比对 md5);未裸跑 pip/npm;未用 Docker;未 `find /`;未越界 `grep -r`(仅 scripts/docs 等项目白名单目录)
- ③ 所有命令带 Bash timeout;未执行任何业务脚本(simulate_trade.py 仅 `ast.parse` 静态检查,未运行——static-only 纪律)
- ④ 本报告按要求**未 commit**
- ⑤ 收尾快照:`git stash list` = 1 条(a2d9fa01,@{1} 完好);分支仍 main

## 四、复现命令(核验用)

```bash
# ① stash:备份核对 + 恢复验证
git stash list                                              # 现应只剩 a2d9fa01 一条
md5 ~/.claude/backups/cleanup-234-20261009/stash-{0,2}-20261009.patch   # 49e54e42… / 7282bfd2…
cd /Users/linhuichen/code/trade
# 原始 diff 对账(注:两条已 drop,diff 源已不可再用;以 patch md5 + 1.3 表 blob 哈希为准)
GIT_INDEX_FILE=/tmp/x git read-tree 98470715be3ffd8539bf9dc698c56b4ede5d0e15
GIT_INDEX_FILE=/tmp/x git apply --cached ~/.claude/backups/cleanup-234-20261009/stash-0-20261009.patch
GIT_INDEX_FILE=/tmp/x git ls-files -s docs/kelly/position/scripts/accum_nav_map.json   # 66062277c…
# ② 109 html:计数 + 生成标记 + 线上可达
ls -1 /Users/linhuichen/code/trade-data/static-site/trade_sim_*.html | wc -l    # 103
ls -1 /Users/linhuichen/code/trade/static-site/trade_sim_*.html | wc -l         # 6
grep -o -E "生成于 [0-9-]+ [0-9:]+" /Users/linhuichen/code/trade-data/static-site/trade_sim_sh.html | head -1
curl -s -o /dev/null -w "%{http_code}\n" --max-time 20 -A "Mozilla/5.0" https://ss.fx8.store/r2/trade_sim/trade_sim_bj50.html   # 200
git ls-files scripts/simulate_trade.py; grep -n -- "--html" scripts/simulate_trade.py | head -3
```

## 五、待拍板项

1. **109 个是否删**?建议:先 tar 归档 + 处置 upload-trade-sim 通道后再删,或保留(线上兜底页在用、通道以本地为源)
2. **云侧副本是否也要清理**?需在云上单独核实(本报告仅本机结论)
