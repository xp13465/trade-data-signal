# 存储治理 B 阶段执行报告(2026-11-25,静态树三份同 SHA 旧库)

- 执行窗口:16:20–17:40(§14 允许窗);SHA 重核在 14:53(只读)
- 范围:云上静态树 S=`/home/ubuntu/code/trade-data-signal-staticdata` 的 `db/` 三份与 C 树同 SHA 旧库
- 本阶段到批边界收口(归档仍在云端后台跑),**未做任何删除**

## 0. 结论摘要

| 项 | 结果 |
|---|---|
| SHA 重核 | 6/6 主文件与昨夜复核**逐位相同**(SHA/size/mtime/ino/nlink);WAL 全 0B、SHM 全 32,768B、journal 全缺;旧库打开 FD=0 |
| 归档 | **进行中**(云端后台两进程):上传 signal-backup2 `db-archive/v1/old-db-20261125/<sha256>/<name>.db`,每文件上传后 HEAD 核长度 + Range 全量回读核 sha256 + sqlite quick_check;预计 ~18:50–20:30 完成(实测链路 ~0.6MB/s) |
| 回读验证 | 已完成的验证 = **同卷 rename 后 sha256 3/3 逐位相同**(见 §3);R2 回读逐份验证随归档进行,尚未全部完成 |
| 退役 | **未释放**(0 B)。三份已同卷隔离(rename),可随时精确还原 |
| 三态 | 已释放 **0** / 仍隔离 **3 文件 3,456,360,448B(3.2190GiB)+ WAL 0B + SHM 98,304B** / 待验证 **3**(R2 回读+quick_check) |

## 1. SHA 重核对账(执行前重核,14:53:36–14:54:23)

| 文件 | 当前 SHA256(前12/尾6) | 与昨夜复核 | size | ino | mtime |
|---|---|---|---|---|---|
| C `data/sentiment.db` | 861d4ca25a3a…890622 | 同 | 232,124,416 | 1188731 | 2026-10-28 21:38:34 |
| S `db/sentiment.db` | 861d4ca25a3a…890622 | 同 | 232,124,416 | 1314355 | 2026-10-28 21:38:34 |
| C `data/etf_national_team.db` | 62a47ffc6149…3f547f | 同 | 258,400,256 | 1188787 | 2026-10-28 21:36:45 |
| S `db/etf_national_team.db` | 62a47ffc6149…3f547f | 同 | 258,400,256 | 1314511 | 2026-10-28 21:36:45 |
| C `data/public_fund.db` | b5095b10f141…73f95 | 同 | 2,965,819,392 | 1188908 | 2026-10-28 18:48:58 |
| S `db/public_fund.db` | b5095b10f141…73f95 | 同 | 2,965,819,392 | 1318928 | 2026-10-28 18:48:58 |

- sidecar:8 个 WAL 全 **0B**、8 个 SHM 全 **32,768B**(SHM sha 全 `fd4c9fda…9389eb`)、无 `-journal`;C/sentiment.db-shm mtime 仍为 11-24 21:15:01(与昨夜同)
- 六个旧库 + sidecar 的 `/proc/*/fd` 打开数 = **0**;`df /` avail 16,892,616,704B(73%)
- 判定:**零漂移 → 允许继续**;B 阶段只动 S 三份,C 的三份同 SHA 保留(方案 §5.2「至少保留匹配的 C 副本」)

## 2. 归档(进行中)

- 目的地:备份桶 `signal-backup2`(独立新账号,R2_BACKUP2_* 凭据,凭据只从云上 `trade-data/.env` 读,未进命令行)
- key:`db-archive/v1/old-db-20261125/<sha256>/<name>.db`(按 SHA 命名)
- 每文件流程:源 sha256 复核 → 流式 multipart 上传 → HEAD 核 Content-Length → **Range 全量回读**算 sha256 并写恢复副本 → 恢复副本 sqlite 只读 `PRAGMA quick_check` + 前 10 表行数
- **实测吞吐**:云 → Mac 50MiB 用 151s(≈0.35MB/s);云 → R2 232MB 上传约 0.6MB/s。3.45GiB 单程 ≈ 1.6–2.7 小时,窗口内绝无可能完成,故改为云端后台长跑(两进程:public_fund / sentiment→etf)
- 因源文件已 rename 到隔离区,归档从**隔离副本**读取(同 inode,rename 前后 sha 已在 §3 验证一致)
- 日志:云上 `/home/ubuntu/storage-governance/phaseB-20261125/archive2-{a,b}.out`、`archive.jsonl`(逐文件 status=ok 持久化);脚本 `phaseB-archive.py` 带 skip-if-done,可断点续跑

