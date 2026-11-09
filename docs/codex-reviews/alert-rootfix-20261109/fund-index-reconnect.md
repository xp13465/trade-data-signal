# 公募基金指数同源重连修复（2026-11-09）

本分支仅实现后端指数查询恢复，尚未合并、push、部署或恢复生产数据。用户明确特批 Codex 在独立树实施和提交，Claude 最终审合；固定 base `e353220e4b400941ae8134d35105b242de1a13bd`，未 rebase。

## 依据与预期

原故障：Nov9 17:00 三个指数分别登录报 `10002007 / 网络接收错误`，`fetch_index_daily` 单次登录即返回 0。16:20 各写 263 行但最新 Nov6，并不能证明当时 Nov9 上游已发布。只读诊断原件为 `/tmp/codex-reports/alert-continue-authorized-20261109/index-diagnosis.json`，未修改。

诊断阶段同机已装 BaoStock 原生 SDK 的 Nov2–9 响应共18行；Nov2–6 的15行 close/pct 与基金库逐值相同；Nov9 原生收盘/pct 分别为 hs300 4056.1081/0.045167%、csi500 6586.1764/-0.169377%、gem 2458.5623/-0.270551%。本轮只将固定样本用于替身测试，没有再次请求生产或公开行情。

预期：瞬态登录、query、rs.next/get_row_data 网络中断后，有界重连并重查同一指数同一区间；任一失败尝试的半批全部丢弃。仍失败返回 0 并打印明确失败原因；合法空仍返回0，不代表稳定恢复。

## 最小实现及复用

只改 `app/collector/public_fund.py:fetch_index_daily`。沿用 `baostock_daily._ensure_login / _NETWORK_ERROR_CODES / _reconnect_with_retry / _logout`，最多两次完整查询，一次恢复调用复用既有最多3次、间隔2秒登录预算。非网络业务错误不触发本层重试；SDK分页接收空而保留error_code=0的静默截断也拒绝提交。登录/查询失败、进程异常、缺结果/坏JSON均不能进入父进程写入段。

SDK 的 default_socket/user_id 及助手的登录标记为进程全局，现有公共入口没有所有调用方共同持有的会话锁。单在本函数加线程锁不能保护股票/主指数调用。因此仿现有 baostock_worker 的进程隔离方式：用当前解释器启动一个只读查询子进程，子进程只导入恢复助手并查询，不初始化数据库、不写进度、不调用worker主流程；结果在 finally logout 后用JSON返回。父进程SDK会话完全不参与登录、重连或登出。日更三个指数仍按原循环串行，未增加worker数量配置。两个并发函数调用的假SDK PID不同，父进程已有会话计数不变。

子进程经真实 `baostock_daily → base → baostock_socket_timeout` 导入链继承既有socket双守卫；没有新setdefaulttimeout、线程超时或子进程超时层。线程/进程隔离测试的40秒看门狗仅存在于测试。重试次数有界不等于整轮时长承诺，socket超时是单次网络操作边界；原调度外层预算保持不动，持续故障仍可能使外层超时。此次没有调整timer/预算登记或宣称“稳定恢复”；父部署审查需考虑进程启动开销与连续故障预算。

指数映射、400天默认范围、date/close/pctChg字段、日频和原始百分数不变；不调用股票fetch_one（000300/000905会被其股票规则误映射为深市）。成功后的原基金写库段原样保留，未引入弱源。因此不搬主库source=intraday_snapshot的Nov9行，不新建腾讯解析器，不用弱源覆盖已有非空或历史。策略、阈值、前端版本串及基准均未改。

## 证据用例与验证

新增测试 `scripts/tests/test_fund_index_reconnect_20261109.py`：固定真实18行样本，恢复函数从既有源码AST原样抽取；临时子包只装假SDK。父写库接口是捕获参数的替身，不创建SQLite库。另有实际public_fund模块导入用例，base/akshare入口先打桩，不运行采集器主体。

- 修前原样末行：`14 failed, 2 passed in 1.09s`。10002007登录、查询/读行中断、半批误成功和logout异常确实红。
- 修后：新测试 + 既有基金指数新鲜度检查和index_pct保护用例，结果见下方原样末行。
- 标准pre-commit由提交时真实hook执行，完整输出落 `/tmp/codex-reports/alert-continue-authorized-20261109/index-implementation-evidence/commit.log`，不跳过hook。
- 未执行全量 `pytest -q scripts/tests/`（先前全量耗时约330秒，超本轮单命令45秒限制）；不以局部通过冒充全量/最终Linux CI，父整合后独立跑。

## 边界清单（七轴）

| 维度 | 已测/不测及理由 |
| --- | --- |
| 输入域 | 三指数ID、固定日期/字段/6行原值；未改映射及未知ID既有回退。 |
| 状态组合 | 首登失败/重连成功、连续登录失败、查询连续失败、业务封禁、合法空。 |
| 时序 | 登录/查询/next/get_row_data各阶段中断；分页满页静默EOF、短读、二次失败均不写半批；显式日期不依赖真实today。 |
| 上下游 | 原生SDK替身+真实恢复助手，实际模块导入；子进程退出、坏JSON、缺返回不写；写库仅捕获替身。 |
| 极端值 | 重点是不完整返回；未改数值清洗/价格策略，不扩展价格合法性需求。 |
| 回退路径 | 仅同源重连，不引入腾讯/实时快照/估算值；持续失败保持返回0并可见。 |
| 并发与重入 | 两个真实假SDK子进程并发，父已有会话不变；finally登出异常不丢完整响应，子进程退出释放残余socket。 |

