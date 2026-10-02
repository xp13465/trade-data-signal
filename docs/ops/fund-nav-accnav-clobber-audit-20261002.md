# fund_daily_nav acc_nav 被 stage0-nav 踩踏独立复核审计(2026-10-02)

> 调研 agent 独立复核另一路报告 `docs/ops/cloud-dual-tree-dataroot-audit-20261002.md` 的「stage0-nav 回填踩踏 acc_nav」结论。
> 复核手段:本机两库逐月测绘(独立锚点)+ 云上两库(REPO 主库 vs GIT_REPO signal 快照)逐月/逐日对比 + 亲自读源码 + 云上 timer/日志/DB 实证。
> 结论均带可复现证据(命令+关键输出+file:line)。实测/推断/未查三档诚实标注见 §7。

## 0. 一句话结论(与另一路报告的差异点)

**核心结论成立**:10-02 01:43 stage0-nav 二轮回填用 `INSERT OR REPLACE` 整行覆盖,把主库 `fund_daily_nav` 9-17/21/23/24 四天的 acc_nav 从 **88646 行清到 123 行**(数据回退,独立 bug)。

**但对另一路报告的三处修正**:
1. **损坏范围不是"9 月 88696→173",而是精确到 9-17/21/23/24 四天**(88646→123)。其余 9 月日期(9-1~9-16/9-18/9-22/9-28/29/30)acc_nav 本来就是 0。
2. **"stage0 首轮(9-18)清 4-8 月 acc_nav"被推翻**:2021~2025 全年 + 2026-1~8 月 acc_nav **本来就是 0**(本机未跑 stage0 的锚点库与云上 signal 快照一致),不存在被清。9-10 的本机(21920 行)vs 云上(10 行)差异是**云上采集 9-13 才起步、从未采集过 9-10**的 acc_nav,不是被清。
3. **"每周五继续清"需修正**:全量回填靠 `/tmp/pf-stage0-collect-progress.json` 断点续采。progress 完好时(9-25)周五跳过不跑;progress 丢失/重置时(10-02 前发生)才全量重跑。所以是**"progress 一旦丢/重置 + 有新增基金,周五就会跑并清"**,不是无条件每周五清。

## 1. 损坏范围测绘(最重要,独立锚点对照)

### 1.1 本机锚点库(未跑 stage0,天然对照)
`/Users/linhuichen/code/trade/data/public_fund.db`(本机定时任务已废弃,memory `local-dev-cloud-prod-split`)。

按年 acc_nav 非空:
```
2021|0/1301682   2022|0/3163543   2023|0/3798688   2024|0/4498569   2025|0/5253398
2026|21944/4146364 (0.53%)
```
2026 逐月:
```
202601~202607 全 0;  202608|2/542367;  202609|21942/231337(集中在 9-02/07/08/10 零星+9-10 的 21920)
```
结论:**2021~2025 全年 acc_nav 本来就全 NULL(历史上采集未写累计净值)。2026 年只有 9 月中旬后部分日子有值。** 这直接推翻"4-8 月被清"。

### 1.2 云上两库逐月对比(REPO 主库 10-02 vs GIT_REPO signal 10-01 快照)
命令(云上 python,逐月):
```
2026: 1~7 月 main 0/sig 0;  8 月 2/2;  9 月 main 173/547123 vs sig 88696/530646
```
**两库 1-8 月完全一致且都≈0** → 被清的只在 9 月,且是 10-01(sig)到 10-02(main)之间发生。

### 1.3 9 月逐日对比(main vs signal)
| date | main acc_nav | signal acc_nav | 差 |
|---|---|---|---|
| 9-17 | 21 | 21959 | **-21938 被清** |
| 9-18 | 0 | 0 | 一致 |
| 9-21 | 23 | 21956 | **-21933 被清** |
| 9-22 | 0 | 0 | 一致 |
| 9-23 | 25 | 21977 | **-21952 被清** |
| 9-24 | 54 | 22754 | **-22700 被清** |
| 9-28/29/30 | 0 | 0 | 一致(数据源未发布净值) |

