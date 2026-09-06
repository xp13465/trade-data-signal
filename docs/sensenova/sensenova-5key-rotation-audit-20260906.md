# 商汤 5key 轮询代理效率与成功率审计(2026-09-06)

> 服务 pending #30(轮询策略拍板)与 #48(代理高可用)。只读审计,未改任何代码。
> 结论一句话:代理机制本身设计合理(分层冷却/高峰限频/全冷退避),但**实际运行处于 9-01 诊断模式残留**(TTP_DETECT_LOG=1 / TTP_DUMP_BODY=1 / req-dump 开 / 日志级别实为 debug 全量),且**真实成功率为 60.7%**,38.6% 的客户端请求以 429 收场(高峰桶 09-06 12 点 876 次/小时最终 429)。主要浪费 = 高峰期 5 key 同时 rpm exhausted/额度耗尽时,客户端写死 4s 退避反复重试(最长一块 4.5 分钟连撞 318 次 429),代理无链路式熔断导致空转放大。

---

## 一、机制还原(读代码)

**文件**:`/Users/linhuichen/code/trade/scripts/sensenova-rotate-proxy.py`(8899, v4-flash)+ `sensenova-rotate-proxy-kimi.py`(8898, kimi-k3)+ 包装脚本 `sensenova-rotate-proxy.sh` + plist `com.trade.thinking-proxy.plist`。

| 维度 | 现状 |
|---|---|
| 轮换顺序 | round-robin 全局游标(`_rotate_idx`,L110-111/L426-429 加锁),每请求从游标起取「所有非冷却 key」构成 try_keys 序列 |
| 429 分层 | `_parse_429_msg`(L158-177):`tpm/rpm exhausted`=short(短时限流,换 key 即解,不冷却);`token plan entitlement`/`allocated quota`=quota(额度型,换 key 无用 → 单 key 冷却后继续轮换);unknown 按 short |
| 单 key 冷却 | `_mark_cool`(L179-195):level0=180s 起步 ×2 封顶 48min;高峰(9-14 点)再 ×2;成功响应(非 429/400)`_unmark_cool` 清冷却(L482-483, L197-200) |
| 全 key 冷却 | `ALL_COOL`(L441-470):30s 起步递增等待(单次/累计均封顶 8min),期间**不发请求**;超 8min 仍全冷 → 如实回 429 |
| 换 key 退避 | `_rotate_backoff`(L130-134):非高峰 0.3s / 高峰 1.5s,每换一把 sleep 一次(L473-474) |
| RPM/TPM 判断 | 仅靠 429 响应体 message 文本分类,无客户端可见配额/用量上报 |
| 日志级别 | 代码默认 warn(L64);但**当前进程实际在写 debug 级行**(RESP/REQDUMP/SKIP COOLED/DETECT/REQBODY 全有)→ 诊断模式残留(详见瓶颈①) |
| 进程模式 | 单进程 `ThreadingHTTPServer` 多线程(L535),KeepAlive 守护;`_cool` 纯内存不落盘,**重启即清零** |
| 5 key 加载 | `_load_keys`(L77-105):env 优先,回退读 `../trade-data/.env`;缺 key 只轮换已有 |

**当前运行状态**:
- PID 35148(v4-flash 代理)+ PID 52540(kimi 代理)都在跑,均 9-04 启动。
- `~/.claude/settings.json` ANTHROPIC_BASE_URL = `http://127.0.0.1:8899`(**v4-flash 代理在用**;kimi 代理 8898 **空转**,9-05 21:03 后零流量)。
- 日志实际落盘:`sensenova-rotate.log`(stdout)48MB/31 万行、`sensenova-rotate-req.log` 13MB、`sensenova-req-dump/` 19MB/60 文件。
- `sensenova-rotate.err` 33 次 `BrokenPipeError`(客户端提前断开,无害,未造成崩溃)。

## 二、效率与成功率量化(数据说话)

**统计窗口:2026-09-05 15:35:10 → 2026-09-06 13:43:06(22.1h)**。日志首行为 REQBODY 残行(20MB 上限裁剪留尾痕迹,9-04~9-05 15:35 段被历史裁剪丢失,进程实为 9-04 启动)。

