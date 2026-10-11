# W1 架构核查报告:CF R2 Local Uploads 可启用性 + 云上 NAT 端口范围(全程只读)

> **残留后台任务声明**:本次仅出现一次 `moved to the background (ID: bkrtg2wo5)`(云上 grep 全树找 R2 环境变量,整条 ssh 超 45s 被转后台),该任务**已完成(exit 0)**、无残留进程;除它之外无其他后台化命令。
> 落档信息(2026-10-11,researcher,W1 只读核查):①报告本体=本文档 ②生成脚本=附录 A(本机桶位置探针)/附录 B(云上读路径探针)③复现段=§四(命令可逐条复跑)④配套 commit=**无**(只读任务,不 commit、不部署、未做任何 git 操作)。
> 任务源:主控派单(方案 v2.1 §2 W1,治本总入口);两核查点出处 = `docs/ops/r2-publish-arch-industry-research-20261005.md` §〇 结论 7 / §七 A4 / §八「未能验证」第 1 条。
> 被挂起的 4 条 A/B 档:#175(断点续传)/ #149④(timer 错峰)/ #239(治本长持锁者分片)/ #129-P2(灾备上传链 P2)。
> **⚠️ 2026-10-11 晚订正(主控实证,LU 落地状态)**:本报告「现状=用户面板操作(或临时开 R2 token)」已改变——用户已提供**两账号** CF API token(老/新账号各一,均账号级 active,经 `/accounts/{id}/tokens/verify` 200 + R2 LIST 实测):**signal-data 实查 `enabled: true`(已启用,开启时间不详)**;**signal-backup2 于 10-11 晚由主控开启**(PUT `enabled:true` + 复查 `enabled: true`;回退=同端点 PUT `false`,一行级)。即「逐账号各做一次」两半均已落地。另注:本机 DNS 对 `api.cloudflare.com` 有污染(解析到假 IP 182.16.62.14+自签证书),本次以 `--resolve` 钉真 CF IP 直连验证(是否钉 hosts 待定)。另:**#149④(timer 错峰)的挂起与本次两核查无耦合**——真实门槛=云上 systemd 写授权(B4b 复核),授权到位即可单独执行,不必等本报告划的 D10 排法。

## 〇、结论先行

| # | 核查点 | 事实结论(明确粒度) | 一句话 |
|---|---|---|---|
| ① | CF R2 Local Uploads 能否启用 | **能启用,三条件全部满足**:(a) 桶非 jurisdiction 受限 —— **已实测核实两桶均为普通桶**;(b) 操作入口 = CF 面板或带 R2 权限的 CF API token(我们现有 S3 key 做不了,`.env` 里也没有 CF API token → 需用户面板操作或新开 token);(c) 接受其 **Beta** 状态(官方文档今日仍挂 Beta 徽章)。**零代码、零附加费、可随时关** | 配置级杠杆成立,先启用 + 前后实测 TTLB |
| ② | 云上 NAT 端口/并发上限 | **不是瓶颈,不构成约束**。实测 **64 并发 / 256 并发出站全部成功(0 失败)**;本地临时端口池 32768-60999(28232 个)、`tcp_tw_reuse=2`(快速复用)、conntrack 模块未加载(本机无表上限);与 docverse#698 **不同构**(GCP 是 64 端口/VM 配额式;本平台实测 ≥256 无耗尽)。真正天花板 = 跨境链路质量 + **单进程 fd=1024** | 分片/续传并发 ≤32/通道安全,单进程 socket <1024 |

