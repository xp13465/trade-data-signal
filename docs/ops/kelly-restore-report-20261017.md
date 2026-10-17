> **落档说明**(2026-10-18,收口批):本文为 kelly trades **原样复原执行报告原文**(原在 `/tmp/kelly-restore-report.md`)。
> 生成者:mech-runner 子 agent(主树就地作业);生成时间:2026-10-17;关联上下文:取证见同目录 `kelly-truncation-forensics-20261017.md`。
> 正文以下**逐字原样保留**(历史记录不追改,CLAUDE.md §6④)。

# kelly trades 原样复原报告(mech-runner,主树就地作业,2026-10-17)

## 结论:PASS。全部 4 步数字核对通过,目标 json 已从 gz 原件级副本原子复原。

## 步骤与证据
### STEP1 验 gz 原件
- 命令:`gzip -dc static-site/data/signal_kelly_trades.json.gz | tee /tmp/kelly-orig.check.json | md5` + `wc -c`
- 结果:流 md5 = `8ace9b51e5f712a856c5a7142df1572b`(预期同值)、字节 = `86254426`(预期 86254426)⇒ PASS
- 源 gz 自身:14099991B,md5 = `eff02f2786740b03ef9e163877eeaa28`,mtime 2026-09-22 11:27(只读未改)

### STEP2 §25 先备份现状
- 复核现状 json:md5 = `bed268677bcdf8cf78eb3b4613ba5492`、字节 `86222094`(与派单描述一致)
- 命令:`cp -p .../signal_kelly_trades.json data/pre-restore-signal_kelly_trades-mirror-86222094.json`
- 复核:两处 md5 均 = `bed268677bcdf8cf78eb3b4613ba5492`,备份字节 = 86222094 ⇒ PASS
- 备份路径:`/Users/linhuichen/code/trade/data/pre-restore-signal_kelly_trades-mirror-86222094.json`

### STEP3 原子复原
- 命令:`cp /tmp/kelly-orig.check.json .../signal_kelly_trades.json.tmp-restore` → 核 md5/字节 → `mv` 覆盖目标
- 临时文件:md5 = `8ace9b51e5f712a856c5a7142df1572b`、字节 = 86254426 ⇒ 核过
- 覆盖后目标:md5 = `8ace9b51e5f712a856c5a7142df1572b`、字节 = `86254426` ⇒ PASS
- 附加校验:`python json.load` 成功,顶层 dict,keys = generated_at / buy_amount / period_cutoffs / fields / quadrants(1.0s)

### STEP4 固化 gz
- 命令:`cp -p .../signal_kelly_trades.json.gz data/kept-signal_kelly_trades-orig-20260922.json.gz`
- 复核:两处 md5 均 = `eff02f2786740b03ef9e163877eeaa28`,字节 14099991 ⇒ PASS
- 固化路径:`/Users/linhuichen/code/trade/data/kept-signal_kelly_trades-orig-20260922.json.gz`

## 三处路径(交付锚点)
1. 复原后目标:`/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json`(md5 8ace9b51…、86254426B)
2. 现状备份:`/Users/linhuichen/code/trade/data/pre-restore-signal_kelly_trades-mirror-86222094.json`(md5 bed26867…、86222094B)
3. gz 固化:`/Users/linhuichen/code/trade/data/kept-signal_kelly_trades-orig-20260922.json.gz`(md5 eff02f27…、14099991B)

## /tmp/kelly-orig.check.json
保留未删(86,254,426B)。理由:内容与 kept gz 解压流逐位一致(本任务 STEP1 已实测),kept gz 双份在位 ⇒ 可随时重生成;任务书标注"可留可删",选择保留零风险。

## 恢复路径(可逆性)
- 回退到复原前状态:`cp /Users/linhuichen/code/trade/data/pre-restore-signal_kelly_trades-mirror-86222094.json /Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json`
- 重生成原件:`gzip -dc /Users/linhuichen/code/trade/data/kept-signal_kelly_trades-orig-20260922.json.gz > signal_kelly_trades.json`

## 纪律遵守
- 改动面:只覆写目标 json 1 处 + 新建 data/ 下 2 文件 + /tmp 2 文件;源 gz 只读未改;未动代码/文档/`.claude/`;未跑 git/ssh/curl/find /。
- 后台残留:无(本次无 Bash 被转后台,无 moved to the background 记录)。