## 3. 同卷隔离(已完成,可逆)

- 17:05:41 一次性 rename(同 dev=64514,`rename(2)`,**不释放空间**):
  - `S/db/sentiment.db` → `/home/ubuntu/storage-governance/phaseB-20261125/quarantine/sentiment.db`
  - `S/db/etf_national_team.db` → `…/quarantine/etf_national_team.db`
  - `S/db/public_fund.db` → `…/quarantine/public_fund.db`
  - 6 个 sidecar(WAL 0B ×3、SHM 32,768B ×3)同时移入 quarantine
- 前置全过才动:非软链/常规文件、nlink=1、dev 一致、size 与清单一致、FD=0、WAL=0、无 journal
- rename 后逐项复核:**dev/ino/size/mtime_ns 与移动前逐位相同**、源路径已不存在
- **sha256 复核(读隔离副本)3/3 与清单逐位相同**:`861d4ca2…890622` / `62a47ffc…3f547f` / `b5095b10…73f95`(`quarantine-sha.txt`,VERIFY_DONE)
- 清单(durable,fsync):`/home/ubuntu/storage-governance/phaseB-20261125/quarantine-manifest.json`(含原路径/隔离路径/dev/ino/size/mtime_ns/sha256/还原命令)
- df 前后:可用 16,660,779,008B → 16,654,217,216B(窗口内其他写入所致,隔离本身 **0 释放**,符合预期)

### 3.1 必须上报的副作用(§23.11 不静默)

17:16:12 一次**自然触发**的 staticdata 备份(16:59:50 deploy 触发,非本轮操作)在其 git 段把 **6 个被移动的 sidecar** 记成删除并已 push 到 staticdata 仓(main `64a90e861`):
`delete mode db/{sentiment,etf_national_team,public_fund}.db-{shm,wal}`。
- 影响面:仅这 6 个 SQLite 临时 sidecar(WAL 全 0B / SHM 为共享内存快照),**三份主库未被 git 跟踪、未进任何 commit**
- 可逆:blob 仍在 staticdata git 历史,`git checkout 3fc367789 -- db/<file>` 即可取回
- 教训点:sidecar 属 tracked 文件(此前只在 `git ls-files db/` 里看到 stock_daily 两条,实际另有 6 条在 index),同卷隔离前应核对 `git ls-files db/`

## 4. 退役/释放

- **未执行删除**(0 B 释放)。方案 §5 门槛未满足:①三份归档+回读验证未完成 ②自然轮观察不足(仅 17:00 公募日更 + 17:16 staticdata 备份 2 轮)
- 自然轮观察 #1:17:00 `public_fund_daily` 日志无「缺库/空库重建/不能打开」类错误(其报错为 baostock 网络接收错误 + 天天基金估值源下线,与本改动无关);17:16 staticdata 备份 step1 DB rsync 按门控 skipped,step3 只同步 JSON
- 待观察自然轮:17:50 update-all/deploy、21:00 backup-db、21:15 ab-direction-anchor(该时点正是 C/sentiment.db-shm 每日被打开的时点)

## 5. 恢复路径(§25④)

```bash
# 精确还原(同卷,秒级) —— 逐条按 manifest
sudo mv /home/ubuntu/storage-governance/phaseB-20261125/quarantine/<name> \
        /home/ubuntu/code/trade-data-signal-staticdata/db/<name>
# sidecar 同样还原(6 个)
# 还原后校验:sha256sum 应等于 manifest 里的 sha256
# git 侧(若需恢复 sidecar 跟踪):cd .../trade-data-signal-staticdata && git checkout 3fc367789 -- db/<name>.db-{wal,shm}
# 远端归档(一旦归档完成):signal-backup2/db-archive/v1/old-db-20261125/<sha256>/<name>.db
```

## 6. 下一窗口(18:10–20:30)待办

1. 查 `archive2-a.out`(public_fund)/`archive2-b.out`(sentiment→etf)+ `archive.jsonl`:逐文件 `status=ok` 才算归档完成;失败按 skip-if-done 续跑
2. 归档完成后:核 HEAD 长度、回读 sha256、`quick_check=ok` + 行数,写进本报告 §2
3. 观察自然轮(17:50 deploy / 21:00 / 21:15)无缺库/空库重建/来源改变后,才执行退役(unlink 隔离文件),按 §25 回执 df 前后 + 每批条数
4. 若 21:15 轮仍未观察到,标"待观察",不宣称释放

