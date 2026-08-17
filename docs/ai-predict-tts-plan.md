# AI 预测语音播报(edge-tts)落地调研方案

> 调研 agent 产出,2026-08-12。用户需求:首页 AI 预测内容上方(次日待回填后面)加播放按钮,点击朗读 AI 预测结果,用 edge-tts 方案。只读调研产出,未改代码。

## 一、edge-tts 技术结论(本环境 WebFetch/WebSearch 被网络策略阻断,以下用 edge-tts 7.2.8 官方源码包核对)

**edge-tts = Python 包/CLI,调用微软 Edge 浏览器"大声朗读"的免费在线 TTS 服务,不是 Azure 商用 TTS**。技术要点(全部来自 `/tmp/edge-tts-src/whl/edge_tts/constants.py`/`communicate.py`/`drm.py` 实际源码核对):

| 项 | 结论 | 证据 |
|---|---|---|
| 底层端点 | `wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=6A5AA1D4EAFF4E9FB37E23D68491D6F4&ConnectionId=...&Sec-MS-GEC=...&Sec-MS-GEC-Version=...` | constants.py `BASE_URL`/`TRUSTED_CLIENT_TOKEN`/`WSS_URL`;communicate.py L466-467 拼 Sec-MS-GEC |
| 要不要 API key | **不要**。TrustedClientToken 是硬编码的"Edge 大声朗读"扩展共享 token,非订阅凭证;无账号/无计费 | constants.py `TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"` |
| 免费? | **免费**(依赖微软 Edge 客户端免费服务,社区大规模使用中;无官方 SLA,微软可能调整,属不可控风险,见风险节) | 服务端无鉴权计费,源码无任何 key 参数 |
| 输出格式 | `audio-24khz-48kbitrate-mono-mp3`(24kHz 48kbps 单声道 mp3) | communicate.py L408/L438 |
| 反滥用机制 | WebSocket 头里 `Origin: chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold`(伪造 Edge 扩展源)+ `User-Agent` 伪造成 Edge/Chrome + query 里 `Sec-MS-GEC`(DRM 模块算的防抖 token) | constants.py `WSS_HEADERS`/`BASE_HEADERS`;drm.py `generate_sec_ms_gec` |
| 中文音色 | 可用标准中文神经音色:`zh-CN-XiaoxiaoNeural`(晓晓,女,推荐)/ `zh-CN-YunxiNeural`(云希,男)/ `zh-CN-YunyangNeural`(云扬,男,新闻)/ `zh-CN-XiaoyiNeural`/ `zh-CN-YunjianNeural` 等;还有港/台 `zh-HK-*`/`zh-TW-*` 系列 | 官方 voices/list 端点数据(见来源);本项目用 `zh-CN-XiaoxiaoNeural` |

**⚠️ 浏览器能否前端直调?→ 不能直接调**。原因(结论核心):
1. 浏览器原生 `WebSocket` API **不允许设置自定义请求头**(Origin/User-Agent 由浏览器固定注入,不可改);
2. 服务端校验 `Sec-MS-GEC`(需用 DRM 算法对挑战值算 HMAC 风格 token)+ 校验 Origin/UA 必须像真实 Edge 大声朗读,浏览器环境下既改不了头也算不了 GEC → 直接连 `wss://speech.platform.bing.com` 会被拒(403/close)。
3. 即使 WebSocket 可连,CORS 语义下微软服务不会放行浏览器页面源。
→ **正确调用方式 = 服务端(Python edge-tts 包)生成 mp3 文件,前端用 `<audio>` 播文件**。

来源:
- 项目 edge-tts 官方 GitHub `github.com/rany2/edge-tts`(本环境 WebFetch 被拒,以 7.2.8 wheel 源码核对,链路一致)
- PyPI `pypi.org/project/edge-tts`
- 微软 Edge 在线 TTS 端点 `speech.platform.bing.com`(Edge 浏览器"大声朗读"功能使用)

**CLI / 程序化用法**(落地要用):
```bash
edge-tts --voice zh-CN-XiaoxiaoNeural --text "今日要点..." --write-media out.mp3
```
```python
import edge_tts, asyncio
async def main():
    c = edge_tts.Communicate("今日要点...", "zh-CN-XiaoxiaoNeural")  # 可加 rate="-5%" 调速
    await c.save("out.mp3")          # 或 save_sync 同步版(communicate.py L599/L648)
asyncio.run(main())
```

