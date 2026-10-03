# 独立 Review: console 洁净度哨兵挂 main-merge.sh 7.7 发版验收(独立审查报告)

- 日期:2026-10-03
- 审查者:reviewer agent(独立,fresh context,未读实施者复现脚本)
- 被审分支:`worktree-agent-a5e9d82d968afd895`(origin,已 push)
- 被审 commit::`1ba0e0058`(base = origin/main `7fd2dbbb0`,merge-base 确认干净)
- 改动 3 文件:`scripts/main-merge.sh`(+42,新增 7.7 步)/ `scripts/playwright-accept/accept_console_clean.mjs`(加严三态退出码)/ `scripts/playwright-accept/README.md`(补索引行)
- 审查要点:⚠️ 改的是 push main 唯一统一入口,爆炸半径=全线发版停摆,按最高标准审

## ① 影响面(§15 核心)

**7.7 插入位置**:在 7.6(文档时点口径机检)之后、8.5(pending-index 销账软提醒)之前,与其前后步骤无数据/变量依赖(8.5 只依赖第 4.5 步 `PRE_MERGE_BASE`,7.7 不触碰)。

**shell 变量作用域**:逐项核对
- `CC_RC`(新):grep main-merge.sh 全文仅本块 1 处引用,无覆盖冲突。
- `SKIP_CONSOLE_CLEAN`(新):全文仅本块 1 处,无冲突。
- `BASE_URL`:`BASE_URL=... node ...` 是命令前缀赋值,且在外层 `( cd "$REPO" && ... )` 子 shell 内,不泄漏到当前 shell(实测上下文无影响)。
- `DRY_RUN`/`REPO`:头部既有定义,复用。
- `set -u`:所有引用均有定义或 `${VAR:-}` 默认(`${SKIP_CONSOLE_CLEAN:-0}`),无 unbound。
- `set -e`:`( cd "$REPO" && ... ) || CC_RC=$?` 惯用捕获,非零被接住不会意外退出;只有 `CC_RC -eq 1` 分支显式 `exit 1`(预期行为)。
- 结论:**无变量泄漏/覆盖,无预期外退出路径。**

**dry-run 路径**:`if [[ "$DRY_RUN" == "1" ]] → echo "[dry-run] 跳过 console 洁净度哨兵"`,与 7/7.5/7.6 三处逐字同模式(均 `if [[ "$DRY_RUN" == "1" ]]; then echo "  [dry-run] 跳过 ..."`),确认一致。

**push 前/后**:7.7 在 merge(第 5 步)之后、push main(第 9 步)之前。哨兵 FAIL 时 `exit 1`,**不 push**,远端 origin/main 保持干净。

**半完成态专项(本单最关键)**:哨兵 FAIL(exit 1)时本地状态 = 本地 main 已含 merge commit(第 5 步已 merge)+ 工作区可能有未提交的 build_min/bump 产物(第 6 步),**远端 origin/main 未被污染**。重跑 main-merge.sh 幂等:第 3 步检测"本地领先"跳过 rebase,第 5 步 merge 输出 Already up to date,第 6/7/7.5/7.6/7.7 重跑。**该半完成态与既有 7/7.5/7.6 FAIL 路径同质,非哨兵引入的新风险**(7/7.5/7.6 同样在 merge 后、push 前 exit 1)。未发现"push 后 FAIL"或"FAIL 后无法恢复"的路径。memory `main-merge-fail-leaves-half-merged-main` 场景未扩大。

## ② UNREACHABLE(exit 2)放行设计判定

**弱点成立性**:「线上长期不可达(域名挂/CF 配置错)→ 哨兵永远放行 → 形同虚设」成立。实施者的兜底理由「main-merge 本身 push 依赖网络,真全网断 push 也会失败自然拦」**不完整**——git push 走 GitHub,与线上域名(ss.fx8.store)可用性独立,域名挂不影响 push。**真实兜底是**:哨兵定位是「#133 复发防线的一环,不是唯一机制」(CSP 白名单 worker/headers.js 是单独部署链),漏检不构成全放手。