其余日子两库完全一致(9-02/07/08/10/11 等零星行原样保留)。**被清的就是这 4 天,合计 88646→123,损 88523 行。**

### 1.4 9-10 差异定性:不是被清,是云上从未采集过
- 本机 9-10 acc_nav=21920(本机采集正常)
- 云上 signal 9-10=10 行
- 云上 daily 采集日志最早 = `public_fund_daily_20260913_*.log`(9-13 起),9-9/9-10 日志不存在;9-14 日志显示写入 `@20260911`(回写历史日期)
- 结论:云上 public_fund 采集 9-13 才起步,9-10 从未有 acc_nav,云上 9-10 的 unit_nav 是 9-18 首轮 stage0 回填的。**9-10 不算"被 stage0 清"。**

### 1.5 月度损坏表(完整)
| 范围 | 状态 | 证据 |
|---|---|---|
| 2021~2025 全年 | 本来就 0,无损坏 | 本机+云上两库三锚点一致 |
| 2026-1~8 月 | 本来就 0(8 月仅 2 行),无损坏 | 同上 |
| 9-1~9-16/9-18/9-22/9-28/29/30 | 本来就 0 | 本机+两库一致 |
| **9-17/21/23/24** | **被 10-02 二轮清空(88646→123)** | §1.3 表 |
| 9-28/29/30 unit_nav | 二轮回填补上(主库 9-30 unit_nav 有值),acc_nav 本无 | deploy 日志 DB最新=(20260930,2.1188,None) |

**结论:损坏 = 9 月 4 天 acc_nav 被清(88523 行),最早损坏日期 = 2026-09-17(无更早损坏)。**

## 2. 根因确证(亲自读源码,行号自己核)

文件 `/Users/linhuichen/code/trade/app/collector/public_fund.py`:
- **L1128**:`rows.append((d, code, None, nav, None, None, nav_pct))` —— 7 元组对应列 `(date, fund_code, fund_name, unit_nav, acc_nav, prev_unit_nav, nav_change_pct)`,`fund_name=None, acc_nav=None, prev_unit_nav=None`(报告引 L1132 有误,真实 append 在 L1128)
- **L1132-1136**:`conn.executemany("INSERT OR REPLACE INTO fund_daily_nav (date, fund_code, fund_name, unit_nav, acc_nav, prev_unit_nav, nav_change_pct) VALUES (?,?,?,?,?,?,?)", rows)`
- **L1076-1089**:fetch_nav_history 定义,`start_date = today - (days+30)`,days=1825 时覆盖 5 年,days=400 时覆盖 13 个月
- schema:`PRIMARY KEY (date, fund_code)`(本机 DB 实测)

**①INSERT OR REPLACE 整行覆盖:确证**(L1132)。REPLACE=删旧行插新行,acc_nav 位恒 None → 清掉 daily 值。
**②写入行 acc_nav 恒 None:确证**(L1128 第 5 位 None)。
**③还覆盖哪些列**:同一 REPLACE 也把 `fund_name`(None)、`prev_unit_nav`(None)覆盖了。**检查 impact:fund_name 是否受影响**——需单独验证(§6.2)。nav_change_pct 有值(由净值算),unit_nav 有值。
**④触发条件**:fetch_nav_history 仅两个调用点(L5474 backfill-nav 命令 days=400、L5531 stage0-nav 命令 days=1825),**两条路径都 REPLACE 覆盖,不区分"只有某路径"**。daily 采集(fetch_daily_nav L911)也用 REPLACE 但只写当日行,不清历史。

### 2.1 为什么 10-02 二轮清到的是这 4 天
9-17/21/23/24 是 daily 采集写入过 acc_nav 的日子(signal 快照有 88646 行)。10-02 二轮回填(接口含全部历史)REPLACE 覆盖这些行 → acc_nav 清成 NULL。9-28/29/30 数据源当时无净值,接口也无值,REPLACE 写 unit_nav 但 acc_nav 恒 None(本来就 0,无可见变化)。