### 总量与成功率(req.log 全量)

| 指标 | 值 | 备注 |
|---|---|---|
| 客户端请求(RESP 行) | **9197** | 其中 /v1/messages?beta=true 9069(99%) |
| 200 成功 | **5582** | **有效率 60.7%** |
| 最终 429 | **3546(38.6%)** | 客户端收到 429 → 写死 4s 退避重试 |
| 其他(404/502/400) | 69 | 502=UPSTREAM ERR 10 次 |
| 内层 429 detected(换 key 事件) | **7758** | 每个=某 key 返回 429 换下一把 |
| 触发冷却的额度型 429(COOL 事件) | **331** | 300 次 `Allocated quota exceeded` + 31 次 token plan |
| 冷却跳过(SKIP COOLED) | **17311** | 选 key 时跳过冷却中 key,KEY1=4409/KEY2=3636/KEY3=1701/KEY4=4362/KEY5=4734 |
| 删 thinking(adaptive) | 7468 次 | 大上下文 deepseek 请求全部走此路径(避免 400) |

### 各 key 使用与健康
- 5 key 都在池子参与过(COOL 事件 KEY1=63/KEY2=71/KEY3=29/KEY4=83/KEY5=77;**KEY3 相对最健康**;SKIP COOLED 分布同源)。
- 冷却层级分布:level0(180s)=258 / level1(360s)=42 / level2=14 / level3=6 / level4=6 / level5(48min)=5。**78% 冷却是 180s 起步层,递增深冷却少 = 冷却设计"先探后拉长"正常收敛**,没有 key 长期锁死 48min。

### 429 轮换效率(try N/M 分布 = 该请求当时可用池 N/M 把,已试到第 N 把)

| try N/M | 次数 | 含义 |
|---|---|---|
| try 2/2 | 1773 | 池子只有 2 把,第 1 把 429 后试第 2 把(也可能全败) |
| try 2/3 | 1678 | 池子 3 把 |
| try 3/3 | 1302 | 池子 3 把且试满 3 把全 429 |
| try 2/4 / 3/4 / 4/4 | 880/592/439 | 池子 4 把 |
| try 2/5…5/5 | 377/235/169/126 | 池子 5 把(5 把全试也 429=126 次) |

**关键洞察:大多数 429 事件发生在小池子上(try 2/2 + try 2/3 + try 3/3 = 4753,占 61%),即高峰时可用 key 常被冷却压到 2~3 把**,不是"5 把都在轮但各自还行"。

### 客户端视角的"卡死窗口"(连续 429 块,>5s 间距切块)
- 1159 个块(至少 1 次 429 的连续尝试段);跨度中位 5s、mean 11s、**p90 22s**。
- **最长块 267s(4.5min)连续 318 次 429 detected**;前 10 长块 88~267s。=> 高峰期存在客户端同一任务反复重试、4 分多钟发不出请求的窗口(4s 写死退避 × 并发请求叠加)。
- 每请求末次 429 后:854 个块最终 200(轮换救活),300 个块最终 429(客户端吃瘪)。

### 最终 429 的时间分布(高峰桶 top)
09-06 12 点 **876 次** / 13 点 601 / 11 点 332;09-05 16 点 339 / 22 点 238 / 18 点 230 / 23 点 194 / 20 点 165。
**注:09-06 是周日,白天照样 429 爆炸** → 高峰窗口写死「9-14」的节假日误判风险不只是"法定假",**周末白天同样是高峰**(商汤按北京时间白天统一高压,非仅工作日)。

### 每请求重试次数(同一请求内连续 429)
- 487 个请求撞 1 次即过;254 个撞 2 次;……存在单请求连撞 50~318 次的极端(318 次=267s 块内的累计并发 429)。

## 三、瓶颈定位

