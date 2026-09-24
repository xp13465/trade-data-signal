# fix/proxy-transport-retry env 数值解析加固 delta 复审(9ea355bbc)

- 日期:2026-09-24
- 复审对象:分支 fix/proxy-transport-retry 相对 origin/main 的 2 个 commit(diff 46+/6-,文件 scripts/sensenova-rotate-proxy.py):
  - `ff3a03e0a` 传输层错误原地退避重试(上轮已 PASS,本轮确认未被新 commit 破坏)
  - `9ea355bbc` env 数值解析加保护(本轮 delta 主对象)
- 复审方式:git show 取分支文件到 /tmp 副本 + import 级 env 实测 + 双实例实测(端口 18997/18998,上游分别 example.com / ttp-nonexistent.invalid),全程未动生产 8899、未碰生产 R2/路径
- 结论:**PASS-with-conditions(1 项必须修才能 merge)**

## 各必查项结论

### 1. 同类错误面穷尽(§23.2③):FAIL(漏 1 处同类,必须修)
grep 全文件 os.environ 消费点 18 行,逐个判定:

| 处 | 位置 | 判定 |
|---|---|---|
| ROTATE_BACKOFF | L129 `_env_num` | 已加固 |
| TRANSPORT_RETRY_MAX | L335 `_env_num` | 已加固 |
| REQDUMP_KEEP / REQDUMP_KEEP_ERR | L439/L440 `_env_num` | 已加固 |
| TTP_PORT | L693(healthz)/L712(__main__)`_env_num` | 已加固 |
| **PEAK_HOURS** | **L140-141 顶层裸 `int(x) for x in PEAK_HOURS.split("-")`** | **仍裸奔,必须修** |
| TTP_LOG L54 / TTP_LOG_LEVEL L65 / SENSENOVA_ENV_FILE L90 / RETRY_ON_429 L128 / TTP_COOLDOWN_FILE L178 / TTP_DETECT_LOG L402 / TTP_REQDUMP_DUMP L437 / TTP_DUMP_BODY L530/L649 / _load_keys L84 | 字符串/路径/布尔比较,无数值解析 | 无风险 |

- **仍裸奔 1 处(必须修)**:L140-141 `PEAK_HOURS = os.environ.get("TTP_PEAK_HOURS", "9-14")` 后模块顶层 `PEAK_START_HOUR, PEAK_END_HOUR = (int(x) for x in PEAK_HOURS.split("-"))` ——与 must-fix 病灶完全同病:env 写错 → **模块加载即崩**。实测 `TTP_PEAK_HOURS=abc` → `ValueError: invalid literal for int() with base 10: 'abc'`(L141 崩,EXIT_CODE=1)。"9-14-15"(多段解包)、"9-"(空段)、""(空串)同样崩。实施方注释自称"同类 6 处 env 数值解析一并根治(§23.2③ 排查同类: 一个共享守卫 < 每个 caller 各写一个守卫)",但同类未穷尽:PEAK_HOURS 是模块顶层第 7 处数值解析,env 手滑写错照样单点全挂(launchd KeepAlive 空转重启,无告警)——必须修项的病灶没有根治干净
- **判断为无风险的**:全部为字符串路径/字符串比较/已带守卫项,不会因 env 非法值崩(详见表)

### 2. `_env_num` 语义正确性:PASS
- `os.environ.get(name, str(default))` 保证缺省时给 cast 的是字符串(str(0.3)="0.3", str(5)="5"),空串 "" 时返回 "" 给 cast → int("")/float("") 抛 ValueError → 回退默认 ✓(实测空串回退 30 正确)
- 默认值类型与 cast 一致:ROTATE_BACKOFF 默认 0.3(float)+cast float;TRANSPORT_RETRY_MAX 5/REQDUMP_KEEP 30/REQDUMP_KEEP_ERR 30/TTP_PORT 8899 均 int+cast int ✓
- 只吞 TypeError/ValueError:本机 Python 3.11.0,int() 超长字符串已抛 ValueError(实测,非 OverflowError)→ 全被捕获回退,无 3.10- OverflowError 盲区;cast 传错(不可调用)→ TypeError 被吞回退默认属理论静默,但 6 处调用 cast 均为内置 int/float 字面量,实际不触发,不算 finding
- 结论:语义正确,无过吞

