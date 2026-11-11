# NAV 采集到公开文件的限定范围凭证

用户已授权 Codex 在独立分支完成待办，由 Claude 复核、合并、部署。本批接续 `20f669d25fc44056f207b15b606e2da7f7a70770`，不修改上一批不可变报告。最终提交、测试原始末行和复核结论以本批总交付 JSON 为准。

## 修复的缺口

已有公募/FOF 凭证证明实际提交的 SQL 输入，但 `nav_bucket/` 走独立 R2 前缀，普通 `data/*.json` 发布凭证不覆盖它。上传 rc0、HEAD 长度、源 MAX 日期、备份成功均不能替代本批净值的公开文件对应关系。

复用现有私有 `trade-delivery-receipt-v1`、publication 索引和原子锁；不新增队列、上传器、Worker 或定时器。

1. 真实 collector 在事务成功后，观察现有输入中的基金代码、源日期、unit_nav、acc_nav；按轮次写不可变私有 sidecar 并在原回执中记录 hash/size/行数。NULL unit 不纳入公开范围；NULL acc 表示 COALESCE 没有新值，不能断言数据库中也为 NULL。源日期不改写为今天。
2. 既有 `export_fund_nav.py` 在成功原子写入或实际读取未变文件后，把所选输入逐值对上真实 payload，并记录实际输出字节 SHA256/size。全量和日更仍共用原 `_build_payload`。从实际读写 fd 取得 dev/ino/mtime_ns/size，索引写锁内和监控读取时只 stat 固定 canonical 路径核对代次。旧回调、写证明失败后的新文件、GET 期间换代均不能沿用旧成功。字节、身份和文件代次都未变才保留同一代；即使相同字节被重新原子写入，也须重新回读。代码身份未知不能确认。
3. 独立限额回读仅 GET `https://ss.fx8.store/r2/nav_bucket/{xx}.json`。禁止重定向，要求 HTTP200、identity 编码、精确长度及 SHA256，绑定采集 run、输入 hash、导出 receipt、remote key 和已审核代码身份。部分成功保留 `partial`；新轮次不继承旧成功。
4. `admin/ops` 展示阶段事实。只有本批所有已记录桶均有对应凭证才显示 `scoped_confirmed`。基金业务总体仍是 unknown；真正采集失败仍是 warning。不是通过改状态或隐藏告警来制造恢复。

## 边界与开销

- 所选非空输入仅证明已提交并被导出的值；不证明未公布基金应已公布、上游完整、全历史、全池、每日 SLA 或策略效果。
- 分桶读取是不同时间的观察，不是原子 256 桶快照，也不保证公开文件此后没有变化。26h 沿用原回执有效期，不是新的业务交付期限。
- 不增加采集 API/SQL 查询，不额外启动 exporter。FOF 独立采集自身不发布；后续正常 17:50 全量 exporter 读取同一数据库，日更增量只覆盖其原有近期窗口。历史 FOF 行没进本次导出就保持未知。
- collector 内存观察沿用合计 0.5s；sidecar 最多 60,000 行/4MiB，每轮一次私有原子写，并记录实际收尾耗时。收尾超过0.5s保留提交事实、使发布输入凭证未知；这不能消除已发生的阻塞。额外本地写入有大小限制，但不承诺任意磁盘故障下 fsync 硬实时或已证明不影响原业务300s总预算。
- exporter 每进程额外观察累计 2s；私有源文件最多两个，每个 4MiB。预算用尽不继续遍历或假绿。监控每对象读取固定当前轮次、最多 256 个命名桶凭证，1s 检查预算，并只 stat 固定 `static-site/data/nav_bucket/{xx}.json` 核对文件代次，不读取/hash业务文件、不查数据库/扫描目录或联网；超预算返回 unknown。代次保护针对现有原子替换和普通写入，不覆盖人为恢复 inode/mtime 的对抗性修改，不能替代内容 hash。
- 回读默认 60s/64MiB，CLI 允许最多 300s/1GiB。`reserved_bytes` 是发请求前预留的响应上限，含失败请求，不是实际网络流量。每桶上限32MiB。CLI Unix alarm 覆盖 DNS 等 socket timeout 之外的等待，正文使用 read1 每次检查截止；库调用者须自己提供执行保护。没有禁用 TLS 验证。
- 全量256桶历史规模约500MiB，**一次默认64MiB很可能只完成部分**。同一有效轮次可重复显式回读，已确认且代次未变的桶跳过。未批准更大生产预算前不擅自增加流量；本功能不承诺默认一次全池确认。

## 接入和复核

默认全部关闭。既有 `OPS_DELIVERY_EVIDENCE_ENABLED=1` 启用 collector/export 元数据；`OPS_NAV_PUBLIC_READBACK_ENABLED=1` 另行启用异步上传成功后的限额回读。两者都为1才 GET；回读失败不改变原上传退出码，也不发“恢复”通知。`update_all` 的 systemd transient service 必须明确透传这两个白名单变量，不能假定父进程环境自动继承。

部署仍由 Claude 执行：核对两个 collector、正常 exporter、异步上传的实际运行目录/环境均指向同一私有证据根；分别审核真实加载入口的 module digest，沿用 `data/ops_delivery/producer-identity.json` 绑定合并后的完整 SHA。`-m`、导入和 `__main__` 的摘要可能不同，不能读 HEAD 或复制未经审核的 receipt 摘要冒充批准。导出和回读身份还须与采集回执的已审核 SHA 一致；版本切换期间保留 unknown。

只读检查（不会创建目录或联网）：

```bash
python3 scripts/ops_nav_publication.py inspect --root /实际运行根目录
```

经部署确认开关、身份及出口预算后，可对当前同轮补验；仅回读公开内容及写私有证明，不采集、不导出、不上传：

```bash
OPS_DELIVERY_EVIDENCE_ENABLED=1 python3 scripts/ops_nav_publication.py verify --root /实际运行根目录 --seconds 60 --max-bytes 67108864
```

命令 rc0 仅表示元数据操作返回 JSON，`status=checked` 也不是业务成功；结论须查 `inspect` 的每对象 state 和未知原因。无凭证/过期/预算不足均不能关闭历史故障。已有无 event ref 的通知原件不迁移、不删除。

## 离线验收入口

```bash
PYTHONPATH=scripts:. .venv/bin/python -m pytest -q scripts/tests/test_ops_nav_publication.py scripts/tests/test_ops_nav_readback_shell.py scripts/tests/test_ops_fund_evidence.py scripts/tests/test_278_nav_bucket_refresh.py scripts/tests/test_collect_fof_nav_333.py --tb=short
OPS_UI_EVIDENCE_DIR=/tmp/nav-ui .venv/bin/python ops/monitoring/tests/smoke_business_evidence_ui.py
```

覆盖真实 collector 的临时 SQLite commit、实际 exporter 字节、失败/NULL/源日期、错误公开字节、部分/续验、代次和身份、侧文件破坏、元数据异常隔离、原异步 wrapper 的退出码，以及真实监控页面桌面/手机渲染。所有网络和业务子程序均被禁止或隔离替身替代；不把离线验证写成线上已恢复。