同类面：三个日更指数及backfill-nav/estimate调用均复用同一函数；其它股票/主指数恢复入口不改。已扫pending-features-index：基金指数新鲜度与公募日更预算历史事项存在，本改动不替换既有新鲜度判据、不调预算、不预留无需求的新抽象。文件占用由父已核；本树开工clean，全部修改只在约定三文件。

## 交付边界

仅实现关及局部回归完成；父独立review、最终Linux CI、合并和部署待办。无refs/消费者/completion/handoff/main/生产写入，无生产采集、DB写/重算、真实通知或push。生产后自然轮次应逐指数核日期及原始值，不能仅凭进程退出0关闭稳定性残余。

最终局部回归原样末行：`56 passed in 2.77s`。


## v2：父进程退出后终止本次查询（Gibbs P2）

保留上一版提交 `5d8abbec37dcf0624ba467aefa742bd6244df8ea`、`index-implementation.json` 和修前红日志，不修改原证据。Gibbs 的范围是 **mac perl-alarm 只终止父进程后，新增查询子进程仍活着**；没有把这个事实外推为 Linux systemd 群杀失败。

已查 app/scripts 的 parent-liveness/getppid/PDEATHSIG/pass_fds 等入口，没有可直接用于该查询的父存活守卫。`codex_review_claims` 的 owner_pid 只是调度元数据，不适合引入采集进程；此次不用消费者、长期任务或 PID 轮询。

最小修复仍只在 `fetch_index_daily`：每次启动查询创建独立匿名管道，父**独占写端**，仅用 `pass_fds` 给查询子进程传读端。父正常退出或因 SIGALRM/SIGTERM 等异常死亡时，写端由内核关闭，子守卫读到 EOF 后 `os._exit(1)` 退出自身。父在调用结束的 finally 中关闭自己持有的两个端点；读端的额外父副本不会阻止 EOF。守卫先于 SDK 导入启动，父早死不会留下尚未进入SDK的长网络worker。

没有设置全局 signal handler、使用 preexec_fn、按 PID/进程组发信号或操作其它锁；没有新增任何行情/SDK超时层。管道读是等待父生存期结束，没有定时网络取消。正常查询的SDK finally/logout、完整结果解析、父已有会话及线程隔离保持原样。旧成功写库段与5d8逐字相同。

验证只运行临时小进程/假SDK/捕获writer，不触达生产、网络行情、生产SQLite或通知。真正的 perl alarm 使用仓库现有形式 `perl -e 'alarm shift; exec @ARGV or exit 127' 2 python ...`；父早死例在启动桩内延迟0.4秒，让父在真正守卫代码开始前收到等价SIGALRM；正常退出例是主线程正常结束、查询线程为daemon。另有独立旁观进程，验证清理没有误伤他人。

| 真实小进程场景 | 修前 | 修后（Mac本轮实测） |
| --- | --- | --- |
| perl alarm | parent=-14，查询仍活过3秒 | parent=-14，查询终止；旁观进程仍活；观察耗时0.006秒 |
| 父早死SIGALRM | parent=-14，查询仍活过3秒 | parent=-14，查询终止；旁观进程仍活；观察耗时0.385秒 |
| 正常父退出 | parent=0，查询仍活过3秒 | parent=0，查询终止；旁观进程仍活；观察耗时0.007秒 |

修前原样末行：`3 failed, 24 deselected in 13.25s`，日志在 `index-implementation-v2-evidence/lifecycle-before-red.log`。反例测试的finally仅按已知测试PID及专属/tmp启动桩校验清理反例遗留，不使用广泛进程匹配。

修后最终原样末行：`61 passed in 6.41s`（本文件29例 + 原相关32例），日志 `index-implementation-v2-evidence/v2-related-tests.log`。新增成功/启动失败两条路径均检查父管道fd已关闭；原有正常查询、三指数原值、父已有SDK会话、两线程隔离和半批拒写均回归通过。生产改动不接触原生SDK/真实DB；相关旧测试仅使用其既有临时SQLite fixture。

进程状态验证把无PID或僵尸视为已终止工作进程；不声称能控制其它系统上PID1何时执行wait。这里Mac实测状态均为空，没有活worker遗留。3秒是测试观察上限，守卫本身没有3秒或其它网络计时器。Linux CI与Gibbs增量复核仍由父完成，未声称上线或生产自然轮恢复稳定。

机制依据：[Python subprocess 的 pass_fds/close_fds](https://docs.python.org/3.11/library/subprocess.html#popen-constructor)、[Python os.pipe 的不可继承描述符](https://docs.python.org/3.11/library/os.html#os.pipe)。标准pre-commit随追加提交真实执行；不push、不合main、不部署。
