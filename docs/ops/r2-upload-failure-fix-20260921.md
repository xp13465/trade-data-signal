# R2 上传失败告警根治(2026-09-21)

> 背景:deploy R2 上传失败告警为噪音。researcher 已查明 root cause=看门狗超时 kill(数据已传完,
> 非上传失败)+周日 verify-r2 全量对账 ~3 万 key 逐个 HEAD 结构性超时 + 大文件单 PUT 卡超时重试放大。
> 本文档=改动+自测+上线步骤(含云上 timer 周日错峰方案说明, 本期不 ssh 改云上)。

## 改动总览(4 项)

| # | 文件 | 改动 | 验收要点 |
|---|---|---|---|
| 1 | deploy.sh + upload_r2.py | 告警降噪:收尾段 R2_FAIL 先跑 `verify-channels` 轻量对账, 数据完整→普通日志不告警, 真缺/verify-r2 自身失败→照常告警 | 真缺文件仍告警 |
| 2 | deploy.sh + upload_r2.py | verify-r2 watchdog 1800→7200; keep-alive 连接复用连续 HEAD | 省 60%+ 对账时间, 周日全量不再超时 |
| 3 | upload_r2.py | >100MB 单文件走 multipart(create→并行 upload-part→complete), 单片 64MiB | md5 一致 / 单 PUT 不破坏 |
| 4 | 方案说明(本档) | 周日大通道错峰到凌晨, 改云上 timer | 不与盘后任务冲突 |

## 改动 1: 告警降噪(核心)

### deploy.sh 收尾段(约 L934)
`R2_FAIL` 非空时不再直接告警, 先:
```bash
"$PY" "$REPO/scripts/upload_r2.py" verify-channels $R2_FAIL > /tmp/r2_verify_channels.log 2>&1
_vc_rc=$?
if [ "$_vc_rc" -eq 0 ]; then
  # 轻量对账全通过 → 普通日志不告警(噪音:看门狗超时 kill, 数据已传完)
else
  # 有缺口 → 照常 --severe 告警(notify 内容附带 verify-channels 详情, HTML 转义)
fi
```

### 新增命令 verify-channels(改动1 落点)
```
upload_r2.py verify-channels [desc...]
```
- desc = deploy.sh R2_FAIL 里的通道描述(`upload-lab`/`verify-r2`/`upload-feed`...)
- 每通道取本地目录 mtime 最新 `_LIGHT_CHECK_SAMPLE=20` 个文件, 逐个 `s3_head`(keep-alive):
  - 小文件(≤100MB):ETag==本地 md5(单 PUT ETag=内容 md5)
  - multipart 大文件(>100MB):存在 + Content-Length==本地 size(multipart ETag=分片组合 non-md5, 不能比对 md5)
- 全部通过 → exit 0(deploy.sh 降级不告警); 任一缺口 → exit 1(照常告警)
- `verify-r2` 本身即对账命令超时, 不做轻量降级(保守保留告警); 不认识通道跳过

## 改动 2: 连接复用 + 窗口放宽

### upload_r2.py keep-alive
- 原 `s3_request`/`s3_head` 每次新建 `HTTPSConnection`(跨境握手 ~1s/次, 周日全量 ~3 万 key 结构性超时)
- `s3_request(..., keep_alive=True)` / `s3_head(..., keep_alive=True)` 走 `threading.local()` 每线程单连接
- 失败/异常时 `_drop_keepalive_conn()` 重建, 防半死连接复用

### deploy.sh watch dog 窗
`run_r2_upload "verify-r2" 1800` → `7200`(与 fund-nav 同档)

## 改动 3: 大文件 multipart

### 阈值与分片
- `_MULTIPART_THRESHOLD = 100MB`(R2 官方:>100MB 建议 multipart; 单 PUT ≤5GiB 但大文件易卡超时)
- `_MULTIPART_PART_SIZE = 64MiB` / `_MULTIPART_WORKERS = 4`(并行)
- 流程:`POST /key?uploads=` → parse UploadId → 并行 `PUT /key?partNumber=N&uploadId=` → `POST /key?uploadId=`+XML complete
- 任一片失败 → `DELETE /key?uploadId=` abort, 错误只重传片不整文件
- multipart 对象 ETag="xxx-N"(non-md5)→ **verify 对账改「存在+Content-Length==本地大小」**判定

## 改动 4: 周日错峰(方案说明, 本期不 ssh 改云上)

### 现状
- 周日 force_full 全量(etf-hist 116MB/fund-nav 577MB/trade_sim 368MB + verify-r2 全量 ~3 万 key HEAD)由 upload_r2.py 内部 `weekday==6` 触发, deploy.sh 无时点判断可改
- 时点全部在云上 systemd timer:17:50 由 `trade-update-all.timer`(OnCalendar=`*-*-* 17:50:00`)触发 update_all.sh → deploy.sh

### 建议方案(云上执行, 需用户拍板后实施)
改 `/etc/systemd/system/trade-update-all.timer` 的 OnCalendar, 让周日全量大通道跑到凌晨带宽低谷:

```
# 原
OnCalendar=*-*-* 17:50:00
# 改(周一到周六维持 17:50, 周日提前到 01:00)
OnCalendar=Mon..Sat 17:50:00
OnCalendar=Sun 01:00:00
```

