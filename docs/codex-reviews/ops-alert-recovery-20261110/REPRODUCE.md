# 固定提交复验

代码集成点：`b5a7483374d252c0622284f17560fd601eb55e3d`。后续报告提交只修改 docs。请在独立工作树按固定提交复验，不以活动分支代替审查对象。

## 本地隔离回归

使用项目 Python 3.11 测试环境；仓库 conftest 的零外发防护必须启用，不连接生产凭据、不绕过通知替身。

```bash
python -m pytest -q scripts/tests/test_fund_index_reconnect_20261109.py
python -m pytest -q scripts/tests/test_overfit_recovered_schedule.py scripts/tests/test_overfit_retry_20261110.py scripts/tests/test_overfit_delivery_20261109.py scripts/tests/test_overfit_public_verifier_20261110.py scripts/tests/test_223_overfit_monitor_timeout.py scripts/tests/test_181_fetchnews_denoise_20261007.py
python -m pytest -q scripts/tests/test_ops_monitor.py scripts/tests/test_ops_monitor_registry.py scripts/tests/test_ops_monitor_delivery.py scripts/tests/test_ops_monitor_delivery_budget.py scripts/tests/test_ops_monitor_recovery.py
```

最终 Linux CI 使用全 Git 历史并执行 `scripts/tests` 与 `ops/monitoring/tests` 的完整组合；精确入口、依赖及 systemd 兼容检查以 `.github/workflows/ops-monitoring-checks.yml` 为准。全量 JUnit 计数不包含此前 HC 手机浏览器的102条断言，不能相加冒充一次全量绿。

新增恢复文案直接调用生产渲染函数，7个正反例由最终CI执行：

```bash
node --test ops/monitoring/tests/schedule-recovery.test.mjs
```

## 需要复核的反例

- 公募：合法空结果与超时/异常分开；登录每次超时但总预算尚足仍返回124；超时后恢复不残留错误分类；分页失败不落半只指数；单只回滚不撤销已提交的前只。
- 过拟合：75后成功只上传一次、不重复计算或模型通知；其他错误不重试；持续争锁与跨日仍失败；四个公开地址的完整响应核验保留。主/ext不是原子事务，部分发布失败不能被写成成功。
- skip消费者：真实skip次数仍为1，另附同轮恢复证据；三次真实重试成功不发假SEVERE；运行中、最终非零、过期成功行和其他任务不能借证据清零；既有fetch_news轮次去重/升级规则保持。
- 监控：旧派生失败+更新且完成的systemd成功可对账；运行态和旧成功不能洗绿；自身恢复需同boot、同invocation的HTTP200 ACK和manager完成双证据；22:15成功→22:30失败→22:45成功真实投影必须保留中间失败。
- 投递：同一snapshot ID及字节重试；每次5秒墙钟、最多3次，仍在原20秒总预算内；慢滴流、第二次3.3秒回复、永久挂起、不可重试错误及子进程回收均验证。

## 生产验收边界

本轮云端仅运行既有生产源码的数据恢复，没有 pull 新源码、没有 main push、没有改原unit、没有对原业务unit执行reset-failed。补采、补传和正常定时unit成功是三种不同证据。

Claude 审合部署后，先核发布合并点、构建版本、两站资源，再按自然窗口或经避撞核查的原任务复跑验收。记录原unit的开始/结束/退出码、业务日期、公开文件校验以及随后监控快照。临时恢复unit成功不能直接消除原unit失败记录。

公募备份完整性限定：SQLite备份调用完成；全库quick_check因磁盘等待未完成。另做了本次恢复数据范围的逐行对账和可恢复行备份，不能把它写成全库完整性检查PASS。

报告重建只读取本地证据：

```bash
python docs/codex-reviews/ops-alert-recovery-20261110/generate_report.py --evidence /tmp/codex-reports/ops-fix-20261110
```

生产恢复脚本和原始日志保存在私有审计归档，属于本次有日期、固定源码、前置条件及唯一unit限制的维护记录。不要作为新的定时任务或无条件重跑脚本。
