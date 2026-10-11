# B2 低危欠账清理批 — 独立审查报告(2026-10-11,周日)

> **残留后台任务声明**:无。全量 pytest 为审查方**主动** run_in_background(id `blds1qd2d`),已完成(exit=1,即 3 failed/746 passed/2 skipped)并已核销;全程无 harness 自动转后台(`moved to the background`)事件,无遗留进程。

- 审查对象:`feat/next-steps-b2-lowrisk` @ `ea3690ecd`(rebase 于 `origin/main` `860fe3d6c`;原 `f59b1b308` 已废弃)
- 审查方:reviewer agent(独立 context,§15 B 级硬门槛:notify.py 生产代码 + 测试基建 conftest/_wrap_util 广涉及面)
- **总判定:PASS**(merge 前硬门槛通过;2 条同型残余面观察 O-1/O-2 + 2 条记录项 O-3/O-4,均不阻断)

## 0. 审查方法与独立复现(不信实施报告,全部独立复跑)

| 复现项 | 命令/手段 | 结果 |
|---|---|---|
| 红先验(main 版 notify.py) | /tmp 副本 scripts + 覆盖 main 版 notify.py(md5 `c943ed81…` vs 修复版 `9a669553…`),跑新测试 | **10 failed / 4 passed** — 与实施报告逐条一致,10 个 FAILED 与静态预测逐条吻合 |
| 修复版 | 同一测试,工作区版 notify.py | **14 passed in 0.06s** |
| 全量 | `pytest -q scripts/tests/`(CI 同命令) | **746 passed / 2 skipped / 3 failed in 81.59s** — 期望值逐字命中 |
| 零外发 | 测试内 `_boom` 哨兵 + 审查方另建全局 socket guard(`/tmp/b2-guard/sitecustomize.py`,先自证 `GUARD-OK` 再跑) | 全程无任何真实外发(邮件/飞书/TG/socket 一律拦截即响亮失败) |
| min 哈希 | 工作区版与 main 版 style.css 分别过 rcssmin | 均 = **253519 B / `d1c8a3db868dc16c90b16bd4d3c719b6`** |
| 污染检测 | 跑前 touch `/tmp/b2-run-marker`,`find -newer` 扫双树 | 见 §二 O-1/O-2(主仓 data/alerts、data/feishu_requests **零新增**) |

diff 面 15 文件与实施报告完全吻合:`alert-denoise-batch2-20261009.md` / `next-steps-b2-report-20261011.md` / `check_failed_units.py` / `nextday_plan.sh` / `notify.py` / `_wrap_util.py` / `conftest.py` / `test_229_230_notify_dryrun_gates_20261011.py` / 5 个 legacy 包装 / `update_all.sh` / `style.css`;无根 data/ 混入、无 style.min.css 提交。

## 一、逐项结论(10 项审查重点)

