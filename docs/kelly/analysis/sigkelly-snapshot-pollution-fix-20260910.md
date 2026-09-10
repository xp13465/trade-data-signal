# 演进快照三项修复打包:9/8 污染清理 + 演进弹窗读 sig_main + 盘中表滚动条撑开

日期:2026-09-10
类型:实施修复(用户全量拍板)
分支:`feat/sigkelly-snapshot-fix`
Commits:`55a29495c`(源码) + `7b14deea2`(min+bump)
测试基准(§5.4):本任务不动回测主链,无基准前提;改动后 sig_main A all(annualized=0.9054, n=1415)逐位不变 ✓

## 一、任务 1:9/8 污染快照清理(防复活)

### 背景
2026-09-09 10:53 da1064998 修复「accum_nav=1.5 占位残留」P0 bug(9/8 单日 total_return 被错误固化,致 G/H/I 全史收益虚高约 82%)。但 9/8 晚~9/9 16:38 期间被污染的演进快照点已经固化进 `signal_kelly_snapshots/index.json`,改名对 `20260908.json` 也需检查。

### 根因(脚本层)
`append_to_index()` 遍历快照 dict 内所有 quadrants,后面的 key 覆盖前面的(mkt_concept 是最后一个),导致:
1. 演进弹窗读到的是 mkt_concept 象限数值,不是 sig_main(任务 2)
2. 污染点被原样写进 index,无任何防护

### 修复
- `scripts/signal_kelly_snapshot.py` 新增 `MUTATION_RATIO = 0.30`:单日 total_return 相对上一快照日突变比 >30% 且非发布日,判定为污染。
  - 依据:sig_main all 全史累计收益每日正常波动 <1%,30% 必为数据污染。
- 新增 `rebuild_index(data_dir, dry_run)`:按日期对 `20*.json` 逐日 append,统计被拦截的 polluted modes。
- 新增 `--rebuild` CLI flag。

### 结果(index.json,updated_at 2026-09-10 07:50)
| 日期 | G | H | I | 备注 |
|---|---|---|---|---|
| 9/8 | None | None | None | `polluted:['G','H','I']`,尖峰消失 |
| 9/9 | 正常 | 正常 | 正常 | |
| 9/10 | 正常 | 正常 | 正常 | |
| A/B/C/D/E/F/J | 保留正数值 | | | 未污染象限不动 |

**防复活**:重跑 `--rebuild` 会再次对 9/8 做突变比拦截,污染点不可能被重新写入。

## 二、任务 2:append_to_index 覆盖 bug(读 sig_main)

### 根因
`append_to_index` 遍历 dict 内全部 quadrants 导致后写覆盖先写,mkt_concept(最后一个)胜出。演进弹窗(lab.js `_labKellyEvoSVG`)只读 index.json 一个源,无象限选择器,后端写哪个象限前端就显示哪个 → 曲线与 16 象限卡的 sig_main 数值不匹配。

### 修复
`append_to_index` 重写为**显式只写 `quadrants.sig_main.all`**(新 helper `_sig_main_all`),演进弹窗曲线与 16 象限卡 sig_main 数值一一对应。

### 验证(Playwright,localhost:8124 演进弹窗)
- 9/8 行显示缺失标记,折线跳过缺失点(6 个有效点)。
- A 数值 1.1k1415 ↔ sig_main 卡 A=1149.68 n=1415 ✓
- G 数值 9.5k ↔ sig_main 卡 G=9499.13 ✓
- pageErrors:none

## 三、任务 3:盘中增量回测表内部滚动条撑开

### 根因(双重)
1. **同元素 overflow 互斥**:`.sim-table-wrap` 本身 `overflow-x:auto`(非 visible),CSS 规范下 `overflow-y:visible` 会被计算为 auto → 之前的内联 `style="max-height:none;overflow-y:visible"` hack 无效。
2. **flex 父级压缩**:row 在 `max-height:85vh` flex 容器(`.rule-modal-body`)中默认 `flex-shrink:1`,wrap 被压到不足内容高度 → 内部滚动条。

修复前实测(60 行注入):`wrapClientH=452 < wrapScrollH=2508`,内部滚动条。

### 修复
- `static-site/common.js`:移除盘中表 wrap 的内联 hack,改 class `sim-table-wrap kelly-intraday-view`。
- `static-site/style.css` 新增专用 override:
  ```css
  .sim-table-wrap.kelly-intraday-view, .kelly-intraday-view {
    max-height: none; flex-shrink: 0; overflow-x: auto; overflow-y: auto;
  }
  ```
- lab 交易记录弹窗(`.lab-sigkelly-intraday-anchor`)复用同一 `_kellyIntradayRender` + 同一 class,同 CSS 覆盖。

### 验证(Playwright,localhost:8124,注入 60 行 distinct etf_code,手动 render fadeOn:false K:0)
修复后实测:
```
tblRows: 60
wrapClientH: 2508  ==  wrapScrollH: 2508   ← 无内部滚动条,完整展开
wrapMH: none        ← max-height:none 生效
flexShrink: 0        ← 不再被 flex 父级压窄
pageErrors: none
```
主表(PAGE=500 分页)不受影响。

## 四、验收对照
- ① index.json 9/8 尖峰消失且不可被 rerun 复活 ✓(MUTATION_RATIO 拦截)
- ② 演进弹窗曲线 === sig_main 卡数值 ✓(A=1149.68 n=1415 逐位对)
- ③ 盘中表无滚动条、完整展开 ✓(60 行实测 2508==2508)
- ④ sig_main A all annualized=0.9054 n=1415 不变化 ✓
- ⑤ 前端源码同 commit bump 版本串 v20260910-a568 + min 重建 ✓(controller 统一部署)

## 五、改动文件
| 文件 | 改动 |
|---|---|
| `scripts/signal_kelly_snapshot.py` | append_to_index 重写(显式 sig_main)+ MUTATION_RATIO 防污染 + --rebuild |
| `static-site/common.js` | 盘中表 wrap 内联 hack → 专用 class |
| `static-site/style.css` | `.kelly-intraday-view` override(max-height:none;flex-shrink:0) |
| `static-site/data/signal_kelly_snapshots/index.json` | 重建,9/8 G/H/I=None(**走 R2 部署,不进 git**) |
| min + bump 产物 | common.min.js/style.min.css + 5 html ?v + sw.js CACHE_VERSION |

## 复现
- **脚本**:`scripts/signal_kelly_snapshot.py`
- **重建 index**:`/Users/linhuichen/code/trade/.venv/bin/python3 scripts/signal_kelly_snapshot.py --rebuild --data-dir /Users/linhuichen/code/trade/static-site/data`
- **输入依赖**:`static-site/data/signal_kelly_snapshots/20*.json`(快照全量文件)
- **输出**:`static-site/data/signal_kelly_snapshots/index.json`(9/8 污染拦截日志见 stdout `[防污染]`)
- **数据截止**:2026-09-10 05:11(20260910.json)
- **关键口径一句话**:append_to_index 显式写 `quadrants.sig_main.all`;单日 total_return 突变比 >30% 且非发布日 → 写 `{"tr": None, "n": n, "polluted": true}`。
- **Playwright 验证脚本**:`/tmp/probe-intraday-fade0.mjs`(60 行注入,断言无内部滚动);演进弹窗数值对账见上文。
- **上线链路**:index.json 走 R2/static-site(data 层被 gitignore),min+bump 已 commit feat 分支,deploy 由主控排期统一执行。
