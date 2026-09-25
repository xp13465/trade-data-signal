# 9-24 晚间生产采集告警根治报告(2026-09-25)

状态: 已修复(代码 feat 分支,待主控 merge)+ 已上线验证
告警来源: 9-24 21:xx 通知邮件 2 条 —— `turnover_backfill|exit!=0|124` + `etf_national_team|exit!=0|1`

---

## 一、告警 1:turnover_backfill exit=124(卡死被 7200s 超时 kill)

### 症状
- pipeline_turnover_20260924_2110.log 连续 120 分钟刷新 `[119.8min] progress: 100/5200 codes done, 1/1 workers alive`——**卡死不是慢**(整条流水线只有 100/5200 且 workers 仍标 alive,一行进度输出都不动)。
- worker_update_0_20260924_211001.log 21:14 后停止在 `180/5200`,之后零输出。

### 根因(P0 新判断):baostock send_msg 对端关闭连接 → recv 返回 b"" → 无限忙循环
- baostock 库 `util/socketutil.py` 的 `send_msg` 是无限 recv 循环,3.11 venv 源码实证:
  ```python
  while True:
      receive += default_socket.recv(8192)
      if receive[-13:] == b"<![CDATA[]]>\n":
          break
  ```
- **两条挂起路径**:
  1. recv **阻塞不返回**(半开连接)→ 需 socket.timeout 兜底。base.py 已有 `socket.setdefaulttimeout(30)`,能保。
  2. recv 返回 b""(对端正常关闭)→ 下端循环立即重试,拿到还是 b"",**不抛异常、不阻塞、无限空转**(CPU 100%,零日志)。`setdefaulttimeout` 对此完全无效——**9-24 实证就是这一条**。

### 为什么排除"慢"与"超时未触发"(证据链)
- worker 进程 socket 诊断确认带 30s timeout(云上 sites-packages base.py L34-35 `setdefaulttimeout(30)` 生效、login socket 实测 timeout=30)。若只是 recv 阻塞,30s 必抛 socket.timeout 打日志且链路重试;实际 120 分钟零任何日志 → 只剩 recv 返回 b"" 空转符合全部特征。
- 9-24 21:10 启动 → 21:14 (180/5200) 连接被服务端关闭 → 空转 120min → 23:10 被 7200s systemd timeout kill(exit=124)。
- 数据面结果:baostock_progress.json `r` 段仅 100 条到 20260924,其余 5099 条停 20260923;a-stock-3m.json 最新只到 20260923(当日换手率 98% 断更)。

### 修复(根因单点修,非逐文件补丁)
新增 `app/collector/baostock_socket_timeout.py`,monkey-patch baostock.util.socketutil(模块单例,一处替换全局生效):
1. `SocketUtil.connect` / `get_default_socket`(baostock 包内**仅这两处建 socket**,grep 实证)→ 建连后显式 `settimeout(30)`,recv/connect 均受保护,不依赖 setdefaulttimeout 可能被第三方改掉。
2. `send_msg` 补 `if not chunk: return None` 守卫——recv 返回 b"" 不再空转,返回 None。
3. ⚠️ **不替换 `socketutil.socket` 模块属性**:直接替换会连带破坏 `socket.AF_INET/SOCK_STREAM` 等常量引用(socketutil 内部用 `socket.XXX`),login 抛 AttributeError——本地+云上已复现。改为只 patch 上述 3 个函数。

**自愈链**:recv 异常或 b"" → send_msg 返 None → `query_history_k_data_plus` 返 `10002007`(BSERR_RECVSOCK_FAIL,已在 baostock_daily 的 `_NETWORK_ERROR_CODES`)→ 调用方 `_reconnect_with_retry` 重建 socket 重试,不再永久卡死。

### 接入位置(公共祖先,一处接入全局生效)
- `app/collector/base.py`(所有 collector 的公共祖先,先于任何 baostock login 执行)`setdefaulttimeout(30)` 之后加 try `apply_socket_timeout()`。
- `app/collector/baostock_daily.py` L64-65 `import baostock as bs` 后同款调用(direct-import baostock 发 query 的主链路,含 baostock_worker 复用)。