理由:
1. 周日 01:00 处于带宽低谷(17:50 盘后高峰 + 各盘后任务避让)
2. 与凌晨既有 timer 不冲突(均在 01:00 之前或之后距 ≥1h):
   - trade-backfill-evening 02:00
   - trade-gold-night 02:40
   - trade-public-fund-quarterly 03:00
   - trade-us-stock-morning 05:00
3. 避开盘后定时任务时点 15:35/16:00/17:50/20:35/22:00(§14)
4. update_all.sh 非交易日(周日)默认「跳过采集仅 deploy 补推数据」, 01:00 跑 deploy 全量上传无数据采集依赖, 行为不变
5. upload_r2.py `weekday==6` 判定基于运行当天日期 → 周日 01:00 跑仍命中 force_full, 逻辑无需改

实施步骤(云上, 需用户确认后执行):
```bash
sudo systemctl stop trade-update-all.timer
sudo vim /etc/systemd/system/trade-update-all.timer   # 改 OnCalendar 如上
sudo systemctl daemon-reload
sudo systemctl start trade-update-all.timer
systemctl list-timers trade-update-all.timer           # 验证下次触发
```

> ⚠ 云上 timer 手动管理(git pull 不更新), 改完验证 systemctl 生效即可; 若后续 revert 回 17:50 同样三步。

## 自测记录(2026-09-21)

脚本:`/tmp/r2_rootcause_selftest.py`(开发机跑, 不提交)

| # | 项 | 结果 |
|---|---|---|
| 3 | 130MB 分片→3 片(64/64/2) | PASS |
| 3 | 10MB→1 片(单 PUT 不破坏) | PASS |
| 3 | multipart 调用序列 create→PUT→complete | PASS |
| 3 | complete 请求体含正确的 CompleteMultipartUpload XML | PASS |
| 2 | `_get_keepalive_conn` 两次返回同一连接 / drop 后重建 | PASS |
| 1 | 场景A 单文件判定全通过 → exit 0(降级不告警) | PASS |
| 1 | 场景B lab 通道真实 HEAD 存在差异 → exit 1(照常告警) | PASS |
| 1 | 场景B2 全部 404 → exit 1 | PASS |
| 1 | 仅 verify-r2 → exit 1(不降级) | PASS |
| 1 | 空通道列表 → exit 1 | PASS |
| - | deploy.sh `bash -n` / upload_r2.py `py_compile` | PASS |

> 说明:本机 trade-data/static-site 为滞后开发源(9-19 后未跑 export), 对账生产 R2 天然 mismatch——
> 这验证了「本地滞后 vs R2 = 真缺口 → 该告警」分支; 云上真实场景 deploy 刚跑完、源=上传源,
> 单 PUT ETag==本地 md5, 数据完整 → exit 0 → 降级。两条路径均正确。

## reviewer 返修(2026-09-21, 已并入)

| # | 项 | 修法 | 自测 |
|---|---|---|---|
| D-1 | `cmd_verify_channels` 对非 `upload-` 前缀 desc 直接 continue, verify-r2 也被跳过 → 若同批含 verify-r2+upload 通道全通过 → exit 0 静默缺口 | desc_list 含 `verify-r2` 立即 exit 1(保守保留告警) | 场景E verify-r2+upload 全通过混合 → exit 1 PASS |
| A1 | `_multipart_part_sizes` parts cap 到 10000 后 rem>0 无人校验 → 切片和<文件大小, complete 成功静默截尾 | 循环后 `if rem>0: raise ValueError`(`_upload_one` 的 `except Exception` 捕住记失败) | 场景F 超上限抛 ValueError PASS |
| A3 | `hdrs.get("ETag")` 大小写敏感, 若 R2/网关回小写 `etag` → multipart 永远判失败 abort | 新增 `_header_lookup()` 统一小写比对, `_put_part` 改用 | 场景G 小写/大写/空 dict 全 PASS |

> 自测路径说明:selftest 通过 `spec_from_file_location` 显式加载
> `/Users/linhuichen/code/trade/.claude/worktrees/agent-a87b228ddc79c9e00/scripts/upload_r2.py`(worktree 新代码),
> 非主工作区旧代码;返修后场景 C(仅 verify-r2→exit 1)与场景 E(混合→exit 1)均重跑 PASS。

## 上线步骤

1. 本分支仅含 `scripts/deploy.sh` + `scripts/upload_r2.py` + 本文档
2. `python3 -m py_compile scripts/upload_r2.py` + `bash -n scripts/deploy.sh` 已通过
3. push feat → 主控走 scripts/main-merge.sh(先验云上 .env 是否含备用 R2_UPLOAD_HTTP_TIMEOUT 覆盖)
4. 云上 git pull main 后, 下一次 17:50 update_all 自动生效(周日 force_full 全量对账时间减半+不再超时)
5. 观察 1-2 个周期:收尾不再收到「deploy R2 上传失败」噪音告警; 若收到, 详情里会带 verify-channels 缺口明细(真缺口该处理)

## 参考
- Cloudflare R2 multipart uploads(官方):5MiB-5GiB/part, max 10000 parts, 5TiB 上限, 全片成功才 complete
- verify-r2 设计:docs/kelly/…/r2 层3 防漏传对账(§3.4)