# 存储治理三机制修复 独立审查报告（reviewer）

- 分支/commit：`origin/feat/storage-mechfix-20261125` @ `91dbec834`（parent/merge-base 均为 `1128f8073`=origin/main，无分叉、无漂移）
- 审查人：reviewer（fresh context，只读；主仓只读、worktree `/tmp/wt-storage-mechfix-20261125` 只读跑测；零外发、未碰生产/本地 data）
- 时点：2026-11-25 07:56–08:2x CST

## 判定：FAIL（P0 = 0；P1 = 2，均可小返工）— 机制本体正确，卡在「方案 §6 两条反例的验证/宣称不成立」

三块机制实现本体经逐行核验正确、测试为真测（非假测）、无数据丢失风险、未改坏老功能（126 既有 + 14 新全绿）。但方案 §6 明确列出的完成标准里，**symlink 反例零测试**、**缺引用（missing referenced payload）反例未实现且代码注释/报告误报「缺引用提前 raise」**，属 §10.7「方案承诺的证据用例没兑现」。补测试 + 改注释或显式声明即可转 PASS。

## 缺陷清单

### P0（数据/安全，阻断）：无

### P1（阻断 merge，需返工）

**P1-1 §6「缺引用」反例未实现 + 代码注释/报告误报**
- 位置：`scripts/r2_safe_write.py:204` 注释宣称「坏 JSON/**缺引用**/非法身份提前 raise，零删除」；报告 §1 同款宣称。
- 实测：代码只对 ①坏 JSON（`ValueError`）②非法身份/格式（`UnsafeWrite`）③引用 pair manifest 文件缺失（`read_text→FileNotFoundError`）抛错。对 **kept journal 引用的 payload 文件缺失**：`keep.add(payload_path)` 后从不校验存在性，`return [p for p in keep if p.is_file()]`（:229）静默过滤 → **GC 照常删其余 garbage，不停批**。
- 复核 11-25 recheck：生产「闭包缺失路径=0」，故当前不触发；且删 garbage 仍安全（garbage 定义=无引用，缺失文件本就不在盘上，删它不影响 keep）。**不是数据丢失 bug，是方案 §4.2/§6「缺引用整批停」未实现 + 注释/报告过度宣称。**
- 处置建议（二选一）：①实现「kept 引用路径 existence 校验，缺失→raise 零删除」并补用例；②若判定 payload 缺失无需停批（安全性已足），则**改注释与报告，显式声明不适用+理由**，别留误导。
- verifier：`grep -n "缺引用" scripts/r2_safe_write.py`（注释在位）；构造 kept journal 的 sha256 指向不存在 payload → 现状 gc 不抛、继续删 → 期望按方案应 UnsafeWrite。

**P1-2 §6「symlink」反例零测试（代码在位但无任何断言）**
- 位置：`scripts/r2_safe_write.py:127`（pre-existing，本 commit 未改）`if any(p.is_symlink()): raise UnsafeWrite('...contains symlink; GC refused')`。
- 实测：`git grep -nE "symlink|is_symlink" scripts/tests/` 命中的全是 fundnav/step35b/alert 等无关测试；3 个新测试文件 + test_r2_protected_writes 均无 symlink 用例。方案 §6 把 symlink 列为「最少验证」项 ⇒ 未兑现。
- 处置建议：新测试加一条「protected 树内放 symlink → gc 抛 UnsafeWrite、零删除」。
- verifier：`pytest scripts/tests/ -k symlink` 当前无相关用例。

## 关键证据点（逐块）