**判别可靠性**:「不可达」与「真实违规」正交——CSP 违规走 console 事件捕获(`page.on("console")`),goto 失败走 `page.goto` 抛错,两者统计独立。实测混合场景(2/6 路由不可达 + 违规)返回 exit 1(违规优先),代码顺序确认:汇总后 `if (fail > 0) exit(1)` 先于 `if (gotoFailTotal > 0) exit(2)`。**「能连上但页面加载失败被误判 UNREACHABLE 放行」的场景:csp/pageerror 计数与 goto 失败相互独立,违规不会被不可达掩盖。**

**醒目程度**:SKIP 分支为整框 `█...█`(强烈);UNREACHABLE 分支为一行 `[UNREACHABLE]` + 一行 `██ 主控注意... ##`(均含「未验证线上洁净度」语义),中等醒目,主控正常操作可见。**建议(不阻断)**:UNREACHABLE 提示补一句「若连续多次发版均 UNREACHABLE,请人工核查线上可用性(哨兵可能形同虚设)」,与 SKIP 同级强度。

**判定:该设计该保留**(不可达若阻断,CDN 单次抖动即锁死发版,代价不对称;哨兵定位为辅助防线,违规仍有部署链/下次硬拦截兜底)。建议两条补强(见上 + UNREACHABLE 提示升级整框),不阻塞 merge。

## ③ 逃生门 SKIP_CONSOLE_CLEAN=1

- 真能跳过:elif 分支命中即打提示不执行哨兵,静态核对确认。
- 真打醒目提示:整框 `█...█` +「已跳过 console 洁净度检查」+ 事后补跑命令。不静默。
- 意外触发路径:变量名唯一、无默认值陷阱(`${SKIP_CONSOLE_CLEAN:-0}`),grep 全文仅本块 1 处;main-merge 为主控本地手动跑,非 CI;即便环境恰有该变量=1 也走醒目提示分支(可被看见),无静默跳过路径。

## ④ 独立证伪对照(自行复现,未读实施者复现脚本)

独立搭建:被审版本脚本取自 `git show 1ba0e0058:<path>` 原文,置于独立目录 + symlink 主树 playwright 依赖;第二个实现为自写可编程本地服务器(违规页/纯净页/奇偶请求 destroy 三模式)。**与实施者「四场景」独立平行实测**:

| 场景 | 复现方式 | 实测结果 | 期望 |
|---|---|---|---|
| 线上正常 | BASE_URL 默认,打线上三路由×两视口 | CSP 违规=0 pageerror=0,exit **0** | 0 |
| 纯净页(防假红) | 本地 8767 serve 无违规页 | exit **0**,4 断言全 PASS | 0 |
| 死 URL(全不可达) | BASE_URL=http://127.0.0.1:1 | 路由加载失败 6/6,exit **2**,打 [UNREACHABLE] | 2 |
| 注入违规(防假绿) | 本地 8765 serve 带自违规 CSP meta 页(真实浏览器 console 报 CSP violation) | CSP 违规=2(每视口 1,Chromium 同源去重),exit **1**,输出含 csp 样例文本+视口+路由(可操作) | 1 |
| 部分不可达+违规(优先级) | 本地 8766 奇数请求 socket destroy、偶数返回违规页 | 路由失败 2/6 + 违规 2,exit **1**(违规优先于不可达) | 1 |

- **证伪对照(防假绿/假红双向)**:违规页真实触发浏览器 CSP violation console 消息并被判 exit 1(假绿不可能:红色端已验证会亮);纯净页 exit 0(无违规不误伤,假红不可能)。「判据永不匹配 → 永远 PASS」的假绿场景:判据为 `/Content Security Policy|violates the following/i` 固定正则,自写违规页被该正则命中实测 FAIL,证伪对照成立。
- **失败输出可操作性**:exit 1 输出含 `csp样例:`(违规文本前 160 字符)+ `[mobile 390]/[desktop 1280]` 视口 + 路由级汇总;实测样例文本为真实 CSP directive 引用,修复定位可用。

