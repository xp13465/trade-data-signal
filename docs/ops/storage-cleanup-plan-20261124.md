# 给Claude主控：旧库与protected本地空间治理执行方案

版本：2026-11-24。Codex只读核查结果；生产未删除、未归档上传、未改源码、未运行GC。请Claude复核证据后按门槛分批实施，不将报告文件等同于无条件删除许可。本方案不需要新增COS或迁MySQL，优先复用已有R2/独立本机恢复能力；使用费按现有实际用量另计。

## 1. 可以回收多少：分阶段，不能重复相加

| 阶段 | 本阶段主文件/候选块数 | 累计目标 | 条件 |
| --- | ---: | ---: | --- |
| A：代码根无引用protected | 7,924,035,584B＝7.379833GiB，7028项 | 7.38GiB | 防回涨修复、保守保留规则、同锁域重算和逐项身份通过 |
| B：静态仓三份同SHA旧库 | 3,456,360,448B＝3.218987GiB | 10.598820GiB | 保留代码仓四库及静态stock；已验证历史副本与消费路径 |
| C：其余旧库全部退出 | 再3.563709GiB | 14.162529GiB | 五个独有SHA均可恢复，代码回退/直读链收口、隔离验证通过 |

C的6.782696GiB旧库全量**已包含B的3.218987GiB**，不能在14.16之外再加3.22。以上按allocated文件块核算，不含很小的sidecar/目录块；新增缓存、临时归档、隔离保留、自然增长会减少净收益。实际释放必须用执行前后df和逐项回执验收。以13:35约8.78GiB可用作静态示例，全量主文件退出后约22.94GiB；14:57可用已约8.75GiB，不应把示例当未来保证。

禁止计入：运行根protected（本轮0候选）；当前四个活库；全部swap；Git pack；整棵staticdata；未决preparing/unknown/purge锚点。过去两人工恢复目录已不在原路径，不再算收益。

## 2. 精确范围与查明的事实

定义：

- D＝`/home/ubuntu/code/trade-data`，权威运行数据在D/data。
- C＝`/home/ubuntu/code/trade-data-signal`，代码树。
- S＝`/home/ubuntu/code/trade-data-signal-staticdata`，静态树。

### protected

14:57:25–14:57:30 CST完整元数据：两根常规文件allocated合9.980564GiB。C/data/.r2-protected有8261文件，其中：现行引用闭包1,266,282,496B；额外保守扣55条plain preparing历史及99个相关payload共306,245,632B；余7028文件7,924,035,584B列候选。D/data/.r2-protected的1047文件1,219,985,408B全部保留。

两根合计保留约2.600731GiB。所有JSON可解析、无缺引用/symlink/硬链接/外部链接；采样复查引用元信息未变。候选具体是3552条终结confirmed history、3468份无保留引用payload、8个已终结pair；8个pair的16条最终history均confirmed、pending_purge=false，identity相符。不能因pair初始嵌入行仍prepared就误判状态，也不能只看文件年龄。

父会话用另一份BFS独立复算：保留所有非confirmed历史、confirmed时间并列全保留、跨根payload并集，候选集合与7028项清单逐项相同。未读payload内容、未向R2请求，因此按**本地既定保留契约**认定可回收，不声称每份内容已在远端重新验证。

### 两套旧库

14:52低优先级顺读八文件一次，前后inode/dev/size/mtime/ctime稳定：sentiment、ETF、公募三对SHA完全相同；stock_daily两份同大小但SHA不同。

- C/stock_daily旧版SHA：`fb948a753e6732ce179c4ffad0334a97e9b84e7b242a9e8471197b88ea49239b`
- S/stock_daily旧版SHA：`36546e2462cd87e3e7b6df69f21b2497dc85522987bbdd430f1cb7e1751c5812`

因此完整退出需保存5个独有字节版本，不能把两个stock合并丢弃。旧主文件全部untracked、非软链、nlink=1；八WAL均0字节，八SHM各32KiB，无rollback journal，SHA窗口sidecar元信息稳定。SHM有较新时间，不能凭DB停在10/28就说没有消费者。

15:09 sudo补采覆盖133进程、基础元信息不可读为0，瞬时旧DB/sidecar FD匹配0；51具体systemd单位已核，45个cwd在D，5个在C（四模拟交易明确D路径、export明确REPO=D），1个在ops根。对应源码16项SHA与固定main一致；环境未发现STATICDATA_DB_LOCAL_COPY=1，今日三轮静态备份明确DB步骤skipped。上述证据不替代后续调度/回退行为验证。

