# Codex 交接包归档:近期问题复核 v1(2026-11-04)

## 1. 基本信息

| 项 | 值 |
|---|---|
| 交接编号 | handoff-20261104-recent-issues-v1 |
| 基线 commit(交接包声明) | 58fabc61efdf35b1331a2ac09c737a9e6fee28be |
| 主控 HEAD(接收时核实) | 58fabc61e(与基线相同,head_equal_baseline=true) |
| 接收时间 | 2026-11-04 16:25 Asia/Shanghai |
| 原报告 sha256 | e67c87e5e74f7032d5d053f2a67b57ee69349f039474eb28f5e99d77c429dbfe |
| worktree 状态 | clean |

## 2. 为何归档

/tmp 只作临时传递通道,仓库是长期依据。交接包的 11 份文件(交接 JSON/TXT + 调研产物 + 复现脚本 + 主控回执)复制进本目录后逐个 sha256 对账,确保与源文件逐位一致;未来任何角色回查本次复核结论、证据锚点、复现脚本,都从本目录取,不依赖 /tmp 会被清。

## 3. 逐项结论表(11 行)

| ID | 主控决定 | 对应任务 | 关键证据锚点(一句) |
|---|---|---|---|
| F01 | 认可 | #366 | `collect_fof_nav.py:231` main() 恒 return 0(不看 collect 结果);`gen_schedule_stats.py:356` LOG_TASKS 不含 UNIT_ONLY,fof_nav_collect 在 UNIT_ONLY(:309) |
| F02 | 重复已有任务 | #333 批2 | `collect_fof_nav.py:155-160` 以 DISTINCT fund_code WHERE date BETWEEN ? AND ? AND unit_nav IS NOT NULL 建 filled 集;pending-features-index:502 已登记「批2 跟进」 |
| F03 | 认可 | #367 | `notify.py:2338-2342` 读用 LOCK_SH 读完即 LOCK_UN;:2349-2356 无锁遍历判幂等;:2372 命中失败才调 _append_jsonl(其内 :2158 用 LOCK_EX)⇒ 读-释放-判-写四步不原子 |
| F04 | 认可 | #368 | `upload_r2.py:5198-5199` lock_plan 两项;:5203-5217 全局屏障 PermissionError 被 except OSError 接住后 continue,fds 只剩 1 项;:5249-5251 取 fds[1] 越界 → IndexError |
| F05 | 认可 | #369 | `lab.js:1794` 无 Content-Length 分支 `return resp.json()` 无 await ⇒ finally(:1835 clearTimeout)在正文读完前执行,超时定时器失效 |
| F06 | 认可 | #370 | `index.html:50` firstMs=(isMain\|\|isLocal)?0:8000 ⇒ 主站 boot 预取无应用级超时;:41 grab(u,0) 用 fetch 无 AbortController |
| S01 | 不纳入(待用户拍板) | — | 四个 workflow 无依赖:ci.yml、deploy-cf.yml、deploy-pages.yml 各自触发;全仓无 workflow_run/needs 关联 CI |
| S02 | 认可(独立登记,不混入本批) | #371 | `check_fade_predicate_parity.mjs:312` 无参即 exit 0,ci.yml:476 不传参;③b check_version 缺源即绿 |
| S03 | 认可(文档销账) | — | #329 fund_pct.py:110/131 LRU 已实现(8d1dc0f7a);#330 backfill:71/232 已实现;#331 第二份公式已收敛;#332 docs/ops/fund-nav-pct-rootfix-20261028.md:139-145 已补 |
| M01 | 不纳入 | — | Codex 自标「仅测量建议,收益未证实」;未给冷/热缓存实测数据 |
| M02 | 不纳入 | — | Codex 自标「仅试验建议,收益未证实」;未给检出耗时/传输量对照 |

## 4. 复核方法

主控派出 **4 个只读复核任务**独立取证:①后端 F01-F04 代码级复核 + 亲跑 Codex 复现脚本(research-20261104-reliability-repro.py);②前端 F05-F06 独立复算 + node 复现(research-20261104-frontend-repro.cjs);③S01-S03 流程与状态对账;④#333 云上生产证据取证(只读)。回执 JSON 的 `files_sha256_verified` = "9/9 与交接包声明逐位一致"。

## 5. 已知的 Codex 脚本瑕疵

F06 复现脚本(research-20261104-frontend-repro.cjs)用「第一个 `<script>` 块」定位 boot 预取逻辑;若 index.html 后续插入新的 `<script>` 块,定位会静默切错目标。建议改锚 `__bootPrefetch` 函数名或含 `firstMs` 的行,避免顺序依赖。

## 6. SHA256 校验

本目录所有文件 sha256 见同目录 `SHA256SUMS`;可用 `shasum -a 256 -c SHA256SUMS` 复验。原报告(research-20261104-report.json)sha256 = `e67c87e5e74f7032d5d053f2a67b57ee69349f039474eb28f5e99d77c429dbfe`,与回执 JSON `report_sha256_verified` 字段一致。

## 7. 恢复/追溯方式

- 原报告全文:`research-20261104-report.json`(sha256 见上)
- 主控回执:`claude-ack-20261104-recent-issues-v1.json`
- 交接摘要:`handoff-20261104-recent-issues-v1.txt`
- git 追溯:本目录由 commit 在 `feat/codex-handoff-ack-20261104` 分支引入,merge main 后 `git log -- docs/codex-handoffs/20261104-recent-issues-v1/` 可反查

## 8. 执行顺序与声明

回执 `execution_order`:①第一批(纯后端,互不冲突):#368 → #367 → #366;②第二批(前端,需构建+版本串+上线):#369+#370 同一分支;③第三批:docs 销账 + 本回执归档(已随本提交)。

**本回执不等于已获准实施。** F01-F06 六条代码修复均需各自走 implementer → reviewer → tester → main-merge → §0 上线三查完整流程;S01 待用户拍板;S02 待固化基线或显式标注后再决定是否修成真门禁。