### 1. dry-run 门控正确性(最重要)—— PASS
- **红先验三层闭合**:main 版 10 failed(与静态预测的十个未加门控写盘路径逐条吻合)→ 修复版 14 passed → 负控(dry_run=False 写路径)4 passed 佐证写路径未被误伤。
- 代码逐字核:`log_info`(:1687)最前 `if dry_run: …return False`,且唯一调用点 `send_tiered` info 分支透传 `dry_run=dry_run`(:2527);`flush_warning_batch`(:2133)/`flush_digest`(:2350) 的 dry_run 短路**置于 mkdir/open 之前**;非 dry-run 路径默认值 False、逐字等价走原路径(**不误伤真实运行**,只多一行 stderr 打印在 dry-run 分支内)。
- 同型面 `--flush-digest`(#230 举一反三)一并修 + 回归机检,门控位置正确;`sent and not dry_run` / 二次确认 `and not dry_run` 等清理条件在 dry-run 下全部只读。

### 2. REPO 隔离穷举性 —— PASS(主项)+ 残余面见 O-1
- 11 个 notify 落盘常量:全核为 Path、登记齐全;双层机制正确——调用时解析(如 `_ledger_path()` 读 env)+ import 期绑定常量经 `_redirect_repo_paths` 显式重绑;重绑在 `import_module` **之后**执行(meta 顺序正确)。
- 13 个常量(notify 11 + feishu_ws_listener 2)扁平化映射无撞名;`_restore_modules` 两层快照 + `_restore_env` + `rmtree` 收尾链完整。
- 5 个启用隔离的包装逐一核对;6 个未启用包装逐一复核:**5 个确不写主仓**;**1 个订正**——test_agent_inbox_watcher 写主仓 data/logs(见 O-1)。
- **正向实证**:全量复跑后 worktree `data/feishu_requests/`、`data/alerts/` 均无;主仓 data/alerts、data/feishu_requests 零新增(跑前跑后 find 对拍)→ 合成数据零进主仓业务目录,机制有效。
- feishu_ws_listener 2 常量形态核:`FORWARD_DEDUP_PATH`(:78)/`AUTODONE_DEDUP_PATH`(:252)均 Path 派生,登记正确。

### 3. #226 conftest atexit 清理 —— PASS
- `atexit.register(shutil.rmtree, _ENV_SHIM_DIR, ignore_errors=True)` 在 mkdtemp 之后注册:正常退出与 SIGINT/SIGTERM(Ctrl-C 触发 KeyboardInterrupt → 解释器退出)均触发;仅 SIGKILL 不触发(不可避,属正常限制)。
- ignore_errors=True 不掩测试结论;多 pytest 进程各自 shim 不互删;全量复跑全程无异常。

### 4. nextday_plan.sh 兜底句文案 —— PASS
- 两类原因(①产物未生成 ②已生成但 R2 上传未同步/关键通知未送达)与 generator 退出码全貌对齐:`return 2` ×4(产物侧)+ `return 1`(r2_rc or notify_rc)+ `sys.exit(2)`(未捕获异常);「py 侧两者同交非 0 退出」如实。
- dedup key `nextday_plan_fail` sh 与 py 已统一(#247 已做):「py 已发时本条被抑制;py 未发时本条兜底」与实际抑制逻辑一致。

### 5. #240 订正准确性 —— PASS
- 同类面 10→16 订正:21600 相关计数独立复算 = 16,与文档逐一对应;行号→文案锚([notify] 汇总:全部渠道未发出,notify.py:2846/2849)可定位。P-1/P-4/P-5 残余文书订正与现状一致。

### 6. #236「222s」来源 —— PASS
- 来源文档(`236-f2-alert-upload-decouple-20261009.md`)自洽:10-08 实测排队 222s(19:33:06→≈19:36:48);update_all.sh 3 处 211s→222s 与来源一致;grep 无 211s 残留。

### 7. min 哈希不变 + 未自行 bump —— PASS
- 两版 style.css 经 rcssmin 均 = 253519 B / `d1c8a3db868dc16c90b16bd4d3c719b6`,与仓内 style.min.css md5 一致 → 纯注释、min 产物零变化。
- diff 无 app.js/lab.js/sw.js/版本串文件 → 未自行 bump,判断正确(注释级改动无需;bump 归 main-merge.sh 机制 C)。

### 8. diff 面 15 文件 —— PASS(清单见 §0,与实施报告吻合)

### 9. 全量 pytest 独立复跑 —— PASS(期望值逐字命中)
- **746 passed / 2 skipped / 3 failed**=实施报告声明值;3 failed 逐条核实为既有预期:test_188(`upload_r2.py:3730` UnboundLocalError,fetch 失败分支,周日环境触发)+ test_245×2(时间敏感:23:25 前应 no-op / 隔日 stale)——均归 B6/B7 修复(已在 main,本分支 rebase 于 `860fe3d6c` 未含,**预期仍挂,勿动勿修**)。
- 无第四类失败、无 collection error、无跳过数漂移。

### 10. §23.2 同类面抽查 —— PASS
- 抽查 3 条:①dry-run 落盘点表(log_info/flushlock/digest lock/write_alert #184 先例)②21600 16 处复算 ③flush-digest 同型扩面——逐项见上。
- 抽查延伸发现 1 条同型残余面(O-1,见下)。

## 二、问题清单

### O-1(中置信,同型残余面,pre-existing 非本批回归)—— agent_inbox_watcher 未纳入隔离,跑 pytest 写主仓 data/logs
- **现象(实测)**:本机全量复跑后,主仓 `/Users/linhuichen/code/trade/data/logs/agent_inbox_watcher.log` 新增合成行(`rev-test-003`/`t-verdict-003`,mtime 10:25:40 = 复跑时刻)。
- **根因**:`agent_inbox_watcher.py:23 REPO = Path("/Users/linhuichen/code/trade")` 硬编码主仓;:29-30 `LOG_DIR/LOG_FILE` import 期由 REPO 派生绑定;原测试 patch `w.REPO`(:110/:274)不更新已绑定的 LOG_DIR/LOG_FILE;`_REPO_PATH_ATTRS` 未登记该模块,包装未启用 isolate_repo。
- **定性与影响**:与本批已修的 feishu_ws_listener 病灶**逐字同型**(import 期绑定量 + legacy 套件),属隔离作业「同类面清单」未穷举(§23.2);本批前即如此,**非本批引入的回归**;危害=主仓日志 append 合成行,无数据产物、无外发;`log()` 有 try/except 兜底,CI 不炸。
- **建议补法(不阻断 merge)**:`_REPO_PATH_ATTRS` 登记 `"agent_inbox_watcher": ("LOG_DIR", "LOG_FILE")` + 该包装 `isolate_repo=True`(机制现成,约 2 行);同时把「6 包装均不写主仓」订正为「**5 个**均不写,agent_inbox_watcher 写主仓日志」。

### O-2(低置信,同型残余)—— feishu_ws_listener LOG_PATH 硬编码 trade-data 树
- `log()`(:81-91)写 `/Users/linhuichen/code/trade-data/data/logs/feishu_listener.log`(复跑实测有新行);有 try/except 兜底(CI 安全),写的是镜像树非主仓;属「硬编码绝对路径不受 REPO 隔离」类。可选补(登记重定向)。

### O-3(记录,非本批)—— notify.py:2256/2257 pre-existing 重复行
- `sent = any(results.values())` 双写,来自 main 历史 commit(`9e1dae8024`/`e14791969e`),origin/main 同存在 → 不算本分支 finding,走 §23.7⑤ 上报通道提一句,由主控定去留。

### O-4(低置信)—— notify_sent.py 注释旧行号引用(notify.py:2359/2362)
- 疑似归 #241 范畴(可能已闭环);下批顺手核对即可。

### 已滤低分项(<80,仅记录)
- 静态机检 `test_static_flush_dry_run_short_circuits_before_lock` 只断言「`if dry_run:` 出现在 mkdir 前」,不防「dry_run 分支不 return」的退化写法(行为用例已覆盖,机检强度改进建议)。
- 实施报告 §5「已删 ahead=0 分支」表述与派单背景小出入(不涉代码,不影响 merge)。

## 三、总判定:PASS

- 本批 10 子项逐项独立验证与实施报告一致;核心项(dry-run 门控)红先验 / 修复版 / 负控三层闭合复现;隔离机制「双树零污染」有跑前跑后对拍实证;全量 746/2/3 逐字命中且 3 失败为既有预期。
- **不阻断项**:O-1/O-2 为同型残余面(pre-existing,建议作为低危补点或在 B2 收尾顺手补),O-3/O-4 为既有记录项。**本批改动本身无可阻断 merge 的 finding。**
- merge 资格:内审 PASS(§23.14,外审用户点名制起,merge 门槛=内审 PASS + §0 上线验证,不等待外部报告)。

---
复现链:
- 红先验副本:`/tmp/b2-redcheck/`(main 版 notify.py md5 `c943ed81…`);修复版 md5 `9a669553…`
- 全局 guard:`/tmp/b2-guard/sitecustomize.py`(自证 GUARD-OK);全量日志:`/tmp/b2-full-pytest.log`;污染基线:`/tmp/b2-run-marker`
