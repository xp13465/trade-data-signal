# 存储治理 A 阶段执行报告(2026-11-25,云上 C 根 protected 无引用候选清理)

- 执行时间:2026-11-25 12:23–14:40 CST(plan 13:56、apply 14:19:06–14:19:09、删后复核 14:19:18)
- 范围:云上 C 根 `/home/ubuntu/code/trade-data-signal/data/.r2-protected`(代码树);D 根(权威数据根)0 候选、全程未删未改
- 前置已核(12:30/12:56):C 9286 文件 / 10,683,998,208B allocated;D 1047 文件 / 1,221,713,920B;
  云上 `r2_safe_write.py` SHA256=`b307119f…79af5`(两树一致,= 主分支修复版);`deploy.sh:761` 已含 `--exclude=.r2-protected/`;执行窗口无 deploy/uploader 在跑
- 工具:`/tmp/storage-phaseA-planner.py`(云上同份 `/home/ubuntu/storage-governance/phaseA-20261125/storage-phaseA-planner.py`,SHA256=`93bd2ce8…f9765`)
  - 与 `scripts/r2_safe_write.py gc()` 同语义闭包 + 方案 §4.2 两条(全部 nonconfirmed 保守保留、跨根 payload 并集)
  - 双根固定顺序(C→D)`flock` 真实现有 `.gc.lock`(inode 不变),批前逐批复核锁、允许集(新文件出现即暂停该批)、保留集身份
  - 零网络、零远端调用、零外发

## 0. 结论摘要

| 项 | 结果 |
|---|---|
| 释放量 | **8045 文件 / 9,091,342,336B(8.4670GiB allocated)**,df 实测 +9,091,334,144B(差 8,192B=目录块,可解释) |
| 保留集完整性 | **PASS**:C 根保留 1241 路径(含 `.gc.lock`/`gc-manifest.json`)逐项仍在且 dev/ino/nlink/size/allocated/mtime_ns 与冻结清单逐位相同;D 根 1047 文件全部未动 |
| 三态 | 已释放 8045 / 仍隔离 0 / 待验证 0 |
| 异常批 | **无**(17/17 批 status=ok,paused=0,failed=0) |

## 1. 锁内重冻结与昨夜快照对账(第 0 步)

- 13:56:22 双根取锁,13:56:23 冻结清单落盘(durable:临时文件 fsync → rename → 父目录 fsync)
  - 云上:`/home/ubuntu/storage-governance/phaseA-20261125/plan-20261125T1352.json`(2.0MB)
  - 本地副本:`/tmp/storage-phaseA-plan-20261125T1352.json`
- 锁内重算结果:删除集 **8045 项 / 9,091,342,336B**;C 保留 **1241**(= 引用闭包 1083 + 保守 hold 158);D 保留 1047;`problems=[]`
  - 构成:history 4064 / payloads 3972 / pairs 9
- 与 `/tmp/storage-recheck-20261125-candidates.json`(11-25 05:34 快照)逐项对账:
  - **identical 8045 / meta_changed 0 / gone 0 / now_kept 0 / newly_added 0**
  - 即:零身份漂移、零新进引用、零消失、零新增候选;删除集与快照逐位相同(仍以锁内重算为准,未照抄)
- 前置门槛全部通过:坏 JSON 0、缺引用(confirmed 行 payload 缺失)0、symlink 0、非普通文件 0、顶层 journal 文件名身份违例 0、D 根候选 0

## 2. 分批删除回执(每批重核)

| 批 | 项数 | 删除 | 失败 | 状态 |
|---|---:|---:|---:|---|
| 1–8 | 各 500 | 各 500 | 0 | ok |
| 9–16 | 各 500 | 各 500 | 0 | ok |
| 17 | 45 | 45 | 0 | ok |
| 合计 | **8045** | **8045** | **0** | 全 ok |

- 每批前复核:允许集外的**新文件出现**、保留文件缺失/身份变化、批内文件不在 keep 且身份与冻结清单相同 —— 全部 PASS,无批次暂停
- 逐项 unlink 时再核 `S_ISREG + nlink==1 + 身份逐位相同`,才删;失败列表为空
- 批次日志(durable,逐批 fsync):云上 `batches-20261125T1419.jsonl`,本地 `/tmp/batches-20261125T1419.jsonl`

## 3. 空间与文件数前后

| 指标 | 删前 | 删后 | 差额 |
|---|---:|---:|---:|
| df `/` used | 52,733,235,200B(12:56) | 43,688,734,720B(14:20) | -9,044,500,480(含窗口内其他写入,见下) |
| df `/` avail | **7,809,052,672B(7.2727GiB,88%)**(apply 起点) | **16,900,386,816B(15.7403GiB,73%)** | **+9,091,334,144** |
| C 根文件数 | 9286 | **1241** | -8045 |
| C 根 allocated | 10,683,998,208 | **1,592,655,872** | -9,091,342,336 |
| D 根文件数 | 1047 | **1047** | 0 |
| D 根 allocated | 1,221,713,920 | **1,221,713,920** | 0 |

- df 增量与逐项 allocated 相差 **8,192B**(2 个块)在目录/元数据块噪声范围内,无 deleted-open(`/proc/*/fd` 指向 r2-protected 已删文件的句柄 = **0**)
- 12:56→14:19 之间 avail 的差额外来自窗口内正常写入(采集/发布),不属于清理验收口径;验收以 apply 内 df_before/df_after 为准

## 4. 保留集完整性核对(§22/方案 §6)