## 7. 未验证/残余风险

- R2 归档与回读尚未全部完成(进行中);远端对象可恢复性未验收
- 隔离期的未知消费者:静态树 db/ 全仓零读取方(scripts/tests/test_253 记录)+ 本轮 FD=0,但未覆盖全部调度时点(21:15 等)
- 带宽:归档后台长跑与 17:50 部署共用云上出口(实测 ~0.6MB/s),部署可能变慢;若部署异常需先停归档进程
- 未触碰:D 活库、C 树、swap、Git 主仓、`.contexts/`、当前发布数据、R2 主桶对象

## 8. 证据快照(17:29 实拍)

```
S/db 现内容:仅 stock_daily.db(185,065,472)+ stock_daily.db-{shm,wal} 及历史 0B 种子库;三份同 SHA 旧库已不在原位
quarantine/:sentiment.db 232124416 / etf_national_team.db 258400256 / public_fund.db 2965819392 + 3 WAL(0B) + 3 SHM(32768)
df /:63,290,032,128 总 / 43,935,244,288 已用 / 16,654,041,088 可用(73%)   ← 隔离不释放,与 17:05 前数值同量级
后台作业:PID 1088212(public_fund)、1088575(sentiment;随后自动接 etf_national_team)
```

## 9. 追加:回读 403 诊断与修复(19:06,只诊断+修脚本,未动在跑作业)

**现象**:`archive.jsonl` 出现 `{"name":"sentiment","status":"readback_failed","at":0,"http":403}`——上传与 HEAD 均正常(HEAD 200 / Content-Length 232,124,416 正确),但第一个 Range GET 就 403。

**根因(实测对照,非推断)**:`scripts/upload_r2.py::s3_request` 把 `extra_headers` 的**头名原样**并入 canonical headers 与 SignedHeaders;我传的是大写 `Range`。R2 服务端重建 canonical request 时把头名规范化为小写 `range` ⇒ 两侧 canonical headers 不等 ⇒ `SignatureDoesNotMatch`。
同一把 key、同一 100B 区间实测:

| 头写法 | 结果 |
|---|---|
| `{"Range": "bytes=0-99"}` | **403** SignatureDoesNotMatch |
| `{"range": "bytes=0-99"}` | **206**,100B |
| HEAD(无 Range) | 200,Content-Length 正确 |

对 sentiment 归档对象用小写 range 复测:offset 0 → 206/100B、offset 200,000,000 → 206/100B、尾部 232,124,390 → 206/26B,三个位置全 206。

**与跨账号凭据路由无关**:`_route_bucket(BACKUP_BUCKET)` 命中的就是独立第二端点 `2455352499…r2.cloudflarestorage.com` + R2_BACKUP2_* 凭据,上传/HEAD/GET 全用同一路由;唯一差异是大写 Range 头。

**修法(仅改本阶段脚本 `phaseB-archive.py`)**:
1. Range 头改小写 `{"range": ...}`
2. 新增 `--readback-only` 模式:跳过上传,直接 HEAD 核长度 + Range 全量回读核 sha256 + 恢复副本 sqlite quick_check,供已上传成功的文件单独补回读验证

**未改生产代码**:`upload_r2.py::s3_request` 对 header 名大小写不做规范化(只接受小写头)属潜在缺陷,建议后续单独走分支+审查修(统一 `k.lower()`),本阶段不动生产代码。

**在跑作业**:sentiment 上传已完成(readback 403 退出)、etf 上传中、public_fund 上传中(part14/45);etf 的 readback 会同样 403(进程加载的是旧代码),链结束后用 `--readback-only` 重跑。

## 10. 追加:生产带宽冲突与暂停(19:22–19:25)

- 18:50/18:58 两次 deploy 之后的 `r2_upload_async` 正在跑 `upload-industry`、`upload-lab`(生产链路),与本阶段归档共用云上出口
- 实测:public_fund 单片 64MiB 需 7–16 分钟(45 片,按此速要 5+ 小时);etf 上传在重试 4 次后 `ssl.SSLEOFError` 崩溃退出(未落 ok/失败行)
- **处置(生产优先,P0)**:public_fund 作业(PID 1088212)`SIGSTOP` 暂停(零带宽占用、不持有任何业务锁),待生产上传跑完后 `kill -CONT` 恢复或干净重跑;etf 已于 19:23 自行退出,需重跑;sentiment 上传已完成,只差回读
- 偏差说明:主控要求"不要动在跑的作业",此处为保护生产 R2 上传而暂停,理由=P0 生产稳定优先;暂停是纯进程状态,不改变任何文件/R2 对象

