# README 命名统一 + og.png 配图优化方案

> 调研产出（2026-08-11，只读调研，本文件为唯一写产物）
> 背景：用户反馈 README 项目名不统一（一会"市场温度看板"一会"A股情绪看板"），且配图 og.png 内容 low，要求整理统一。

---

## 1. 现状盘点

### 1.1 命名现状（README vs 全站实际用名）

**README.md（滞后，仍是旧名）：**

| 位置 | 内容 | 判定 |
|---|---|---|
| L1 主标题 | `# 📊 市场温度看板 · tdsignal` | 旧名 ❌ |
| L3 副标题 | `> **多源 A股情绪看板** —— 把散落各处的情绪值、涨跌家数、连板高度、买卖点信号、ETF 评分、策略实验室汇总到一处…` | 旧名 ❌ |
| L16 一句话 | `一个把「数据采集 → …」全链路打通的开源 A股看板。` | 旧名 ❌ |
| L38 图片 alt | `![市场温度看板 · tdsignal](static-site/og.png)` | 旧名 ❌ |
| L40 仓库标识 | `trade-data-signal` / `tdsignal` / `tdsignal-ujpzw01zm` | 半旧（tdsignal-ujpzw01zm 为废弃旧域名，见下） |
| L290/356/370 等处「启动看板」「本看板仅供学习研究」 | 普通名词泛指（本产品），非名称 | 可保留 |

**全站（index.html + manifest.json）已统一为「信号实验室」+「tdsignal」：**

| 位置 | 内容 |
|---|---|
| index.html L9 | `apple-mobile-web-app-title` = 「信号实验室」 |
| index.html L11 title | `信号实验室 | 盘后复盘·多市场情绪·技术分析参考点 · tdsignal` |
| index.html L24-26 og | `og:site_name` / `og:title` = 「信号实验室」 |
| index.html L28 og:image | `https://ss.fx8.store/og.png` |
| index.html L31-32 twitter | 「信号实验室 | 盘后复盘…」 |
| index.html L35 schema.org | `name="信号实验室"`，`alternateName=["tdsignal","A股情绪看板","情绪数据复盘看板"]` |
| index.html L80 h1 | 「信号实验室 · tdsignal」 |
| index.html L81 | 「tdsignal（信号实验室）是 A股/港股/全球盘后复盘情绪数据看板」 |
| index.html L98 h1 | 「📊 信号实验室」 |
| manifest.json | `name`「信号实验室 | 盘后复盘·多市场情绪看板」、`short_name`「信号实验室」 |

- **结论**：全站实际主名已是「**信号实验室**」（英文标识 **tdsignal**），README 滞后。用户意图（以"信号实验室"为主名）与全站现状一致，README 只需向全站对齐，方向无分叉。
- `tdsignal-ujpzw01zm` = 早期 MaoziYun 部署子域名（`tdsignal-ujpzw01zm.maozi.io`，见 docs/archive/NOTES-history.md），已废弃（maozi 兜底站、s.aisusu.cn 已撤 DNS）。对 GitHub 读者无意义，建议从 L40 清理（保留 `trade-data-signal` / `tdsignal` 两个有效标识即可）。

### 1.2 og.png 现状

- **文件**：`static-site/og.png`，PNG，**1200 x 630**（已符合 OG 标准尺寸），8-bit RGB non-interlaced，61KB。**已 tracked 进 git**（`git ls-files` 确认），GitHub 仓库内相对路径可渲染。
- **生成方式**：`scripts/gen_og_image.py`（Python **PIL** 手绘，中文字体 PingFang.ttc，垂直渐变背景 + 顶部 tdsignal 品牌条 + 主标题 + 3 张数据卡 + 底部域名）。**无任何调用点**（grep 无 CI/launchd/export 引用），是**手动跑 + commit 上线**的独立脚本。
- **后端路由**：`app/main.py` `/og.png` → `FileResponse(static-site/og.png)`，index.html og:image 指向 `https://ss.fx8.store/og.png`。
- **现有内容**：顶部「tdsignal」蓝标 + 「trade-data-signal」灰字；主标题「**信号实验室**」（名字已对）；slogan「盘后复盘 · 情绪数据 · 买卖点信号」；3 数据卡（A股综合情绪分 68.4 / 涨停跌停 64/12 / 成交额 9876 亿）；底部域名「s.sugas.site」。

**og.png 问题清单（"low"的根因）：**
1. **假数据**：3 张数据卡数字**写死**（68.4 / 64/12 / 9,876），非实时、会误导、显 low。
2. **域名错误**：底部写死 `s.sugas.site`（MaoziYun 备站），但主站是 `ss.fx8.store`，index.html og:image 也指向 ss.fx8.store —— 分享卡域名与主站不一致。
3. **描述偏旧**：slogan 与底部描述只提情绪/回测，未体现信号实验室完整定位（信号灯 / 策略实验室 / 凯利回测 / 降亏过滤 / AI 速递）。
4. **无可视化**：仅 3 张纯文字数字卡，无走势线/信号灯/温度计等图形元素，视觉单薄。