仍有app/db.py环境/兄弟目录/代码树回退，简报/影子/ledger按MAX(date)择库，完整性检查、回测、损失特征及若干逻辑源码根直读。已列到代码报告，不能声称C/data全无读者。五个旧版的现有外部恢复证明目前unknown，不等于没有备份；由Claude验证或建立确切SHA归档后退出。

## 3. 先修三个机制问题，防止清完再涨

固定核查源码基线main=`f4015bb695b98c9defb9e90ff1e435b630b8a02f`，云相关文件hash匹配。实施时版本若变化，重新对照，不套旧行号直接改。

1. **阻断protected跨树复制。** `scripts/deploy.sh:749–754`的REPO/data→GIT_REPO/data rsync目前没有排除`.r2-protected/`，且不带--delete，源端回收的旧文件会继续留在目标树。只为已核运行态增加精确排除；不在整个data镜像上开启宽泛--delete，不取消必要JSON/parquet镜像。该入口已由纯/tmp rsync夹具复现；不是对每个现存文件来源的唯一归因。
2. **保守保留所有nonconfirmed。** `scripts/r2_safe_write.py:144–153`现逻辑没有普遍保留plain preparing等历史；补为保守hold，并递归保住new/old payload及pair。现0.285GiB额外保留集合不能误入删除清单。不要为减少占用把HISTORY_KEEP改0或改写未知状态为confirmed。
3. **拆开GC回收预算和新增写入许可。** `scripts/r2_safe_write.py:190,205–219`先用全部旧文件做check_capacity，会在C根8261文件>8192且默认2GiB超限时阻止GC。应允许在引用已证明、同锁域、清单安全落盘条件下清理本地无引用文件，随后新增payload仍按原cap/8192/reserve受限。不能通过调大cap、降低reserve或绕过CAS/purge守卫假装修复。若仅保留集合本身仍超预算，继续明确阻止新写，单独处置未决材料。

修改走Claude自己的分支、审查和部署流程。Codex不负责业务修改或生产清理。

## 4. A阶段：只清本地protected候选

1. 在非关键采集/发布窗口，核实际REPO及两个根realpath/device/inode，短暂停止/互斥相关部署rsync、uploader、自愈、人工操作；对两个根按固定顺序使用真实现有storage_lock，保持锁文件inode稳定。文件夹存在或只看FD=0不算充分互斥。
2. 读清单并重算**当前**双根引用：顶层journal、全部nonconfirmed、pending_purge、默认每key最新confirmed、pair递归和new/old SHA，跨根保守引用并集；坏JSON、缺引用、权限不明、symlink或异常文件类型均整批停。HISTORY_KEEP实际值不同须重算。
3. 重新验证7028项每个path/realpath/dev/ino/nlink/size/mtime与快照一致，并确认当前仍无引用。变化时废弃旧计划重算，不能只跳过报错后继续rm。仅允许C根精确清单，D根0候选不碰。
4. 独立保存原始引用JSON、审计清单和修复版本；本次本机报告已有一份取证。对按当前契约已过保留期的终结缓存可在同锁域回收；若业务另有超出当前契约的历史保留要求，先验证已有R2版本或归档相应对象，再从本批放行。**未决材料不以“状态备份成功”替代payload恢复证明**，它们本轮本就保留。
5. 本地-only plan/apply必须不初始化远端写路径、不发PUT/DELETE/purge。先生成只读计划，持久写入本批清单成功后才unlink仍匹配的普通文件。分批且每批重核引用/锁；持久化、空间或身份校验失败零删除。不要调用副作用未审清的业务CLI --dry-run代替本地planner。
6. 记录每批实际移除文件数/allocated、df前后、保留集合完整性和失败列表。阶段A预计7.379833GiB文件块可回收；目录块/自然写入使df不必逐字节相等，偏差须解释。删除但df未释放时先查deleted-open，不扩大范围。

保留目录和永久.gc.lock，禁止rm -rf根目录。禁止删除R2 protected-versions、pair远端对象、D活库、.contexts proof/tombstone、当前发布文件。

## 5. B/C阶段：旧DB按历史版本归档后退役

B先列S/db/sentiment.db、etf_national_team.db、public_fund.db三份同SHA，保留C四库与S/stock_daily；C再评估全部旧库退出。

