# 配色皮肤切换实施方案

## 背景
站点配色偏素（白底+字节蓝+灰，商务报表感）。用户要做成**皮肤切换**，一次解决众口难调和"配色素"。

## 现状调研
- `web/style.css` 1484 行 + `web/lab.css`，**无 :root 变量**，色值全硬编码散落
- 高频色：`#86909c`(52) 灰文字 / `#4e5969`(44) 深灰 / `#1f2329`(41) 近黑 / `#165dff`(41) 主蓝 / `#e5e6eb`(37) 边框 / `#c9cdd4`(17) 浅灰 / `#f7f8fa`/`#f2f3f5`(28) 浅底 / `#e6492e`(11) 涨红 / `#2e8b57`(10) 跌绿
- `app.js`/`lab.js` 大量 ECharts 配置 + 内联样式硬编码色值
- 双版（web/ + static-site/）逐字一致，index.html 有 header（PC）+ h5-topbar（移动）

## 核心设计决策

### 决策1：分两类色值（关键）
- **UI 色抽变量**（随皮肤变）：主色、背景、卡片底、边框、文字（主/次/弱）、hover、按钮、tab 激活、阴影等 ~15 个语义变量
- **数据语义色不抽**（所有皮肤一致）：涨红 `#e6492e`/跌绿 `#2e8b57`/冰点红/过热绿/恐贪色阶/热力图色块/买卖点信号色。这些是**数据含义**，改了会误导（红涨绿跌是 A 股铁律），不随皮肤变。app.js 里 ECharts 配置的这些色保持硬编码。

### 决策2：变量命名（语义化）
```
:root {
  --bg-page: #f5f6f8;        /* 页面背景 */
  --bg-card: #fff;           /* 卡片背景 */
  --bg-hover: #f7f8fa;       /* hover/浅底 */
  --bg-active: #f0f5ff;      /* 激活浅底 */
  --border: #e5e6eb;         /* 边框 */
  --border-strong: #d9dce0;  /* 强边框 */
  --text-1: #1f2329;         /* 主文字 */
  --text-2: #4e5969;         /* 次文字 */
  --text-3: #86909c;         /* 弱文字 */
  --text-4: #c9cdd4;        /* 最弱 */
  --primary: #165dff;        /* 主色 */
  --primary-hover: #0e42d2;  /* 主色hover */
  --primary-bg: #f0f5ff;     /* 主色浅底 */
  --shadow: rgba(0,0,0,0.04);/* 卡片阴影 */
}
```

### 决策3：4 套主题
1. **浅色（默认/现状）**：保留字节蓝，微调层次（加深阴影、卡片圆角）
2. **深色专业版**：`#0d1117` 背景 + `#161b22` 卡片 + 青蓝 `#58a6ff` 主色（金融终端风）
3. **红金中国风**：`#1a1d29` 背景 + 琥珀金 `#f0b90b` 主色（喜庆专业）
4. **莫兰迪柔和**：米灰 `#f5f1ec` 背景 + 雾蓝 `#6b7c93` 主色（低饱和高级）

用 `[data-theme="xxx"]` 选择器覆盖变量，body 默认无 data-theme = 浅色。

### 决策4：切换 UI
- header 右侧（PC）+ h5-topbar（移动）加 🎨 皮肤按钮
- 点击弹小弹层，4 个选项（色块预览 + 名称），当前选中高亮
- localStorage 持久化（`trade-theme` key），下次访问记住选择
- 切换即时生效（改 document.documentElement.dataset.theme），无需刷新

## 实施步骤

### Step 1: 抽 CSS 变量（style.css + lab.css 双版）
- 顶部加 `:root { ... }` 定义 15 个默认变量（=现状浅色值）
- 全局 sed 替换：`#86909c` -> `var(--text-3)` 等，按语义映射 15 个变量
- **只替换 UI 色位**，跳过数据语义色（涨跌红绿/冰点过热/恐贪色阶等）。逐个 grep 确认替换点正确（如 `#e6492e` 在 `.tag.freeze` 是数据语义保留，在 `.buy` 信号也是数据保留）
- lab.css 同样处理

### Step 2: 4 套主题变量块（style.css 顶部）
```
[data-theme="dark"] { --bg-page:#0d1117; --bg-card:#161b22; ... }
[data-theme="redgold"] { ... }
[data-theme="morandi"] { ... }
```
深色主题的文字/边框/阴影全套反色。

### Step 3: 切换 UI + 逻辑（app.js + index.html 双版）
- index.html header 加 `<button class="theme-btn">🎨</button>` + h5-topbar 同步
- app.js 加 `initThemeSwitcher()`：渲染弹层 + 读 localStorage + 绑定切换
- 弹层复用现有 modal 风格（`.rule-modal` 模式），4 个选项卡片
- bootstrap 启动时读 localStorage 立即应用（避免闪烁：在 index.html `<head>` 加一小段 inline JS 提前设 data-theme）

### Step 4: bump 版本号 + 验证
- 4 个皮肤逐个切换看效果（node --check + 视觉）
- 双版 diff 确认一致（除 URL）
- bump_asset_version + commit push

## 范围与风险
- **改动文件**：web/style.css + static-site/style.css + web/lab.css + static-site/lab.css + web/app.js + static-site/app.js + web/index.html + static-site/index.html（8 文件）
- **风险点**：① 全局 sed 替换色值可能误伤数据语义色 -> 逐个 grep 确认，保留涨跌/冰点/过热/恐贪色阶 ② 深色主题下 ECharts 图表背景仍是白（图表色不随皮肤，可接受，后续可加 chart 主题） ③ inline style 里的 UI 色（如 `summary-snap-tag` 的 `#86909c`）也要改 var()
- **不改**：ECharts 配置色值、数据语义色、布局结构、功能逻辑

## 验收标准
- 4 个皮肤切换流畅，每个都美观协调（无撞色/无看不清的文字）
- 涨红跌绿在所有皮肤下一致（数据语义不变）
- localStorage 持久化，刷新记住选择
- 双版一致，公网部署生效
- 现有功能无回归（图表/卡片/tab/modal 都正常）

## 派子 agent 执行
按 supervisor-loop 模式派 1 个 agent 串行做 Step 1-4（单 agent 避免双版冲突），完成后派验收 agent 切 4 皮肤验证。
