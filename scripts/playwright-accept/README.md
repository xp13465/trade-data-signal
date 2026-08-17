# scripts/playwright-accept/ — Playwright 前端验收脚手架

把「看图验收」变成「程序化断言」的通用工具。主控看不了图片,这里把所有验收证据
(console 报错、网络请求、DOM 断言、accessibility snapshot)变成文本,主控/ reviewer/
tester 可直接读。

纯工具,不碰 static-site/ 任何业务文件、不碰后端、不碰 app.js/lab.js。

## 目录索引(§23.5 塞入即归类)

| 文件 | 作用 |
|---|---|
| `accept.js` | 主入口:console 抓取 + 网络断言 + DOM 断言,输出 PASS/FAIL |
| `snapshot.js` | 辅助:输出页面 accessibility snapshot 文本结构 |
| `ticker-check.js` | 首页「全球盘面跑马灯」验收模板(占位断言,待上线回填) |

> 新增脚本在此索引追加一行。

## 安装

```bash
cd /Users/linhuichen/code/trade/scripts/playwright-accept
npm init -y
npm i playwright
npx playwright install chromium   # 下载 Chromium(首次)
```

> 若项目其他目录已有 node_modules/playwright 可复用,不必重复下载。首次 `npx playwright
> install chromium` 需联网下载浏览器;网络被墙时设 `PLAYWRIGHT_DOWNLOAD_HOST` 镜像
> (如 `https://npmmirror.com/mirrors/playwright/`)重试。

## 用法

### accept.js(主入口)

```bash
# 本地静态站(先起服)
python3 -m http.server 8000 -d /Users/linhuichen/code/trade/static-site

node accept.js http://localhost:8000 \
  --expect-request news_digest.json \
  --assert '#app|exists'

# 线上三站任选
node accept.js https://ss.fx8.store \
  --expect-request news_digest.json \
  --block-on-error
```

选项:
- `--expect-request <子串>` 断言某请求发出且 HTTP 200(可多次)
- `--expect-request-missing <子串>` 断言某请求未发出(验证降级后旧源已停)
- `--block <子串>` 屏蔽匹配请求,模拟源故障,验证降级(可多次)
- `--assert <选择器|期望>` DOM 断言,期望值:`text=xxx` / `exists` / `attr=key=value` / `count=N`
- `--assert-file <路径>` 从文件读断言列表(每行一条)
- `--block-on-error` 有 error 级 console 或 pageerror 时 exit 1
- `--wait <ms>` 加载后额外等待毫秒(给前端渲染/网络留时间)

退出码:0=全 PASS;1=有 FAIL / error 级 console(开启 --block-on-error)/ 参数错误。

### snapshot.js(辅助)

```bash
node snapshot.js http://localhost:8000 --wait 2000
# 输出页面 accessibility 树文本(role/name 层级),主控直接读页面结构
```

### ticker-check.js(跑马灯模板)

```bash
# 正常跑(断言 8 品种 + 布局滚动 + 主源发出)
node ticker-check.js http://localhost:8000

# 屏蔽东财主源验证降级
node ticker-check.js http://localhost:8000 --block push2delay.eastmoney.com
```

> 选择器已按 2026-08-17 实测回填:.global-ticker 容器 / .gt-scroll 滚动条(一行超宽即滚动)/
> .gt-name 品种(无缝滚动复制2份 → 16 节点,唯一品种 8)/ 主源 push2delay.eastmoney.com。
> 降级模式当前预期 FAIL = 跑马灯备源兜底尚未就位(block 东财后 8 品种无备源请求 + 页面
> error),为真实验收发现,待跑马灯实施 agent 回填备源子串后转 PASS。

## 派单模板句(给 reviewer/tester 派单 prompt 复制)

> 用 Playwright 验收脚手架跑前端验收:`node /Users/linhuichen/code/trade/scripts/playwright-accept/accept.js <URL> --expect-request <关键请求子串> --block-on-error`。要点:①URL 本地静态站(先 `python3 -m http.server 8000 -d /Users/linhuichen/code/trade/static-site`)或线上三站(ss.fx8.store / sss.sugas.site / s.sugas.site);②`--expect-request` 断言数据请求发出且 200;③`--block <主源子串>` 屏蔽主源验降级到备源;④`--assert '选择器|期望'` 断言 DOM;⑤`--block-on-error` 使 error 级 console 直接 FAIL;⑥看页面结构用 `node .../snapshot.js <URL>`。

## 参考与致敬

- 基于开源库 [Playwright](https://playwright.dev)(Node.js API,headless Chromium 驱动
  浏览器执行 console 抓取/网络拦截/DOM 断言/accessibility snapshot)。MIT 协议。