### 2.2 首轮(9-18)为何没清 9-17(推断)
9-18 首轮全量跑完(batch 56/56 done=27758/27758,日志实证)。但 signal 快照(10-01)9-17 仍有 21959 行 acc_nav → **首轮没有覆盖 9-17**。推断:9-18 01:43 拉单位净值走势时接口尚无 9-17 净值行(9-17 晚发布),fetch_nav_history 对无值日期跳过(L1123-1125 `nav=None: continue`)→ 9-17 行保留 daily 值。未直接确证(诚实标注 §7)。

## 3. 复现性:是否每周五再跑

**timer 确证**(云上实测):
```
trade-pf-stage0-nav.timer: OnCalendar=Fri *-*-* 01:43:00, Persistent=true
Next: Fri 2026-10-09 01:43  Last: Fri 2026-10-02 01:43
```
stage0_nav.sh → `python -m app.collector.public_fund stage0-nav --days 1825`(云上 REPO `/home/ubuntu/code/trade-data/scripts/stage0_nav.sh`)。

运行史(日志 `stage0-nav.log`):
- 9-18 首轮:01:43~07:37,全采 27758 只(~6h)
- 9-25:**01 秒 end rc=0**(progress 完好,`已完成27758,待采0`,跳过)
- 10-02 二轮:01:43~07:44,又是 `已完成0,待采27758`(**全量重跑**)→ 清 acc_nav

**"每周五继续清"修正**:是否跑取决于 progress(`/tmp/pf-stage0-collect-progress.json` 的 nav.done)。9-25 时 nav.done=27758(pending=0 跳过);10-02 时 nav.done=0(全量重跑)。**progress 在 9-25~10-02 之间被重置,根因未完全确证**(候选:文件损坏/手动重置;已排除 tmpfiles 清理——云上无 /tmp 清理规则、uptime 19 天无重启、/tmp 非 tmpfs)。只要 progress 再丢/重置,或 fund_basic 新增基金(新 code 不在 done_set),周五就会再跑并 REPLACE 覆盖 → **周期性继续清成立,频率不固定**。

## 4. 修复方案(可执行,不实施)

### 4.1 SQL 改法(根治,只改一处)
`app/collector/public_fund.py` L1132-1136 改为 UPSERT,只更新有值字段、不碰 acc_nav:
```sql
INSERT INTO fund_daily_nav(date, fund_code, fund_name, unit_nav, acc_nav, prev_unit_nav, nav_change_pct)
VALUES (?,?,?,?,?,?,?)
ON CONFLICT(date, fund_code) DO UPDATE SET
  unit_nav = excluded.unit_nav,
  nav_change_pct = excluded.nav_change_pct;
```
约束 `PRIMARY KEY (date, fund_code)` 已确认,SQLite 3.24+ 支持 UPSERT。acc_nav/fund_name/prev_unit_nav 不再被覆盖。源码内已有 UPSERT 先例(同文件 L605-625 附近注释"UPSERT 而非 INSERT OR REPLACE")。
> 备选:REPLACE 前先 SELECT 旧行合并 acc_nav;但 UPSERT 更干净,推荐前者。

### 4.2 acc_nav 从哪补回来(穷举来源)
| 来源 | 覆盖范围 | 可获取性 | 代价 | 判定 |
|---|---|---|---|---|
| **GIT_REPO signal 库(10-01 16:01)** | 9-17/21/23/24 共 88646 行 acc_nav,= 被清前完整状态 | 云上同机直接可读 | 一条 UPDATE | **推荐** |
| R2 signal-backup 桶 | **无** public_fund.db(upload_r2.py cmd_upload_db L1977-1980 只备 sentiment.db+etf_national_team.db) | — | — | 排除 |
| 本地 release 备份(8-10)`data/release/public_fund.db.tar.gz` | 578MB,8-10,不含 9 月 | 本机 | 恢复全库 | 排除(不含 9 月) |
| 本地 trade-data 库 | 只到 9-10,云上 9-10 无 acc_nav | 本机 | — | 排除 |
| 第三方重取累计净值 | 全市场可重取 | 需要天天基金累计净值走势接口全量拉(27000+只) | 数小时~天 | 备选(成本高) |

