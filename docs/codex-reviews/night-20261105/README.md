# 2026-11-05 夜间接力：前端加载与后端返修复验

用户授权：睡觉期间自主推进可做优化，避开 Claude 正在处理的任务，完成后通知 Claude。本轮授权只用于这些交付，不改变长期角色规范。

用户原话：“我去睡了。你检查所有能做的优化都自动做下去 做好后同步通知claude就好了。只要别和他撞车就行”。原始子报告中的具体 focus 摘录是 Codex 派单范围，不额外当作用户逐字需求或已采纳修复方案。

## 所有权与提交边界

- Codex 延续 `codex/369-370-frontend-timeouts`，独立工作区 `.claude/worktrees/codex-frontend-timeouts-369-370`。先前交付 `04fd4a8c2163e05b29c0e72811b7790dd0b4135e` 保留；通过 merge 纳入 main 的 F04 合并点，不重写已推提交。
- 开工快照 main：`aac5d19bd`。Claude 当前工作为 F01/F03 内部审查、镜像收尾。Codex 对这些后端提交只读复验，不在 Claude 分支返修。
- 前端实施仅处理已识别的正文超时同类缺口：`_labKellyFetchTrades`、`_fundScoreApiFetch`、`_fundScreenerApiFetch`，及必要的回归测试。保持预算、回退顺序、业务数据与布局口径。
- CSS、按钮尺寸、策略算法、生产数据、云端任务、watcher/consumer 和合并部署不在本轮写入范围。
- 版本串前后均为 `20261031-a654`；不提交生成的 min，不自行 bump。Claude 独立审查后统一 build/bump/SW/合并与部署。

## 交付与证据

### 前端：已实施，待 Claude 独立审查与上线

将 5 条请求腿的 timer 清理移到随正文 Promise 结算的 `finally`：Kelly 的 R2/CF/SSD 各 60000ms，基金评分与高级筛选 API 各 15000ms。删除了只清理再原样抛出的 catch，生产代码净减少2行；未增加请求框架。

认证 headers、credentials、cache、URL、正常返回值、错误口径、三源回退顺序保持。三个辅助函数原本没有外部 signal/cancel 参数，本轮不凭空增加不可达的取消接口。既有 `fetchJSONProgress → fetchJSON` 取消链继续按真实 callee 回归。

- 新增 Node 用例 49/49，既有 27/27，共 76/76；两个 pytest 包装 2 passed。旧源码用同一最终测试为 41 passed / 8 failed；初版测试监听计数误报已过滤，未计作业务缺陷。
- Chromium 147 桌面与手机视口 46/46，保留上轮14项，新增基金12项、Kelly20项。旧版 `37a4fa707` 对照 34 passed / 12 failed，失败全为正文停滞/无法回退。真实 loopback HTTP、浏览器 fetch/Response/AbortController；无外网请求，服务/响应/连接释放。
- 浏览器记录4份源码与9个提取函数的 SHA256，运行前后相同。时钟按0.02倍缩放，不代表真实秒数 SLA；WebKit/真机和完整站点视觉未验。
- app/lab 候选 min 构建并语法检查通过，分别1,093,462 / 568,274字节；产物只写 `/tmp`。构建检查的两次调用形态错误已纠正并保留日志，未修改生产构建脚本。
- 完整 pytest：**2286 passed / 3 skipped / 0 failed**，330.30s，退出0；测试前后源码/测试文件 SHA256 相同。运行的是当前前端分支（含F04/L56，尚不含F01/F03未合并分支）；两个后端固定head另行验证，不能混为一次全量全绿。任务状态2 OK/0 warn/0 fail；版本一致性检查1/2通过，正式源/min检查3留给合并构建。

输入/状态/时序/上下游/极值/回退/并发七轴、17个非 min JS/HTML 的同类扫描及范围逐字核验，见[前端实施明细](evidence/frontend-summary.md)。没有在本次扫描覆盖内确认其它同根因项；不能外推为所有 fetch 或全站所有问题均已消除。

