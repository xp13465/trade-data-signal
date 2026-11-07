# 系统运行架构总览

本图谱的代码基线为`d4238f5b24aa1aa5632dd5fed1098ce9fbdb3620`。实际云端与本机观察有各自时间，见02和07；不是实时服务状态页面。实线表示已查源码中的逻辑连接，不代表每个部署节点已在线验证；虚线表示外部控制面未验证或后续设计连接。

## 一、执行与数据拓扑

```mermaid
flowchart LR
  subgraph Work[开发与审查]
    CC[Claude主控与开发分支]
    CX[Codex只读分析与外审]
    Git[代码仓与审查合并]
    CC --> Git
    CX -->|报告与固定版本证据| CC
  end
  subgraph Cloud[云主机：配置与运行观察见02]
    Code[CODE：代码checkout]
    Sched[systemd timers / services]
    Run[DATA：运行入口与任务]
    Collect[采集与补采]
    DB[权威业务库：sentiment / ETF / stock等]
    Signal[信号计算与映射构建]
    Freeze[历史ETF冻结与回测]
    Export[静态数据与交易产物]
    Checks[任务 / 数据 / 发布检查]
    Ledger[事件与通知台账]
    Backup[备份与恢复验证工具]
    Sched --> Run
    Code -->|app/scripts等运行引用| Run
    Run --> Collect --> DB --> Signal --> Freeze --> Export
    DB --> Backup
    Run --> Checks
    DB --> Checks
    Export --> Checks
    Checks --> Ledger
  end
  Upstream[市场/基金/新闻等上游]
  R2[对象存储与发布证据]
  CDN[CDN与静态站点]
  UI[市场全景 / 实验室 / 交易计划 / 通知等入口]
  RT[实时/代理服务：源码与部署见06]
  Channels[飞书 / 邮件等通知渠道]
  Git --> Code
  Upstream --> Collect
  Export --> R2
  Backup --> R2
  R2 -.->|远端与缓存状态需单独观察| CDN
  CDN -.-> UI
  RT -.-> UI
  Ledger --> Channels
```

图用于定位逻辑链路；准确服务名、入口、调度、状态及证据见各清单。外部存储/CDN/渠道存在配置或代码依据，不等于本次登录其控制面确认。实时服务的进程观察与前端实际请求来源应对照06，不能仅凭服务名推断全站请求都经同一后端。

## 二、三种事实不能合并

| 层 | 回答的问题 | 证据入口 |
| --- | --- | --- |
| 声明/源码 | 应该运行什么、读写什么、谁依赖谁 | 01任务源清单、03数据合同、04规则、06部署 |
| 部署/注册 | 实际安装了什么、何时触发、入口在哪里 | 02云端systemd/cron观察、07本机launchd观察（launchd 已废弃/历史存档，生产定时任务已迁云上 systemd timer） |
| 运行/业务结果 | 最近是否执行、数据是否完整可读、产物是否发布可见 | 运行观察、具体业务校验、发布proof与页面验证；本次未全量验收 |

`inactive`的oneshot通常只表示当前未执行；`active`只说明调度/进程层状态。程序exit0、文件mtime更新、对象上传成功、CDN purge、邮件发送和业务恢复是不同阶段。

## 三、任务与运行状态模型（面板拟议，不是统一实现现状）

```mermaid
flowchart LR
  Trigger[预期触发窗口] --> Calendar{本窗口应执行?}
  Calendar -->|否| NotDue[正常不应执行：带日历依据]
  Calendar -->|是| Dependencies{输入与前置就绪?}
  Dependencies -->|未就绪| Waiting[等待 / 超期：显示阶段]
  Dependencies --> Lock[锁与资源等待]
  Lock --> Run[执行入口]
  Run --> Result{业务结果必要条件}
  Result -->|证据通过| Publish[发布与服务可见性验证]
  Result -->|未满足| Incident[失败 / 降级事件]
  Publish -->|当前证据完整| Healthy[该范围可判健康]
  Publish -->|证据缺失或过期| Unknown[未知]
  Incident --> Verify[修复与独立复验]
  Verify --> Result
```

调度计划、交易日/市场日历、最大时长、下游截止时间和采集证据有效期分别定义。实现前必须逐任务核对当前约定，不能把设计状态映射成现有代码已经具备的功能。

## 四、事件到修复的协作闭环

```mermaid
sequenceDiagram
  participant Detector as 检测与事件记录
  participant Channel as 通知渠道
  participant Claude as Claude主控
  participant Dev as 独立分支开发与内部审查
  participant Codex as Codex只读复核
  participant Deploy as main合并与部署
  Detector->>Channel: 事件/摘要与投递尝试
  Channel-->>Claude: 通知只是入口，需读取固定证据
  Claude->>Dev: 复核问题成立后实施
  Dev-->>Claude: 固定head、改动与验证
  Claude->>Codex: 明确范围的审查request
  Codex-->>Claude: 固定报告、SHA与交接元数据
  Note over Claude,Codex: 正常hook事件提供元数据，显式ACK；不自动代主控处置
  Claude->>Deploy: 按项目门禁合并与发布
  Deploy-->>Detector: 新版本/新批次与业务结果证据
  Codex-->>Claude: 独立验收，限定通过范围和剩余未知
```

## 五、对账时必须保留的区别

- 代码仓、DATA权威库、静态副本和外部发布副本是不同资产；同名文件不证明同一内容。
- 交易主档有新mtime不证明某个原信号已入账；数据库有价格不证明实际消费者能读到它。
- 同日备份映射不自动等于冻结时实际使用的映射；缺可信历史输入时不能用今天映射补造历史。
- 规则定义、历史告警、当前检测、通知投递和人工回执是不同事实，不能互相替代。
- 业务过拟合/策略风险和系统故障分开看，不以“全部通知归零”为健康目标。

完整数据资产/写入责任、发布视图、监控分类、运行手册、对账和面板合同分别由03、06、04、05、10和08承担，避免总图变成另一份无法维护的配置副本。