### 1.3 README 配图嵌入现状

- README L38：`![市场温度看板 · tdsignal](static-site/og.png)` —— 用**仓库内相对路径**。
- 用户在 GitHub 看到的就是 `https://github.com/xp13465/trade-data-signal/raw/main/static-site/og.png`（相对路径被 GitHub 自动解析为 raw URL，即用户反馈的那个 URL）。
- **相对路径是 GitHub 推荐做法**（raw URL 硬编码仓库名，仓库改名/迁移会断链），**无需改成硬编码 raw URL**。优化点集中在：alt 文案 + 可选限宽。

---

## 2. 命名统一方案

### 2.1 命名决策

| 项 | 决策 | 理由 |
|---|---|---|
| **主名（中文）** | **信号实验室** | 全站 index.html/manifest 已统一用此名，用户意图一致，零迁移成本 |
| **英文标识** | **tdsignal** | 全站 + 仓库代号（trade-data-signal）已一致 |
| **描述性副名** | **A股/港股/全球盘后复盘情绪数据看板** | 描述用途非名称，index.html L81 已有此口径，README 副标题对齐 |
| **旧名「市场温度看板」「A股情绪看板」** | 不再作主名/副名 | 仅 schema.org `alternateName` 保留「A股情绪看板」作 SEO 兼容（已存在，不动） |
| **「本看板」泛指** | 保留 | 普通名词，非名称 |

### 2.2 改动点清单（README.md）

| 位置 | 现状 | 建议文案 |
|---|---|---|
| L1 主标题 | `# 📊 市场温度看板 · tdsignal` | `# 📊 信号实验室 · tdsignal` |
| L3 副标题 | `> **多源 A股情绪看板** —— 把散落各处的…` | `> **A股/港股/全球盘后复盘情绪数据看板** —— 把散落各处的情绪值、涨跌家数、连板高度、买卖点信号、ETF 评分、策略实验室汇总到一处…`（其余不变） |
| L16 一句话 | `…全链路打通的开源 A股看板。` | `…全链路打通的开源情绪数据看板。`（或「开源信号实验室」，二选一，推荐前者更朴实） |
| L38 图片 alt | `![市场温度看板 · tdsignal](static-site/og.png)` | `![信号实验室 · tdsignal](static-site/og.png)` |
| L40 仓库标识 | `trade-data-signal` / `tdsignal` / `tdsignal-ujpzw01zm` | `trade-data-signal` / `tdsignal`（删除废弃的 `tdsignal-ujpzw01zm` 旧 Maozi 子域名） |

> 其余章节（功能亮点/架构/技术栈/参考致敬/数据开源/快速开始/声明/License）经 grep 无旧名残留，不需改。

---

## 3. og.png 优化方案

### 3.1 新设计（内容/布局）

目标：一张图讲清「信号实验室」是什么 —— **盘后复盘 · 情绪温度 · 买卖点信号 · 策略实验室**，带可视化元素，去掉假数据观感。

**布局建议（1200x630，保持 OG 标准尺寸）：**

```
┌────────────────────────────────────────────────────────────────────┐
│  [tdsignal 蓝标]  trade-data-signal                   信号实验室 · tdsignal │  ← 顶部品牌条(右对齐中文名)
│                                                                      │
│   ╭─ 主标题区 ───────────╮    ╭─ 情绪温度计 ─────────────────╮         │
│   │ 📊 信号实验室         │    │  0─────50─────100  (渐变条+冰点/过热标尺) │
│   │ 盘后复盘 · 情绪温度 · │    │  ● 当前 68.4 · 偏热  (示例/或注入值)   │
│   │ 买卖点信号 · 策略实验室 │    ╰──────────────────────────────╯         │
│   ╰───────────────────────╯                                          │
│                                                                      │
│  ╭─ 涨跌家数 ──╮  ╭─ 信号灯 ──╮  ╭─ 策略实验室 ──╮  ╭─ AI 速递 ──╮    │
│  │ ▓▓▓ 涨 3100 │  │ ●买  ●卖  │  │ 凯利回测     │  │ 每日白话    │    │
│  │ ▓ 跌 1800   │  │ ●辅买 ●追  │  │ 降亏过滤31项 │  │ DeepSeek   │    │
│  ╰──────────────╯  ╰───────────╯  ╰──────────────╯  ╰─────────────╯    │
│                                                                      │
│  ss.fx8.store   ·  A股/港股/全球 · 情绪分/跨市场评分/行业热力图/模拟回测  │  ← 底部域名(改主站)
└────────────────────────────────────────────────────────────────────┘
```

**关键设计决策：**

