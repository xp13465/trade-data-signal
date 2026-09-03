# CodeGraph 开源项目实测评估（2026-09-01）

> 背景：codex 推荐开源项目 [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)（v1.6.0，~69k star，Rust 内核 + tree-sitter，SQLite+FTS5 知识图谱，宣称「surgical context / blast radius / 44% 低成本 62% 少 token」）。用户拍板「先对评估的内容实测验证下是否达到预期」，并要求列全功能清单逐项说明蒸馏采纳与否及原因。本文=主控在本仓库（trade-data-signal）**实测验证结论**，非转述 codex 评估。
> 评估对象核心痛点诉求：①近来回测口径漂移定位 ②项目庞大快速定位。

## 一、实测环境与索引基线

- 版本：codegraph v1.6.0（npm 全局），索引项目根 /Users/linhuichen/code/trade
- 配置：新增 `.codegraphignore`（排除 node_modules/.git/__pycache__/data/static-site/data/.tmp/logs/tmp/），已随本报告 commit（进 git）
- 索引结果：443 文件 / 14,798 节点 / 40,467 边 / DB 51.54MB（WAL）/ 建索引 6.6s
- 文件语言分布：python 368 / javascript 68 / yaml 7

## 二、实测结论速览

| 验证点 | 结果 | 证据 |
|---|---|---|
| 唯一命名函数 callers 准确性 | ✅ 准 | `_kellyAihlineRealizeReal`→2 调用方全命中；`_kellyCollectBasePool`→真实调用方 `_kellyApplyFeeRecompute:8407`/`_openSigKellyTradesModal:11571` |
| impact 爆炸半径 | ✅ 准 | `impact _kellyAihlineRealize`→8 受影响符号（FifoCap/P3dCap/Sim 全中） |
| **2MB 大文件覆盖** | ❌ **静默跳过** | app.js=2,014,447B>1MB 上限 → 0 symbols，**无任何告警**；727 个顶层函数完全不可查 |
| **通用短名 callers** | ❌ **同名污染** | `callers passesFade`→8 个「调用方」无一是 lab.js 主引擎真调用点（L8554/8558/8572/8722/8730/8733 全漏），反混入 docs 里 5 个恰好同名函数 + 定义处所在函数 |
| **函数内局部符号** | ❌ **不可查** | `_gihRefRows` L9961 定义/L9973+9991 使用 → query/callers 全部 not found（模块级才索引） |
| affected（找测试文件） | ⚠️ 本项目无测试结构 | 实测返回空 |

### 坑 1（最重）：>1MB 文件被静默跳过，无警告

README L639 明文默认排除「Files larger than 1 MB — generated bundles, minified JS, vendored blobs」。app.js = 2,014,447 字节 → 0 symbols；app.min.js = 1,015,493 字节（≈991KB，勉强在限内）→ 1055 symbols 但行号全压成 1。**本项目定位痛点最重的文件（app.js 727 顶层函数）恰好整个不可查**，`query _sigWinN` 只能命中 app.min.js:1。属于 codex 报告 #407 类静默错：索引看似建好，核心文件缺失，无告警。

### 坑 2：跨文件同名函数污染 callers/impact

`passesFade` 是凯利引擎通用短名，回测脚本里遍地同名局部函数，codegraph 合并为同一符号。实测 8 个「调用方」：lab.js 只报定义处所在函数 `_kellyApplyFeeRecompute:8407`（定义点非调用点），其余 5 个全是 docs 里恰好同名的无关函数（`pfFull`/`run_seg`/`collectModeTrades` 等）。**拿它做影响面分析会被严重误导**，且这是本项目最常见的命名风格。

### 坑 3：函数内局部符号不索引

`_gihRefRows` 定义于 `_kellyAihlineFifoCap` 函数体内部（模块级 const 数组），codegraph 只索引模块级符号，query 完全搜不到。本项目大量这种函数体内对象/数组/局部函数。

### 对「回测口径漂移」痛点：无直接帮助

口径漂移根因 = 数据重生成（signal_kelly_trades.json 重跑）+ repro 脚本第二份实现静默漂移（s06NoBull 返回对象非布尔）→ **数据/语义层问题，非代码引用层问题**。codegraph 能回答「谁调用了 X」，查不出「X 算出的数字与页面对不对得上」（structural not semantic，codex 报告自认）。