### 3. 合法 env 行为不变:PASS
实测 `TTP_TRANSPORT_RETRY=3 / TTP_ROTATE_BACKOFF=1.5 / TTP_REQDUMP_KEEP=7 / TTP_REQDUMP_KEEP_ERR=7 / TTP_PEAK_HOURS=9-16` 下 import 加载:
`TRANSPORT_RETRY_MAX=3, ROTATE_BACKOFF=1.5, REQDUMP_KEEP=7, REQDUMP_KEEP_ERR=7, PEAK_START/END=9/16` ——与加固前取值逐位一致 ✓;实例 18997 healthz `"port": 18997` 端口字段正确 ✓

### 4. 非法 env 不再崩(上轮病灶):PASS
实测 `TTP_TRANSPORT_RETRY=abc / TTP_ROTATE_BACKOFF=xyz / TTP_REQDUMP_KEEP=zzz / 3.5 给 int / 空串` 混装:
- import 加载不崩,回退默认值 5 / 0.3 / 30 / 30 ✓(**上轮 `TTP_TRANSPORT_RETRY=abc` 实测 CRASH,本轮同样输入不再崩**)
- 实例 18997(携垃圾 env)正常启动,`/healthz` 200 `status:ok rotate_keys:1 cooling_keys:[] port:18997`,启动日志 `backoff=0.3`(xyz 回退 0.3 的旁证)✓

### 5. 传输重试逻辑未被破坏(ff3a03e0a 复验):PASS
- 实例 18998(上游 ttp-nonexistent.invalid,DNS 解析失败):POST → **502**,耗时 **31.06s**(与上轮 31.08s 一致),日志 5 条 `transport retry 1-5/5`(时间戳 18:55:39→40→42→46→54,退避 1/2/4/8/16s 逐位吻合)+ 1 条 `transport retries exhausted`,请求后 healthz `cooling_keys: []`(重试期间不写 key 冷却)✓
- **4xx/5xx 不触发重试(上轮重点结论独立复验)**:读 `_do_upstream` 确认 `getresponse()` 对 4xx 不抛异常,正常返回 `(status,...,None)`,err=None 不进入重试分支(仅在网络层异常时 err=字符串);**实测** 实例 18997(上游 example.com)POST → 原样转发 **405**,耗时 0.78s,日志 **0 条** transport retry 行 ✓ ——客户端错误不会被拖成 31s
- 结论:重试语义与上轮逐位一致,9ea355bbc 未破坏 ff3a03e0a

### 6. 生产不受影响
- 测试实例用 /tmp 副本(改 UPSTREAM_HOST 隔离),测试产物全落 /tmp,未碰生产 R2/路径/生产文件
- 清理:按端口精确 kill(18997/18998),未用 pkill;收尾确认生产 `lsof -ti :8899` 进程存活(38456/72679),`/healthz` 200(rotate_keys=7,uptime 递增),**生产代理未重启未 kill**

## 必须修才能 merge(1 项)
1. **L140-141 PEAK_HOURS 顶层裸数值解析加守卫**(同病同修,§23.2③)。最小修法:
```python
try:
    _p0, _p1 = (int(x) for x in os.environ.get("TTP_PEAK_HOURS", "9-14").split("-"))
    PEAK_START_HOUR, PEAK_END_HOUR = _p0, _p1
except (TypeError, ValueError):
    PEAK_START_HOUR, PEAK_END_HOUR = 9, 14
```
(非法值回退默认 9-14,行为与"默认峰值窗口"一致;也可扩 _env_num 为二元组守卫,本次最小改为上)

## 可 merge 后建议跟进(不阻塞)
1. 超时型传输错误最坏 18.5min(上轮遗留,建议超时随重试递减或加总时限)——上轮已列,本轮无新增
2. DNS 全挂时日志 ×5(上轮已列,20MB 裁剪兜底已验在位)

## 低分项已滤
- 1 个 <80:cast 传错被 TypeError 吞回默认(理论静默,6 处调用均为字面量内置 int/float,不触发);稳妥起见 PEAK_HOURS 修法里一并 try 了 TypeError,无需单独处理