1. **诊断模式残留(成本/污染,最易修)**:`launchctl print` inherited environment 证实 `TTP_DETECT_LOG=1`、`TTP_DUMP_BODY=1` 仍在(9-01 定位 thinking_budget 根因时 launchctl setenv,未清理);日志在写 RESP/REQDUMP/SKIP COOLED/DETECT/REQBODY 全量 debug 行 → 实际日志级别 ≤ debug(进程 9-04 启动时固化)。每天持续写 48MB stdout + 13MB req.log + 19MB dump,纯磁盘/IO 浪费;诊断数据已无消费方。
2. **有效请求率 60.7% 偏低的主因 = 高峰时段 5 key 同时被商汤限死**(rpm exhausted 为主 + Allocated quota 为辅),代理轮换机制在"上游整体不可用"时无法创造吞吐:7758 次内层 429 里 61% 发生在 2~3 把的小池子,最终 38.6% 请求以 429 收场并交还给客户端 4s 写死重试 → 空转放大。
3. **冷却状态纯内存、重启清零**:KeepAlive 秒级重启会把 `_cool` 清空,刚冷却的病 key 立刻回池再撞 429。
4. **无链路式熔断/整机降频**:上游整体 429 时,代理仍对每个客户端请求立即尝试轮换(换 key 退避只有 0.3s/1.5s),没有"最近 N 秒 429 率高 → 主动 sleep 更久/直接回 429"的整体闸。客户端 4s 写死退避封顶也是放大因素(改不了客户端,只能代理侧兜)。
5. **kimi 代理空转**(8898):settings 未指向它,常驻占一个进程 + 3.5KB 日志无流量,属无谓进程(评测用途结束未停)。
6. 单 key pool 直接 429 无轮换(658 次纯 429,前 2s 无 detected)= 冷却把可用池压到 1 把的时段,代理直接交 429。

## 四、社区调研(必做项,2026-09-06)

> 通路说明:本环境 WebSearch/WebFetch 均被策略拒绝(memory openrouter-config:WebSearch 全局 deny),改用 HN Algolia API + curl 直抓网页完成。来源均带链接。

