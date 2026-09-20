# 基笔唯一化三表 Review(feat/kelly-unique-export, L42 步1)

日期:2026-09-20 | 角色:reviewer(独立, 批判性) | 分支:feat/kelly-unique-export(2 commit: d6a2e0515 主实现 + 71c5391c7 对账工具)
测试基准:current baseline v1.1.7(本步只做数据形态唯一化, 不重算口径)

## 结论:PASS(附 2 项文档勘误建议)

无损还原三重验证(独立复验, 不轻信 implementer 报告):
- **独立对账脚本**(reviewer 自写, Counter 计数比 implementer 工具 set 更严格, 不 import 其工具):
  - 本地 9-13 主档 signal_kelly_trades.json(78,296,778 B):n_base=7608 × 10 mode, 原 304,320 行;A)计数等价 304,320==304,320 零差异 PASS / B)值逐位 304,320 行零缺失零不一致 PASS / C)总行数 PASS;归属枚举码 -1=0(4 组全覆盖)、None 变体=0。
  - 本地 9-13 sdc signal_kelly_trades_sdc.json(78,351,370 B):n_base=7612, 原 304,480 行, 三重全 PASS。
- **implementer 正式工具** check_kelly_unique_restore.py 对主档跑:RESULT: ALL PASS(退出 0), 工具本身不会假绿——set 去重被 C 总行数 + B 的 checked==len(orig_set) 双重兜底;值逐位索引比对逐行对。
- **体积实测**(reviewer 独立生成 unique):主档 5,892,709 B = 5.6 MB, 压缩率 78,296,778/5,892,709 = 13.3x;gz 1,272,071 B。体积目标(75MB→~5MB)达成。

## 逐复核点结论+证据

### 1. 代码 diff 正确性 — PASS
- `_build_unique_tables`(L1575 新增, 108 行)由 main() 传 trades_output 的数组行 quadrants(27 列), `r[i]` 整数索引正确;share_idx/sell_idx/key_idx 均由 TRADE_FIELDS.index() 现算, 无列序漂移风险(TRADE_FIELDS 单一事实源)。
- share 19 + sell 8 = 27 == len(TRADE_FIELDS), 程序断言覆盖零漏字段(实测 True)。
- 归属逻辑:每基笔 4 组各取 1 个 qk 枚举码, 当前数据 4 组全覆盖零 -1(独立实测);还原时 code<0 跳过, None 变体哨兵兜底已实现但当前 0 触发。
- **开关真默认关**:`KELLY_UNIQUE_EXPORT = int(os.environ.get(..., "0"))` = 0;main() 开关分支在 L2274 `if KELLY_UNIQUE_EXPORT:`, 关时完全跳过, 零副作用。
- **compute_intraday 零影响**:开关分支只在 main() 主流程末尾;`--intraday-rerun` 路径在 L2209 提前 return, 不达开关分支;`_build_unique_tables` 为纯新函数, `_build_outputs`/`_classify_buy_rows`/`compute` 均未改(diff 仅 +108 行零删除)。盘中档无 40 倍膨胀, 唯一化无必要(审计 §2.2 一致)。

### 2. 字段划分实证复验 — PASS
- 独立程序断言:share+sell 排序 == TRADE_FIELDS 排序(19+8=27 全覆盖)。
- current_price/real_current_price 归卖出侧:整个还原逐位对账全 PASS——若这两字段误归共享, 33/86 基笔「部分 mode 已卖」的未卖 mode 行必然 mismatch, 但实测 0 不一致, 间接证明划分正确(机制=schema §1.3: 部分 mode 已卖时 current_price 空串 vs 未卖 mode 最新净值不同)。
- 基笔去重键 signal_date|index_id|signal|buy_date|etf_code == 前端 `_simBaseKey`(app.js L3573)逐字段一致(独立核对 app.js L3573-3575)。

### 3. 独立复验对账 — PASS(数据可得, 已实际跑)
- 本地 static-site/data/ 有 9-13 主档+sdc 两份 trades 产物(78MB), reviewer 用其独立生成三表 + 独立还原断言(见上), 全部 PASS。数据可得, 不需 ssh 云上(云上 9-20 行数已 ssh 核实 305,920=7648×40, 与审计一致)。

### 4. 键集/体积数字 — PASS(数字来源有出入, 见勘误①)
- 自洽性:base×40==还原行数全部成立:本地 7608×40=304,320 ✓ / 7612×40=304,480 ✓;云上 7648×40=305,920 ✓(ssh 实测)。
- 主控 prompt 的「7624/7758、304,960/310,320」与本地(7608/7612)及云上(7648/7767)均不一致, 疑为中间数据版本, 属正常动态漂移(审计 §1.1 已确认「差异随数据版本动态增长」), 非 bug。
- 体积 5.6MB/13.3x 与主控 prompt 吻合, reviewer 独立实测同值。

### 5. §23.3 举一反三 — PASS
- 双套独立生成:main() 由 KELLY_BUY_NEXTDAY env 切口径, 主档/sdc 各跑一次各自生成 unique 文件;文件名派生 `os.path.splitext(trades_path)[0]+"_unique.json"` → signal_kelly_trades_unique.json / signal_kelly_trades_sdc_unique.json, 与 _trades_parts_dir 双口径命名一致(独立核对 L2059-2065)。
- 无遗漏组合:intraday 档(26 列/无膨胀)不唯一化, 正确;无其他 trades 口径。

### 6. 验收口径对照 — PASS
- 纯新增 373 行(108 代码+135 工具+130 文档), 零删除 ✓
- 开关默认关 ✓ | 现有产物 diff 零变化(diff 只加新函数+main 末尾分支)✓
- 未 commit main / 未 bump(改后端脚本不改前端源码, 不需 bump)✓ | 未 add data/ 文件 ✓
- §21 公示:数据形态重构不改算法/数值口径, 前端公示无需同步 ✓
- §22 一致性:unique 为纯新增产物不替代现有文件, 前端继续读原 trades, 无展示位不一致风险 ✓

## 勘误建议(不阻断, 但建议实施核对/修正)
1. **schema 文档体积数字不符**:文档 §四 写 unique 5,246,852 B(5.0 MB)/14.9x, reviewer 独立实测 5,892,709 B(5.6 MB)/13.3x(同一本地 9-13 主档)。差 646 KB, 疑数据版本/序列化差异, 建议核对后修正文档。
2. **主控 prompt 数字来源**:7624/7758 无对应本地(7608/7612)或云上(7648/7767)产物, 建议实施说明该数字来源;不影响还原正确性。

## 已滤低分项(<80, 不进 finding)
- `_build_unique_tables` docstring 写「由 _classify_buy_rows 中间态直接生成」, 实际输入是 trades_output 数组行(语义等价, 注释不精确)。
- 归属逻辑对「同一基笔同组出现 2 个 qk」无显式防御(当前数据零例外, 对账工具会抓)。