**收益预期必须诚实标注(重要)**:官方 75% TTLB 基准场景(WNAM 客户端 + APAC 桶)与本项目**形似但不等价**——本次实测我们云上 VM 的**上行能力是 475KB/s、下行 1.1MB/s**,而 R2 上传实测吞吐 326-390KB/s(#180 注释实测值)≈ 贴住上行能力 ⇒ **大文件墙钟的主瓶颈在「客户端→CF 边缘」跨太平洋段,LU 只省「边缘→桶区(APAC)」段**。⇒ **不承诺 75% 墙钟收益**;小文件/每请求延迟(小对象 GET 实测 0.705s)的收益预期最直接。落地方案内置「启用前/后 TTLB 与单文件耗时对比」观测步。

---

## 一、核查点①:CF R2 Local Uploads

### 1.1 事实结论(能/什么条件下能)

| 判定 | 内容 | 证据 |
|---|---|---|
| **能启用** | 桶级配置(非账号级/非全局),dashboard 一键或 wrangler 一条命令 | 官方文档 §Enable 步骤(见 1.2/C1) |
| 条件 a:非 jurisdiction 桶 | **两桶均满足**。`signal-data`/`signal-backup2` 的 S3 endpoint 都是**无 jurisdiction 段**的 `<account>.r2.cloudflarestorage.com` 形态(受限桶必须走 `<ACCOUNT_ID>.<JURISDICTION>.r2.cloudflarestorage.com`),且两桶 HeadBucket 实测 200、生产上传链一直在用 → 非受限桶 | 官方 data-location 文档(C5)+ 本次实测(1.3) |
| 条件 b:操作入口 | **CF 面板** 或 **wrangler + CF API token(R2 权限)**。两个桶分属**两个 CF 账号**(老账号 `9be954e8…` 持 signal-data;新账号 `24553524…` 持 signal-backup2)→ **逐账号各做一次**。⚠️ 现有 S3 key(access key)只能读写对象,不能开关桶配置;云上/本机 `.env` 均**无** `CLOUDFLARE_API_TOKEN` → 现状=**用户面板操作**(或临时开一个 R2 权限 token) | wrangler PR #11867(API: `GET/PUT /accounts/{account_id}/r2/buckets/{bucket_name}/local-uploads`)+ `.env` 键名清单实测 |
| 条件 c:Beta 状态 | 官方文档侧边栏该项**仍挂 Beta 徽章**(今天 2026-10-11 抓取);无申请/白名单要求(文档直给 Enable 步骤),无附加费 | 文档 HTML 徽章(1.2/C6)+ 定价段(C4) |
| 可回退 | `disable` 随时;在途请求正常完成复制,「no interruption to your traffic」 | 官方文档 Disable 段(C3) |

### 1.2 官方依据(引文 + 链接,均为本次 curl 抓取原文)

- **C1 机制与强一致**(https://developers.cloudflare.com/r2/buckets/local-uploads/):
  > "You can enable Local Uploads on your bucket to improve the performance of upload requests when clients upload data from a different region than your bucket. Local Uploads writes object data to a nearby location, then asynchronously copies it to your bucket. **Data is available immediately and remains strongly consistent.**"
  > "When you make an upload request (i.e. **PutObject and UploadPart**) to a bucket with Local Uploads enabled…" ← **multipart 分片上传明确纳入**
- **C2 jurisdiction 限制**(同页):
  > "Local uploads are **not supported for buckets with jurisdictional restrictions**, because it requires temporarily routing data through locations outside the bucket's region."
- **C3 启用/停用**(同页):dashboard R2 → 桶 → Settings → Local Uploads → Enable;或 `npx wrangler r2 bucket local-uploads enable <BUCKET_NAME>`。停用对称,且:
  > "When you enable Local Uploads, existing uploads will complete as expected with **no interruption to traffic**." / "You can disable local uploads at any time."
- **C4 定价**(同页):
  > "There is **no additional cost** to enable local uploads. Upload requests made with this feature enabled incur the standard Class A operation costs, same as upload requests made without local uploads."
- **C5 读延迟注意点与 jurisdiction 端点形态**(同页 + data-location 页):
  > "Reads from the uploader's region will be fast, while reads from near the bucket's region may experience cross-region latency **until replication completes**."
  > 受限桶 S3 端点必须为 `https://<ACCOUNT_ID>.<JURISDICTION>.r2.cloudflarestorage.com`
- **C6 官方博客**(https://blog.cloudflare.com/r2-local-uploads/,2026-02-03,注:"open beta"):
  > "we saw **up to 75% reduction in Time to Last Byte (TTLB)** when upload requests are made in a different region than the bucket. In these results, TTLB is measured **from when R2 receives the upload request** to when R2 returns a 200 response."
  > 合成基准拓扑原文:"We deployed a test client in **Western North America** and configured an R2 bucket with a **location hint for Asia-Pacific**. The client performed around 20 PutObject requests per second over 30 minutes to upload objects of 5 MB size."(p50 TTLB 约 2s → 约 500ms)—— **注意:该 2s 基准不含「客户端→边缘」段;我们实测上行 475KB/s(→5MB 单对象≈10s+ 量级),故 75% 不能直接套用(详见〇节诚实标注)**
  > "R2 writes to the storage infrastructure located in the **client region** while still publishing to the object metadata to the region of the bucket" + "there's **no waiting period** for background replication to finish before the object can be read."
  > 复制任务细节:"whether the **source should be deleted after successful replication**"(复制完成后本地副本可被回收)
- **C7 官方限制表**(https://developers.cloudflare.com/r2/platform/limits/,LU 不改这些):最大上传 5 GiB(单请求)/ 4.995 TiB(multipart);最大分片数 10,000;同一 key 并发写 1/s;桶管理操作 50/s/桶。**LU 无额外的大小/并发/协议限制条目**(文档未列)= 按普通 R2 限制走。
- **C8 wrangler 命令来源与时间线**:workers-sdk PR #11867「[wrangler] R2-3896 Add R2 local uploads command」**merged 2026-01-30**,命令含 `get/enable/disable`(`get` = 可读当前是否已启用!,走 `GET /accounts/{account_id}/r2/buckets/{bucket_name}/local-uploads`);cloudflare-docs 仓库 `local-uploads.mdx` 首次提交 2026-02-03「LU docs (#27645)」,其后**无 GA 改版提交** → 至今 Beta。
- **社区先例(诚实标注)**:GitHub API 仅检索到官方 PR(#11867,含 14 个单测);**未检索到第三方踩坑/经验帖**(CF 社区论坛对 curl 返回 "Just a moment…" 机器人挑战、搜索引擎索引稀薄、特性较新)→ 结论主要立在官方文档 + 本项目实测上,以「可回退 + 先观测」对冲「无社区交叉验证」的剩余风险。

### 1.3 本项目桶的实测核查(只读)

用自写 SigV4 探针(附录 A,不复用生产脚本)在**本机**对两桶做 `GetBucketLocation` + `HeadBucket`:

```
[signal-data(老账号)]   GetBucketLocation status=200  <LocationConstraint>APAC</LocationConstraint>
[signal-data(老账号)]   HeadBucket status=200
[signal-backup2(新账号)] GetBucketLocation status=200  <LocationConstraint>WNAM</LocationConstraint>
[signal-backup2(新账号)] HeadBucket status=200
```

- **主桶 signal-data 的实际 location = APAC**(研究文档「桶在 APAC」的假设,**实测坐实**);
- **备份桶 signal-backup2 = WNAM**(新账号桶,2026-10-05 由用户新建);
- 两桶都可通过普通(无 jurisdiction 段)端点读写 → **非 jurisdiction 受限桶 → LU 的 jurisdiction 限制不挡我们**(C2 条件满足)。

### 1.4 对本项目现有上传链的适配点(事实核对 + 逐条)

**先纠一个事实**:项目**并未使用 rclone** —— 全仓 grep `rclone` 仅命中 `scripts/r2_upload_async.sh` L71/L112 两处**注释**(引用业界 rclone 超时语义作看门狗判据依据)。上传链 100% 是自研 `scripts/upload_r2.py`(手写 SigV4 over `http.client`)。研究文档 §六里的 rclone 是业界参照,不是项目组件。→ **适配分析只针对 upload_r2.py**。

| 适配点 | 现状事实(文件:位置) | LU 影响 |
|---|---|---|
| 零代码 | LU 是桶级配置,作用于 S3 API `PutObject`/`UploadPart` | **不改任何代码**,`upload_r2.py` 现有 SigV4 请求自动受益 |
| multipart 通道 | `_MULTIPART_THRESHOLD=100MB`(L359)/ `_MULTIPART_PART_SIZE=64MiB`(L360)/ `_MULTIPART_WORKERS=4`(L362);`_upload_multipart` L833;data-large 通道增量引擎 8 线程(L976-1008) | `UploadPart` 明确纳入 LU(C1)→ 每片 commit 由「边缘→APAC 存储」降为「本地写」;data-large/kelly/etf-hist 等大通道全受益 |
| 单 PUT 大文件 | ≤100MB 走单 PUT(+`_ProgressBody` 字节进度,L466-520) | 同 multipart,请求级受益 |
| 上传后对账(verify) | `s3_head` ETag/Content-Length 对账(L644+);marker/ckpt/state 三件(`.r2_<ch>_ckpt.json` 等) | **语义不变**:官方「available immediately + strongly consistent」(C1)→ 上传后立即 HEAD/GET 对账照旧;唯一注意 = 「靠近桶区(APAC)的读者在复制完成前跨区读」——本项目直接读者=云上 VM(在 LAX 侧=uploader 侧,快)+ CF 内部读取(未见文档说明,判低风险);被删掉的本地副本语义(blog C6)意味着**别指望「副本永驻客户端侧」** |
| 连接复用 | 线程本地 keep-alive 已接(#176/#178,upload_r2.py L325 注) | 互补:LU 省 R2 内段,keep-alive 省跨境握手(实测 TLS 握手 1.19s/次) |
| 回退 | — | `disable` 随时、零成本 → 符合 §25 可逆精神 |

### 1.5 风险与诚实标注

1. **Beta**:官方仍标 Beta(1.2/C8)→ 行为/参数有变动的窗口期;对冲 = 零成本 + 随时 disable + 先观测再依赖它做架构决策。
2. **收益幅度**:**不承诺 75%**。官方 75% 的 TTLB 口径**从「R2 收到请求」起算**(不含客户端→边缘段);我们实测该段是本项目主瓶颈(上行 475KB/s、TLS 握手 1.19s)。预期:小对象/每请求延迟收益明确(小对象 GET 实测 0.705s 里含跨区成分),大文件墙钟收益待实测。
3. **残余未知(1 个,必须观测解决)**:「客户端 region」的精确归类规则官方未文档化 —— 中国客户端算 APAC(≈不生效)还是按请求落地的边缘算(实测落 LAX ⇒ 非 APAC ⇒ 生效)无法从文档判定。**双路验证**:①dashboard → R2 → 桶 → Metrics → **Request Distribution** 看我们写请求的区归属;②启用后实测单文件耗时/TTLB 前后对比。
4. 复制完成时延无 SLA(文档没给数字)→ verify 流程不受影响(强一致),但对「近桶区读者」的读数窗口无法承诺具体时长。

### 1.6 启用操作路径(给主控/用户拍板用,本次核查未执行任何启用动作)

1. **用户面板(推荐,最快)**:dashboard → R2 → 选 `signal-data` → Settings → **Local Uploads → Enable**;顺手在同一页核对该桶 Location 处**没有** "Specify jurisdiction";再开 Metrics → Request Distribution 存图(留启用前基线)。备份桶 `signal-backup2`(另一账号)同法可选做(非关键路径)。
2. **工具路径(可选)**:开一个带 R2 权限的 CF API token → `npx wrangler r2 bucket local-uploads enable signal-data`;查状态用 `... get signal-data`(PR #11867 的 get 命令,可验证是否已启用——现有 S3 key 读不了这个状态)。
3. **观测(启用后 3-5 天)**:对比 ①`upload-large-json`/data-large 通道单文件耗时(现有日志已含逐文件输出与进度行)②小对象 HEAD/PUT 耗时 ③官方 TTLB 口径(dashboard 指标)。
4. **回退**:同路径 Disable(随时、不影响在途)。

---

## 二、核查点②:云上 NAT 端口范围与并发连接上限

### 2.1 事实结论

- 云上 VM 的**本地临时端口池 = 32768-60999(28,232 个,无 reserved 段)**;`tcp_tw_reuse=2`(TIME_WAIT 快速复用)→ 本地侧端口**极充裕**。
- `nf_conntrack` 模块**未加载**(`/proc/sys/net/netfilter/*` 不存在)→ 本机无连接跟踪表上限;**连接跟踪在腾讯云公网 NAT(网关侧)**,本机不可见。
- **实测并发**:64 并发 → 64/64 成功;256 并发 → 256/256 成功(**零失败、零超时**)。
- **单进程 fd 上限 `ulimit -n` = 1024** ← 这是「单进程能握多少 socket」的真实天花板(不是 NAT)。
- 平台侧公开限值:腾讯云**公网 NAT 网关**文档口径「同一协议/目的 IP/目的端口,连接数上限 = 绑定的 EIP 数 × 55000」(该页为 SPA,curl 抓不到正文,引文来自检索通道=**二手**,见 §五诚实标注);CVM 单实例层面**未找到**更小的公开文档限值,且实测 ≥256 与 55000 量级差距巨大 → 对我们**无实际约束**。
- **与 docverse#698 同构性判定:不同构**。GCP Cloud NAT 默认 64 端口/VM 是「每 VM 配额」式硬限制(90 并发即耗尽);本平台实测 256 并发毫无压力 + 本地端口池 28k ⇒ **#698 的 64 端口场景不可套用本项目**。

### 2.2 本机内核事实(命令 + 输出,均可复跑)

```
$ ssh … "sysctl net.ipv4.ip_local_port_range; sysctl net.netfilter.nf_conntrack_max; …"
net.ipv4.ip_local_port_range = 32768	60999        # 28,232 个本地端口
sysctl: cannot stat /proc/sys/net/netfilter/nf_conntrack_max: No such file or directory   # conntrack 模块未加载
net.ipv4.tcp_fin_timeout = 60
net.ipv4.tcp_tw_reuse = 2                            # TIME_WAIT 端口快速复用(出站)
net.ipv4.ip_local_reserved_ports =                   # 空,无保留段
$ … "ulimit -n; cat /proc/sys/fs/file-max"
1024                                                 # ← 单进程 fd 上限 = 真实并发天花板
9223372036854775807
$ … "ip route / ss -s / cat /proc/net/sockstat"
default via 10.0.0.1 dev eth0 … src 10.0.0.11        # 私网 10.0.0.11/22 → 公网 122.51.111.173 经 NAT
TCP: inuse 6 … tw 0                                  # 稳态下连接数极低
$ … "nstat -az | grep -E 'TcpAttemptFails|TcpRetransSegs|TcpOutSegs|AbortOnTimeout'"
TcpAttemptFails       94089                          # 历史建连失败累计
TcpOutSegs            145482262
TcpRetransSegs        8621385                        # 重传率 ≈ 5.9%(!)跨境链路质量差旁证
TcpExtTCPAbortOnTimeout 6484                         # 超时中止(重传耗尽)累计
```

实例元数据:`ins-9kbwuuip` / `ap-shanghai-5`(**CVM**,不是 Lighthouse;公网 IP 经 NAT 映射,私网 10.0.0.11)。

### 2.3 实测并发探针(64 / 256)

方法:对 R2 端点(anycast,未认证请求会得到 400——**能拿到 400 即证明 TCP+TLS+HTTP 全通**)并行建连,数响应码分布。单命令用 `seq | xargs -P`(无 `$` 变量、无副作用、只建连):

```
$ seq 1 64  | xargs -P 64  -I{} curl -s -o /dev/null -w '%{http_code}\n' --max-time 15 https://<老账号>.r2.cloudflarestorage.com/ | sort | uniq -c
     64 400
$ seq 1 256 | xargs -P 256 -I{} curl -s -o /dev/null -w '%{http_code}\n' --max-time 20 https://<老账号>.r2.cloudflarestorage.com/ | sort | uniq -c
    256 400
# 爆破后 TCP 状态:timewait 198-200 个(快速复用,tcp_tw_reuse=2);无异常堆积
```

### 2.4 与 docverse#698 的对照表

| 维度 | docverse#698(GCP) | 本项目(腾讯云上海 CVM) | 判定 |
|---|---|---|---|
| 平台 NAT 形态 | Cloud NAT,**默认 64 端口/VM**(配额式) | 公网网关 NAT;公开口径 NAT 网关 = EIP×55000,单机未见小限值 | 不同构 |
| 实测耗尽点 | 90 并发即 ConnectTimeout | **256 并发 0 失败** | 不同构 |
| 本地端口池 | 64 | 28,232 | 量级差 |
| 修复参数 | 并发≤32 + keep-alive + min_ports_per_vm=4096 | 无需调端口;并发≤32 同样合理 + keep-alive(项目已有) | 措施可借鉴 |

### 2.5 真实瓶颈与定参建议(给 #175/#239/#129-P2 用)

本次实测的链路画像(云上 VM ↔ CF):

| 指标 | 实测值 | 出处 |
|---|---|---|
| TCP connect 到 R2 端点边缘 | 0.157s(另一次 0.31s) | `curl -w '%{time_connect}'` |
| **TLS 握手**(跨境握手成本) | **1.19s**(appconnect−connect) | 同上 |
| 边缘 colo(VM 落点) | **LAX**(两桶端点同为 LAX) | cf-ray 响应头 |
| 上行能力(→CF 边缘,隔离测) | **475 KB/s**(3MB POST speed.cloudflare.com) | `curl -w '%{speed_upload}'` |
| 下行能力(CF 边缘→) | 1.11 MB/s(10MB GET) | `curl -w '%{speed_download}'` |
| R2 读路径:小对象 GET(19B) | 0.705s(含跨区 + 跨境) | 附录 B 探针 |
| R2 读路径:LIST 1000 key(218KB) | 2.07s ≈ 105KB/s | 同上 |

**定参建议**:
- 分片/续传**单通道并发 ≤ 32**(8-16 更稳),全站总并发登记上限 **256-512**(256 已实测安全);
- **单进程 socket 总数 < 1024**(fd 限制,按「每进程」计,别按总数算);
- 长连接复用优先(已在用);每请求新连接的跨境成本 = TCP+TLS ≈ 1.3s/次(实测);
- TIME_WAIT 无需治理(tcp_tw_reuse=2);若将来真需要,可把 `ip_local_port_range` 上限扩到 65535(本次只读不动)。

---

## 三、对 4 条 A/B 档的解锁意义

| 条目 | 原先挂起逻辑 | 本次核查给出的事实 | 解锁结论 |
|---|---|---|---|
| **#175 断点续传(A4)** | 是否值得做,取决于「跨境是否结构性慢」;若 LU 能一举提速则 A4 优先级下降 | ①LU **能启用且零成本** → 先启用(配置级先试)②但 LU 只覆盖 R2 内段,**kill→全量重传的成本主项(客户端→边缘 475KB/s 段)不受 LU 改变** ③NAT 不挡续传分片 | **先启用 LU(观测);A4 仍有独立价值**(看门狗 kill→marker→全量重传的振荡语义问题不因 LU 消失),但可按观测到的提速幅度**重排优先级**;分片重试并发 ≤32 无平台障碍 |
| **#149④ timer 错峰** | 被列入「被两核查挂起」清单,但其真实挂点 = 云上 systemd 写授权 | 本次两核查**对该条无直接耦合**(它既不需要 LU 也不吃 NAT 参数) | **诚实标注**:该条状态**不因本次核查变化**,仍是「缺云上 systemd 写授权」;建议主控把它的挂起原因从「等两核查」修正为「等授权」(若主控原判有误请以本表纠正) |
| **#239 治本长持锁者分片** | 分片(长持锁者拆并行)可行性 = 有没有足够并发连接/端口 | **256 并发实测 0 失败**;本地端口 28k;唯一登记点 = **单进程 fd 1024** 与总并发上限 | **解锁**:分片方案(多进程/多线程并行上传/对账)不受 NAT/端口约束;落地时登记「单进程 socket <1024、总并发 ≤256-512」两行即可 |
| **#129-P2 灾备上传链 P2** | 2.6 万小文件灾备上传的痛点既有「长跑持锁」也有「每文件跨区请求」;P2 计划是锁分离/砍清单/降噪 | ①**小对象每请求跨区延迟大**(小对象 GET 0.705s、LIST 205KB/2.07s 实测)→ LU 对「每请求 commit 本地化」收益最直接 ②并发无平台障碍(分片上传 2.6 万文件可行) | **解锁 + 建议重排**:先启用 LU(配置级、零代码)→ 观测 `upload-large-json` 每文件耗时是否显著下降 → 再决定 P2 里「砍 fund_nav 清单/并行分片」的必要性与优先级 |

---

## 四、复现段(命令可逐条复跑)

```bash
# ②-A 云上内核事实(只读)
ssh -i /Users/linhuichen/tdsignal.pem -4 -o ConnectTimeout=10 ubuntu@122.51.111.173 \
  "sysctl net.ipv4.ip_local_port_range; sysctl net.netfilter.nf_conntrack_max; sysctl net.ipv4.tcp_tw_reuse; ulimit -n; ip route; ss -s"
# ②-B 并发探针(64/256;把 <EP> 换成 R2_S3_ENDPOINT 的 host)
ssh … "seq 1 256 | xargs -P 256 -I{} curl -s -o /dev/null -w '%{http_code}\n' --max-time 20 https://<EP>/ | sort | uniq -c"
# ②-C 隔离测速(客户端↔CF 边缘)
ssh … "curl -s -o /dev/null --max-time 40 -w 'down=%{speed_download}B/s\n' 'https://speed.cloudflare.com/__down?bytes=10000000'"
ssh … "head -c 3000000 /dev/zero | curl -s -o /dev/null --max-time 40 -X POST --data-binary @- -w 'up=%{speed_upload}B/s\n' https://speed.cloudflare.com/__up"
# ②-D R2 端点延迟/colo
ssh … "curl -s -D - -o /dev/null --max-time 15 https://<EP>/ | grep -i cf-ray"
# ①-A 桶 location(本机,读 .env 凭据,只读)
python3 /tmp/w1_probe_r2.py        # 脚本=附录 A
# ①-B 云上读路径计时(经 ssh stdin 管道执行,不落盘云上)
ssh … "python3 -" < /tmp/w1_probe2_cloud.py   # 脚本=附录 B
```

## 附录 A:桶位置探针(/tmp/w1_probe_r2.py,本机运行,只读)

```python
#!/usr/bin/env python3
# 只读探针: GetBucketLocation + HeadBucket(不写任何对象)。自含 SigV4, 不执行生产脚本。
import hashlib, hmac, http.client, ssl, datetime, urllib.parse
def parse_env(path):
    d = {}
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k, v = line.split('=', 1); d[k] = v.strip().strip('"').strip("'")
    return d
def hm(k, msg): return hmac.new(k, msg.encode(), hashlib.sha256).digest()
def hh(k, msg): return hmac.new(k, msg.encode(), hashlib.sha256).hexdigest()
def sign_key(ds, sk):
    k = hm(("AWS4" + sk).encode(), ds); k = hm(k, 'auto'); k = hm(k, 's3'); k = hm(k, 'aws4_request'); return k
def req(method, ep, bucket, ak, sk, query=''):
    u = urllib.parse.urlparse(ep); host = u.netloc; path = '/' + bucket
    now = datetime.datetime.utcnow(); amz = now.strftime('%Y%m%dT%H%M%SZ'); ds = now.strftime('%Y%m%d')
    ph = hashlib.sha256(b'').hexdigest()
    headers = {'host': host, 'x-amz-date': amz, 'x-amz-content-sha256': ph}
    si = sorted(headers.items()); ch = ''.join(f'{k}:{v.strip()}\n' for k, v in si); sh = ';'.join(k for k, _ in si)
    cr = '\n'.join([method, path, query, ch, sh, ph]); scope = f'{ds}/auto/s3/aws4_request'
    sts = '\n'.join(['AWS4-HMAC-SHA256', amz, scope, hashlib.sha256(cr.encode()).hexdigest()])
    headers['authorization'] = f'AWS4-HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={sh}, Signature={hh(sign_key(ds, sk), sts)}'
    ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")   # macOS 系统 CA 束
    conn = http.client.HTTPSConnection(host, timeout=15, context=ctx)
    conn.request(method, path + ('?' + query if query else ''), headers=headers)
    r = conn.getresponse(); data = r.read(); conn.close()
    return r.status, data
# 用法要点: GetBucketLocation 的 query 必须写成 'location='(带等号,与 R2 canonical query 对齐,否则 403 SignatureDoesNotMatch)
env = parse_env('/Users/linhuichen/code/trade/.env')
for label, ep, bk, ak, sk in [
    ('signal-data', env['R2_S3_ENDPOINT'], env['R2_BUCKET'], env['R2_S3_ACCESS_KEY_ID'], env['R2_S3_SECRET_ACCESS_KEY']),
    ('signal-backup2', env['R2_BACKUP2_ENDPOINT'], env['R2_BACKUP2_BUCKET'], env['R2_BACKUP2_ACCESS_KEY_ID'], env['R2_BACKUP2_SECRET_ACCESS_KEY'])]:
    st, body = req('GET', ep, bk, ak, sk, query='location=')
    print(f'[{label}] GetBucketLocation status={st} body={body[:200]!r}')
    st, _ = req('HEAD', ep, bk, ak, sk)
    print(f'[{label}] HeadBucket status={st}')
```

## 附录 B:云上读路径计时探针(/tmp/w1_probe2_cloud.py,经 `ssh … "python3 -" < 脚本` 执行,不落盘云上)

要点(完整脚本与 A 同构,省略重复段):读 `/home/ubuntu/code/trade-data/.env`,①`GET ?list-type=2&max-keys=1000` 计时(tcp_connect / req_resp / 字节数)②解析 `<Contents>` 取最小对象,再 `GET` 该对象计时。关键输出:

```
LIST status=200 tcp_connect=0.306s req_resp=2.408s bytes=217890
GET accum_nav/158030.json status=200 size=19 tcp_connect=0.311s req_resp=0.705s
```

---

## 五、诚实标注(已验证 / 未验证 / 推断)

**已验证(有直接证据)**:
- 官方文档/博客全部引文(本次 curl 实抓 HTML 后本地解析,非记忆复述);文档 Beta 徽章、wrangler PR #11867、docs 仓库提交时间线(GitHub API 实查)。
- 两桶 location(signal-data=APAC / signal-backup2=WNAM)与「非 jurisdiction 端点形态」— 实测命令+输出见 §1.3/附录 A。
- 云上内核参数、ulimit、实例元数据、并发探针 64/256 零失败、测速 475KB/s / 1.11MB/s、R2 读路径计时 — 全部实测输出贴于 §二。
- 项目上传链事实:rclone 未使用(grep 仅 2 处注释)、multipart 参数(L359/360/362)、keep-alive、对账流程。

**二手/推断(已标注)**:
- 腾讯云「NAT 网关 55000/EIP」引文:来自检索通道(官方页 552/12955 是 SPA,curl 与 jina 代理均未取到正文)→ **二手,仅作量级参考**;但我方结论主判据 = 本地实测(256 并发 0 失败),不依赖该引文。
- 「中国客户端在 LU 的 region 归类」= 推断有分歧(LAX 边缘实测 ⇒ 倾向「不同区、生效」;文档未定义)→ 列为残余未知,双路验证方案见 §1.5。
- 「LU 的全站小文件/大文件收益幅度」= 待实测(本次给出的是瓶颈分解,不是 LU 前后对比)。

**未验证(本次未做/做不了)**:
- LU 当前是否已启用:S3 key 读不了桶配置读(此前 GetBucketLifecycleConfiguration 403 是旁证),需 dashboard 或 `wrangler … local-uploads get`。
- 256 以上并发上限(受单进程 fd=1024 与探针成本约束;对设计量级已足够)。
- R2 复制完成的具体时延(文档无 SLA)。
- 第三方社区经验(检索通道受限,见 §1.2 末条)。

## 六、维度自检表

| 维度 | 覆盖 | 位置 |
|---|---|---|
| 官方文档层(启用/限制/定价/一致性) | ✅ | §1.2 C1-C7 |
| 官方博客层(75% 基准/机制/region) | ✅ | §1.2 C6 |
| 社区/第三方先例层 | ✅(诚实:未检索到第三方帖) | §1.2 末条 |
| 本项目实测层(桶 location/jurisdiction 形态) | ✅ | §1.3 |
| 适配层(逐通道/multipart/verify/回退) | ✅ | §1.4 |
| 风险与收益诚实标注(LU 收益幅度分解) | ✅ | §1.5 + §〇 |
| 平台侧限值层(NAT 官方口径) | ✅(二手标注) | §2.1/§2.4 |
| 探针层(并发 64/256/测速/读路径) | ✅ | §2.2-2.5 |
| 同构性判定层(docverse#698) | ✅ | §2.4 |
| 定参层(给 4 条 A/B 的具体数字) | ✅ | §2.5/§三 |
| 复现层(命令+脚本) | ✅ | §四+附录 |

(全文完,2026-10-11;只读核查,未 commit/未部署/未改云上任何配置。)