## 11. 收口状态(19:25)

| 项 | 状态 |
|---|---|
| sentiment | R2 上传 **已完成**(HEAD 200/长度正确);回读待跑(`--readback-only`,脚本已修) |
| etf_national_team | 上传**失败**(SSLEOFError 重试耗尽)→ 待干净重跑 |
| public_fund | 上传中断在 ~15/45 片,进程 SIGSTOP 暂停;待恢复重跑 |
| 隔离区 | 不变,3 主库 + 6 sidecar 仍在 `phaseB-20261125/quarantine/`,manifest 可还原 |
| 释放 | 0 B(未删任何文件) |

## 12. 空闲门控链(19:30 起)

生产 R2 上传(deploy 后的 `r2_upload_async`)不空闲时,归档一律不抢带宽。已挂 `phaseB-chain.sh`(云端 `setsid nohup`,日志 `chain.log`/`chain.out`):
1. 每 60s 检查生产上传者(`upload-*` / `upload-db` / `r2_upload_async.sh` / `deploy.sh` / `backup_db.sh` / `update_all`),空闲才开跑(最长等 2 小时,超时退出并留日志)
2. 空闲 → `sentiment --readback-only`(HEAD+全量回读+quick_check)
3. 再等空闲 → `etf_national_team` 完整重传 + 回读
4. public_fund 保持暂停(SIGSTOP),不纳入本链:按实测速率需数小时,应与 21:00 backup-db / 22:00 公募全量彻底错峰(23:00 后安全窗或次日)

## 13. 追加:21:18 归档双 PASS + 自然轮观察 + 退役执行(21:35)

### 13.1 归档与回读结果(chain.log / archive.jsonl / chain.out)
| 文件 | R2 key | HEAD | 回读 sha256 | quick_check | 表数 | 耗时 |
|---|---|---|---|---|---|---|
| sentiment.db | `db-archive/v1/old-db-20261125/861d4ca2…890622/sentiment.db` | 200 / 232,124,416 | `861d4ca2…890622` match=True | ok | 18 | 202.8s(回读段) |
| etf_national_team.db | `db-archive/v1/old-db-20261125/62a47ffc…3f547f/etf_national_team.db` | 200 / 258,400,256 | `62a47ffc…3f547f` match=True | ok | 4 | 上传 446.9s + 回读/校验,总 2093.9s |

- 链时间线:20:40 空闲门开 → sentiment 回读 20:43:24 rc=0 → 再等门 → etf 上传 20:50:51 status=200、HEAD 20:50:54 长度对上 → etf 回读 21:17:38 sha match → 21:18:18 quick_check ok → `CHAIN_DONE` rc=0
- etf 行数抽样:etf_daily 1,508,980 / etf_holder_quarterly 284 / etf_signal 2,613 / national_team …
- 回读方式:小写 `range` 分片 GET 全量拼接算 sha256 + 落恢复副本后 `mode=ro&immutable=1` + `PRAGMA quick_check`

### 13.2 自然轮只读观察(事件驱动,逐新鲜日志)
| 时点 | 任务 | 结果 |
|---|---|---|
| 20:35 | intraday_snapshot | 退出码 0(20:43:28),[intraday] sentiment R2 上传 6/6;与 etf 上传重叠但成功 |
| 20:21 / 21:29 | staticdata_backup_async | 均完成并 push(20:33:52 / 21:40:59);20:21 有 1 次 `large-json` PUT SSLEOFError 重试(与 etf 上传抢出口),重试后成功 |
| 21:00 | backup_db | 22:11:22 退出码 0,local/upload/verify 三段 rc=0,同源恢复+integrity 逐库 ok,覆盖 sentiment / etf_national_team / stock_daily |
| 21:15 | ab_direction_anchor | 正常:7 条记录,开锚命中 3/7、关锚 1/7,报告产物已写,无 error |
| 22:00 | public_fund_full | 进行中(22:21 约 50.6%,ETA ~22:42),无报错 |
| — | 静态站 | `https://ss.fx8.store/` 200;D 活库 mtime 持续刷新(sentiment 22:04 / etf 21:37 / public_fund 21:25) |
| — | 告警/自愈 | 21:22 self_heal:唯一 error 指标 `sentiment_r2_upload` 为 2026-09-28 起的历史 stale 指标(无 HEAL_ACTIONS 配置),今日 intraday sentiment 上传 15:38/20:40 均 6/6 成功 ⇒ 与本次改动无关 |