**恢复 SQL 草案(云上执行,用 signal 库补齐主库)**:
```sql
ATTACH DATABASE '/home/ubuntu/code/trade-data-signal/data/public_fund.db' AS sig;
UPDATE fund_daily_nav
SET acc_nav = (SELECT s.acc_nav FROM sig.fund_daily_nav s
               WHERE s.date = fund_daily_nav.date AND s.fund_code = fund_daily_nav.fund_code)
WHERE date IN ('20260917','20260921','20260923','20260924')
  AND acc_nav IS NULL
  AND EXISTS (SELECT 1 FROM sig.fund_daily_nav s
              WHERE s.date = fund_daily_nav.date AND s.fund_code = fund_daily_nav.fund_code
                AND s.acc_nav IS NOT NULL);
```
恢复后验证:9-17/21/23/24 acc_nav 有值行数回到 ~88646。**注意 9-28/29/30 无 acc_nav 可恢复(数据源当时未发布,非损坏)**。

### 4.3 防再犯告警(挂哪条链)
1. **fetch_nav_history SQL 修复后**加断言:写入前统计受影响 (date,fund_code) 的 acc_nav 有值行数,写入后对比,骤降=FAIL(最直接,挂在 fetch_nav_history 内)。
2. **acc_nav 完整性日检**:check_data_integrity 加一项"最近 30 天 acc_nav 有值行数 < 阈值(如 10000)= WARN/FAIL"。当前 check 只比 DB↔产物一致性(被清+重出产物后自洽,测不出),需独立阈值判断。
3. **daily 采集全 NULL 告警**:fetch_daily_nav 若 unit_nav 全 NULL(9-28/29/30 场景)应告警(报告 P1 同)。
4. **产物日期停滞告警**:nav_bucket 最新 date 连续 N 天不推进 → 告警(报告 P1 同)。
5. **stage0 progress 丢失告警**:`/tmp/pf-stage0-collect-progress.json` 存在性 + nav.done 完整性监控(本次全量重跑的直接导火索)。

## 5. 影响面(谁消费 acc_nav)

### 5.1 前端(报告"画线只用 unit_nav"已亲自核实为真)
- `static-site/app.js` L27471-27476 净值 payload 校验:`row[1]`(unit_nav)必须 number,`row[2]`(acc_nav)可 null(`// unit_nav 必须数值(acc 可 null)`)
- L27547-27561:单位净值映射伪 OHLC `[date,v,v,v,v]`,画线/tooltip 只读 `row[1]`(L27581 tooltip 文案"单位净值")
- 全 repo 前端 JS grep `acc_nav`:**app.js/lab.js/min 版零引用**
- **结论:用户可见影响低,acc_nav 不展示**。数据层损坏(历史累计净值丢失),未来若加累计净值展示则缺数。

### 5.2 后端/产物
| 消费方 | 位置 | 影响 |
|---|---|---|
| export_fund_nav.py | L175 SELECT date,unit_nav,acc_nav → nav_bucket 桶 | 桶产物 acc_nav 全 null(桶文件实测 nav 行 [...,null]) |
| check_data_integrity.py | L1411 SELECT acc_nav,L1415-1417 DB↔产物逐位比 | **10-02 17:50 deploy FAIL 已捕捉 acc_nav 回退**(DB最新=(20260930,2.1188,None) vs 产物最新=(20260924,2.1287,2.3984)) |
| export_offshore_fund.py | L175 读 fund_performance.acc_nav | **不受影响**(fund_performance 独立表,stage0 不动) |
| 邮件链路 | 全 repo grep 无 acc_nav | 无影响 |

### 5.3 10-02 17:50 deploy FAIL 详情(实测)
```
fund_nav: DB↔产物不一致: 000065: DB最新=('20260930',2.1188,None) vs 产物最新=('20260924',2.1287,2.3984)
DB尾3=9-30/29/28 acc_nav 全 None; 产物尾3=9-24/23/21 acc_nav 有值
```
→ FAIL 除"DB 领先产物 6 天"外,**还叠加了 acc_nav 被清(DB None vs 产物有值)**。止血 agent 21:42 重出 export 用的是被污染主库 → 产物 acc_nav 变全 null → 后续 check 自洽(测不出回退)。

