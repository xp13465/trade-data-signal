# 独立审查:turnover 采集卡死根因修复(2026-09-25)

被审:feat 分支 `worktree-agent-afd201d75625b1456`,commit `5b8bcfd78`
审查人:reviewer(独立证伪,未参与实施)
改动分级:B 级(采集主链路,merge 前硬门槛)
结论:**PASS-with-conditions**(根因成立、修复安全、同类错误面全覆盖、回归风险低;4 条非阻断条件见文末)

---

## 一、逐条审查结论

### 1. 根因是否成立:成立(高置信,三重证据)
- **代码实锤**:baostock `util/socketutil.py` L66-73 的 `send_msg` 是 `while True: receive += recv(8192)` 无限循环,break 条件仅 `receive[-13:] == b"<![CDATA[]]>\n"`,`recv` 返回 b"" 时 receive 不增长、尾标记永不匹配 → **不抛异常、不阻塞、无限空转**。本地 venv 3.11 源码逐行核实(`.venv/lib/python3.11/site-packages/baostock/util/socketutil.py` L66-73)。
- **实测**:socketpair 精确模拟"send 成功→对端关闭→recv 返回 b""" ,patch 版 `_send_msg_patched` 102ms 返 None 不空转(原版从代码判定死循环)。
- **事件证据(云上)**:`pipeline_turnover_20260924_2110.log` 21:10 启动,17min 达 `100/5200` 后直到 `[117.3min]` 全部 `100/5200, 1/1 workers alive` 刷屏,文件 mtime 23:09(≈21:10+120min,与 systemd 7200s timeout kill 时刻吻合)。
- **排除"慢/阻塞"推理成立**:worker socket 带 30s timeout(云上实测 login socket timeout=30),若 recv 阻塞必有 30s 级超时日志;实际 120 分钟零日志。且卡死位置在 fetch 边界——`baostock_daily.fetch_one` 的 2 次尝试+重连逻辑零触发,只有"baostock 库内空转、控制权永不返回"能解释该特征。
- **替代假说(DB 锁)评估**:低概率。卡在 180/5200 恰在 fetch 边界;sqlite 默认 5s 锁超时抛 OperationalError 会留日志;且 DB 锁无法解释 fetch_one 重连逻辑不触发。不能 100% 排除,但证据链远弱于 recv-b"" 假说。**建议今晚验证点观察判别特征**:再遇同款卡死(零推进+alive+无日志),优先怀疑 DB 锁方向。

### 2. 修复是否安全:安全
- **patch 范围**:仅替换 `baostock.util.socketutil` 模块 3 个函数(`SocketUtil.connect`/`get_default_socket`/`send_msg`)。baostock 包内**仅这两处建 socket**(全包 grep `socket.socket(` 仅 L37/L47),`send_msg` 被 40+ 调用方(login/logout/query/sector/eval/metadata 等)经模块属性引用自动统一接管。login 流程也走 patch(connect 后 apply timeout + send_msg 守卫),login 返 None → `BSERR_RECVSOCK_FAIL("10002007")`(contants.py L153 核实)→ `baostock_daily._ensure_login` raise → `_reconnect_with_retry` 重建。链通。
- **settimeout(30) 误杀评估**:baostock 单次 query = 一次 send_msg = 一次网络往返(响应含尾标记即 break,无二次请求;`fetch_one` 的 `rs.next()` 是本地解析不涉网络);正常响应 <1s;30s per-recv 超时仅对"30 秒完全无数据到达"触发,极宽松。理论边界(服务端响应前静默 >30s)概率极低,非阻断。
- **守卫语义链实测全通(端到端)**:真实 login 后把 socket 设 0.01s 超时模拟卡死 → `fetch_one("600519",...)` 走 `timed out`→None→10002007→`_reconnect_with_retry`(logout+login)→重试取到 4 行数据(msg='ok')→ 重连后 socket timeout 恢复 30。**生产同款代码路径上"卡死后自动恢复"真实成立**(本地 venv 实测,`/tmp/verify_reconnect_chain.py`)。
- **"不替换 socketutil.socket 属性"坑核实**:patch 代码未对 `socketutil.socket` 赋值,只替换 3 个函数;测试 3 断言 `sutil.socket is _s`(socket 模块未被替换),socket.AF_INET/SOCK_STREAM 常量引用安全。
- **更干净修法对比**:①改 baostock venv 库本体——pip 包不受 git 管理、deploy 后易漂移,monkey-patch 随代码版本化更可控;②换数据源——工作量大且 baostock 为主源;③进程级 watchdog——只能发现卡死不能自愈。当前方案=根因单点修+自愈链,合理最优。
- **连带副作用确认**:base.py 顶部 apply 会连带 `import baostock.util.socketutil`(触发 baostock `__init__.py`),`__init__` 纯 import 无网络副作用(已读源码核实),安全。