**等待时长的边界**：Kelly 三腿全停滞仍最多180秒；其既有 Retry caller 默认3次尝试加1秒/2秒退避，理论最坏约543秒。修复的是原预算不生效，不把它宣传成短等待。缩短大文件预算、改变重试策略、给 UI 增加取消入口或分片续传是另一组行为变更，需结合文件大小与真实弱网验证；本轮保留原语义交 Claude 决策。

### 后端：固定新 head 复验，源码未改

| 项目 | 固定版本与实测 | 结论及 Claude 待复核项 |
| --- | --- | --- |
| F01-R1 / #366 | `1f98f67baf38864222890f8379c288a782d7eea2`；104个head场景、旧版合法空判别场景；作者辅助测试23 passed/1 deselected | 合法空与真实异常拆分有效，R1目标 Ready。另复现新旧版本均存在的P2：单只基金写入中途失败未rollback，残留行被下一只commit。挂回#366/#333上下文交 Claude 处置；不是R1新增回归 |
| F03-R1 / #367 | `197a0bedaf259bea48bf3c43a17390a038af5e82`；真实半写/rename/权限失败、稳定侧车锁、10进程并发及send/flush/dedup链 | 核心原子写与已有/新增条目失败语义通过。仍有2条P2：显式0600文件在umask022下原子替换后变0644（条件性兼容回归，未证实生产泄漏）；并发测试把合法“先吸收再flush、两条均交付、buffer为空”误判丢失。建议按“已知回归不进main”约定先复核处置，再验新head |
| F04 / #368 | 实际merge `aac5d19bdc60ebeb136efc12efd1e8022138724e`；源码/测试与分支blob一致；16项定向、15项独立验证 | fd释放、原OSError、失败/重试/正常锁顺序通过；无新finding。对应[CI Quality Gate #1026](https://github.com/xp13465/trade-data-signal/actions/runs/41864831762)成功，官方HTML含exact-SHA链接；API403限流，未伪称API验证 |

F03 权限项不是“默认权限从0600降到0644”：默认新建文件在新旧实现均为0644；只影响曾显式收紧的既有文件。测试项是验收假红，不是已证实的业务丢数据。F01残留写入的负向验证器故意exit1；不能把本次所有后端探针描述为全部绿。

原始报告：[F01](evidence/f01-recheck.json)、[F03](evidence/f03-recheck.json)、[F04合并点](evidence/f04-main-recheck.json)。其中命令的 `/tmp` 路径记录当时隔离环境，不是生产路径；固定SHA、原始末行与限制作永久证据保留。Codex未收到也未声称收到这两条新head的Claude内部审查PASS回执。

文件摘要见同目录 `SHA256SUMS`；浏览器归档为保留结果/源码摘要的精简JSON，截图与完整网络轨迹仍在 `/tmp/codex-reports/night-20261105/`，不将大量生成图片或候选min加入开发仓。

Node红对照日志用JSON封装原始文本与SHA256，保留可还原字节；日志自带的空格行不混入代码空白校验。其它归档JSON原样复制。

## Claude 接续

1. 核对本分支最终 head 并独立审查前端；此前 `04fd4a8c2` 的自测不能替代后续增量的审核。
2. 后端复验以报告所写的固定新 head 为准。报告不代替 Claude 内部审查回执；若 head 再变，旧结论不能直接沿用。
3. F04 核验以 main 的实际 merge SHA 及同 SHA 的 CI 为准，不能用分支 PASS 或时间接近的 CI 代替。
4. 合并、构建和部署仍由 Claude 统一入口完成；云上同步沿用镜像实际收工及 F04 合并 CI 绿等条件。
5. 对候选问题逐项复核后再决定处置，不因 Codex 报告直接当作确定需求或自动修复命令。

## 通知边界

本轮不投 `.ready`，避免现有消费者启动另一个可编辑 Claude 会话。当前 Claude 终端不在工具允许的访问范围；不绕过限制。完成时通过既有通知桥写被动 `.done` 与开发群消息，记录投递结果；没有 Claude 回执时只记“已投递、待接收”，不记为已复核或已合并。
