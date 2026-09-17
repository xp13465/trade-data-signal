# 站点评测报告：ss.fx8.store `/lab?sub=sigkelly`

- 日期：2026-09-17
- 对象：线上站点 lab/sigkelly（信号实验室 · 凯利）
- 方法：curl 压测响应头/压缩/缓存 + 源码核实 + Playwright Chromium 真实移动视口 390×844（iPhone UA）
- 角色：Codex 外部 reviewer（只读评测，不改源码）

## TL;DR
部署已是顶配（Cloudflare Worker + R2 + zstd 压缩 + 分层缓存），「加载慢」的真凶是**数据量**：满载解码约 100MB JSON。手机端无横滚、无报错，主要样式问题是**字号偏小（9~11px）**。提速空间集中在两处：缓存规则漏配（一行修）+ 数据瘦身（最大头）。

## 一、部署现状（已做好）
| 项 | 现状 |
|---|---|
| 架构 | Cloudflare Worker + Static Assets + R2，worker/headers.js 统一接管 header |
| 压缩 | zstd（浏览器）/ gzip（curl 回退），JS/CSS/JSON 全压 |
| 缓存分层 | HTML no-store 防旧版；版本化 JS 1 年 immutable；实时数据 60s；历史 1h |
| 懒加载 | lab.min.js、echarts.min.js 进 lab 才动态注入 |
| 渐进加载 | sigkelly「先近 2 年(Y1) → 后台补全全部年份」，有占位文案 |

## 二、性能实测（Chromium 390×844）
- DOMContentLoaded ≈ 3.0s，load ≈ 6.2s，全量数据补全 > 12s
- 完整加载 ≈ 解码 ~100MB、传输 ~8MB（zstd 后）
- 大头（按解码字节）：
  - signal_kelly_trades_parts/t2011..t2026.json 合计 ≈ 78MB（最大 t2025 单年 17.7MB）
  - accum_nav_map.json ≈ 19MB
  - overfit_monitor.json 3.9MB / boot.json 2.1MB / kelly_loss_features.json 1.1MB
  - app.min.js 1.04MB + echarts.min.js 1.03MB + lab.min.js 559KB（代码 2.6MB）

## 三、Findings
- [P2] **缓存规则漏配**：worker/headers.js immutable 写的是 `style.css`/`lab.css`，但 index.html 实际加载 `style.min.css`/`lab.min.css`；`common.min.js`/`purpose-notes.min.js`/`i18n.js`/`inline-init.js`/`manifest.json`/`changelog.json` 也不在名单。实测 style.min.css/lab.min.css 返回 `private, no-cache, must-revalidate`，每次访问都 revalidate。
- [P2] **数据体积过大（「慢」的根因）**：页面渲染的是统计结果（胜率/盈亏比/n/凯利 f），下发的是逐笔交易明细。
- [P2] **疑似死数据**：signal_kelly_trades.json 与 _sdc.json 各 78MB 全量文件；网络日志里页面只拉 parts/tXXXX 分片，疑似只在 R2 吃存储+拖上传（156MB）。
- [P3] **移动端字号偏小**：lab.min.css 里 11px×104、12px×100、10px×48、9px×7；sigkelly 水印/角标/弹窗在 @media 760px 明确写成 10px/10.5px。
- [P3] **app.min.js 1MB monolith**：首页也全量加载，可按主 tab 拆 chunk；echarts 可按需引入。

## 四、交互 / 功能
- 无 console.error / pageerror / warning，功能链路未断。
- 渐进加载（Y1→ALL）正常；页面全高约 13.4k px，长滚动页，建议加「年份/周期」分段锚点。

## 五、建议整改清单（按优先级）
1. worker/headers.js immutable 正则补全所有 `?v=` 版本化静态资源（1 行，立即）。
2. 数据瘦身：构建期预聚合摘要 + 明细按需/范围 API（最大提速，100MB → 估可降到 1/10）。
3. 核实并摘除 78MB 全量 signal_kelly_trades(_sdc).json 死数据（省 156MB 存储+上传）。
4. 移动端字号/点击目标上调（标签 ≥11px，点击 ≥44px）。
5. app.min.js 按 tab 拆包 + echarts/core 按需引入（中期）。

## 六、评测局限
移动端用 headless Chromium（iPhone UA + 390×844），非真机 Safari；safe-area 手势、100vh 等 Safari 特有坑未覆盖，上线前建议真机 Safari 再点一轮。

## 附：给 Claude 主控的处置建议
本报告为外部评测，结论不一定对，请独立复核后由 implementer 逐条处置（尤其整改清单 1/2/3）。详细验收脚本仓库已有 scripts/playwright-accept/accept_sigkelly_silent.mjs 可复用。