### 块1 deploy.sh rsync 排除（最重）— PASS
- `scripts/deploy.sh:761` 仅加 `--exclude=.r2-protected/` 一条；**无 `--delete`**；原有排除（logs/notify_dedup/alert_state/alerts/warning_*/backups/index_etf_map/stock_codes/trade.db/trade_dates/*.db*）逐一在实文在位。
- **语义独立复核**：trailing slash 只匹配「目录」且匹配任意深度 final component；**不误伤同名普通文件/正常 JSON/parquet**。我用真实 rsync 独立跑了小样：`src/.r2-protected/history/a.json + src/normal.json` → dst 仅得到 `normal.json`，protected 子树零复制（rsync 2.6.9 本机口径；与 CI/云上 rsync 3.x trailing-slash 语义一致）。
- 测试为真测：`test_storage_deploy_protected_exclude_20261125.py` 从 deploy.sh 抽同一条逻辑命令（复用 test_253 的续行合并解析），**原样喂 bash，先在 /tmp 夹具 `-n -i` dry-run 断言 protected 不列出/正常项列出，再真跑**断言 protected 子树未复制、目标旧副本因无 --delete 保留、normal.json/hist.parquet/nested/x.json 逐字节到位。非假测。
- 无其他回涨入口：全仓实际 rsync 命令扫描，只有 `deploy.sh:756`（本处）复制 `$REPO/data/` 根；`staticdata_backup_async.sh:154` 只搬 `*.db` glob（不命中目录）；`static-site/data` 各 rsync 不涉 `data/.r2-protected`。

### 块2 保守 hold 全部 nonconfirmed — PASS
- `scripts/r2_safe_write.py:159` 由旧 `state=='unknown' or pending_purge or (pair_id and state!=confirmed)` 改为 `state != 'confirmed' or pending_purge`。是旧保留集的**严格超集**（preparing/prepared/plain/failed 新增保留；confirmed 且非 pending 仍走 HISTORY_KEEP 窗口）。
- payload/pair 递归：新增 kept 行进 `rows` → 闭包（:170-190）保 `sha256`/`old_sha256` payload + pair manifest.objects；正是 recheck「55 preparing 行 + 103 old_sha payload」漏删的根因修复。
- HISTORY_KEEP 语义未改（:161 默认 1、range 0..16、越界仍 `UnsafeWrite`）、**未改写任何 state**。测试 `test_storage_protected_hold_*` 覆盖 preparing/plain/unknown(pending_purge)/failed + pair(prepared) + old_sha 全保留、KEEP=0 仍保 nonconfirmed、KEEP=17 仍拒、状态未被改写。

### 块3 GC 回收预算与写入配额拆分（最重）— PASS（四闸全在）
- GC 不再调 `check_capacity`（旧 :190 已删）；超 cap/超 8192 的无引用文件能回收，日志打 `reclaim-over-write-budget`（:210）。
- **四道闸逐条核**：
  ① 引用已证明：坏 JSON/非法身份/非法 payload 引用/非法 pair 引用/缺失 pair manifest 均 raise，先于任何 unlink；
  ② 同锁域：生产 `.gc()` 唯一调用方 = `store_many`（:251，在 `storage_lock` 内）；`git grep` 确认 upload_r2/nav_selfheal/probe 均无直接 `gc()` 调用（仅 :1362 设 `gc_tolerate_unreadable` 属性，实际写仍走 save→store_many）。锁冲突用例证明拿不到锁不删。
  ③ 清单 durable 先落盘：`:224 durable(manifest_path, manifest)` 在任何 `unlink`（:226-228）之前；durable=tmp+fsync+os.replace+父目录 fsync，失败上抛→零删除（用例覆盖 ENOSPC）。
  ④ 清单后复核：`:225 _revalidate_gc_plan` 比对「文件集 = planned 集」且「每个待删文件 (dev,ino,size,mtime_ns) 未变」，变化→UnsafeWrite 整批零删除（用例覆盖身份变化 / 计划后新引用）。
- 新写入仍被原配额拦：`store_many → check_capacity(files,writes)`（:252/:263）用 `PROTECTED_FILE_BUDGET=8192` + cap + reserve；用例证 cap 拦 / 文件预算拦目标文件零落盘。
- CAS/purge 未动（diff 仅动保留条件/预算/常量，无 purge/CAS 行）。
- gc-manifest 不被任何「删除决策」消费（upload_r2:1366 / nav_selfheal:103 只是跳过解析；backup 仅注释），故 revalidate 失败时已写清单的 retired_count 偏乐观也无害（下轮重算覆盖）。
- 未做远端写：gc 全程本地 fs；无 PUT/DELETE/purge。

## 方案 §6 完成标准逐条对账

| §6 反例 | 实现 | 测试 | 判定 |
|---|---|---|---|
| 超cap/超8192无引用能回收 | 是 | 是 | PASS |
| 新写仍被原配额拦 | 是 | 是（cap+文件预算） | PASS |
| preparing/prepared/unknown/pending_purge/pair/旧SHA 不删 | 是 | 是 | PASS |
| 坏JSON 整批停 | 是 | 是 | PASS |
| 缺引用 整批停 | **payload 缺失不停（仅 pair manifest 缺失 raise）** | **无 true 缺失用例（只有格式非法）** | **FAIL(P1-1)** |
| symlink 整批停 | 是（pre-existing:127） | **无** | **FAIL(P1-2)** |
| 文件身份变化 整批停 | 是 | 是 | PASS |
| 计划后新引用 整批停 | 是 | 是 | PASS |
| 锁冲突不删 | 是 | 是 | PASS |
| 清单落盘失败 零删除 | 是 | 是 | PASS |
| 本地清理无远端写 | 是 | 代码路径 | PASS |
| 普通JSON镜像保留/protected复制0 | 是 | 是 | PASS |

## 边界完整性独立复核（§10.8，自己先推再对账）

自推清单（不看实施七轴）→ 与实施清单对账三分类：

- **两边都有（核合理）**：rsync trailing-slash 误伤 / 无 --delete / 原排除保留 / 其他 rsync 复制方 / 全部 nonconfirmed 状态 + old_sha + pair / HISTORY_KEEP 不改 / 四闸 / 新写配额 / CAS 不动 / 父链无分叉 / 时敏固定 epoch。
- **实施有我没（接受）**：极端值 cap=1/预算=5 缩小替代真实 8k 规模（等价覆盖，可接受；真实 9286 规模未跑属残余，风险低）。
- **我有实施没有（差集，逐条处置）**：
  1. **缺引用(missing payload) 不停批 + 注释误报** → 已列 P1-1（补实现或改注释声明）。
  2. **symlink 零测试** → 已列 P1-2（补用例；代码在位正确）。
  3. **新保留行会经闭包校验**：若生产存在 write_id 不合 `[a-f0-9]{32}`/key 非 protected 的 nonconfirmed 历史，旧逻辑是「当垃圾清掉」，新逻辑会 `raise` 让整轮 GC 失败(fail-closed)。recheck 实测 0 违例 → 当前无影响；属**更保守**的良性副作用，**不阻断**，建议知会。
  4. **gc() 移除 check_capacity 后，非法配额 env 不再在 GC 前校验**：cap<=0/reserve<0 时 grep，新逻辑先删 garbage 再在 store_many 的 check_capacity 抛错。删 garbage 本身安全 → **不阻断**；属未声明行为变化，建议注释一句。
  5. `_revalidate` 失败时已落盘的 gc-manifest retired_count 偏乐观 → 下轮重算覆盖、且无消费方按它删 → **不阻断**。

## 测试真实性 / CI 范围 / 时间锚

- 3 新测试直接测生产 `SafeWriter`/真 rsync/真 fs（夹具仅落盘形状，不含生产逻辑）→ 真测。
- 全量末行**独立佐证**：`/tmp/storage-mechfix-pytest.log` 尾行 `5584 passed, 6 skipped, 176 subtests passed in 724.83s` + `grep -c FAILED/ERROR=0`（非仅采信报告首述）。
- CI ⑧ `pytest -q scripts/tests/` 覆盖 3 新文件；⑫ faketime+45d 也覆盖（夹具全用固定 epoch 1700000000，无 today()）→ 隔天/跨月不红。
- worktree 与主仓只读：`/tmp/wt-storage-mechfix-20261125` 干净、HEAD=91dbec834；主仓 main=1128f8073 未动。

## 尺子验证行（§10.0）

- 块1 尺子=「抽 deploy 真命令 + 真跑 rsync」：先用独立 /tmp 小样验证 trailing-slash 只排目录、normal.json 照传（见上），再跑新测试 real-run 断言 → 尺子有效，且该用例在旧无排除代码上会因 protected 被复制而红（判别力成立）。
- 块3 尺子=真 `SafeWriter`+monkeypatch 常/预算：`test_over_budget...` 在旧代码（gc 内 check_capacity 超 cap 即抛）必红 → 判别力成立；durable 打桩只在临时树、零外发（无告警/邮件链路）。
- 未使用任何会真发通知/真连生产的探针。

## 复跑末行

- 3 新测试：`14 passed in 0.17s`
- 4 受影响既有：`126 passed in 8.99s`（test_r2_protected_writes / test_nav_autorecover / test_upload_retry_capture_fix / test_253_disk_reclaim）
- 全量：引用实施日志 `/tmp/storage-mechfix-pytest.log` 末行 `5584 passed, 6 skipped, 176 subtests passed in 724.83s`（0 failed，独立 grep 佐证）

## 低分项（<80，已滤，仅供追问）

1. 块1 新测试未断言 `notify_dedup.json/alert_state.json/warning_*` 三条原排除（源码实文在位，纯测试补充）。
2. env 非法配额行为变化（差集 4，安全）。
3. revalidate 失败清单 retired_count 偏乐观（差集 5，无害）。
4. 「配对 pair 保留」措辞在报告里可再精确（代码正确）。

## §21 公示 / §24 前端 / 冒烟 P0
- 本次无算法/前端源码改动（diff 不含 app.js/lab.js/index.html/sw.js）→ §21 公示 N/A、§24 四查 N/A、无需 bump（统一归 main-merge）。
- 冒烟 P0（影响面视角）：块1 属部署链基础设施、块2/3 属 uploader 本地缓存治理，均不改变任何用户可见数据产物；无 P0 冒烟点需 curl。数据校验（三查/§22 多展示位同值/check_data_integrity·check_r2_consistency）归 tester。

---

## 复核返工(commit 40a2da02f,只核两 P1)

### 判定:PASS —— 两 P1 均已解决,无新增阻断。

### P1-1(kept payload 存在性校验)结论:兑现,口径细化可接受
- **代码路径**(`scripts/r2_safe_write.py:199-228`):引用闭包构建后、`garbage` 计算前、任何 `unlink`(:260)前,遍历 `rows` 的 `sha256`+`old_sha256`,按行状态分流:
  - `state=='confirmed'` 进 `must_exist`;缺失 ⇒ `:219 raise UnsafeWrite('protected payload reference missing…; unresolved anchors retained')` ⇒ 整批零删除(raise 早于 durable/unlink)。
  - 其他状态进 `soft_missing`;缺失 ⇒ `:225-226` 打 `missing_nonconfirmed_payload` 结构化 stderr 告警后照常回收。
- **confirmed 是否全覆盖**:是。`rows` 含顶层全部 journal(含当前 confirmed)+ 块2 保留的全部 nonconfirmed history + HISTORY_KEEP 窗口内 confirmed + pair 嵌入行,confirmed 行的 `sha256`/`old_sha256` 全部进硬校验。
- **口径细化的真实风险 = 无数据丢失**(关键论据,读码得出):`garbage = files - keep`(:229 附近),`keep` 对**任何状态**行的 `sha256`/`old_sha256` payload 都递归加入(:176-180)。缺失的 payload 本不在盘、不在 `files`、不能成为 `garbage`;而存在的被引用 payload 无论状态恒在 `keep`、永不删除。故 soft/hard 只差「是否整批中止」,**删除集合完全一致**,告警放行 nonconfirmed 不带来任何误删。
- **preparing 缺口是协议内瞬态(实测代码时序)**:`upload()` 在 `:514 self.save(row)`(写 preparing journal+history,此时 row 已带 `sha256`/`old_sha256`)→ `:516` 存新 payload → `:517-518 if old: 存旧 payload`。二者是**两次独立 `store_many` 加锁**,故两写之间确有 payload 未落盘窗口;对它硬失败会让一条崩溃残留卡死此后每次 `store_many→gc`(每次写入都 gc),这是真实可用性风险。soft 处理正确。
- **legacy 行不会误伤(回答断点疑问)**:
  1. `old_sha256` 字段与「存旧 payload」`payloads/sha(old[0])` **同 commit `ac76c8037` 引入**(`git log -S` 双双只命该 commit)→ 历史上从无「设 old_sha256 却不存旧 payload」的代码版本;
  2. `old_sha256` 仅在 `old` 真值时设值(:495),而 `old` 真值即在同一 `upload()` 内 :518 落旧 payload,先于 `prepared`/`confirm()`;
  3. 全文件仅 `gc`(:260)删 protected 文件(:79 为原子写临时清理),keep 恒含被引用 payload ⇒ 被保留 confirmed 行的 payload 不会被任何后续 GC 删掉;
  4. 昨夜复核 `/tmp/storage-recheck-20261125.md` 实测:protected 闭包「坏 JSON/缺引用/symlink/非普通文件 **0**」「闭包缺失路径=0」。
  ⇒ 新硬校验**今日零误伤**,且结构上不会对合法 confirmed 行误报。
- **残余建议(非阻断)**:协议内合法缺 payload 窗口严格只有 `preparing`;`prepared/failed/unknown` 缺 payload 属损坏(字节先于这些状态落盘)。当前对这些也 soft,略欠检,但①无丢失风险②有可观测告警③避免残留卡写,可接受;后续可考虑把 soft 收窄到 `preparing`。

### P1-2(symlink 零删除用例)结论:真实断言,非空跑
- 用例 `test_symlink_in_tree_refuses_gc_with_zero_deletion`(`scripts/tests/test_storage_gc_budget_split_20261125.py:159-174`):`tree.add` 默认 `state='confirmed'`,`_superseded` 造 confirmed 行;在 `root/payloads/<64d>` 建真实 symlink 指向行 payload → `pytest.raises(UnsafeWrite, match='symlink')`(:167),并断言 symlink 仍在、各行 history/payload 仍在、无 `gc-manifest.json`。
- 对应守卫 `r2_safe_write.py:127 if any(p.is_symlink() for p in self.root.rglob('*')): raise UnsafeWrite('…contains symlink; GC refused')`(位于 garbage/unlink 之前)。

### 尺子验证行(§10.0)
- 探针=只读 pytest,全在临时 `tmp_path`,零网络零外发,不触生产/本地 data/;worktree `/tmp/wt-storage-mechfix-20261125` 只跑只读测试。
- 判别力:P1-1 两用例断言串 `payload reference missing` / `missing_nonconfirmed_payload` 在旧 commit `91dbec834` **不存在**,故在返工前代码必红判 = 有效。

### 复跑末行(worktree@40a2da02f,PYTHONPATH=scripts)
- 3 个返工相关测试文件:`17 passed in 0.16s`
- 3 个返工新用例(verbose):`test_missing_referenced_payload_stops_whole_batch PASSED` / `test_missing_nonconfirmed_payload_only_warns PASSED` / `test_symlink_in_tree_refuses_gc_with_zero_deletion PASSED` ⇒ `3 passed in 0.03s`
- 受影响既有(253 登记点 + r2_protected_writes + r2_purge_delivery):`103 passed in 12.67s`
- 全量日志抽验 `/tmp/storage-mechfix-fulltest2.log` 末行:`5587 passed, 6 skipped, 176 subtests passed in 736.02s`,0 FAILED/ERROR —— 与实施声明一致。
