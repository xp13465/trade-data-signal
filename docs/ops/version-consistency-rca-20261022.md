> 落档:2026-10-22(只读根因调查,原样归档)
> 关联:`docs/ops/batch-fix-20261022.md`、`docs/ops/alert-week-review-20261021.md`

# §24⑤ 版本一致性校验失败根因（只读续查，2026-10-22）

## 1. 云上当前状态
- HEAD：`dc242231dd603a6199e4143764d461a15ce5bcd6`（2026-10-22T01:50:39+08:00）
- `git -C /home/ubuntu/code/trade-data-signal status --porcelain`：0 行（干净）
- worktree md5 == `git cat-file blob HEAD:static-site/...` md5，逐位一致：
  - purpose-notes.min.js：两侧均 `22306377b98ad1ff46af4ef915a7d7c7`
  - app.min.js：两侧均 `87dbf668fa654f28b3cbf1860fcc3412`
- 云上当前实跑 `check_version_consistency.py --checks 3`：8 对全部 PASS（源 app.js 2,206,319B / purpose-notes.js 77,709B）。

## 2. 校验的「HEAD 重建」实现（与构建入口是否同源）
- `scripts/check_version_consistency.py:200-203` 调用 `build_min.build_pairs_in_memory`，`scripts/build_min.py:90-96` 用 `git show HEAD:<rel>` 读源（失败才回退工作区并告警），`scripts/build_min.py:155-167` 调 `npx --yes terser`：
  - app.js：`--compress unused=false --mangle keep_fnames`
  - 其余 JS：`--compress --mangle keep_fnames`
  - CSS：rcssmin
- deploy 自身构建 `scripts/deploy.sh:608` 与 main-merge 统一构建 `scripts/main-merge.sh:254` 调的都是同一个 `scripts/build_min.py`，命令逐字相同（无第二套实现）。
- 云上工具：node v22.23.2，npx /usr/bin/npx，npx 缓存 terser **5.51.2**（缓存 mtime 2026-09-13）；本机：node v25.8.0，terser 5.51.2。
- 风险点（非本次致因）：`npx --yes terser` 未 pin 版本，未来 latest 漂移会让历史 min 与重建不一致。

## 3. 本机 vs 云上重建：同源同结果，无工具差异
- 本机以 `build_min.build_pairs_in_memory(base=trade/static-site, repo=trade)` 从 HEAD 重建：
  - purpose-notes.min.js 76,473B `22306377...`
  - app.min.js 1,090,838B `87dbf668...`
  → 与仓库 HEAD 中已提交的 min 完全一致。
- 云上当前重建同样 8/8 PASS。⇒ 两侧工具链一致、确定性的；00:42 的差异不是工具版本/参数/换行/时间戳注入。

## 4. 00:42 失败的真实机制 = 检查期间并发 git pull（TOCTOU）
- `deploy_20261022_0042.log` 是 00:42:44 启动的段1；其校验3读到的源尺寸是 **app.js 2,176,940B / purpose-notes.js 75,824B**（= 合并前旧源），重建结果 `0f658507 / e44dbcbe`；而「当前」min 读到的却是 `87dbf668 / 22306377`。
- Git 事实链：
  - `2b2841454^`（合并前）：min blob 正是 `0f658507 / e44dbcbe`；
  - `2b2841454`（00:52:36）：源与 min 一起变为新值，min blob = `87dbf668 / 22306377`；
  - 云上 reflog：`2b2841454 HEAD@{2026-10-22 00:52:49}: pull origin main: Fast-forward`；
  - 云上 `static-site/{app.js,purpose-notes.js,*.min.js}` 四个文件 mtime 全是 `00:52:49`。
- 谁 pull：`scripts/main-merge.sh:629-655` 第 10 步「merge 即同步」在 push 后 ssh 云上执行 `git pull origin main`。
- `check3` 先 `build_pairs_in_memory`（从 HEAD 读源、跑 terser，耗时几十秒），**之后**才读磁盘 min 文件比对（`check_version_consistency.py:203 / 222`）。pull 恰好落在「源已按旧 HEAD 读完、min 尚未读」的窗口 → 旧源 vs 新 min，必然 FAIL。
- 结论：不是「只要跑到这一步就必失败」，是**并发 pull 与校验窗口重叠**的竞态误报（虽然拦下的动作本身符合安全设计）。

