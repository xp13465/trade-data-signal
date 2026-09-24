# fix/proxy-transport-retry 审查报告(传输层错误原地退避重试)

- 日期:2026-09-24
- 审查对象:commit `ff3a03e0a`(分支 fix/proxy-transport-retry,base=main `0f435dd4f`),scripts/sensenova-rotate-proxy.py +25/-1
- 审查方式:只读 + /tmp 副本实测(上游不可达/可达两种场景),全程未动生产 8899(生产进程 pid 72679 存活验证)
- 结论:**PASS-with-conditions**(1 项必须修)

## 结论总览
- 核心修法本身正确:重试只在 `_do_upstream` 抛异常(err 非 None)时触发;**HTTP 4xx/5xx 时 err=None,不重试**(实测 405 零重试),不会把客户端错误拖成 31s
- 一个 **P0 级防御缺口必须修**:`TRANSPORT_RETRY_MAX = int(os.environ.get("TTP_TRANSPORT_RETRY", "5"))` 无 try/except,env 非法值(非数字/空串/小数)→ ValueError → 代理**启动即崩**(实测 CRASH),launchd KeepAlive 空转重启起不来 = 所有会话全挂

## 必查项逐项

### 1 重试逻辑正确性:PASS(1 个子项必须修)
- 退避序列:`1.0 * 2^(_t_try-1)` 取 min 16s → 1/2/4/8/16s,累计 31s(自行核算:1+2+4+8+16=31)。实测总耗时 **31.08s**,日志时间戳间隔 1/2/4/8s 逐位吻合([2026-09-24 18:44:38→39→41→45→53])
- err 判据:读 `_do_upstream`(L351-372)确认 `except Exception` 只包网络层;`getresponse()` 对 4xx/5xx **不抛异常**,正常返回 (status,...,None)。**实测**:上游 example.com 返回 405,代理原样转发 405,日志零 transport retry 行 → 4xx 不会触发重试 ✅
- 不写 key 冷却:重试路径(L597-607)无 `_mark_cool` 调用,耗尽后 605 行直接 502 return(610 行 `_unmark_cool` 也走不到)。**实测**:失败后 /healthz `cooling_keys: []` ✅

### 2 不阻塞其他请求:PASS
- L697 `http.server.ThreadingHTTPServer` ✅
- 锁检查:`_rotate_lock` 只在 L543-546 取轮换游标短持有;`_cool_lock` 在 `_cooled_out/_mark_cool/_unmark_cool` 内短临界区;重试 sleep 期间不持任何锁,只阻塞当前请求线程 ✅

### 3 与既有 429 换 key 逻辑交互:PASS(1 个建议跟进)
- 嵌入层:新增重试在 `for key in try_keys` 循环内(L589),但传输错误重试耗尽后 **L605-607 直接 502 return**,不进 L612 的 429 轮换分支 → **不会每个 key 都试一遍**;同一 key 固定重试(传输错误与 key 无关的设计意图正确)
- 最坏总耗时:
  - 目标场景(DNS 抖动,失败毫秒级):**31s**,实测 31.08s,合理
  - 极端场景(上游连接挂起 180s 超时型失败):6 次请求 ×180s + 31s sleep ≈ **1111s(18.5min)**。客户端(Claude Code)早超时断开,代理线程傻等但不阻塞其他线程;建议跟进:超时随重试递减或加总时限
  - 与 ALL_COOL(480s)不叠加:ALL_COOL 在 try_keys 构建阶段,传输重试在其后,两条路径互斥

### 4 错误路径不吞错:PASS
- 重试耗尽 → L606 `logmsg(..., "transport retries exhausted")` + L607 502 + 原始 err 文本。**实测**:返回 502,响应体 `[Errno 8] nodename nor servname provided, or not known`,日志含 exhausted 行 ✅

### 5 环境变量开关:**FAIL(必须修,P0)**
- 默认 "5" 时安全;0 / 负数安全(while 条件 `_t_try < MAX` 恒 False = 禁用重试,实测 -3 加载正常,不会死循环)
- **`TTP_TRANSPORT_RETRY=abc` → 模块加载即 ValueError CRASH(实测);空串 `""` → 同样 CRASH(实测);`3.5` 同崩**。模块顶层 L311 执行,launchd 环境一但设置过非法值(哪怕手滑/脚本空串赋值),代理起不来 = 单点全挂,且 KeepAlive 空转无告警
- 修法(1 行):`try: TRANSPORT_RETRY_MAX = max(0, int(os.environ.get(...))) except ValueError: TRANSPORT_RETRY_MAX = 5`

### 6 实测复现:PASS
- 测试实例(端口 18998,上游指向 ttp-nonexistent.invalid):502 / 31.08s / 5 条 retry warn 行(1/2/4/8/16s 时间戳逐位吻合)/ exhausted 行 / cooling_keys 空 —— 四项全中
- 测试实例按端口 `lsof -ti` 拿 pid kill 清理干净;生产 8899 代理进程 pid 72679 前后存活,未受影响

### 7 正常路径回归:PASS
- 上游可达实例(端口 18997,上游 example.com):GET/POST 原样转发 405,2.6s(网络往返),日志零 retry 行零额外等待 ✅ 重试分支只在 err 非 None 时进入

### 8 日志量:可合并(既有问题说明)
- 日志裁剪机制**在位且有效**:logmsg L337-344,超 20MB 自动留尾 10MB 截断;当前生产日志 12M 未超限(任务书提到的 64MB 与本文件现状不符,可能指别的日志,未追查)
- 重试日志 warn 级 5 条/请求:DNS 全挂时每个在飞请求 +5 条 warn,与既有 429 轮换日志同量级;有 20MB 裁剪兜底不会雪崩,暂不修(建议跟进:可后续观察增长速率)

## 必须修才能 merge
1. **L311 `int()` 无防御(env 非法值启动即崩)** —— 实测 CRASH,1 行修复,见必查项 5

## 可 merge 建议跟进
1. 超时型传输错误最坏 18.5min(见必查项 3),建议超时随重试递减或加总时限
2. DNS 全挂期间日志增速 ×5(5 条 warn/请求),观察 20MB 裁剪兜底是否够

## 低分项已滤
- 无 <80 分 finding(全部必查项均有实测/代码直接证据)
