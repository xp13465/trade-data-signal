# #193 R2 通道覆盖缺口根治(同族静默根治第一批)

- 日期: 2026-10-05(晚)
- 分支: `feat/193-r2-channel-coverage-20261005`(只推 feat, 不推 main; 未自行 bump 版本串)
- 基线: `bf8a58429`(base-fresh 已核)
- 关联: #188(台账机制来源) / §18 L48(自测打桩) / §22(登记点一致) / §23.2(同类错误面) / §23.3(举一反三) / §23.5(落档四件套)
- 落档四件套: 本体=本文件 · 生成/校验脚本=`scripts/check_r2_channel_coverage.py` + `scripts/test_193_r2_channel_coverage.py` · 复现段=文末 `## 复现段` · 配套 commit=同一 commit

---

## 1. 结论(TL;DR)

三处缺口里 **两处是真静默缺口(已修)**, 一处是 **设计非漏配(已就地写清理由)**:

| # | 缺口 | 判定 | 处置 |
|---|---|---|---|
| ① | `offshore_fund` / `fund_score` 前缀不在 `_R2_CHANNELS` | **真缺口(静默)**: 连周日全量都不对账; `fund_score` 链每日活跃且是前端 fallback 数据源 | 补 2 个通道登记 + 上传失败 loud 化 |
| ② | `news_digest/` 归档(31 json 子目录) 无通道覆盖 | **真缺口(静默)**: 非递归 glob 扫不到, 且登记进台账后成「死键」被过滤 ⇒ 归档层永不对账 | 补 `news-digest` 通道(`patterns=["*.json","*/*.json"]`) |
| ③ | `_DATA_EXCLUDE_PREFIXES` 也排除 `offshore_fund`/`fund_score` | **设计非漏配**: 二者上传到**独立 R2 前缀**(非 `data/`), 若不排除会被 all-data/data-large 再传一份 = 双副本 | 就地写清理由(代码注释), 不改行为 |

根因(一条): **「上传侧写出的 R2 前缀集合」与「对账侧 `_R2_CHANNELS` 清单」是两份独立登记点, 漏配即静默**。
本轮不是逐文件补刀, 而是补登记 + 把漏配变成可执行机检(`check_r2_channel_coverage.py`)。

---

## 2. 三处缺口的取证与判定

### ① 通道补齐: `offshore_fund` / `fund_score`

- 事实: 二者此前只在**上传侧**存在(`cmd_upload_offshore_fund` L1726 `_upload_glob(..., "offshore_fund")` / `cmd_upload_fund_score` L1748 `_upload_glob(..., "fund_score")`), **对账侧 `_R2_CHANNELS` 无对应项** ⇒ `verify-r2` 平日/周日都不会 HEAD 这些 key。
- `fund_score` 是**每日活跃**链(`update_all.sh:228-238`: export → rsync → `upload_r2.py upload-fund-score`), 且上传失败**只 `echo`**(`update_all.sh:237-238`), 又**不在 deploy 的 `R2_FAIL` 框架**里(`r2_upload_async.sh:165-190` 通道清单有 `upload-etf-score`, 无 `upload-fund-score`)⇒ 无 `verify-channels` 轻量兜底 ⇒ **用户侧完全静默**。
- 用户可见性: 前端 `app.js` 以 `https://ss.fx8.store/r2/fund_score/fund_score_top.json` 作**场外基金评分 fallback 数据源** ⇒ 该前缀停更 = 用户看到旧评分。
- `offshore_fund`: 定时链 2026-08-22 P2-15 已停用(零消费方, `#84` 手动用), 但命令仍在、仍会被手动调用 ⇒ 同样补登记(文件不存在时通道自动跳过, 零成本)。

### ② `news_digest/` 归档

