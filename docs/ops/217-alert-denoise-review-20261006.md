# #217 告警降噪 ①②③ 独立评审报告(2026-10-06)

- 评审对象: `feat/217-alert-denoise-20261006`,远端 tip **`407debecf`**(链 `d714be25b` → `e1e7a7261` → `ea16648da`(merge origin/main)→ `407debecf`)
- 评审角色: reviewer(独立只读)——未改任何文件/未 push/未跑业务脚本主体/未真发通知/未 R2 写;本报告=只写文件,不做 git 操作(commit 归主控)
- 评审时点 `origin/main` = **`42e687b1c`**(评审期间由 `debb9dfea` 再前进一格,增量均 docs-only)
- **merge 资格结论: PASS**(8/8 必审项过;2 条 advisory/nit 非阻断;无返修硬项)

---

## 0. 变更面(实测)

`git diff 6376da90a..origin/feat/217-alert-denoise-20261006` = **5 文件**:

| 文件 | 增量 | 性质 |
|---|---|---|
| scripts/upload_r2.py | +51 | ① 有界等锁重试 + 注释口径对齐(无逻辑覆盖) |
| scripts/r2_upload_async.sh | +42 | ② 守卫 + 默认 900;③ `_dump_kill_tail` + 告警正文 |
| scripts/fetch_news.py | +14 | ① 影响面: subprocess timeout 120→120+窗口 |
| scripts/overfit_monitor.py | +16 | 同上 |
| docs/ops/217-alert-denoise-20261006.md | +166 | 实施报告落档 |

- 零前端文件(app.js/lab.js/index.html/static-site 未碰)、零 `data/` 夹带 ⇒ **§21(算法公示)/§24(前端防撕裂)/§23.1(README)确为 N/A**,实施报告 §5.3 判定成立(⑧ ✓)

## 1. ① 有界等锁重试(AST 单函数独立探针,8/8 PASS)

独立探针(评审自写 `/tmp/r217rev_probeA.py`:AST 摘 `_acquire_r2_upload_lock` 单函数 exec、私锁文件、真 flock 争用):

| 用例 | 实测 |
|---|---|
| A 锁空闲 → 立刻 fd,无 SKIPPED | 0.0s |
| B 持锁 3s + retry=15 → 等到锁(4.0s),无 SKIPPED | 瞬时撞锁被吸收 = 降噪本体 |
| C 持锁 8s + retry=4 → 4.0s 后返回哨兵 + 打印 `SKIPPED_LOCKED:` 开头消息 | |
| D retry=0 → 立即跳过(旧行为 / 向后兼容) | 0.00s |
| D2 retry=-5 → 按 0 处理 | |
| E 排队模式(无 skip)→ 等锁 4.0s 后拿 fd,语义不变 | 真争用 |
| F env 缺省 → 默认 60s | |
| G 新消息仍以 `SKIPPED_LOCKED` 开头 → 子串谓词成立 | |

- **判别保持**:`gen_schedule_stats.py:556/684` 谓词(`"SKIPPED_LOCKED" in line`)+ `schedule_monitor.sh:538` 连续 3 轮阈值 **文件零 diff**;消费方(fetch_news.py:734 bytes 子串+rc==0、overfit_monitor.py:1875、push_schedule_stats.sh:84 grep)全为子串匹配,新消息前缀保留 ⇒ 计数/阈值不失效、不放松。窗口内拿到锁 ⇒ 不打印 ⇒ 不计数;窗口耗尽 ⇒ 每轮 1 条 ⇒ 第 3 轮 SEVERE = 真缺口判别完整保留。
- **父子 timeout 一致性**:fetch_news.py:732 `timeout=120+_r2_skip_retry`,取值自**同一份传给子进程的 env 字典**(经 `force_env`+`_load_dotenv`);overfit_monitor.py:1863/1868/1872 同模式(同一 `_env` 对象)。env 非数字/空串两侧同样回退 60 ⇒ 不会出现"子等 60s 被父 120s 杀"错位。