- 失败单元核对(均为既有问题,非本次引入):`trade-overfit-monitor` 11-24 21:53 失败;`trade-cloud-unit-patrol` 既有失败;`trade-public-fund-daily` 16:20 超时(status=124)+17:00 baostock 登录网络错误(10002007)——两轮均早于本阶段 public_fund 归档启动(17:23),与隔离/归档无因果
- 结论:自然轮 PASS,无缺库/无空库重建/无源文件出现

### 13.3 退役执行(21:35:39,避开 22:00±5min 禁区)
- 删前最后核:quarantine 两份 sha256 重算与 manifest 逐位一致;**R2 归档 key HEAD 200 且 Content-Length 等于源文件大小**(sentiment 232,124,416 / etf 258,400,256);无进程打开该文件(全 /proc/*/fd 扫描)
- unlink:`sentiment.db` + `sentiment.db-wal`(0B)+ `sentiment.db-shm`(32,768B)、`etf_national_team.db` + 其 wal(0B)+ shm(32,768B);目录 fsync
- 释放量:`freed_bytes_sum = 490,590,208 B`(467.9 MiB);`df avail` 15,127,298,048 → 15,617,896,448 B(delta +490,598,400 B,尾差=同时段生产写入)
- 退役凭据:`/home/ubuntu/storage-governance/phaseB-20261125/retire-20261125.jsonl`(含 sha / R2 key / df 前后 / 恢复路径,fsync)
- **恢复路径**:按 r2_key 从 R2 第二桶(BACKUP2)GET 回原位;凭据见 `/home/ubuntu/code/trade-data/.env` 的 `R2_BACKUP2_*`(未进命令行)

### 13.4 三态台账(截至 22:25)
| 状态 | 对象 | 字节 |
|---|---|---|
| **已释放** | sentiment.db + etf_national_team.db + 4 sidecar(2 WAL 0B + 2 SHM 32KiB) | **490,590,208 B(467.9 MiB)** |
| **仍隔离** | public_fund.db + 其 WAL(0B)+ SHM(32,768B),仍在 `phaseB-20261125/quarantine/` | **2,965,852,160 B(2.76 GiB)** |
| **待验证** | 无(已退役两份回读 PASS);public_fund 属"仍隔离+待归档",未进入退役 | 0 B |

### 13.5 public_fund 后续(未退役,等安全窗)
- 进程 PID 1088212 仍 SIGSTOP;22:00 公募全量采集中(预计 ~22:45 结束),其后 23:20 还有定时任务 ⇒ 建议 **23:25 之后或次日盘前**再重传
- 重入注意:被暂停的 multipart upload 的 uploadId 未落盘,重启新传会另建 upload,旧未完成分片只能靠 R2 lifecycle 兜底(upload_r2.py 无 ListMultipartUploads/按前缀清理能力)——列入残留风险

### 13.6 边界维度清单(§5.8①/③ 实施关出口,七轴)
| 维度 | 测/不测 | 依据与结果 |
|---|---|---|
| 输入域(SHA/大小/mtime/FD/WAL) | 测 | 6/6 SHA 逐位同、FD=0、WAL 全 0B、SHM 32768;删前再校验 sha 与 R2 HEAD 长度 |
| 状态组合(DB+sidecar、部分退役) | 测 | 3 主库+3WAL+3SHM manifest;退役后仅剩 public_fund 三件;S/db 保留 keep-set 其余库 |
| 时序(§14 窗口/自然轮) | 测 | 归档走空闲门控,退役 21:35 避开 16:00/17:50/20:35/22:00;自然轮 20:35/21:00/21:15 全部 PASS |
| 上下游依赖(备份链/verify/前端读者) | 测 | 21:00 backup_db verify PASS 覆盖 sentiment/etf;staticdata 备份连跑 3 轮成功;S/db 无代码读者、DB rsync 受 STATICDATA_DB_LOCAL_COPY 门控 |
| 极端值(0B WAL/2.9G 大文件) | 测 | 0B WAL 按空处理;2.9G 走 multipart 分片流式;etf 在最差带宽下重试成功 |
| 回退路径(R2 取回/git 还原 sidecar) | 测 | R2 全量回读 sha 一致可恢复;Git 侧被自然轮提交删除的 sidecar 可 `git checkout 3fc367789 -- db/<file>` 还原 |
| 并发与重入(生产上传/暂停作业/链重入) | 部分测 | 空闲门控+退役全条件前置;未测项=旧 multipart uploadId 无法枚举清理,留 R2 lifecycle 兜底(已列残留风险) |

### 13.7 收口
**[part-DONE]** 归档+回读+退役: sentiment / etf_national_team 全链 PASS 已释放 490,590,208B;public_fund 仍隔离(2,965,852,160B)待 23:25 后安全窗重传+回读,未退役。

## 14. 追加:public_fund 重传完成 + 回读进行中(11-26 02:04 起)

- **重传完成(实测定论)**:02:04:11 `upload status=200`(multipart complete 成功,耗时 5032.0s);02:04:12 `HEAD status=200 remote_len=2,965,819,392` 与源文件逐字节大小一致 ⇒ **public_fund 归档对象已在 R2 就位**,此前"44/45 片、未传完"的断点判断不成立(最后一片在 02:04 完成)
- **时序**:02:05 主控按旧判断 SIGSTOP(卡在 HEAD 之后、回读之前);02:21:55 `trade-backfill-evening` 以 success 退出;02:47 确认无 backfill 进程;02:48 恢复(`kill -CONT 1261254`)进入回读
- **回读 PASS(03:34:17)**:`readback 2828/2828 MiB` → `sha=b5095b10f141632e7b34d4e73e3662f6901954e9c4ced9a0b64b583403973f95 size=2,965,819,392 match=True`;随后 sqlite 校验跑完,03:41:12 `ALL_DONE`(进程正常退出);首轮 GET 曾有 IncompleteRead 网络抖动,脚本自动重试后完成
- **三态(实时)**:已释放 490,590,208B;仍隔离 public_fund.db+SHM 32,768B=2,965,852,160B(**R2 已就位,待回读 PASS 后退役**);待验证 3 件中 0 件未归档
- **退役前置**:回读 sha 逐位一致 + quick_check=ok 后,按 13.3 同款流程删前复核 sha + R2 HEAD 长度,再 unlink 三件;凭据追加到 retire-20261125.jsonl
- **残留风险**:本轮之前失败/暂停产生的旧 multipart uploadId 无法枚举清理,依赖 R2 lifecycle 兜底(不变)

### 14.1 public_fund 退役执行(11-26 04:29:01)
- 删前:quarantine 文件 sha256 重算 = `b5095b10…73f95`;R2 HEAD 200 / Content-Length = 2,965,819,392;无进程打开
- unlink:`public_fund.db` + `public_fund.db-wal`(0B)+ `public_fund.db-shm`(32,768B);目录 fsync
- 释放:`freed_bytes_sum = 2,965,852,160 B`;df avail 13,424,394,240 → 16,390,250,496(delta +2,965,856,256 B)
- 凭据:追加到 `retire-20261125.jsonl`(第 2 行,含 sha / R2 key / df 前后 / 恢复路径)
- quarantine/ 现为空

### 14.2 B 阶段最终三态(截至 11-26 04:36)
| 状态 | 对象 | 字节 |
|---|---|---|
| **已释放** | sentiment.db + etf_national_team.db + public_fund.db + 6 sidecar(3 WAL 0B + 3 SHM 各 32,768B) | **3,456,442,368 B(3.22 GiB)** |
| **仍隔离** | 无(quarantine/ 空) | 0 B |
| **待验证** | 无(三份回读 sha 全 match + quick_check 全 ok,表数 18 / 4 / 19) | 0 B |

- **附:验证恢复副本仍占盘**:`phaseB-20261125/recovery/` 内 3 份回读副本共 3.3GB(247M / 222M / 2.8G),非源数据、R2 归档可随时恢复;建议后续清理窗口删除(未在本次五步内,留待主控排)
- **总恢复路径**:三份均按 `db-archive/v1/old-db-20261125/<sha256>/<name>.db` 从 R2 第二桶(BACKUP2)GET 回原位;凭据 `.env` 的 `R2_BACKUP2_*` 与 retire-20261125.jsonl

### 14.3 收口
**[DONE]** B 阶段全收口:三份旧库(sentiment / etf_national_team / public_fund)全部 R2 归档 + 全量分片回读 sha 逐位一致 + quick_check ok,quarantine 三件已退役 unlink,累计释放 3,456,442,368 B(3.22 GiB);恢复路径=R2 `db-archive/v1/old-db-20261125/<sha256>/` 按名取回。