- 事实: 归档结构 = `static-site/data/news_digest/<YYYY>/<date>.json` + `_index.json`(当前 31 个)。
- 此前**无任何通道覆盖**: `all-data` 通道是 `data/` 下的**非递归** `*.json`, 扫不到子目录; 而 `fetch_news.py:sync_news_digest_live` 走 `upload-data-files`(前缀 `data`)把归档 key 登记进 #188 台账后, 因「非递归 glob 扫不到」被判为**死键过滤掉**(`_record_standalone_keys` 的 P2-2 过滤)⇒ 归档层**任何模式都不对账**, 且日志里连提示都没有(死键只在 stderr 打一行「N 个 key 扫不到」)。
- 修法: 新增 `news-digest` 通道, `patterns=["*.json","*/*.json"]` **精确递归到「年目录一层」**(正好覆盖实际结构; 不写 `**` 全局递归, 免吞掉未来更深子目录与其它通道双传)。

### ③ `_DATA_EXCLUDE_PREFIXES` 排除 offshore_fund/fund_score —— 设计判定

`_DATA_EXCLUDE_PREFIXES = ("industry-", "public_fund", "offshore_fund", "fund_score", "etf_score_list")` 的语义是
「`all-data` / `data-large` 这两个 `data/` 前缀通道**不收录**的文件前缀」。
`offshore_fund`/`fund_score` 上传到**独立 R2 前缀**(`offshore_fund/…`、`fund_score/…`, 不是 `data/…`), 本地文件却躺在 `static-site/data/` 下 —— 若不排除, `all-data` 就会把它们**再传一份到 `data/` 前缀**(双副本、双倍流量、R2 上留两份真相)。
⇒ **排除是设计, 不是漏配**。已在代码处(`_DATA_EXCLUDE_PREFIXES` 定义上方)写明该理由, 防后人误判为「漏登记通道」而顺手删掉。

---

## 3. 修法(根因, 非逐文件补丁)

### 3.1 通道登记(2 + 1 项)

`scripts/upload_r2.py:3255-3284` 新增三项(含逐条理由注释):

```python
{"label": "offshore-fund", "local_dir": lambda: STATIC_DIR / "data", "patterns": ["offshore_fund*.json"],
 "r2_prefix": "offshore_fund", "state_name": None},
{"label": "fund-score", "local_dir": lambda: STATIC_DIR / "data", "patterns": ["fund_score*.json"],
 "r2_prefix": "fund_score", "state_name": None},
{"label": "news-digest", "local_dir": lambda: STATIC_DIR / "data" / "news_digest",
 "patterns": ["*.json", "*/*.json"], "r2_prefix": "data/news_digest", "state_name": None},
```

`state_name=None` 语义(新引入, 头部注释已声明): 这三条链的上传命令走 `_upload_glob`(**不写** `.r2_<ch>_state.json`), 没有 `changed` 增量语义 ⇒
- **周日全量**: 直接 `to_check = files`, 全覆盖(修好了「连周日都不对账」);
- **平日**: `changed_rels` 恒空, 覆盖由「全池均匀抽样 100(`_uniform_sample`) + #188 独立链台账」承担。三者文件数都极小(fund_score 2 / offshore_fund ≤7 / news_digest 31)⇒ 抽样 100 即全量。

### 3.2 失败 loud 化(复用既有轮子, 不新造)

- 新增 `_notify_channel_upload_fail(label, cmd_name, r2_prefix, ok, total, failed_rels)`(`upload_r2.py:1683`):
  复用 `scripts/notify.py`(`check_dedup` 6h 窗口 + `send(severe=True, from_prefix="[告警]")` + `update_dedup`), **判据锚在退出码 `ok != total`**(稳定标识), 不 grep 日志文本/不按字段值过滤(→ memory `data-source-switch-field-filter-blindspot`)。
- `cmd_upload_offshore_fund` / `cmd_upload_fund_score` 失败路径: `notify` + `sys.exit(1)`。
- **单点修**: 放在**上传命令内部**(而非三个调用方 `update_all.sh:237` / `pf_score_daily.sh:46` / `pf_score_weekly.sh:46`) ⇒ 一处覆盖全部调用方, 且**不会重复告警**。
- 未迁移到 `_incremental_upload`: 该引擎有 `export-guard L3`(无状态首跑全量被闸), 首跑会被拦 ⇒ 生产事故风险; 故维持 `_upload_glob` + 命令级 notify。