## 2. ② 停滞阈值 900 + 防倒置守卫 —— 实施者诚实缺口已闭合

- **云上 `.env` 实测**(ssh 只读):`/home/ubuntu/code/trade-data/.env` 仅 L33 `R2_UPLOAD_HTTP_TIMEOUT=600`;`R2_UPLOAD_STALL_SECS` **未显式设置** ⇒ 默认 900 > 600,梯度真实成立 ⇒ ② 真修好,非注释级。
- 独立探针(sed 摘 L118-125 守卫块包函数执行,**绝不 source 脚本主体**)8 组合:云上真实形态(600/缺省)→900;显式 300 倒置 → 自动抬 900 + 警告日志;1200 → 不动;全缺省(本地)→900/30;http 非数字 → 回退 30;600/600 边界 → 900。与实施者自测互为独立复核。
- 全仓 `grep R2_UPLOAD_STALL_SECS` 消费者只有本脚本默认值 + 两份历史报告文字(时点快照)⇒ 无第二消费者依赖 300,"停下上报"条件未触发,判定成立。

## 3. ③ kill 定因材料(独立探针逐项核对)

- `_dump_kill_tail` 定义 L87 + **三处 kill 分支全接线**:L142(停滞)/L152(7200s 硬兜底)/L174(低速),grep 计数 5 = 1 注释 + 1 定义 + 3 调用 ✓
- 实测:50 行 tmp_log → 主日志恰好 30 行(含 21..50、不含 20);告警片段逐行 `<br>` 累积;`<`/`>` → `&lt;`/`&gt;` 转义生效;空 tmp_log 分支标「无任何输出」/「(无输出)」且可与"有输出被 kill"区分;多通道累积正常。
- 告警面:`R2_KILL_CTX` 只进 **L243 唯一 severe 口**(verify-channels rc!=0 真缺口 → "[告警] R2上传失败");rc==0(对账全过)不告警(降噪哲学保持,不因 kill 本身轰炸)。L259 purge 告警与本改动无关。
- 日志体积:每通道最多 +30 行,单次最多 4 通道 × 30 = 120 行 ⇒ 无 log 爆炸。

## 4. 发现问题(均非阻断)