## 6. 补充影响核查

### 6.1 nav_bucket 桶产物实测
云上 `static-site/data/nav_bucket/00.json`:`"nav":[["20210705",3.083,null],...]`(acc_nav 已全 null)。桶 date 字段 20260929(unit_nav 到 9-29/9-30)。

### 6.2 fund_name/prev_unit_nav 是否也被清(待主控拍板后实施侧复核)
REPLACE 同样写入 fund_name=None、prev_unit_nav=None。**未验证这两列当前主库 vs signal 是否有损坏**——需实施侧对比(推荐在恢复方案里一并核对)。

## 7. 诚实标注

- **实测**:云上两库逐月/逐日 acc_nav 对比、本机锚点库、源码 L1128/L1132、timer OnCalendar、stage0-nav 三次运行日志、progress 文件内容、deploy 10-02 FAIL 详情、前端 app.js L27471-27581、nav_bucket 桶文件、schema PRIMARY KEY、R2 upload-db targets、云上 daily 采集最早日志(9-13)。
- **推断**:①9-18 首轮为何没清 9-17(接口当时无该日净值行,L1123-1125 跳过)——未直接确证;②progress 9-25~10-02 被重置的根因(候选:文件损坏/手动重置;已排除 tmpfiles/重启/tmpfs)——未确证。
- **未查**:①fund_name/prev_unit_nav 是否也被 REPLACE 清(§6.2);②R2 signal-backup 实际 key 清单(upload-db 代码已确认不含 public_fund.db,未列 R2 实查);③9-17/21/23/24 为何 daily 采集能拿到累计净值列而 9-18/22 不能(数据源侧行为,未查社区)。

## 8. 复现锚点速查

```bash
# 1) 云上两库 9 月 acc_nav 对比(主库 173 vs signal 88696)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 -c "
import sqlite3
for t,p in [(\"main\",\"/home/ubuntu/code/trade-data/data/public_fund.db\"),(\"sig\",\"/home/ubuntu/code/trade-data-signal/data/public_fund.db\")]:
    c=sqlite3.connect(p)
    r=c.execute(\"SELECT SUM(acc_nav IS NOT NULL),COUNT(*) FROM fund_daily_nav WHERE date>=20260901 AND date<=20260930\").fetchone()
    print(t, r)
"'

# 2) 根因 SQL(亲核行号)
sed -n '1128,1136p' app/collector/public_fund.py

# 3) timer
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cat /etc/systemd/system/trade-pf-stage0-nav.timer'

# 4) stage0 三次运行史
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep "stage0-nav start\|stage0-nav end" /home/ubuntu/code/trade-data/data/logs/stage0-nav.log'

# 5) deploy FAIL acc_nav 证据
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep "DB↔产物不一致" /home/ubuntu/code/trade-data/data/logs/deploy_20261002_1750.log | head -1'
```

## 9. 补充发现:fund_name 与 prev_unit_nav 也被 REPLACE 清空(2026-10-02 复核追加)

REPLACE 整行覆盖同时写入 `fund_name=None`、`prev_unit_nav=None`(L1128),**两列同样被清**。

### 9.1 量化(云上实测)
| 列 | main(10-02) | signal(10-01) | 损坏 |
|---|---|---|---|
| fund_name 非空(9-17/21/23/24) | 813/856/840/109 | 24054/24099/24098/24139 | 主库仅零星残留 |
| prev_unit_nav 非空(9-17/21/23/24) | 16/780/36/26 | 22624/23413/22663/22667 | 主库几乎全清 |
| **fund_name 全 NULL 基金数** | **24031/26596(90.4%)** | — | 主库 90.4% 基金无 name |

### 9.2 可见影响(均为实测)
- **fund_name**:export_fund_nav.py L179-189 桶 name 取 `fund_daily_nav.fund_name` 最新非空行,否则退化为 code → **桶 name 对 90.4% 基金已是 code**。但:①前端净值走势弹窗画线只用 hist.nav,未用 hist.name(L27528-27548);②基金弹窗标题用 `e.fund_name`(评分详情数据源,L27637),fund_basic 表 100% 完好(实测 27758/27758)→ **前端可见影响低**。
- **prev_unit_nav**:全 repo grep 仅 schema 定义(L276)与写入(L912/L1133),**无任何 SELECT 消费者** → 清空无实际影响。

