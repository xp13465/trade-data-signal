# FIX5：长摘要全量投递与断点续传（2026-11-06）

实现位置：`scripts/notify.py` 的 digest 区域及纯标准库 `scripts/alert_digest_delivery.py`。
本次仅在隔离源分支实现，待 Claude 审核；未提交、推送、部署或实际通知。默认 Codex 外审角色不变。

## 内容与请求大小

保留既有摘要标题、明细、原因、故障域、恢复留痕、邮件白名单、report 群与 ledger key。
邮件仍是完整 HTML；飞书改走 `send(feishu_post=..., feishu_group="report")`，全部节点为
`text`，从同一 intro/rows 生成。节点文本拼接可精确还原邮件显示文本；显式换行、中文、
emoji、引号、反斜线、尾部明细均保留。现有其他 `send()` 调用及其 text 截断行为不变。

飞书段同时受 80 行和 **16 KiB 请求 envelope** 限制；按现有发送器实际的
`json.dumps(ensure_ascii=False)` 编码测量 webhook 对象以及 app 双重 JSON 字符串的 UTF-8
字节数。超大单行按 Unicode codepoint 切分，无省略。post title 基础部分最多 240 UTF-8
字节，序号提前预留；溢出标题放回正文。传给 send 的原始邮件主题不变。

官方依据：[自定义机器人使用指南](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)
明确 webhook 请求体最多 20 KB；[发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)
为 app 接口参考。30 KB app post 上限来自本任务约束；当前网页读取未独立取到该项正文，
实现与测试均采用更严格的 16 KiB envelope，不依赖更宽上限。

## checkpoint 与完成条件

复用现有侧车锁、buffer 解析、原子 buffer 写入，增加同一 state 文件的可选
`pending_delivery`：完整冻结 entries/subject/body/lines/parts、SHA-256 signature、目标路由
hash、已确认段、其他渠道 attempted/success、逻辑计数回执以及 complete 标志。parts_signature 把分段绑定到
冻结 signature；读取时验证正文/行/节点全文覆盖、版本/字段类型、唯一且有效的回执索引、
其他渠道布尔回执与 complete 的一致性。已损坏但可解析的 journal 也明确诊断并保留，
不能凭重复索引或伪 complete 进入清理。
不新增队列、守护进程、consumer、CAS 或 ready 信号。

每轮/每段发送前 checkpoint，发送结果后再 checkpoint；任一写入失败立即停止，未完成不清
buffer、不推进水位。新 state 文件及临时文件默认 0600，既有 mode 严格保留；fchmod、fsync、
replace 失败上抛，临时文件尽力删除。state 损坏/不可读会明确诊断并保留条目，需人工检查，
不会伪称投递完成。

配置启用飞书时必须全部段成功，即使 report 目标缺失也不以邮件成功代替。已有但畸形的
配置文件始终视为飞书必需；配置缺失且有有效凭证也必需。真正无配置/无凭证，或显式
disabled，沿用任一渠道成功即可完成的旧规则。chat_ids/webhook_urls 非对象时输出诊断并
保留，不走错误的成功分支。

发送继续复用 `send()` 的路由、邮件门控、ledger 和 latest mirror。首个发送尝试使用全部
渠道；一旦邮件或 Telegram 任一成功，其后仅 `feishu_only=True`，不会重复已确认成功的
邮件。其他渠道全失败可再次尝试，不能仅凭 attempted 标志永久抑制。飞书每轮按顺序尝试
未确认段，失败即停止；已有发送器保留原有限次数重试。所有已确认段均跳过。

只有第一次实际任一渠道成功的逻辑发送带 `merged_count=n`，后续/重试的已计数发送为 0。
ledger 仍为成功的传输调用逐条计数，单个摘要可有多条传输记录；sum(merged_count) 才是被
合并条目数。latest mirror 仍按既有 send 调用留痕，可能有多条同主题完整摘要，不能当成
独立摘要数量或端到端完整送达证明。

未完成 pending 绕过每日时间/水位门控，跨午夜仍重试同一冻结内容。新到条目、相同 rid
但 hits/hits_ts 或任何字段改变的条目不替换冻结快照。目标 hash 不保存凭证或明文 URL；
模式/目标变化会使全部飞书段回执失效，重新分段并发送，其他渠道成功回执保留。该校验也
适用于 complete 后清理失败的 pending，旧目标完成回执不能清掉新目标尚未接受的条目。

全部必需回执完成后先持久化 complete，再读当前 buffer，以完整 JSON 内容做多重集相减，
保留坏行、增加条目和更改过的条目。清理失败保留 pending，不推进水位，同目标下次只清理
不重发。清理成功才保存 last_sent_day=已发快照最大 day，并移除 pending；保留的新行/
hits 按旧每日节奏等下一日，不触发同日额外摘要。最后 state 写失败时已送达内容可能已
清理，但 durable complete 仍在，下轮重试收尾，不会把未确认内容当成已送。

发送成功到回执写入之间崩溃可能导致重放（包括邮件、飞书段和逻辑计数）；不承诺 exactly
once。checkpoint 只能避免重发已持久化确认的成功，不能实现跨远端发送和本地文件的事务。
配置在读取后、单次 send 内突变无 CAS 保证；此任务不扩大为配置并发协议。

## 定向验收

新增测试 `scripts/tests/test_codex_digest_delivery_20261106.py`：真实临时 buffer/state，
真正 flush/send 编排与分段，只有渠道外部边界打桩。导入 notify 前正控证明网络、邮件、
进程与 .env 陷阱有效。既有套件通过 `/tmp/codex-reports/alerts-continuation-20261106/run_digest_targeted.py`
在 `--noconftest` 下执行，显式 stub 配置/凭证，避免既有 fixtures 意外读取真实配置或凭证。

各轮原始输出、失败原因、最终计数、文件哈希及兼容性证据在同目录 digest-implementation.json/md。
最终联合定向套件 152/152 通过（新增 39 + 既有 113），其中 app/webhook 两个持久测试走真实
flush→send→Feishu core→实际序列化，只在 HTTP 边界捕获请求；逐包验证 post 类型、report
目的地、实际请求字节上限和全量文本/尾部。真实 shadow 测试清除原目录 sys.path 与缓存
模块，复制 notify、alert_denoise_rules、alert_digest_delivery 三个运行依赖后可独立完成。
限定扫描未发现上述 digest 套件复制 notify.py 而遗漏 helper 的构造；更广 fixture 覆盖留给
parent 的一次完整 suite。

首轮既有套件 111 通过、2 失败的原始日志保留：
`test_264b_digest_watermark_20261017.py::test_08_send_fail_keeps_no_state` 和
`test_245_l2_budget_digest_20261010.py::test_04c_flush_send_fail_keeps_entries` 原先要求全渠道
失败不生成任何 state。获得 parent 窄授权后，仅这两个函数改为更强的 journal 契约：保留
原失败/条目断言，固定离线配置，验证无完成水位、pending 未完成、同窗口真实重试成功、
仅删除冻结快照并保留晚到行。未改其他旧测试。完整项目 suite 留给 parent 冻结后统一跑。

本机无 ruff/flake8/pyflakes/pycodestyle，未安装依赖；已通过标准库 compile、AST 变更范围
核对及 tabnanny。

## Claude 分支兼容性

未编辑 `_chmod_like_target`、`_replace_latest` 或其他作者文件。digest state 的独立严格
fchmod 原子写与 Claude `feat/notify-p2-fixes-20261105` 的 strict chmod 目标一致；基于
`56e9fd8ff` 的兼容性检查单独记录。尚无 overlap ACK，不复制整文件、不合并未完成草稿。
