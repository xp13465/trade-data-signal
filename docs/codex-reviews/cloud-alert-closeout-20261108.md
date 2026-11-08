# cloud 告警与监控接管交付（2026-11-08）

## 授权和范围

用户本轮原话：“claude 没token了暂时 你借力做下去吧先”。本次临时接管正文分类、turnover发布范围、新监控配置与验证；不改长期角色规范。代码在独立`codex/cloud-alert-closeout-20261108`工作树，基线`606b64721`。Claude原有15分钟周期两提交`07d5f0eff`、`37e955910`已保留到本轮分支，不整文件覆盖其工作树。

## 修复内容

1. 正文与标题按同一canonical key分类。配置漂移用“配置漂移级告警”，真实停摆保留“停摆级告警”；邮件、飞书、Telegram共用同一正文，原始内容、直发及去重不变，旧两参调用兼容。
2. turnover改为专属small/large发布集合，不再调用全站候选集合。完整依赖是9件：overview、6个a-stock范围、boot及signals_today；boot内嵌overview和首页补拉signals_today不能遗漏。复用现有锁、预算、备份、增量、断点和缓存清理，专属状态不覆盖全站状态；采集/重导失败不上传，发布失败保留非零。
3. 保留已获用户认可的15分钟采样方案及30分钟陈旧阈值。源码、生成源、安装模板、Worker定时声明、前端与离线验证同步；分支快照的15分钟值仍须发布窗口现场实装、实读核对，不能作为已经安装的证据。

## 真实故障和验证边界

11月8日08:27告警由预装monitor的service/timer未进入当时生产仓库快照/登记表触发；10:00真实巡检已返回0（90unit一致、45个service登记一致、47项R2梯度通过）。该问题不是整站停机证据。

11月6日turnover的采集聚合/重导完成，个股源另有5只失败，不能称无错误采集。发布末段增量选23/24件，两个凯利文件约174.7MiB，反复TLS EOF后耗尽3120秒工作预算，最终service为124。11月8日线上A股all和凯利文件的HEAD200及最近修改时间证明后来有发布，不证明历史批次完整或用户已消费。新范围在真实上线前须对照源文件和依赖做首跑核验，不能以离线测试代替。

## 本轮已做的生产准备与首样

- 只读查询实际独立OPS_DB：4份迁移存在，查询rows_written=0；已部署Worker的OPS_DB绑定匹配，OPS_ADMIN_TOKEN/OPS_INGEST_TOKEN绑定存在，OPS_ALERT_ENABLED=false、OPS_ALERT_SCOPE=watchdog。未更改Worker密钥、业务库或真实通知设置。
- 新增缺失的`/etc/trade-ops-monitor/collector.json`和`collector.env`，目录root:ubuntu0750，JSON0640，EnvironmentFile0600。云端旧令牌副本与已配置来源不匹配，先在同目录的root私有backup目录逐字验证备份，再同步采集端正确副本；未轮换Worker密钥。恢复时先保持timer停用，按私有回执恢复原副本/目录元数据，保留所有新旧文件，不清理业务数据。
- 12:29:13一次启动检查先于配置落地而失败（resources，进程未执行），已当场告知用户。配置补齐后，12:30:38–12:30:42真实运行成功；journal记录与认证API返回相同snapshot_id：`7c204fca-af1c-4774-9c4f-82f59b4d158d`，177项检查，采集器/看门狗fresh，bootstrap_overdue=false。
- 首样134正常、2警告、1严重、40未知。严重项是周五turnover失败状态；警告为该任务派生执行结论和仍停用的monitor timer；未知主要是轻量元数据不能证明业务内容，未伪造为绿。
- oneshot未被活动timer引用时可能被systemd回收，`systemctl show`再次加载会显示默认success及n/a时间；本轮以journal实际运行记录和API持久样本相互匹配，未用默认值证明成功。

## 测试和发布验收

实施者定向测试：正文55 passed；turnover/断点/预算82 passed。独立周期审查：249个Python用例、24个Worker用例、2个额外临界用例通过；30分钟等号、+1ms及无首样45分钟检查轮已覆盖。其余组合回归和独立审查证据以本轮最终交接JSON为准，不把实施者自验当最终放行。

发布步骤：独立审查及CI通过后，在授权窗口备份当前timer，安装并实读15分钟timer（保持停用），只更新该项真实快照；经仓库统一合并/发布流程使Worker15分钟cron和阈值同版生效。验证首样后启用timer，观察真实调度，保留alerts disabled。turnover新状态首次建立必须明确ALLOW_FULL_UPLOAD=1；先核实9件源产物及线上指纹，运行专属范围即可，不重跑业务采集，不迁移或删除旧全站marker/checkpoint。

本报告不是“全部业务已健康”声明；未通过的生产事实和需要自然窗口的观察须如实留在最终交接中。