### 3.3 台账机制注释补强(要求 3)

- `_load_standalone_keys` docstring 与 `_LEDGER_*` 常量注释已显式写明: **「台账状态非 ok = 平日对账覆盖静默退化为空集, 必须显式发声」**(#188 落地, 本轮复核保留并确认调用方 verify-r2 有 dedup 告警兜底)。
- **未新建第二本台账**: 复用 `data/.r2_standalone_keys.json`(#188)。
- 连带修正 3 处**因本轮改动而变过时的注释**(§22 一致性): `_channel_files` / `_reconcilable_keys_for` / `_record_standalone_keys` 里原以「`news_digest` 子目录键」为**死键样例**, 本轮后它已可对账 ⇒ 样例改为「无任何通道 glob 覆盖的子目录键」并注明变更。

---

## 4. §23.2 修 bug 三铁律 —— 同类错误面清单 + 逐项自测

**错误面定义**: 「会 PUT 数据到 R2、但失败只 `echo`/不发声」的上传路径。穷举全仓 `_upload_glob` / `_incremental_upload` 消费者:

| # | 消费者 | 失败是否 loud(修前) | 判据/证据 | 本轮处置 |
|---|---|---|---|---|
| 1 | `cmd_upload_offshore_fund` | ❌ 仅调用方 echo | `upload_r2.py:1726-1733` | **已修**(notify+exit1) |
| 2 | `cmd_upload_fund_score` | ❌ 仅调用方 echo | `upload_r2.py:1748` + `update_all.sh:237-238` | **已修**(notify+exit1) |
| 3 | `cmd_upload_intraday` | ✅ 本就 loud | `upload_r2.py:2116-2117` `sys.exit(1)` | 不改, **加断言** |
| 4 | `cmd_upload_data_files` | ✅ 本就 loud | `upload_r2.py:2255-2256` `sys.exit(1)` | 不改, **加断言** |
| 5 | `cmd_verify_r2` 补传段 | ✅ 本就 loud | `upload_r2.py:3507,3513-3515` `FAILED_FILES` + `exit 1` | 不改, 读码确认 |
| 6 | `_incremental_upload` 内部(12 通道) | ✅ 引擎内 loud | `upload_r2.py:1460-1468` `FAILED_FILES` + `exit 1` | 不改, 读码确认 |

**逐项自测结果**(`test_193` 的 [D]/[D4]/[D5] 段, notify 已打桩):
`cmd_upload_fund_score` 失败 → exit 1 + 发告警 ✓ / 成功 → 不告警 ✓ / `cmd_upload_intraday` 失败 → exit 1(本就 loud)✓ / `cmd_upload_data_files` 失败 → exit 1(本就 loud)✓。

**发现但本轮未改(超本任务范围, 主动上报不静默 §23.11)**:
`update_all.sh:235-236` 的 **`fund_score` rsync 失败仍只 `echo`**(「⚠ fund_score rsync 同步失败, 可能发布不全」)。
它属同一症状族(「发布不全 → 只 echo」), 但机制不同(本地树同步, 非 R2 上传), 且派单禁区限定「只动 R2 通道侧」, 故**不动 update_all.sh**, 在此记录 + 给现成处置样板:
按 `update_all.sh` 既有 `SEVERE`/`ISSUE` 聚合范式「样板抄齐」—— 捕获 `FUND_SCORE_RSYNC_RC` → `SEVERE=1` → `ISSUE` 追加一句。**建议主控另立小任务拍板**。

---

## 5. §23.3 举一反三 —— 同模式/同数据源/同组件清单

| 维度 | 清单 | 覆盖结果 |
|---|---|---|
| **同模式**(非递归 glob 漏子目录) | `all-data` / `data-large`(`data/*.json`)、`index`、`etf`、`nav_bucket`、`accum_nav`、`kelly-*` 各通道 | 逐通道核对: 其余通道的 `local_dir` 已精确指向各自子目录(`data/index`、`data/etf/`...)⇒ 非递归即正确, 无需递归; 只有 `news_digest` 是「子目录挂在 `data/` 下且无专属通道」⇒ 本轮补齐 |
| **同数据源**(`_upload_glob` 家族) | 见 §4 表 6 项 | 逐项判定/断言, 2 修 4 确认 |
| **同组件**(`_R2_CHANNELS` 消费者) | `verify-r2`(平日增量 / 周日全量)、`verify-channels`(轻量抽查)、`_reconcilable_keys_for`(台账登记侧)、`_assert_no_double_upload` | 前二者已由 `test_193` [C] 断言(平日+周日两模式); 第三者由 [B] 断言; 第四者由真实数据树探针实测互斥 PASS |
| **相关展示位**(用户可见面) | ① `fund_score` → 前端 `app.js` 场外基金评分 fallback(`/r2/fund_score/fund_score_top.json`); ② `news_digest` → 首页新闻看板/`news_digest/_index.json`; ③ `offshore_fund` → 筛选器阶段0 产物(当前链停用) | 三处均在通道覆盖后纳入对账; ② 另经 `upload-data-files` 登记进台账 → **平日确定性对账**(不只靠抽样) |
| **同族**(`data/` 直传不经通道状态) | `intraday`、`upload-data-files` 的 s06/nextday_plan/daily_brief/feed.xml 等 | #188 已用统一台账覆盖; 本轮新增的 `news-digest` 通道使归档键由「死键」转「可对账」, 与台账**协同**而非重复 |

---

## 6. §22 登记点清单 + 机检

同一事实(R2 前缀集合)在本仓的登记点:

| 登记点 | 内容 | 本轮是否需改 |
|---|---|---|
| `upload_r2.py:_R2_CHANNELS` | 对账侧权威清单 | **改**(+3) |
| `upload_r2.py` 各 `cmd_upload_*` 实参 | 上传侧实际前缀 | 否(未动上传语义) |
| `upload_r2.py:_DATA_EXCLUDE_PREFIXES` | `data/` 通道排除前缀 | 否(设计, 加注释) |
| `r2_upload_async.sh:upload_data_channels()` | deploy 异步链跑哪些通道 | 否(`fund_score` 链属 `update_all`, 不属 deploy 链; 加进去会双告警) |
| `scripts/README.md` | 运维文档 | 否(无逐通道清单, 只有调度时点描述) |
| `sync_dev_from_r2.sh:172,227` | 遍历 `_R2_CHANNELS` 但按 `TARGET_LABELS={"index","industry","data-large"}` 白名单过滤(#dev-sync 专用) | 否(白名单式, 新通道自然可选, 不参与即默认不变) |
| `check_r2_consistency.py` | 仅在注释提及 verify-r2(另一链路, #187 归属, 本轮禁区) | 否 |

**机检**(要求 4): 新增 `scripts/check_r2_channel_coverage.py`, 纯 **AST 静态分析**(不 import `upload_r2`, 免 `.env`/免副作用), 双向断言:
- **[1] 产出侧全覆盖**: 每个 `_upload_glob`/`_incremental_upload` 实参写出的前缀, 必须被 ≥1 个通道前缀覆盖(相等或子前缀), 或在白名单 `_EXEMPT_PREFIXES`(6 项私桶备份前缀, 逐条附理由)内;
- **[2] 通道侧有来源**: 每个通道前缀必须被 ≥1 个上传命令前缀覆盖 ⇒ **无孤儿通道**(对账永远对不上东西);
- 支持传参指定文件 ⇒ 可喂历史版本做**回归对照**。

机检本身的能力已被实测(见 §7): 喂**修复前**版本 → `HAS_FAIL(2)` 且清单恰为 `fund_score`/`offshore_fund`。
> 未挂 deploy 链: 触碰生产 deploy 流水线属高爆炸半径动作(→ memory `gate-position-blast-radius`), 派单禁区亦限定「只动 R2 通道侧」。**是否挂闸/挂哪一环, 请主控拍板后另派**; 当前它由 #193 自验脚本每次都跑, 不是「写完没处跑」。

---

## 7. 自验证据(逐条)

| 项 | 命令 | 结果 |
|---|---|---|
| #193 自验 | `python3 scripts/test_193_r2_channel_coverage.py` | **40 PASS / 0 FAIL / ALL_PASS** |
| §22 机检(现版) | `python3 scripts/check_r2_channel_coverage.py` | **ALL_PASS**(产出前缀 15 / 通道 18 / 豁免 6) |
| §22 机检(修复前对照) | `git show HEAD:scripts/upload_r2.py > /tmp/old.py; python3 scripts/check_r2_channel_coverage.py /tmp/old.py` | **HAS_FAIL(2)**: `fund_score`(L1708) / `offshore_fund`(L1692) —— 证机检真能抓这类漏配, 非空转 |
| #188 回归 | `python3 scripts/test_188_s06_sync_blindspot.py` | **31 PASS / 0 FAIL / ALL_PASS** |
| 真实数据树探针(只读) | `REPO=/Users/linhuichen/code/trade-data python3 /tmp/probe193c.py` | `news-digest n=31` / `fund-score n=2` / `offshore-fund n=0`(链停用) / `news-digest ∩ all-data = ∅` / `news-digest ∩ data-large = ∅` / `_assert_no_double_upload = True` |
| 语法 | `python3 -m py_compile`(4 文件) + `bash -n scripts/update_all.sh` | PY_COMPILE_OK / SH_SYNTAX_OK |

### #188 回归为何要改(3 条断言过时, 非功能回归)

`test_188` 的 [E] 段原以 `data/news_digest/2026/*.json` + `data/news_digest/_index.json` 作为**「死键」样例**。
本轮 ② 号修法**刻意**让这些键变为可对账 ⇒ 原断言(「全死键登记 → 台账仍为空」「混合登记只留 overview.json」「死键确为扫描不可达」)**按设计必然翻转**。
处置(§15 回归义务 / 不静默): 把 [E] 的死键样例改为**仍然真死**的键(`data/uncovered_subdir/x.json` 无任何通道 glob 覆盖 + `data/feed.xml` 非 `.json`), 并**新增一条互证断言**(`news_digest` 归档键现已可达)防「过滤非空转」假绿。断言语义不变(仍是「台账只收可达键」), 只是样例随事实更新。
`data/feed.xml` **仍为死键**且**正确**: 它由 `upload-feed`(`r2_upload_async.sh:188`)轻量校验覆盖, 不进通道对账(它也非 `.json`)。

### §18 L48 / memory `notify-script-selftest-must-stub` 证据(零真实外发)

- 自测先把 `sys.modules["notify"]` 换为 Fake, **并给真实 `notify.send` 挂陷阱函数**(触达即 `AssertionError`)。
- 断言「真实 `notify.send` 陷阱从未触发」**PASS** ⇒ **本次自测未产生任何真实外发**(邮件/飞书零发送)。
- `s3_head` / `_upload_glob` 全程打桩 ⇒ **零真实 R2 PUT/HEAD/DELETE**; 探针只读本地数据树, 不触网。

---

## 8. 已知边界 / 未覆盖项(上报不静默)

1. **`update_all.sh` 的 `fund_score` rsync 失败仍只 echo** —— 见 §4 末; 超本任务范围, 建议主控另立任务(现成样板已给)。
2. **机检未挂 deploy 链** —— 见 §6; 挂链位置/爆炸半径需主控拍板。
3. **`offshore_fund` 定时链已停用** —— 通道登记是「将来手动用时自动纳入对账」, 当前文件数为 0(通道自动跳过, 零成本)。
4. **`news-digest` 递归深度口径** —— 精确到「年目录一层」(`*/*.json`)。若将来归档结构加深(如 `年/月/`), 需同步扩 patterns; 已在通道注释写明。
5. **§23.7 冻结契约** —— 本轮为**纯新增通道 + 纯新增失败告警**, 不改任何既有通道的上传/对账语义(既有 15 通道行为逐位未动, 由 #188 回归 31 断言 + #193 自验覆盖), 未触碰已上线功能口径/数字/交互。

---

## 9. 变更文件

| 文件 | 类型 | 说明 |
|---|---|---|
| `scripts/upload_r2.py` | 改 | `_R2_CHANNELS` +3 通道; `cmd_verify_r2` 支持 `state_name=None`; 新增 `_notify_channel_upload_fail`; 两命令失败 loud 化; 3 处过时注释订正 + `_DATA_EXCLUDE_PREFIXES` 设计理由 |
| `scripts/check_r2_channel_coverage.py` | 新增 | §22 双向覆盖机检(AST, 可喂历史版本对照) |
| `scripts/test_193_r2_channel_coverage.py` | 新增 | #193 自验 40 断言([A]~[E], notify/R2 全打桩) |
| `scripts/test_188_s06_sync_blindspot.py` | 改 | [E] 死键样例随事实更新 + 新增 news_digest 可达互证断言 |
| `docs/ops/193-r2-channel-coverage-20261005.md` | 新增 | 本报告 |

---

## 复现段

全部命令在 worktree 根 `/Users/linhuichen/code/trade/.claude/worktrees/agent-a8b3fdd34ffa01896` 下执行(mac 本机即可, 零外部依赖; 探针需真实数据树)。

```bash
# 1) #193 自验(40 断言; notify 已打桩, 零真实外发; R2 全打桩, 零真实 PUT)
python3 scripts/test_193_r2_channel_coverage.py
#    期望末行: 断言 40 PASS / 0 FAIL   →   ALL_PASS

# 2) §22 通道覆盖机检(现版应 ALL_PASS)
python3 scripts/check_r2_channel_coverage.py
#    期望末行: ALL_PASS

# 3) 机检回归对照: 喂「修复前」版本 → 必须 FAIL, 且 FAIL 清单恰为 fund_score/offshore_fund
git show HEAD:scripts/upload_r2.py > /tmp/old_upload_r2_193.py
python3 scripts/check_r2_channel_coverage.py /tmp/old_upload_r2_193.py
#    期望: HAS_FAIL(2) + FAIL fund_score(L1708) / FAIL offshore_fund(L1692)

# 4) #188 回归(本轮改了 [E] 死键样例, 应 31 PASS / 0 FAIL)
python3 scripts/test_188_s06_sync_blindspot.py
#    期望末行: ALL_PASS

# 5) 真实数据树只读探针(通道文件数 / 双传互斥 / 死键集) —— 需真实数据树
REPO=/Users/linhuichen/code/trade-data python3 /tmp/probe193c.py   # 探针脚本内容见下
#    期望: news-digest n=31 / fund-score n=2 / offshore-fund n=0
#          news-digest ∩ all-data = []  / news-digest ∩ data-large = []
#          _assert_no_double_upload = True
```

探针 `probe193c.py` 为本轮一次性只读脚本(不入仓); 其内容等价于:

```python
import os, importlib.util
os.environ.setdefault("REPO", "/Users/linhuichen/code/trade-data")
spec = importlib.util.spec_from_file_location("ur", "<worktree>/scripts/upload_r2.py")
ur = importlib.util.module_from_spec(spec); spec.loader.exec_module(ur)
for lbl in ("news-digest", "fund-score", "offshore-fund", "all-data"):
    ch = next(c for c in ur._R2_CHANNELS if c["label"] == lbl)
    ld = ch["local_dir"](); print(lbl, len(ur._channel_files(ch, ld)), ch["r2_prefix"])
print(ur._assert_no_double_upload(ur.STATIC_DIR / "data"))
```

**回退**: 本改动为纯新增(通道 + 告警), 回退 = `git revert <本 commit>` 即回到修复前行为(缺口重新出现, 无更坏状态)。无需备份/删除动作(本轮零删除, §25 未触发)。