## 5. 历史频次（10-01~10-22）
- deploy 日志总数：339；实际跑到版本校验的轮次：121。
- 其中 PASS：120；FAIL：1（仅 `deploy_20261022_0042.log`）。
- 首现/唯一一次：2026-10-22 00:42 轮。

## 6. 02:06 轮复验（已到校验段）
- `deploy_20261022_0206.log:597` `✓ 数据产物校验通过(含仅告警级失败继续)`；`:729` `✓ 版本一致性校验通过(所选子集 1,2,3, §24⑤ PASS)`。
- 段2 独立日志 `deploy_20261022_0213.log`：02:13:36 开始、02:13:41 `退出码=0`。
- 线上 overview date：`ss.fx8.store` = 20261021、`ssd.fx8.store` = 20261021（R2/主站一致）。
⇒ 部署链已通，本轮不是持续性故障。

## 7. 修法建议（A/B/C + 风险 + 不修的后果）
**A. 统一构建入口（云上不再重建，以 merge/CI 产物为权威）**
- A1：main-merge 已经是唯一 bump+build 入口；deploy 去掉 build_min 重建（deploy.sh:604-613），check3 改为「min 内容 == HEAD blob」（不重建）。
  - 动作面：deploy.sh、check_version_consistency.py、main-merge.sh。
  - 风险：失去「提交里的 min 是否真由源生成」的校验，历史脏 min 可混过；依赖主控纪律。不推荐单独用。
- A2：CI 跑 `--checks 3`，云上只验 artifact。动作面：CI workflow + deploy.sh。风险：CI 与云上 node/terser 版本需钉死一致。

**B. 修复重建不一致根因（推荐，治本）**
- B1（最小完整）：`check3` 开头固定一次 `head=$(git rev-parse HEAD)`；先把 8 个磁盘 min 字节读入内存快照；源全部用 `git show $head:<path>`；重建后与快照比；结束再 `git rev-parse HEAD`，若与开头不同 → 明确报「HEAD 在校验期间移动」并重试一次。动作面：check_version_consistency.py（约 20 行）。风险极低，保留「脏工作区 min」检测能力。
- B2（互补）：main-merge 第 10 步云上 pull 前检查 deploy.lock / 正在跑的 deploy，等待其结束再 pull（或 pull 后自动触发一次 deploy）。动作面：main-merge.sh（+ deploy 状态文件）。风险：merge 后云上生效延迟数秒~数分钟；但能同时消除 pull 对 rsync/commit 阶段的扰动。
- B3（加固）：`npx --yes terser@5.51.2`（或 package.json + npm ci）钉版本。动作面：build_min.py。风险低；诚实标注：本次不是它导致的（两端都是 5.51.2），但 npx 不 pin 是未来必然漂移点。

**C. 其他**
- C1：check3 检测到「HEAD 在校验期间变化」时自动重试一次（可与 B1 合并，B1 已含）。
- C2：把 check3 降为 warn —— 不推荐，违背 §24⑤ 防 2026-08-14 全站白屏初衷。
- C3：校验改在临时目录用 `git archive <sha>` 解出源与 min 再比（完全免疫并发 pull，但改动面比 B1 大）。

**不修会怎样**：只在「main-merge 自动 pull 与某轮 deploy 的 check3 窗口（约几十秒）重叠」时触发；触发即该轮段1 终止（不 rsync、不上 R2、不 commit），该 scope 数据停在上一成功轮，自愈 3 次/日额度可能被耗尽并误报「min 过期」。不会永久停更——下一次成功轮会补上（本次 02:06 已补，线上 overview=20261021）。22 天 121 次里仅 1 次，但 merge 高峰期会重复出现，且报错指向误导（像是 min 过期），建议至少落 B1。