| 项 | 方案 |
|---|---|
| 主标题 | 「信号实验室」+ 右侧/右上「tdsignal」英文标识，品牌双标识对齐 index.html |
| slogan | 「盘后复盘 · 情绪温度 · 买卖点信号 · 策略实验室」（对齐 README 一句话定位） |
| 可视化元素 | ① 情绪温度计：0-100 渐变条 + 冰点(≤20)/过热(≥80)标尺 + 指针/标记（PIL 可画）② 涨跌家数红绿条形 ③ 信号灯（红卖/绿买/紫辅买，对齐首页配色）④ 迷你 sparkline 走势线（可选，PIL 画折线） |
| 数据卡 | 改为**可视化面板**为主，弱化"精确数字"；若保留数字 → 右下角标「示例」小字，或用 `--live` 参数注入当日真实值（见 3.3） |
| 底部域名 | **`ss.fx8.store`**（主站，对齐 index.html og:image）；描述行补「信号实验室 · tdsignal」 |
| 尺寸 | **1200x630**（OG 标准，现状已合规，保持不变） |
| 配色 | 沿用现有深色渐变（#1f2329→#2d3239）+ 品牌蓝 #165dff + 红绿信号色，与站点 4 皮肤/红金默认一致风格 |

### 3.2 生成技术路线

- **结论：改造现有 `scripts/gen_og_image.py`（PIL），不引入 matplotlib/新依赖**。理由：现有脚本已是 PIL 手绘 1200x630 完整框架（渐变/卡片/字体均可用），加可视化元素（渐变条/条形/折线/圆点）PIL `ImageDraw` 原生支持，零新依赖；matplotlib 输出中文字体配置反而更麻烦。
- 改造点：
  1. 品牌条右对齐补「信号实验室 · tdsignal」；
  2. slogan 更新（4 段定位）；
  3. 数据卡 → 可视化面板（温度计渐变条 + 涨跌家数条形 + 信号灯三色点 + 可选 sparkline）；
  4. 底部域名 `s.sugas.site` → `ss.fx8.store`；
  5. 新增 `--live` 可选参数：从当日 `static-site/data/overview.json` 读真实情绪分/涨跌家数注入，无参数/无数据时回退示例值并在卡片标「示例」。
- 生成 + 上线：`python3 scripts/gen_og_image.py` → 覆盖 `static-site/og.png` → commit（og.png 已 tracked，push main 后 GitHub 渲染 + ss.fx8.store/og.png 同步更新）。

### 3.3 真实数据 vs 示例值（决策点，附推荐）

- **问题**：og.png 是**单一静态文件**，用于 GitHub 仓库首图 + 微信/Telegram/微博社交分享卡片。若注入"当日真实数据"，每次收盘都要重生成 + commit（新增定时负担），且分享的是历史某个时点快照，无"实时"意义。
- **推荐**：**布局/可视化为主 + 示例值标注「示例」**。og.png 的本质是**品牌宣传图**（让读者一眼看懂这是什么），不是数据快照。具体：温度计/涨跌家数/信号灯用代表性示例值，卡片右下角标「示例」小字，避免误导；`--live` 模式作为可选增强保留（想发"今日快照"分享时手动跑）。
- 若用户坚持实时：可接 export.py 末尾或 update-all 后自动跑 `gen_og_image.py --live` + commit（需避开 §14 定时撞车时点），成本是每日多一个 commit，一般不推荐。

### 3.4 README 配图嵌入优化

- **引用方式不变**：保留相对路径 `static-site/og.png`（GitHub 自动渲染为 raw URL = 用户反馈的 URL，且仓库改名/迁移不炸）。**不要**硬编码 `https://github.com/xp13465/trade-data-signal/raw/main/...`。
- **alt 更新**：`![信号实验室 · tdsignal](static-site/og.png)`（随命名统一）。
- **可选限宽**：GitHub 对 README 图片默认 max-width 100%，1200x630 显示正常。如想控制，可改为 HTML 标签 `<img src="static-site/og.png" alt="信号实验室 · tdsignal" width="600">`（GitHub 支持 HTML img），不强制。

---

## 4. 实施 checklist（供实施 agent 使用）

1. 命名：按 §2.2 改 README.md 5 处（L1/L3/L16/L38/L40）。
2. 配图：改造 `scripts/gen_og_image.py`（§3.2），跑 `python3 scripts/gen_og_image.py` 生成新 `static-site/og.png`。
3. 自验：
   - `grep -n "市场温度看板\|多源 A股情绪看板\|开源 A股看板\|tdsignal-ujpzw01zm" README.md` 无残留（仅「A股情绪看板」允许出现在 index.html schema alternateName，README 中不出现）；
   - `file static-site/og.png` = 1200x630 PNG；
   - 用 `git diff --stat` 确认改动集中在 README.md + gen_og_image.py + og.png。
4. commit（feat 分支）message 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`。

---

## 5. 相关文件

- `/Users/linhuichen/code/trade/README.md`（命名改动目标）
- `/Users/linhuichen/code/trade/static-site/og.png`（配图目标，已 tracked）
- `/Users/linhuichen/code/trade/scripts/gen_og_image.py`（配图生成脚本，改造目标）
- `/Users/linhuichen/code/trade/static-site/index.html`（全站命名参照，已统一为信号实验室，不需改）
- `/Users/linhuichen/code/trade/static-site/manifest.json`（同上）
- `/Users/linhuichen/code/trade/app/main.py`（/og.png 路由，不需改）