## ⑤ 误伤正常发版风险(生产稳定性 P0)

- **耗时实测:34.8 秒**(2.36s user + 0.71s system,8% cpu)。实施者自述「约 1 分钟」偏保守,实际更快。每发版 +35s,可接受。
- **线上当前真实 CSP 违规**:实测 0 违规 0 pageerror(2026-10-03 ~12:00,主树旧版 + 被审版本双跑一致)。但线上存在 **9 条 `net::ERR_EMPTY_RESPONSE`**(每视口,东财 push2 类外部源空响应,缺 _EM_HOSTS failover)——**不阻断**(errors 数组不计入 fail,设计如此),与 #133 收尾登记 #148 一致。
- 「上一个发版带违规会阻断新代码发版」:合理。§15 核心=坏的不该上线;线上已带违规先修再发新,是正确顺序;有 SKIP 逃生门。
- **环境因素假 FAIL 面**:
  - Playwright launch 异常(版本漂移/浏览器缺失)→ uncaught exception → exit 1 → **会假 FAIL 阻断**(安全方向),主控可见 stderr 输出可分辨,有 SKIP 兜底。
  - 网络抖动/单路由加载失败 → exit 2 **放行**(不会假 FAIL)。设计方向正确。
  - 超时:goto timeout 60s×6 路由最坏 6 分钟,但超时即计入 gotoFail(exit 2 放行),不会无限卡。实测每路由实际 ≈4.8s(含 5s waitForTimeout)。

## ⑥ 范围与冻结

- 超范围改动:无。diff 仅 3 文件(主链 +42/哨兵 +28-5/README +1),逐行核对无越界。
- 告警阈值/降噪规则/去重窗口:未动(本单为 #133 复发防线,与 #123 告警降噪无交,无 §23.7 触碰)。
- 版本串 bump / rebuild min:未动(改的 main-merge.sh 本身是 bump 入口,非前端源码;diff --stat 无 static-site 产物)。§24 机制 C 由 main-merge.sh 统一负责,本次不是前端源码改动,无需 bump。
- §21 公示:本单无算法改动,不涉及。
- deploy.sh 未挂哨兵(实施者明确,避与补数任务撞;grep deploy.sh 无 accept_console_clean 引用)——挂 main-merge(代码上线正位)决策合理。

## 判定

**PASS(可 merge)**,附两条不阻断建议:
1. UNREACHABLE 分支提示补「连续多次 UNREACHABLE 请人工核查线上」+ 升级整框醒目度。
2. node 不可用分支(1 行 ⚠️)可升级为 SKIP 同级提示(虽 main-merge 依赖环境几乎必装 node)。

## 复现段

前置:node v25.8.0 + 主树 `scripts/playwright-accept/node_modules`(playwright,chromium-1234 已装)。
被审版本脚本:`git show 1ba0e0058:scripts/playwright-accept/accept_console_clean.mjs` 原文,置于独立目录 + `ln -s <主树>/scripts/playwright-accept/node_modules <目录>/node_modules`。

1. 线上: `node accept_console_clean.mjs` → 期望 exit 0,CSP 违规=0 pageerror=0,实测 34.8s。
2. 全不可达: `BASE_URL=http://127.0.0.1:1 node accept_console_clean.mjs` → 期望 exit 2,实测 6/6 路由失败 + `[UNREACHABLE]`。
3. 违规阻断: 本地 8765 serve `csp_violator.html`(meta CSP `default-src 'none'` + 内联 script)→ `BASE_URL=http://127.0.0.1:8765 node accept_console_clean.mjs` → 期望 exit 1,实测 CSP 违规=2 + `csp样例:` 输出。
4. 优先级(违规优先): 本地 8766 奇偶服务器(奇数请求 destroy、偶数返回违规页)→ 期望 exit 1,实测路由失败 2/6 + 违规 2 → exit 1。

(测试服务器与临时文件已清理;worktree git 状态干净)