## 二、项目 AI 预测数据结构 + 合成点

### 数据结构(已核对 `static-site/data/daily_brief.json`)
- 顶层:`meta` + `text` + `disclaimer` + `generated_at`
- `text` 四段(读前端渲染,适合朗读的核心内容):
  - `review`(复盘,~141 字)、`trend`(趋势,~95 字)、`watch`(关注,~102 字)、`risk`(风险,~72 字)、`note`(免责)
- `meta`(适合朗读的断言):`date`(如 20260811)、`direction`(flat/up/down)、`confidence`(0-100)、`confidence_reason`、`highlights`(🎯今日要点列表)、`watch_list`、`risk_items`、`roles`(四角色结论)、`debate`(多空辩论)
- 历史:`daily_brief_history.json` → `{items, total, offset, limit, stats}`;items 每条 `{date, meta, text, disclaimer}`,**今日条目在 items[0]**(write_outputs L1175 `history.insert(0, item)`)

### 前端渲染点(已核对 `static-site/app.js`)
| 位置 | 函数/行 | 内容 |
|---|---|---|
| 首页横幅 | L8898/8933 | `🤖 AI 预测` 按钮(打开弹窗),非内容区 |
| AI 预测弹窗单条 | `_dailyBriefItemHtml` L19348 | `sh-date` 行:`方向 + 把握度 + 日期 + 命中 + 次日待回填(_dbActualHtml) + 展开提示`;**今日条目在首行** |
| 历史收盘分析结合块 | `_summaryHistoryItemHtml` L19110 | `sh-ai-brief-head`:`方向 + 🤖AI预测 + 把握度 + 命中 + 次日待回填` |
| 次日待回填 | `_dbActualHtml` L19243-19251 | `hit.actual_sh_pct != null` 显示"次日上证 ±x.xx%",否则"次日待回填" |

"次日待回填"在以上 **2 个渲染函数**都出现(弹窗单条 + 历史收盘分析结合块)。用户说"首页 AI 预测内容上方(次日待回填后面)"——**主落点 = AI 预测弹窗今日条目 `sh-date` 行 `_dbActualHtml` 之后**;为 §22 一致,结合块同 helper 同位置一起加。

### 后端生成流程 + 合成插入点(已核对 `scripts/gen_daily_brief.py`)
- 每日 20:40?否——**17:50 盘后 update_all 管线**内触发(launchd `com.trade.daily-brief` → `run_daily_brief.sh` → gen_daily_brief.py;`config/daily_brief.yaml` `schedule_enabled: true`)
- main() 关键段(L1732-1781):
  1. `backfill_hits` + `write_outputs(static_dir, brief, cfg)` → 写 daily_brief.json + history
  2. `notify_daily_brief`(邮件/飞书,失败不阻塞)
  3. `upload_to_r2(repo, args.no_upload, files=[BRIEF_FILE, HISTORY_FILE])` → 调 `upload_r2.py upload-data-files <files>`,上传到 **R2 `data/` 前缀**
  4. `staticdata_sync(...)` → 同步到数据仓库 git(防留旧版)
  5. 再单独传 run_log
- **推荐合成插入点:在 `write_outputs` 之后、`upload_to_r2` 之前**(L1732-1759 之间):用刚写好的 `brief` 组朗读文本 → edge-tts 合成 → 写 `static-site/data/daily_brief_tts_<date>.mp3` → **把 mp3 文件名加进 upload_to_r2 的 files 列表**(`cmd_upload_data_files` 支持任意文件名,已核对 L786-833,`_upload_glob` 对具体文件名 glob 可匹配 + `f.exists()` 过滤,自动传 R2 `data/` 前缀 + purge cache)→ 同批 staticdata_sync。失败不阻塞主流程(edge-tts 异常 catch 记日志继续)。