### 自测结果(全部 PASS)
- 本地 `docs/ops/scripts/test_baostock_socket_timeout.py` 4 组断言:
  1. `_apply_timeout_to_default_socket` 对已有 socket 设 timeout=30 ✓
  2. `_send_msg_patched` 对端关闭(socketpair 模拟)返 None,耗时 <2s 不空转 ✓
  3. apply 幂等 + connect/get_default_socket/send_msg 三函数已替换 + `socketutil.socket` 模块属性未被替换(常量引用不破坏)✓
  4. 真实 login 建 socket 带 timeout=30(云上验证 PASS,本地网络跳过)✓
- 云上(生产 venv 环境)真实 login 验证:default_socket.timeout = 30 ✓
- 全部接入文件语法编译通过。

### 同类错误面清单(§23.2 修 bug 三铁律/§23.3 举一反三)
所有 `import baostock` 发 query 的采集链路,逐一确认均被接管(base 或 baostock_daily 顶部 apply):

| 调用方 | 接入路径 | 覆盖 |
|---|---|---|
| baostock_daily.py(主采集) | 文件内 L64-65 直连 apply | ✓ |
| baostock_worker.py | `from app.collector.baostock_daily import ...` → 顶部 apply 先执行 | ✓ |
| mootdx_daily.py L562 | 延迟 `from . import baostock_daily` | ✓ |
| public_fund.py L65 | `from . import base` → base.py apply | ✓ |
| hkex_ccass_quarterly.py L27 | `from .base import UA` → base.py apply | ✓ |
| index_backfill.py L35 | `from .base import log_collect` → base.py apply | ✓ |

其余任何 `import app.collector.base` 的采集模块默认接管,零遗漏。

## 二、告警 2:etf_national_team exit=1(9-24 20:07 + 21:30 双败)

### 根因:新浪/腾讯回退(9-24 被屏蔽)带入场内 LOF,触发断言 4 失败 → deploy 阻断
- 回退采集把两只场内 LOF(无 fund_type 字段 → 错误标为 etf)注入 sw_801200/sw_801950,与 board_etf_map 一致性断言冲突 → `universe_rules` 对齐校验 FAIL → deploy rc=1。
- **注意:告警 2 无需新代码**——commit `b891a29c5`(9-24 23:50)已含根修:
  1. `_is_lof_code` 守卫(code 前缀 16/15/501/502,对齐 universe_rules.yaml)
  2. 写 board_etf_map 前清空 empty_array_ids 的最终写入栅栏
- 验证:pending 数据空数组,board_etf_map sw_801200[]/sw_801950[];`check_universe_alignment` 4 个断言全部 PASS;云生产代码已含栅栏(line grep -c=1)。
- "较全量少传 1 个"(R2 文件 23/24):对/错增量模式跳过未变化文件,非丢失。

## 三、未决项(无需人工)
1. **9-24 换手率数据 98% 断更(仅 100/5200)**:增量续采逻辑断点 resume——今晚 21:10 定时任务自动从 9-23 续到 9-24,**不需要手动补采**;若今晚 21:10 后仍未补齐再人工介入(届时先查 baostock_progress.json 断点)。
2. 今晚 21:10 是修复上线后的首次生产验证点(观察点)。

## 四、本次改动文件(commit 清单)
- `app/collector/baostock_socket_timeout.py`(新增,核心修复)
- `app/collector/base.py`(接入 apply)
- `app/collector/baostock_daily.py`(接入 apply)
- `docs/ops/scripts/test_baostock_socket_timeout.py`(新增,复现测试)
- 本报告 `docs/ops/turnover-backfill-stuck-rootcause-20260925.md`

## 五、复现段
- 复现 send_msg 空转:本地 `python docs/ops/scripts/test_baostock_socket_timeout.py`(需系统已装 baostock,测试 2 用 socketpair 模拟对端关闭,断言返 None 且 <2s)。
- 云上验 socket 超时生效:`ssh -i ~/tdsignal.pem ubuntu@122.51.111.173` 后运行 bs_verify_real(login 后查 default_socket.gettimeout()==30)。
- 生产同款场景:任何 baostock socket 对端关闭时,worker 日志不再静默 120min,而是 recv 空 → 10002007 → 断线重连打日志,任务持续推进或明确失败可告警。