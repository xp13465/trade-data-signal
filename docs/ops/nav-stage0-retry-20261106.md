# stage0 NAV 零行完成状态的有界重试

本轮修复只处理原NAV完成状态与后续重试：旧done/empty0或legacy无摘要不能永久豁免已有行校验；正常空仍是soft result，不改基金产品范围、数据源或timer。

## 有效性与查询

沿用原有效契约：`fund_daily_nav`有任意行即保留done，包含unit_nav为NULL的已有行，不在本轮重新定义货币/yield-only产品支持范围。经理采集的合法空哨兵和其他fetcher行为保持。

原`SELECT DISTINCT fund_code FROM fund_daily_nav`只读生产计时10.0003秒仍被中断，不能放到3秒入口guard后宣称安全。因此采用下面的keyset分页查询，每页返回500个目录code及对应有行布尔值；没有在WHERE中先过滤EXISTS后再LIMIT，也不读取NAV历史值。

```sql
SELECT b.fund_code,
       EXISTS(SELECT 1 FROM fund_daily_nav AS n
              WHERE n.fund_code = b.fund_code) AS has_any
FROM fund_basic AS b
WHERE b.fund_code > ?
ORDER BY b.fund_code
LIMIT ?
```

首参为`""`，后续为上页最后code；第二参为500。要求现有`idx_daily_nav_code`以fund_code开头，并核对catalog/NAV两端covering计划；不创建索引、不强制INDEXED BY。每SQL最多3秒、完整校验总预算30秒；持同一只读事务，全部页完成才修改内存进度并允许持久化/GET。缺索引、非covering计划、SQL错误或超时均停止本轮GET，保留原progress，不把未完成查询当作全池失效。

独立只读工具必须显式使用`sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)`及`PRAGMA query_only=ON`。本修复不改常规业务`get_conn`的连接约定；其校验函数仅执行读事务。

## 进度与预算

本轮实现决策由父会话在用户整体实施授权内选定：24小时资格冷却、每Python进程最多100只旧状态迁移/重试；不是用户逐参数显式批准。

- 有效历史done保留；零行旧done迁入retry，legacy仅记`next_retry_at=0`为可选资格，不伪造历史尝试时点。
- 只有实际解析非空并成功提交后才记录okN/done；原批次无条件done更新取消。
- 正常空不进fail，实际异常进fail；两者均在真实逐code `attempted_at`后设置冷却。
- run指一个Python进程的模块初始化身份，不是上层整个编排。100只仅限制迁移/重试，首次初始化豁免；不承诺整个流程或所有HTTP流量最多100。
- fresh首采与retry均在GET前原子预留；fresh不扣100额度。结果保存失败后，同一run重入不再请求。预留没有逐code尝试时间，后续进程可恢复未确认预留；正常已保存空/异常仍遵守24小时资格。
- 共享progress mtime不代表逐基金尝试时间；其他fetcher分区保存，manager合法empty0不被全局重解释。

## 实际迁移队列与恢复限制

2026-11-06 00:42:46 UTC（08:42:46 +08）父会话唯一最终只读benchmark完整成功：57页、28,456个目录code、26,831有行code，耗时6.937869秒。28,434个旧done中有1,603个零行，invalid_outside_catalog为0；两端covering计划已实证。

|目标code|当时due排名（1起）|按100/进程的首次触达调用序号|
|---|---:|---:|
|158076|1255|13|
|158901|1262|13|
|581070|1546|16|

三只都不在首100。按该固定队列，首遍理论至少17次成功校验后的调用；这是快照分批算术，不是恢复保证。现有周频时点不变时，24小时只代表资格冷却，实际仍等待下次调度。真实周频恢复进度、后续数据变化及全部修复所需时间未知，不能宣称很快恢复。

若需加速，由Claude结合只读计划决定受控的一次性恢复窗口或额外正常启动节奏；本修复不自动猛重采、不新增collector或timer、不改100额度。没有从官方NAV存在推断当前东财HTTP一定有值。

## 本地验收与上线边界

便携定向测试运行真实函数AST、真实safe_call/原子保存及临时SQLite，源请求仅为本地替身，不import业务采集模块、不读生产DB/凭据或发网络请求。`fixture_NAV_rows`表示/tmp fixture行数，不能当作生产写入或恢复。

覆盖NAV-01（value/empty/error结果保存失败后同run不重复且fresh不扣100）、原有行NULL-unit保留、legacy重新入池、冷却/下进程、100队列推进、首采豁免、SQL超时/缺索引无GET且progress字节不变、manager分区保留。

本地测试和只读benchmark不等于已经部署、采集、补齐或发出恢复通知；生产数据修复仍需Claude按后续窗口验收。