1. 按代码报告逐条核known production路径：app.db、简报/影子/ledger、完整性检查、ETF/回测/损失特征及模拟交易。正常调用显式指向D的正确主库；主库缺失应明确失败，不能读取旧镜像或sqlite3自动新建空库。手动sync_dev_from_r2目前会写回代码仓，需限制生产误用/改为明确数据目标；静态DB gate维持关闭。不要未经审查把旧库路径软链到活库，可能引入新写入口。
2. 复用已有R2或独立本机，对五个唯一SHA保存历史归档（第一批也应有可验证历史副本，至少保留匹配的C副本）。按SHA命名、流式上传/下载核完整摘要与大小，不仅看ETag/上传成功；archive来源指纹前后稳定。不要在同一根盘再打6.78GiB大包。已有完全匹配的可回读归档可复用，不重复传。
3. 在独立恢复目录取回每个独有旧版，完整SHA一致；只读SQLite quick_check及代表表/日期/行数验证留回执，两个stock分别核验。旧库归档与当前活库备份用途不同；旧版绝不覆盖D活库。若任何版本恢复不通过，只停止对应退役批。
4. 维护窗口下核具体allowlist及其WAL/SHM身份、无读写FD、WAL仍0且journal无内容。精确同卷隔离，可短期回滚以验证未知消费者；隔离路径保持清单映射，**同卷rename不会释放空间**。
5. 用只读路径诊断/隔离输入验证代表链，禁止为清理验收触发真实下单、发送告警或全量生产采集。下一自然调度轮确认无缺库/空库重建、结果仍读D，静态DB继续skipped，部署不重造旧DB。异常则恢复隔离文件，不覆盖活库。
6. 代表链/自然轮和既定回滚观察通过后释放对应隔离文件及已核sidecars，写df回执。B主文件3.218987GiB，三SHM额外98,304B；C全八主文件6.782696GiB，全部SHM额外262,144B。小sidecar不纳入14.16GiB主预算，不能使用*.db*通配。

代码仓tracked的0B trade.db等clone种子、日历/map不在清单中。S整树仍有发布数据和恢复索引，不能整树退役。

## 6. 回退、验证和完成标准

修复前反例已留：GC超配额会在无引用payload删除前拒绝；rsync会复制protected且保留源端已删旧文件。Claude新增/调整后最少验证：

- 超cap/超8192的无引用文件能本地回收；新增写入仍被原配额拦截。
- preparing/prepared/unknown、pending_purge、pair任一保留对象及旧SHA都不删；0.285GiB保守集合保持。
- 坏JSON/缺引用/symlink/文件身份变化/计划后新引用/锁冲突全部阻断删除；清单落盘失败零删除。
- 本地清理无任何远端写请求；普通JSON镜像保留，protected复制为0。
- 两版stock恢复均有证据；缺主库不建空库、不使用旧镜像；业务输出不因清理改变来源。

回退：源码退回审核过的版本；尚在隔离区的旧文件按精确映射放回。已释放历史版本从验证过的归档取回到独立目录校验后再恢复指定旧路径，绝不覆盖当前活库。protected若发现意外需要某个已退役历史，先停止相应写者，用对应已验证远端版本/保留材料恢复；无法证明可恢复的未决材料必须在清理前已被剔除，不能先删后补证。

完成回执须包含：修复commit及云文件hash、前后df、每批计划/实际条数与字节、旧五SHA归档与恢复凭证、保留集校验、下一自然部署/静态备份/采集/自愈轮结果。不要以‘脚本退出0’或‘同卷移走’宣称释放完成；未观察自然轮则标待观察，不能宣称根治。

本方案预计将持续增长入口封住，并提供最多14.162529GiB主文件块回收路径；不是已经释放或未来零告警承诺。

## 7. Claude必须读的证据与清单

- 总算术：`/tmp/codex-reports/storage-cleanup-20261124-space-math.json`
- protected逐项候选：`/tmp/codex-reports/storage-cleanup-20261124-protected-candidates.json`
- protected完整引用分类：`/tmp/codex-reports/storage-cleanup-20261124-protected.json`
- protected说明：`/tmp/codex-reports/storage-cleanup-20261124-protected.md`
- 独立复算：`/tmp/codex-reports/storage-cleanup-20261124-independent-check.json`
- 旧库精确候选及sidecar：`/tmp/codex-reports/storage-cleanup-20261124-old-db-candidates.json`
- 旧库hash/51单位/133进程证据：`/tmp/codex-reports/storage-cleanup-20261124-old-db.json`、同名`.md`
- 源码consumer与修复定位：`/tmp/codex-reports/storage-cleanup-20261124-code-plan.md`
- 源码快照hash与rsync夹具：`/tmp/codex-reports/storage-cleanup-20261124-code-evidence/`
- GC反例夹具：`/tmp/codex-reports/storage-cleanup-20261124-gc-fixture.json`

上述JSON是有时间戳的审查输入，不是可直接pipe给rm的删除脚本。执行时状态有变化应重新生成清单并解释差额。