### 3. 同类错误面是否全覆盖:全覆盖(逐个核实,声明属实)
全仓 `import baostock` 发 query 的采集点逐一核实接管链:
| 调用方 | 接管路径 | 核实 |
|---|---|---|
| baostock_daily.py L58 | 文件内 L64-65 直连 apply | ✓(diff 实见) |
| baostock_worker.py L26 | L21 `from app.collector.baostock_daily import ...` → 顶部 apply 先执行 | ✓(import 链核实) |
| mootdx_daily.py L562 | 延迟 `from . import baostock_daily`;mootdx 自身**无**直接 import baostock(全文 grep 仅 L562) | ✓ |
| public_fund.py L64 | `from . import base` → base 顶部 apply | ✓ |
| hkex_ccass_quarterly.py L27 | `from .base import UA` → base import 触发 apply | ✓ |
| index_backfill.py L35 | `from .base import log_collect` → base import 触发 apply | ✓ |
| **额外**:docs/kelly/backtest-ai/.../stock_daily_backfill.py | `from app.collector.baostock_daily import (...)` → 间接接管 | ✓ |
| scripts/notify 等 5 个"提及 baostock"文件 | 仅注释/日志文本,不 import baostock,非调用点 | ✓(逐个看过) |

**零遗漏。** runner.py / cleanup_d3d2.py 只 import baostock_daily → 间接接管。

### 4. 回归风险:低
- **正常路径独立验证无回归**:socketpair 构造完整非压缩响应,`_send_msg_patched` 返回完整内容(`'21\x011\x0110\x010000000000000hello-body<![CDATA[]]>\n'` 含 body),与原文逐行一致(仅加守卫),压缩分支代码逐字比对一致。
- **性能影响**:每次 recv 仅多一次 `if not chunk` 判断,可忽略;正常响应 <1s,30s 超时不触发。
- **变脆风险**:patch 后若服务端偶发 30s 无数据,会从"永久卡死"变为"30s 后重连自愈",反而是改善。
- **测试盲点(重要)**:测试脚本测试 2 时序是 `b.close()` 在 `a.send` **之前**,实际触发的是 send 阶段 BrokenPipe(except 分支),**未真正走到 recv-b"" 守卫分支**(`if not chunk: return None`)。实施报告对测试 2 的描述("socketpair 模拟对端关闭")不精确,且该用例**对 recv 守卫无防回归作用**——若守卫被删,测试 2 仍 PASS。reviewer 独立验证了守卫本身工作(send 成功后 close 对端,102ms 返 None),故不阻断,但建议补用例。

### 5. 可提前验证性:已验证(缺口明确)
- **本地已做的提前验证**(全部 PASS):
  1. recv-b"" 守卫:send 成功后关对端,`_send_msg_patched` 102ms 返 None 不空转(`/tmp/verify_recv_eof.py`)
  2. 正常路径无回归:完整响应返回内容正确(`/tmp/verify_normal_path.py`)
  3. 端到端重连链:真实 login + 模拟卡死 → 10002007 → 重连 → 恢复(`/tmp/verify_reconnect_chain.py`)
  4. 实施测试脚本 4 组断言 ALL PASS(本地 venv)
- **验证缺口(明确)**:「真实 baostock 对端关闭」的完整生产链路场景无法在本地制造(本地无法主动让 baostock 服务端半开/关闭),真实验证只能等**今晚 21:10 生产观察点**。届时判别标准:worker 不再静默 120min,而是 recv 空 → 10002007 → 重连日志 → 任务持续推进或明确失败可告警。
- **流程前置(重要)**:今晚 21:10 验证点依赖 **main merge + deploy 生效**。PASS 后主控需在 21:10 前完成合并部署,否则验证点顺延。merge 避开盘后任务时点(§14)。

---

## 二、Conditions(非阻断,建议在今晚验证点前处理)
| # | 严重度 | 事项 | 建议 |
|---|---|---|---|
| C1 | 重要 | 测试脚本测试 2 实际测 send-BrokenPipe 分支,非 recv-b"" 守卫;对该守卫无防回归作用 | 补"send 成功后 close 对端"用例(reviewer 已验证该场景 102ms 返 None,可直接照抄) |
| C2 | 重要(流程) | 今晚 21:10 验证点依赖 merge+deploy 在 21:10 前生效 | 主控 PASS 后立即走 main-merge.sh + deploy,避开盘后时点 |
| C3 | 次要 | 测试脚本 sys.path 硬编码 `/Users/linhuichen/code/trade/.claude/worktrees/agent-afd201d75625b1456`,worktree 清理后测试不可运行 | 改为相对 `Path(__file__)` 推导或参数化 |
| C4 | 次要(信息) | 压缩响应路径(K 线实际走此路)测试未直接覆盖;patch 版与原文逐行一致 | 风险可忽略,今晚验证点顺带观察 K 线正常返回即可 |
| C5 | 信息 | DB 锁等替代假说无法 100% 排除(证据链远弱) | 今晚验证点若再现同款卡死,查 DB 锁方向;当前修复已覆盖主假说 |

## 三、复现/验证命令
- 实施自测:`/Users/linhuichen/code/trade/.venv/bin/python <实施worktree>/docs/ops/scripts/test_baostock_socket_timeout.py` → ALL PASS
- reviewer 独立验证(脚本在 /tmp,未入库):verify_recv_eof.py / verify_normal_path.py / verify_reconnect_chain.py
- 云上事件证据:`ssh -i ~/tdsignal.pem ubuntu@122.51.111.173` tail `data/logs/pipeline_turnover_20260924_2110.log`