### R2 上传机制(已核对 `scripts/upload_r2.py`)
- 现有前缀命令:upload-lab/trade-sim/index/industry/public-fund/offshore-fund/data-large/all-data/db/claude-backup/intraday/data-files 等
- **不需要新建前缀命令**:mp3 走现有 `upload-data-files`(gen_daily_brief 已用它传 daily_brief.json),文件放 `static-site/data/daily_brief_tts_<date>.mp3` → R2 key `data/daily_brief_tts_<date>.mp3`
- 前端取用 URL:
  - **推荐** `https://ss.fx8.store/r2/data/daily_brief_tts_<date>.mp3`(Worker `/r2/` 代理 `r2ProxyHandler` L108-142 对任意 R2 对象生效,含 .mp3;R2 key=pathname 去 `/r2/`;带 ACAO:* 备站可跨域;边缘缓存 1h)
  - 注意:**`/data/` rewrite 只接 `.json`/feed.xml**(worker L271),`./data/xxx.mp3` 相对路径**不会被 Worker 服务**,不能走 dataUrl 相对路径
  - 备选 `https://ssd.fx8.store/data/daily_brief_tts_<date>.mp3`(公开桶直链,现有硬编码模式,upload_r2.py L509 注释)
- ⚠️ Content-Type:`s3_request` 按扩展名推断(L122-130),mp3 不在 `_CONTENT_TYPE_MAP` → 回退 `application/octet-stream`(浏览器 `<audio>` 大多能播,但为规范建议 `_CONTENT_TYPE_MAP` 加 `".mp3": "audio/mpeg"` 一行)

### 环境依赖
- edge-tts **未安装**于 trade-data/.venv 与 trade/.venv(aiohttp 也不在)。落地需 `pip install edge-tts`(自拉 aiohttp+certifi)到 **trade-data/.venv**(gen_daily_brief 跑在 REPO=trade-data)
- 17:50 管线已有 deepseek 生成 ~1-3min,edge-tts 合成 ~500 字约 10-30s,加在管线内可接受

## 三、推荐方案(主方案:后端生成 mp3 → R2 → 前端播放按钮)

1. **合成**:gen_daily_brief.py 在 `write_outputs` 后合成 `static-site/data/daily_brief_tts_<date>.mp3`。
   - 朗读文本(按序拼接,`zh-CN-XiaoxiaoNeural`,§22 与前端 _dbBriefDetailHtml 同源同口径,2026-08-17 校准):`方向+把握度(措辞与前端 _dbDirLabel 一致:偏强/偏弱/震荡)` → `大盘区间(meta.range lo~hi)` → `🧭结论(meta.debate.summary,回退口径同前端 _dbConclusionHtml: confidence_reason→highlights[0])` → `meta.highlights`(🎯今日要点) → `text.review` → `text.trend` → `text.watch` → `text.risk`。全程约 600 字 → 约 2 分钟音频 ~800KB(48kbps)。旧条目无 range/结论字段时该句跳过(不伪造,与前端一致)。
   - 可选"要点版":只读 highlights+trend+watch(约 300 字,~1.2 分钟 ~450KB),省时省存储;默认给完整版,用户可 veto。
   - 合成失败(网络/微软调整)→ catch 异常记日志,**不阻塞** daily_brief 主流程,前端按钮隐藏(字段缺省)。
2. **上传**:mp3 加入 `upload_to_r2`/`staticdata_sync` 的 files 列表(复用现有 `upload-data-files` → R2 `data/` 前缀)。`_CONTENT_TYPE_MAP` 加 `".mp3": "audio/mpeg"`。
3. **数据字段**:brief.meta 加 `tts_available: true`(合成成功时),随 write_outputs 归档进 history 今日条目;前端据此只给今日条目显示播放按钮(历史旧条目无字段不显示)。
4. **前端播放按钮**(A 级纯显示,主控可直接做):
   - 新 helper `_dbPlayBtn(meta, dateRaw)`:返回 `<button class="db-play">🔊</button>`;点击创建 `<audio>` 元素,`src = "https://ss.fx8.store/r2/data/daily_brief_tts_" + dateRaw + ".mp3"`,play();再次点击停止;播放前先停掉上一个(单例 currentAudio)。
   - 放 2 处 `_dbActualHtml(meta)` 之后:`_dailyBriefItemHtml` L19348(sh-date 行)+ `_summaryHistoryItemHtml` L19110(sh-ai-brief-head),§22 一致。仅 `meta.tts_available === true` 时渲染。
   - 备站跨域:URL 走 `/r2/` 代理(带 ACAO:*),`<audio>` 跨域可播。

## 四、备选方案(浏览器 speechSynthesis 实时读,需降级才用)