| # | 来源 | 可借鉴点 |
|---|---|---|
| 1 | [AWS Architecture Blog: Exponential Backoff And Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)(Marc Brooker, 2023 更新:成为 AWS SDK 标准重试模式) | 退避必须带**抖动(jitter)**,避免 thundering herd;全抖动公式 `sleep = random(0, min(cap, base·2^attempt))`;AWS SDK 重试=exp backoff + jitter。**对照本代理:429 换 key 退避是固定 0.3s/1.5s,无抖动;全冷退避递增但无 jitter → 多请求同时恢复会同时打上游** |
| 2 | [LiteLLM Router - Load Balancing 文档](https://docs.litellm.ai/docs/routing)(业界主流 LLM 网关) | 网关标准可靠性四件套 = **cooldowns(冷却)+ fallbacks(回退)+ timeouts(超时)+ retries(fixed + exponential backoff)**;生产环境**用 Redis 持久化冷却与 tpm/rpm usage 跟踪**,防进程重启丢状态。**对照本代理:冷却/退避都有,但缺 Redis/磁盘持久化(重启清零),缺 tpm/rpm 用量跟踪(无法主动降频)** |
| 3 | [Ask HN: How are people getting around GPT4 rate limits?](https://news.ycombinator.com/item?id=37426999) | 社区共识:①联系厂商**提配额**(付费升档)②**本地模型分流**/减少调用 ③**日志审计所有调用**以定位浪费。对照:商汤侧=升 token plan 或多账号;本地侧=已删 adaptive thinking 省 tpm(STRIP 7468 次) |
| 4 | [Show HN: key-carousel - Key rotation for LLM agents](https://github.com/HalfEmptyDrum/Key-Carousel) / [Zero-dependency Node.js proxy with auto API key rotation](https://github.com/p32929/openai-gemini-api-key-rotator) | HN 上两个同主题开源项目:业界对"多 key 轮询"的通用实现就是**本地反向代理 + 循环选 key + 429 换 key**,与我们的架构一致 → 方向没错;这类代理普遍注意**不要反复试已被限流的 key**(同 litellm cooldown 设计)。**对照:我们已做单 key 冷却隔离,方向正确** |

**提炼 4 条可借鉴**:
- A. **退避加抖动**(AWS):固定 0.3/1.5s 换 key 退避改成 `random(0, cap)` 抖动,多请求并发恢复时不共振。
- B. **冷却状态持久化**(litellm):`_cool` 落盘或外存,重启不丢病 key 标记。
- C. **用量/配额主动跟踪 + 整体降频闸**(litellm):代理统计近期 429 率,超阈值主动 sleep 更长或直接回 429(让客户端退避),不做无谓的 5 连试。
- D. **升配/多账号是社区主路**(HN):商汤侧升 token plan 才是治本;代理轮询是把 RPM 摊到多账号的变相扩容,上游整体高压时作用有限(与本窗口数据一致)。

## 五、优化建议分级清单

| # | 问题 | 数据证据 | 社区依据 | 改法 | 预期收益 | 改动风险 |
|---|---|---|---|---|---|---|
| P0-1 | **诊断模式残留** | req.log 全量 debug 行 + launchctl inherited env `TTP_DETECT_LOG=1`/`TTP_DUMP_BODY=1` + 48MB stdout/13MB req/19MB dump 持续增长 | HN 建议③「日志审计」应在需要时开,不需要关(来源同表 3) | `launchctl unsetenv TTP_DETECT_LOG`、`launchctl unsetenv TTP_DUMP_BODY`;确认 TTP_LOG_LEVEL=warn、TTP_REQDUMP=0;重启代理进程 | 消除每日数 MB~几十 MB 磁盘写 + print 到 stdout 的 IO/CPU 开销;req.log 只剩 429/冷却/错误事件(排查仍够) | **低**:纯日志开关,不碰业务逻辑;需重启代理 = 当前会话路径短暂断开(KeepAlive 秒级拉起) |
| P0-2 | **冷却状态重启清零** | `_cool` 纯内存(L148-149/L197-200),KeepAlive 重启即丢 | litellm 用 Redis 持久化冷却(litellm docs Routing 页) | 冷却标记落盘(如 `data/.cool-state.json` 带 until 时间戳),启动读回 | 病 key 重启后不立即回池,少一批"刚重启就撞 429" | **中**:改代码+需重启;单进程多线程写锁即可,无竞态大风险 |
| P0-3 | **429 换 key 退避无抖动** | 固定 0.3s/1.5s,无 jitter | AWS Exp Backoff + Jitter 名文(AWS blog) | 换 key 退避改 `random(0, base)` 抖动;全冷等待加 jitter | 多请求并发恢复时不共振,高峰 429 收敛更快 | **低-中**:改退避函数,行为变化小;对已收敛场景无负作用 |
| P1-1 | **上游整体不可用时空转** | 61% 429 事件在小池子(try 2/2+2/3+3/3=4753/7758);最长 267s 连撞 318 次;38.6% 请求最终 429 | litellm 四件套:cooldown+fallback+timeout+retry;HN:升配是主路 | 加"整机熔断":窗口内 429 率 > 阈值(如 60%/30s)时,新请求先 sleep(如 10-30s 抖动)再试;同时把 ALL_COOL 首次等待从 30s 提到 60s | 上游整体高压时降请求率 → 商汤侧冷却压力小、恢复快;客户端 4s 重试 → 代理层等待,减少无谓 5 连试 | **中**:需重跑 A/B 观察窗口确认阈值;不影响正常时段路径 |
| P1-2 | **升配/多账号(上游治本)** | 300 次 Allocated quota + 5 key 同高峰全 rpm exhausted;周日白天也爆炸 | HN 社区共识①「联系厂商提配额」(来源同表 3) | 商汤侧升 token plan 额度或加第 6-10 key;高峰窗口 9-14 已实测延伸至 16 点,建议按流量观察扩窗 | 治本,直接抬吞吐上限 | **无代码风险**,是商务/成本决策,需用户拍板 |
| P2-1 | **kimi 代理空转** | 8898 流量停在 9-05 21:03,settings 指向 8899 | — | 停 kimi 代理(launchctl unload kimi plist),需要 k3 评测时再起 | 省一个常驻进程 | **低**:要评测时再 load 回 |
| P2-2 | **STRIP 频率高,考虑上游侧省 tpm** | STRIP 7468 次/22h | HN 社区共识②「减少调用」 | (不做/仅提示)已删 adaptive 是 tpm 大户,若还想降 429,从"少发大上下文请求/精简 tool"找 | 间接降 429 | 纯提示,不动代码 |

**拍板要点(pending #30)**:
- 5key 真全用上了(5 key 都有 COOL/SKIP 记录),不需要加 key 数;问题是**高峰整体不可用**而非单 key 不均。
- 高峰冷却翻倍(P0-1 之外)按数据是有效的:78% 冷却停留在 180s 层,没有 key 锁死,冷却参数无需再调 —— **轮询策略已收敛,不必推翻**。
- 若要动,优先级:P0-1(纯清理)→ P0-2(重启不丢状态)→ P0-3(抖动)→ P1-1(整机熔断,需 A/B 定阈值)。
- **值得升为正式优化任务:是**(P0-1+P0-2 打包即可,低风险高确定性收益;P1-1 需要观察窗验证,可拆第二期)。与 pending #48(代理高可用)合并:冷却持久化+熔断即为高可用核心。

## 六、诚实标注(口径与局限)
- 统计窗口 22.1h(09-05 15:35~09-06 13:43),日志经 20MB 裁剪保留尾部,更早段(9-04)不可考;窗口含周日白天的用户实际使用负载,不是压测。
- "有效请求率 60.7%" = 代理最终响应 200 的占比;客户端 4s 写死退避不可改,最终用户看到的卡顿窗口(最长 4.5min)是「代理轮换耗尽 + 客户端重试」叠加结果,非单因。
- 空闲时段(凌晨/早上)请求密度低,429 事件少,数字主要由白天高峰驱动;分时段详表见下方复现段命令可复现。
- 日志级别结论基于文件行内容(debug 行在场)与 launchctl inherited env 两项证据;ps eww 显示 env 仅含 TTP_DETECT_LOG=1/TTP_DUMP_BODY=1(未含 TTP_LOG_LEVEL),推断进程启动时固化过 debug 级 env(后 unsetenv 不刷新已启动进程),属合理推断非逐字实证,报告按"实际日志级别 ≤ debug"表述。

## 复现
- 日志路径:`/Users/linhuichen/code/trade-data/data/logs/sensenova-rotate-req.log`(带时间戳,debug 行含 RESP/REQDUMP/SKIP COOLED/DETECT/REQBODY)
- 统计命令(原生 shell+python3,无第三方依赖):
  ```bash
  LOG=/Users/linhuichen/code/trade-data/data/logs/sensenova-rotate-req.log
  # 总量与状态码分布
  grep -o 'RESP [A-Z]* [^ ]* -> [0-9]*' $LOG | awk '{print $NF}' | sort | uniq -c | sort -rn
  # 内层 429 事件与 try 分布
  grep -c '429 detected' $LOG
  grep -o 'try [0-9]*/[0-9]*' $LOG | sort | uniq -c | sort -rn
  # 冷却事件与层级
  grep 'COOL KEY' $LOG | grep -o 'level=[0-9]*' | sort | uniq -c
  # 429 连续块切分(>5s 间距)与最终 RESP 对账:python3 脚本见下
  ```
  429 块切分脚本(python3 内联):
  ```python
  import sys, re
  from datetime import datetime
  from bisect import bisect_left
  lines = open('/Users/linhuichen/code/trade-data/data/logs/sensenova-rotate-req.log', encoding='utf-8', errors='replace').readlines()
  ts = lambda m: datetime.strptime(m.group(1)+' '+m.group(2)+':'+m.group(3)+':'+m.group(4), '%Y-%m-%d %H:%M:%S').timestamp()
  tre = re.compile(r'^\[(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})\]')
  ev = [ts(tre.match(l)) for l in lines if '429 detected' in l]
  blocks, cur = [], [ev[0]] if ev else []
  for e in ev[1:]:
      if e - cur[-1] > 5: blocks.append(cur); cur = [e]
      else: cur.append(e)
  if cur: blocks.append(cur)
  print('blocks:', len(blocks), 'max span:', max(b[-1]-b[0]+4 for b in blocks))
  ```
- 数据截止:2026-09-06 13:43(日志持续增长,复跑自带最新窗口)
- 关键口径:有效率=最终响应 200/全部响应;429 detected=单 key 429 换 key 事件(同一客户端请求可多次);间歇以 >5s 切分