## 三、功能全清单 + 蒸馏采纳判断（18 CLI + 8 MCP）

| 功能 | 做什么 | 蒸馏用? | 原因 |
|---|---|---|---|
| `init` / `index` | 建/重建索引 | ✅ 用 | 6.6s 建完，DB 51MB 可接受 |
| `sync` | 文件改动自动增量同步（2s debounce） | ⚠️ 慎用 | 仅对**已入索引**文件有效；2MB 大文件永远同步不进（坑1） |
| `status` / `files` | 索引统计 / 文件结构树 | ✅ 用 | 省事，结构树直观 |
| `query` | 搜符号 | ⚠️ 半用 | 只见模块级符号，函数内局部查不到（坑3） |
| `callers` / `callees` | 调用方 / 被调用方 | ⚠️ 半用 | 唯一命名准；通用短名同名污染（坑2），影响面决策不能信 |
| `impact` | 改动爆炸半径 | ⚠️ 半用 | 同坑2，唯一命名符号准 |
| `affected` | 找受影响的测试文件 | ❌ 不用 | 项目无测试文件结构，实测空 |
| `explore` / `context` | 一次拉取符号+源码+调用链 | ⚠️ 慎用 | 价值高但对坑1/坑2 无免疫 |
| `node` | 单符号源码+调用轨迹 | ⚠️ 半用 | 同 query 限制 |
| `daemon` / `unlock` | 后台守护 / 解锁 | ✅ 用 | 运维必备 |
| `install` / `uninstall` | 装进 Claude Code/Cursor/Codex 等 agent | ❌ 暂不 | 会改写 agent 配置，坑未修前把错误带进流程 |
| `telemetry` | 匿名统计开关 | ✅ 用 | 顺手关掉 |
| `upgrade` / `version` | 升级 / 版本 | ✅ 用 | 常规 |
| `uninit` | 卸载 | ✅ 备用 | 回滚路径 |
| **MCP 8 工具** | 上述命令的 agent 版封装 | ❌ 暂不 | 依赖同一索引，坑未修前装 MCP = 把错误带进 agent 流程 |

## 四、跨角色蒸馏判断（§5.1 穷举）

- **implementer**：定位改动前找调用点 → **半用**。唯一命名符号比 grep 快，但通用短名（passesFade 类）会误导，须 grep 交叉验证。
- **reviewer**：影响面 / 回归范围 → **暂不用**。passesFade 案例证明会漏真调用点+混入同名无关函数，拿它定回归范围=埋雷。
- **researcher**：算法调用链追踪 → **半用**。唯一命名有帮助；口径漂移 / 数据再生类问题无力（结构非语义）。
- **tester**：affected 找测试 → **不用**。无测试文件结构，零收益。

## 五、落地建议

**结论：值得装，但要改装 + 只用于「定位」不当「影响面依据」，先给 codex 外审用，不装 MCP。**
1. 查 1MB 上限是否有配置项可调（**遗留问题，待查**；未找到则坑1 无解，接受「app.js 定位不到」）
2. `install` 先不碰（会改写 agent 配置），要用走 CLI 手动查询
3. 三条使用红线：唯一命名符号可信 / 通用短名必须 grep 交叉验证 / 函数内局部符号查不到

## 复现

- 脚本：无独立脚本（交互式实测），复现命令如下，索引已建于项目根 `.codegraph/`
- 输入依赖：/Users/linhuichen/code/trade（git HEAD=main @1fc98edd），.codegraphignore 在本仓库
- 重跑命令：
  ```bash
  cd /Users/linhuichen/code/trade
  codegraph init -y -v .           # 建索引（6.6s）
  codegraph status                  # 索引统计
  codegraph files | grep -A2 "app.js"     # 坑1：app.js 0 symbols / app.min.js 1055
  codegraph callers _kellyAihlineRealize  # ✅ 准
  codegraph callers passesFade            # 坑2：8个同名污染调用方，无真调用点
  codegraph query _gihRefRows             # 坑3：not found
  codegraph affected static-site/lab.js   # 无测试文件 → 空
  ```
- 关键口径：app.js=2,014,447B>1MB 上限被默认排除（README L639）；passesFade 真调用点=lab.js L8554/8558/8572/8722/8730/8733
- 数据截止：2026-09-01，codegraph v1.6.0