### 9.3 恢复建议(在 §4.2 恢复 SQL 基础上)  
fund_name 建议一并从 signal 库恢复(与 acc_nav 同 SQL 模式,按 date+fund_code 补 `fund_name`);或直接用 fund_basic.fund_name 回填(更稳,27758/27758 全量)。prev_unit_nav 无消费者,可暂不恢复。

---

## 10. 补数源重大变更:审计 §4.2 推荐源已失效(2026-10-02 复核追加)

### 10.1 云上三处 public_fund.db 已全部损坏且 md5 一致

审计 §4.2 推荐「GIT_REPO signal 库(10-01 16:01)」作补数源,并给出 ATTACH 恢复 SQL。**但复核发现该源已失效**:云上三处库文件 md5 完全一致、mtime 全部 2026-10-02 16:01:38:

```
/home/ubuntu/code/trade-data/data/public_fund.db              md5=53df2a5d7fac mtime=10-02 16:01:38
/home/ubuntu/code/trade-data-signal/data/public_fund.db       md5=53df2a5d7fac mtime=10-02 16:01:38
/home/ubuntu/code/trade-data-signal-staticdata/db/public_fund.db md5=53df2a5d7fac mtime=10-02 16:01:38
```

三处内容逐位一致 = 10-02 16:01 有一轮同步/拷贝把损坏的主库覆盖到了 signal 库与 staticdata 库,**审计时的完整快照(10-01 16:01)已被覆盖销毁**。signal 库不再是补数源。

### 10.2 补数源穷举结论(2026-10-02 复核后)

| 来源 | 覆盖范围 | 可获取性 | 代价 | 判定 |
|---|---|---|---|---|
| ~~GIT_REPO signal 库(10-01 16:01)~~ | 9-17/21/23/24 共 88646 行 | **已失效(10-02 16:01 被同步覆盖)** | — | ~~推荐~~ → **作废** |
| **R2 signal-data 主桶旧 `fund_nav/` 前缀(9-20/9-21/9-22 上传)** | **26458 个 per-code JSON(全市场);9-22 批 21957 只含 9-17/9-21 acc_nav 有值;9-20 批 4453 只 acc_nav 全 None** | R2 可直接下载(实测 000001 等 9-17/9-21 acc_nav 有值) | 下载 26458 文件 + UPDATE | **唯一现成可用源(部分覆盖)** |
| R2 signal-backup 桶 | 无 public_fund.db | — | — | 排除 |
| R2 nav_bucket/(10-02 13:47 上传) | 256 桶,但 acc_nav 全 null(损坏后生成) | — | — | 排除(损坏后产物) |
| 本地 release 备份(8-10) | 不含 9 月 | — | — | 排除 |
| 第三方重取累计净值 | 全市场 9-23/9-24 可重取 | 天天基金累计净值走势接口实测可用(110022 返回 3897 行,列=['净值日期','累计净值'],尾行 2026-09-30=2.790) | 数小时~天 | 备选(9-23/9-24 唯一来源) |

**关键结论**:
- 9-17/9-21 acc_nav → R2 旧 `fund_nav/` 前缀(9-22 批 21957 只)可恢复
- 9-23/9-24 acc_nav → **R2 旧 fund_nav/ 不含(9-22 已上传,当时无这两日数据)**,唯一来源=天天基金累计净值走势重取(成本高,审计 §4.2 判定备选)
- fund_name → fund_basic.fund_name 回填(27758/27758 全量,审计 §9.3 更稳方案,不依赖已失效源)
- prev_unit_nav → 无消费者,可暂不恢复

---

## 11. 补数命令清单(2026-10-02 实施侧产出,本文件阶段不执行;执行前须经主控拍板+非盘后时点)