- 冻结清单保留 C 根 1241 项;删后:
  - 路径集合与删后重算闭包**完全相等**(1241/1241)
  - 逐项身份(dev/ino/nlink/size/allocated/mtime_ns)与冻结值**逐位相同,0 变化**
  - `keep_missing=0`
- 删后**独立**再跑一次只读闭包重算(postcheck):C 根 1241 文件、garbage=**0**、problems=**0**;D 根 1047、garbage=0 —— 即无悬空引用、无坏 JSON、无异常类型
- `gc-manifest.json`(C/D 同为 02:46:22 那份 72,159B rsync 副本)未被改写(本轮不跑业务 GC,不制造"假 manifest")

## 5. 三态区分

| 态 | 文件数 | 字节 | 说明 |
|---|---:|---:|---|
| **已释放** | 8045 | 9,091,342,336 | 真删除(unlink),df 实测 +9.091GB 印证;非同卷移动 |
| **仍隔离** | 0 | 0 | A 阶段无 rename/隔离动作;没有"移走当释放" |
| **待验证** | 0 | 0 | 文件层面无待定项 |

观察项(不属于文件三态,如实列出):
1. **远端恢复性未验证**:按任务书"零外发",本轮未对 R2 做任何 HEAD/GET;候选"无引用"是**本地保留契约**判定(方案 §2/§4.4 原文口径)。恢复通道见 §6,是否逐份可回读尚未核验。
2. **下一自然轮待观察**:下一轮 deploy / 静态备份 / GC / 采集轮次是否零缺库/零重建/零回涨(方案 §6 要求"未观察自然轮则标待观察")。已排除:deploy 已 `--exclude=.r2-protected/`,且本轮删除前 C 根无自有 GC 成功记录。

## 6. 恢复路径(§25④)

- **删除清单与身份**:`/home/ubuntu/storage-governance/phaseA-20261125/plan-20261125T1352.json` 有逐项 `path/dev/ino/nlink/size/allocated/mtime_ns`(payload 文件名即其 sha256);本地副本 `/tmp/storage-phaseA-plan-20261125T1352.json`
- **原始取证**:`/tmp/codex-reports/storage-cleanup-20261125-protected-raw.json`(sha256 `784d473b…b30151`)+ 分类/复算产物(见昨夜复核报告 §7);旧 7028 项快照 `/tmp/codex-reports/storage-cleanup-20261124-protected-candidates.json`
- **远端通道**:protected payload 每次被取代前,旧字节由 `r2_safe_write.prepare()` 写入**备份桶**、内容寻址键 `protected-versions/v1/<bucket>/<key>/<sha256>`(`immutable`,见 `scripts/r2_safe_write.py:506,519`);pair manifest 远端对象 `protected-pairs/v1/<bucket>/<pair_id>.json` 本轮**未删除**。恢复 = 按前缀 `protected-versions/v1/` 列出对象,以路径尾段 `<sha256>` 与清单 `payloads/<sha256>` 匹配取回,再按需恢复对应 history/payload 路径。
- **恢复命令(示意,本轮未执行)**:
  - 列出:`python3 scripts/upload_r2.py recover-protected`(现网恢复入口,只读/定向恢复,`scripts/upload_r2.py:1338`)
  - 取回后校验 sha256 == 文件名,再放回 `.r2-protected/payloads/<sha256>`;**绝不覆盖当前活库/当前发布数据**
- **风险(方案原文口径)**:方案 A 段未要求"删前本地打包备份",原文 §4.1/§4.4 为「对按当前契约已过保留期的终结缓存可在同锁域回收」+「未决材料不以状态备份成功替代 payload 恢复证明,它们本轮本就保留」。故本轮属"按现有本地保留契约回收",可逆性依赖上述备份桶历史版本;**未逐份验证远端存在**——这是本阶段最大的残余风险,须由 B/C 阶段或专门只读核查补齐。

## 7. 偏差与诚实标注

- 与方案唯一偏差:未做"短暂停止/互斥 uploader"的人工停服动作,而是**双根真锁互斥**(uploader `store_many` 同锁域,锁内它无法写);deploy 因机制 1 已排除 protected,且窗口内无 deploy 在跑。删除窗口实际持锁约 **3 秒**(14:19:06–14:19:09)。
- 未验证项:远端 payload 逐份可恢复性;下一自然轮行为;R2 侧对象未动(零外发)。
- 未触碰:D 根、活库、swap、Git、`.contexts/`、当前发布数据、R2 对象、B/C 阶段旧库。
- 云上近 60 分钟日志扫描:`storage lock timeout` / `protected capacity` / `UnsafeWrite` / `R2_PROTECTED_GC` / `missing` 关键字 **0 命中**,无告警副作用。

## 8. 证据文件

- 云上:`/home/ubuntu/storage-governance/phaseA-20261125/{storage-phaseA-planner.py, plan-20261125T1352.json, result-20261125T1419.json, batches-20261125T1419.jsonl, postcheck-20261125T1420.json}`
- 本地:`/tmp/{storage-phaseA-planner.py, storage-phaseA-plan-20261125T1352.json, result-20261125T1419.json, batches-20261125T1419.jsonl, postcheck-20261125T1420.json}`
- 夹具测试:`/tmp/phasea-fixture-test.py`(坏 JSON/symlink/缺引用/新文件/保留文件被改/批内身份变化/正常 7 例)+ `/tmp/phasea-fixture-frozen-test.py`(快照对账漂移)全部 PASS