### 4.1 (advisory,§23.10 相关) 加长正文在飞书文本副本可能触发 2000 字截尾
- 事实:`notify.py` `FEISHU_TEXT_LIMIT=2000`,飞书文本模式取 `subject + _html_to_text(body)` 后**截尾保头** + 「…(已截断)」;邮件(`MIMEText` html)无长度限制。新 `R2_KILL_CTX` 追加在正文**末尾**(30 行 × 平均 ~60 字符 ≈ 单通道 ~2.0K 字符),单通道 kill + 缺口场景正文约 2.2K 字符 ⇒ 飞书副本尾部(新增定因材料)可能被截;邮件/主日志完整(`tee -a "$LOG"`)。
- 定性:**截断机制既有**(对任何长告警都生效,非 #217 引入);head 保留 ⇒ 告警本体与缺口详情不丢,丢的是尾裁定因材料。
- **判定:非阻断,主控评估**。可选:该口按 §23.10「超长拆多条」或调限处理——⚠ 动 notify.py 属既有告警冻结面,须另行拍板,不在 #217 scope。

### 4.2 (test-quality nit,非阻断) 实施者自测 E 用例实际未制造争用
- `/tmp/t217_lock_selftest.py` E(排队模式)用例:新 holder 锁的是 E 自己的临时路径,但**漏设** `os.environ["R2_UPLOAD_LOCK"]=lp` ⇒ 函数锁的是 D 用例残留(空闲)路径 ⇒ 断言"等锁成功"实为"未争用即成功"。
- 补位:评审独立探针 E(同锁路径真争用,持锁 3s)实测排队模式等锁 4.0s 成功、无 SKIPPED ⇒ 语义不变已有独立证据。不影响产品正确性。

### 4.3 (merge 时点注意) base 新鲜度
- 分支含 `6376da90a`;评审时 `origin/main`=`42e687b1c`(增量 `debb9dfea`+`42e687b1c` 均 docs-only)⇒ 分支不含最新 main,**main-merge.sh base 同步步骤需生效**(其内置行为);两份增量 docs,预期无冲突面。`42e687b1c` 标题=#219 合并把 main CI 搞红(另一线在修),与本分支无交集。

## 5. 其余复核

- **⑤ 同类面**:全仓 `--skip-if-locked` 调用方实测恰 4 处(与报告 §4.3 一致);3 个"不动"判定复核成立(push_schedule_stats.sh 有显式 ⚠ + 计数消费;intraday_snapshot.sh 20:30+ 收尾轮排队;with_lock.py --nb 有 --on-skip 钩子,改会动 update_all 互斥语义)。3 处未修梯度倒置(gen_daily_brief.py:3115=120 / nextday_plan_generator.py:1177=300 / fapi_bj_width_export.py:75=600)实测**均不传 `--skip-if-locked`** ⇒ ① 不改其行为,倒置为既有问题;`origin/main` pending-index **#223 已登记在案(待拍板)**,上报链路闭合。本次不修正确(§23.7 冻结 vs §5.1 彻底性的最小冲突解=登记待拍板),后续按 #223 逐处评估(先核"兜底/自愈设计是否依赖当前值")。
- **③ 时点安全(§14)**:云上只读实测——fetch-news `*:01,45` 日槽(TimeoutStartSec=600,实测 24~37s):最坏 +60s ≈ 100s ≪ 600s、槽距 44min ⇒ 安全;overfit-monitor 21:40 日跑(实测 ~76s,unit 无 timeout,DUR 阈值 900s):+60s ≈ 136s ≪ 900 ⇒ 安全;intraday-snapshot 每 10min(TimeoutStartSec=0,DUR 900s):最坏 4 次 skip 上传 × +60s = +240s,正常 ~286s ⇒ ~526s < 900 ⇒ 安全;收尾轮(≥20:30)本就排队不 skip,不受影响。gen_daily_brief 历史 7300s 事故为**无界排队**所致,新行为上界 60s,不可能复现。
- **⑥ 零真外发独立取证**:自测脚本均在 /tmp 且方法论合规(AST 摘单函数 / awk 摘块,**未 source/exec 业务脚本主体**,§18 L50 合规;无 notify/网络调用);本机 `data/alerts/latest.md`(17:40)、`trade-data/data/alerts/latest.md`(18:10)、`warning_buffer.jsonl`(17:45)、`alert_state.json`(09-13)mtime 均早于自测窗口(22:05-22:40);worktree `git status` 干净、无 data/logs ⇒ 无任何真实告警痕迹。
- **⑦ git**:3 commit + 1 merge;远端 3 次 push 全 fast-forward(reflog 无 force 记录;首个 `a4b495114` 为本地 rebase 前置物,未留远端痕迹);无 data/ 夹带、无无关文件、无前端;tip 稳定 `407debecf`(ls-remote 复核)。

## 6. 复现命令(评审侧)

```bash
# ① 独立探针(8/8)
/Users/linhuichen/code/trade/.venv/bin/python /tmp/r217rev_probeA.py \
  /Users/linhuichen/code/trade/.claude/worktrees/agent-a5e093cebf1ec7bd9/scripts/upload_r2.py
# ② 守卫块 / ③ dump 块: sed -n '118,125p' / '87,100p' 摘出包函数执行(static-only,不 source 主体)
# 变更面
git diff --stat 6376da90a origin/feat/217-alert-denoise-20261006
```
> 评审探针在 /tmp(非仓内),如被清理可按上法重建同构。

## 7. 结论

**merge 资格:PASS**。走主控 `scripts/main-merge.sh feat/217-alert-denoise-20261006`(注意 §14 安全窗口 + base 同步)。
