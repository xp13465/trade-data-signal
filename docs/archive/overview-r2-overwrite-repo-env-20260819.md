# 根治「盘中手动 upload_r2.py 未带 REPO → 读 trade 侧旧库整体覆盖 R2」通道

日期:2026-08-19
级别:B 级修复(脚本修改 + implementer skill 条款)
状态:已修复(哨兵+注释+skill 条款三件套)

## 一、根因(Researcher 命令级锚定)

**时间线**:2026-08-19 12:43:28 北京,fix 实施 agent 手动跑:
```
cd /Users/linhuichen/code/trade-data && python .../trade/scripts/upload_r2.py upload-intraday
```
因为命令没带 `REPO=` env,`upload_r2.py` 的 `STATIC_DIR` 缺省回退到脚本 ROOT=trade/,
抓走 `trade/static-site` 里 8-18 旧库 631607B 整体覆盖 R2 → 线上(实时数据)变回 8-18。

**为什么会有双重库(已确认设计,不改 DB 路径,只加守卫)**:
- `app/db.py:5` `DB_PATH = Path(__file__).absolute().parent.parent / "data" / "sentiment.db"`(cwd 在哪个 repo 就读哪个库,这是设计,别动)
- `upload_r2.py:33` `STATIC_DIR = Path(os.environ.get("REPO", str(ROOT))) / "static-site"`(这里缺省回退 trade 是破防线点)

**手动 vs 定时唯一区别**:
- 定时链路安全:launchd intraday plist 显式设 `REPO=trade-data`,`intraday_snapshot.sh:25-28` 也有 `REPO=...; export REPO`,故定时读 trade-data 8-19 正确。
- 手动命令没继承 REPO → 退化成读 trade 旧库,缺失的一环。

**命令证据**:上述 12:43 命令;双库 `score_daily` 日期差异(trade 侧停留 8-18,trade-data 已 8-19)。

## 二、修复方案(三件套)

### A. upload_r2.py 加「盘中读 trade 侧 → abort」哨兵(首选根治,Researcher 方案2)
在 `cmd_upload_intraday` 开头加 `_guard_upload_intraday()` 守卫:
1. 解析当前 `STATIC_DIR`;若解析出的目录落在 trade 侧(STRIC=...,用 `str(STATIC_DIR).find("/trade/static-site")>=0` 或 resolve 比对 trade/static-site 判为 trade 侧)
2. 且当前是交易日盘中(09:30-15:30 北京,`datetime.now(ZoneInfo("Asia/Shanghai"))`;交易日用项目 `app.calendar.is_trading_day`,异常降级周末判断)
3. 命中 → 打印「⚠ 疑似读滞后库:STATIC_DIR=trade 侧(非 trade-data),盘中拒绝上传,防覆盖线上」,退出码非 0,不执行上传。

要点:**仅在「盘中 + 读 trade 侧」双条件同时成立才 abort**(防止盘后正常跑 trade 侧导出被误拦),跳过周末。

### B. 统一入口注释 + 手动跑法固化(Researcher 方案3脚本侧)
- 哨兵注释写明正确手动跑法:`REPO=/Users/linhuichen/code/trade-data python .../trade/scripts/upload_r2.py upload-intraday`
- `cmd_upload_intraday` docstring 与脚本头部注释补「盘中手动 upload 必须显式 REPO=trade-data」提醒。

### C. implementer skill 加条款(`.claude/skills/role-implementer/SKILL.md` §3.1 R2 段)
任何 agent 盘中手动跑 `upload_r2.py` / export 相关脚本覆盖 R2,必须带 `REPO=/Users/linhuichen/code/trade-data` 前缀;哨兵兜底说明;标注「关联规范源」(`upload_r2.py:33 STATIC_DIR 缺省回退 trade` + `intraday_snapshot.sh` 显式 REPO),按 §23.8 skill 维护同步。事故:2026-08-19。

## 三、点检

| 项 | 状态 |
|---|---|
| A 哨兵(abort 判定+注释) | ✅ |
| B 统一入口注释 | ✅ |
| C skill 条款(§3.1 + 关联规范源) | ✅ |
| 落档报告(本文件 + ## 复现) | ✅ |

## 五、同类排查(§23.2③ 评估,不擅自扩大)

`upload_r2.py` 所有 `data/` 上传命令(cmd_upload_lab / cmd_upload_trade_sim / cmd_upload_index / cmd_upload_industry / cmd_upload_public_fund / cmd_upload_offshore_fund / cmd_upload_fund_score / cmd_upload_etf_score / cmd_upload_data_large / cmd_upload_all_data / cmd_upload_data_files / cmd_upload_intraday 等)全走 `STATIC_DIR / "data"` 同一缺省回退机制,即**任一**手动不带 REPO 的 upload 命令都有「读 trade 侧旧库覆盖 R2」的理论风险(机制同病)。

但本次哨兵按任务范围**只挂在 `cmd_upload_intraday`**(实际事故命令 + 盘中实时数据链路最关键):
- 盘中手动跑其他 upload cmd 概率低(多为盘后/deploy 定时跑,且 deploy.sh 本身带 REPO);
- 其余命令做同样改造会扩大本次改动面,按「只上报不擅自扩大」原则不在此次展开。
- 评估:若未来要根治机制层,可将守卫提到 `if __name__=="__main__"` dispatch 层对「盘中 + trade 侧 + 写 data/ 前缀」统一拦,一处覆盖所有 cmd(记录待办,不在本次实施)。

## 复现

**复现命令(未带 REPO → 哨兵 abort)**:
```
unset REPO; python3 scripts/upload_r2.py upload-intraday
# 若当前为交易日盘中 09:30-15:30(北京),STATIC_DIR 落 trade/static-site → 打印:
#   ⚠ 疑似读滞后库:STATIC_DIR 落在 trade 侧(非 trade-data),盘中拒绝 upload-intraday,防覆盖线上
#   正确手动跑法:REPO=/Users/linhuichen/code/trade-data python scripts/upload_r2.py upload-intraday
# 退出码非 0,不执行上传。
```

**正确命令(带 REPO → 正常放行)**:
```
REPO=/Users/linhuichen/code/trade-data python3 scripts/upload_r2.py upload-intraday
# STATIC_DIR = trade-data/static-site,哨兵不触发,正常上传。定时链路(intraday_snapshot.sh)即此形态。
```

**脚本路径**:`scripts/upload_r2.py`(guard 块在 STATIC_DIR 定义后 + `cmd_upload_intraday` 开头)
**输入依赖**:无(仅读 .env 凭证,R2_BUCKET);交易日判断读 `app/calendar.py`(`data/trade_dates.txt`)
**数据截止**:2026-08-19(本修复不重跑 data,不触碰生产数据)
**关键口径一句话**:盘中(交易日 09:30-15:30 北京)+ STATIC_DIR 落 trade 侧 → abort 拒传;REPO 缺省回退 trade 是覆盖源。