> 原则(§25 删除/覆盖前必备份):以下每条恢复 SQL 执行前,必须先做 DB 备份并验证可恢复。
> 目标:把 9-17/9-21/9-23/9-24 四天 acc_nav 从当前损坏态(合计 123 行)恢复到 ~88646 行,
> fund_name 90.4% NULL 回填到 100%。

### 11.0 步骤概览
1. 备份当前主库(必做,回滚前提)
2. 从 R2 旧 `fund_nav/` 前缀恢复 9-17/9-21 acc_nav(21957 只,现成源)
3. 从 fund_basic 回填 fund_name(27758 只)
4. (备选,主控拍板)天天基金重取 9-23/9-24 acc_nav
5. 验证 + 比对

### 11.1 执行前备份(必做,§25)
```bash
# 在云上(public_fund.db 是生产主库所在)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173
DB=/home/ubuntu/code/trade-data/data/public_fund.db
TS=$(date +%Y%m%d_%H%M%S)
cp "$DB" "$DB.bak-$TS"                     # 硬拷贝(2.67GB, 注意云上磁盘)
sqlite3 "$DB" ".backup '$DB.wal-$TS.bak'"  # 或 SQLite 在线备份(更稳,不丢 WAL)
ls -la "$DB"* | tail -3                     # 验证备份文件存在
# 验证可恢复: 对备份文件跑一条查询(如 SELECT COUNT(*) FROM fund_daily_nav) 能返回即 OK
```
> 回滚方式(§25④):若恢复后发现问题,`cp "$DB.bak-$TS" "$DB"` 恢复原状。

### 11.2 恢复 9-17/9-21 acc_nav(从 R2 旧 fund_nav/ 前缀,21957 只)
思路:先在本机把 R2 26458 个 per-code JSON 下载,抽(9-17/9-21)两日 acc_nav 生成中间表,再在云上主库按 (date, fund_code) UPDATE。

```bash
# 步骤 A(本机): 下载 R2 旧 fund_nav/ 前缀全部 JSON(26458 个, ~1-2GB)
# 用 upload_r2.py s3_request 翻页 list + GET(实测可用), 存到 /tmp/fund_nav_r2/ 目录
#   —— 完整脚本见本报告 §12 复现段 repro_download_fundnav.py

# 步骤 B(本机): 生成补数中间表 accnav_fix.db(只含 (date, fund_code, acc_nav) 三列, 9-17/9-21)
python3 - <<'PY'
import sqlite3, json, glob
out = sqlite3.connect("/tmp/accnav_fix.db")
out.execute("CREATE TABLE fix(date TEXT, fund_code TEXT, acc_nav REAL, PRIMARY KEY(date, fund_code))")
for f in glob.glob("/tmp/fund_nav_r2/*.json"):
    d = json.load(open(f))
    code = d.get("code")
    for row in d.get("nav", []):
        if len(row) >= 3 and row[0] in ("20260917", "20260921") and row[2] is not None:
            out.execute("INSERT OR IGNORE INTO fix VALUES (?,?,?)", (row[0], code, row[2]))
out.commit()
print("fix 行数:", out.execute("SELECT COUNT(*) FROM fix").fetchone()[0])
# 预期: ~21957 * 2(9-17/9-21) 但有交叉基金≈4 万行
PY

# 步骤 C(云上): 把 accnav_fix.db 用 scp 送到云上, 在主库执行 UPDATE
scp -i ~/tdsignal.pem /tmp/accnav_fix.db ubuntu@122.51.111.173:/tmp/
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'sqlite3 /home/ubuntu/code/trade-data/data/public_fund.db "
ATTACH DATABASE \"/tmp/accnav_fix.db\" AS fix;
UPDATE fund_daily_nav SET acc_nav = (
  SELECT f.acc_nav FROM fix.fix f
  WHERE f.date = fund_daily_nav.date AND f.fund_code = fund_daily_nav.fund_code)
WHERE EXISTS (SELECT 1 FROM fix.fix f
              WHERE f.date = fund_daily_nav.date AND f.fund_code = fund_daily_nav.fund_code)
  AND acc_nav IS NULL;
DETACH DATABASE fix;"'
```
> 预期影响:9-17/9-21 两日 acc_nav 有值行数从 21/23 恢复至 ~21957 行(以 fix.db 实量为准)。
> 验证方式:恢复后 `SELECT date, COUNT(*), SUM(acc_nav IS NOT NULL) FROM fund_daily_nav WHERE date IN ('20260917','20260921') GROUP BY date;` 比对 9-22 上传批样本(000048 等 9-17/9-21 acc_nav 有值)。
> **9-20/9-21 上传批诚实标注**:R2 `fund_nav/` 另有 9-20 批(4453 只)与 9-21 批(48 只),实测 acc_nav 全 None、nav 尾日期 ≤9-17。这些基金 9-17/9-21 有值行数极少(审计 §1.3 signal 9-17=21959,9-22 批已含 21957,差值 ≤2),9-20/9-21 批对本补数无实质贡献,保留不处理。