- 浏览器内置 `window.speechSynthesis` + `SpeechSynthesisUtterance`,`lang="zh-CN"`,直接实时读当前页面文本。**优点**:零后端零存储零部署。
- **缺点**:①音色/质量明显差于 edge-tts 神经音色(依赖 OS 本地语音,Chrome 常用 Google 中文男声,机械感强);②跨设备音色不一致(iOS/Android/桌面各不同);③无 mp3 可缓存复用,每次重新读;④后台/低电量可能被系统打断。
- **适用**:edge-tts 合成失败时的前端兜底(播不了 mp3 才用),不推荐为主方案。

## 五、落地步骤 + 验收口径 + 风险

### 落地步骤(B 级,派实施 agent)
1. `pip install edge-tts` 到 trade-data/.venv
2. gen_daily_brief.py:write_outputs 后加 `_synth_tts(brief, static_dir, date)`(组文本 → asyncio.run(edge_tts.Communicate.save) → 返回 mp3 路径/是否成功)→ 成功则 `brief["meta"]["tts_available"]=True`(在 write_outputs 之前设,才能归档进 history)→ upload_to_r2/staticdata_sync files 加 mp3 名
3. upload_r2.py `_CONTENT_TYPE_MAP` 加 mp3
4. app.js:加 `_dbPlayBtn` helper + 两处 `_dbActualHtml` 后插入(仅 tts_available 渲染)
5. build_min.py + bump_asset_version.py + bump sw.js CACHE_VERSION(§9 三步)
6. commit + push feat + merge main + push main(**避开 17:50 update_all 推 main 时点**;盘中 push 代码 main 不撞 intraday,§14/§16)

### 验收口径(实施 agent 自验 + reviewer)
- 后端单测:手动跑 `gen_daily_brief.py` 一次(或 --mock),确认 mp3 生成 + R2 `data/daily_brief_tts_<date>.mp3` 存在 + purge cache
- 线上数据层:`curl -sI https://ss.fx8.store/r2/data/daily_brief_tts_<date>.mp3` → 200 + Content-Type audio/mpeg + Content-Length >0
- 线上前端层:curl 线上 app.min.js 含 `db-play` class / 中文串(§8 "功能 done"三查清单第③项)
- daily_brief.json meta.tts_available=true 且 history 今日条目带该字段
- 前端:首页 AI 预测弹窗今日条目"次日待回填"后出现 🔊 按钮,点击播放完整播报;历史旧条目无按钮;备站(s.sugas.site/sss.sugas.site)可播放
- §22:弹窗 + 历史收盘分析结合块两处一致
- 失败降级:mock 强制 edge-tts 失败,确认 daily_brief 主流程不阻塞、按钮不显示

### 风险
| 风险 | 等级 | 对策 |
|---|---|---|
| edge-tts 依赖微软免费服务,无 SLA,可能被限流/调整 token | 中 | 合成失败不阻塞主流程 + 前端 tts_available 缺省隐藏按钮 + 备选 speechSynthesis 兜底;监控 daily_brief.log 里合成失败行 |
| 盘后 17:50 管线 +30s 左右合成时长 | 低 | 实测一次;失败不阻塞;必要时只合成要点版 |
| mp3 ~800KB/天 存储(R2) | 低 | R2 便宜;文件名带日期天然滚动,可定期清理 >30 天(或保留 90 天与 history 对齐) |
| `<audio>` 跨域/缓存 | 低 | /r2/ 带 ACAO:*;1h 边缘缓存对日更文件安全;mp3 文件名含日期天然破缓存 |
| 微软调整协议致 edge-tts 失效 | 低-中 | edge-tts 社区活跃常更新(7.2.8),升级包即可;备选 speechSynthesis |

### 关键文件路径
- 后端:`/Users/linhuichen/code/trade/scripts/gen_daily_brief.py`(main L1732-1759 插入点;upload_to_r2 L1247;write_outputs L1167)
- R2:`/Users/linhuichen/code/trade/scripts/upload_r2.py`(cmd_upload_data_files L786;Content-Type map L114-130)
- Worker:`/Users/linhuichen/code/trade/worker/headers.js`(r2ProxyHandler L108;/data/ 只接 .json L271)
- 前端:`/Users/linhuichen/code/trade/static-site/app.js`(_dbActualHtml L19243;_dailyBriefItemHtml L19348;_summaryHistoryItemHtml L19110;_R2_DATA_BASE L3649)
- 配置:`/Users/linhuichen/code/trade/config/daily_brief.yaml`(schedule_enabled: true)