### 11.3 回填 fund_name(从 fund_basic,全量 27758 只)
```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'sqlite3 /home/ubuntu/code/trade-data/data/public_fund.db "
UPDATE fund_daily_nav SET fund_name = (
  SELECT f.fund_name FROM fund_basic f WHERE f.fund_code = fund_daily_nav.fund_code)
WHERE fund_name IS NULL
  AND EXISTS (SELECT 1 FROM fund_basic f WHERE f.fund_code = fund_daily_nav.fund_code);"'
```
> 预期影响:fund_name NULL 从 24031 降到 0(最多补 24031 分位,以 fund_basic 匹配为准;实测 fund_basic 27758/27758 非空)。
> 验证方式:`SELECT COUNT(*) FROM fund_daily_nav WHERE fund_name IS NULL;`(恢复前 24031, 恢复后 ≈0)。
> 注意:fund_daily_nav 有 2.6M+ 行,**本 UPDATE 会扫全表**,云上执行预计数分钟;SELECT 空列统计用 `WHERE fund_name IS NULL`,不用 `SUM(fund_name IS NULL)`(NULL SUM 坑)。

### 11.4 (备选)天天基金重取 9-23/9-24 acc_nav(主控拍板后才执行)
9-23/9-24 无现成快照,唯一来源=天天基金累计净值走势接口全市场重取。
- 接口实测:ak.fund_open_fund_info_em(symbol, indicator="累计净值走势") 返回 3897 行(110022),列=['净值日期','累计净值']。
- 已接入路径:app/collector/public_fund.py L1076 fetch_nav_history 的数据源同接口(单位净值走势),改为/新增 "累计净值走势" 分支可全史累拉。
- 成本:26458 只 × 1 请求/只 ≈ 2.7 万请求,含限速 ~数小时~天(审计 §4.2 判定)。
- 预期影响:9-23/9-24 acc_nav 恢复至 ~21977/22754 行(参照审计 §1.3 损坏前 signal 值)。
- 执行方式:复用 §11.2 步骤 B/C,源换成本机批量拉取结果。

### 11.5 恢复后验证汇总
```bash
# ① 四天 acc_nav 有值行数(期望 ~88646, 允许 9-23/9-24 未做待重取)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'sqlite3 ... "SELECT date, COUNT(*), SUM(acc_nav IS NOT NULL) FROM fund_daily_nav WHERE date IN (\"20260917\",\"20260921\",\"20260923\",\"20260924\") GROUP BY date;"'
# ② fund_name NULL 计数(期望 0)
# ③ 抽样逐位: 取 000001 9-17 acc_nav vs R2 fund_nav/000001.json 该日值(必逐位一致)
# ④ 重出 nav_bucket 产物 + deploy, 验 DB↔产物逐位比对 PASS(check_data_integrity L1415)
```

### 11.6 本阶段不执行声明(§23.15 完整版铁律)
本清单只落档,不执行。原因:①9-23/9-24 是残缺补数(需天天基金重取,成本高,需主控拍板是否值得为「前端不展示的 acc_nav」花数小时~天)②执行须避盘后定时任务时点(15:35/16:00/17:50/20:35/22:00) ③按 §25 备份先行。**在补数未执行期间,acc_nav 数据保持损坏态但对用户无可见影响(前端不展示,审计 §5.1 已核实),不构成「残缺版上线」事故。**
