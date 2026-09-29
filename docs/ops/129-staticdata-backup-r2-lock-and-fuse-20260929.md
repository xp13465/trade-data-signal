# #129 staticdata 灾备备份 R2 持锁 10h+ 机制缺陷(P1 熔断/预算已实施, P2 锁分离待排期)

- 日期: 2026-09-29
- 角色: researcher(方案) → implementer(P1 实施) → 独立评审(PASS + 1 行修正, 2026-09-29)
- 状态: **P1 已实施待审**(分支 `fix/r2-large-json-fuse-20260929`, 含评审修正); **P2 仍在待办**
- 评审修正: HEAD 网络失败低于熔断阈值时**降格 `st=404; etag=None` 继续走 PUT**(恢复旧代码「HEAD 失败仍试 PUT」韧性, 瞬时失败可自救, 不无谓 exit 1 造告警噪音; `elif` 改独立 `if` 使降格生效)。详见三.改动点 5/6。

## 一、根因(事故链)

1. `deploy.sh` L952-1000 每次 deploy push main 成功后用 `systemd-run` 异步拉起 transient 单元
   `staticdata-backup-<时点>.service`(无同名 timer,每次触发)。
2. 其 `staticdata_backup_async.sh` L166-176 step3.5b 调 `upload_r2.py upload-large-json`,
   逐文件 gzip 上传 staticdata 备份 git 排除的大 JSON 到 R2 私有桶 `signal-backup/large-json/<日期>/`。
3. 09-29 01:50 合入 `478ab452a`(补 `data/fund_nav`)后清单首次膨胀到 **3.2 万文件**(fund_nav 26458 大头),
   且是首次全量 PUT。弱网下每文件撞 `TimeoutError: _ssl.c:999 handshake timed out`/`RemoteDisconnected`,
   `s3_request`/`s3_head` 最多 5×30s 超时重试 → 单次跑 **10h+ 不结束**。
4. `cmd_upload_large_json` **无整体超时/熔断**;且备份整体被 `with_lock --block-timeout 3600` 包进
   `/tmp/trade_deploy.lock`(**与生产 deploy 同一把锁**)→ 全天 intraday/生产 R2 通道 `SKIPPED_LOCKED`。
5. 事故放大器 = 生产 deploy R2 段有看门狗(900-7200s),灾备无看门狗/熔断,不对称。

## 二、方案(P1/P2, 2026-09-29 21:40 researcher 出)

| 方向 | 结论 |
|---|---|
| ①锁分离(step3.5b 移 trade_deploy.lock 外) | 是 P2, 前提是先有 P1(否则分离后备份无限占 R2 锁更糟); 今晚改 backup_async.sh 结构风险高 |
| ②上传熔断 + 整体预算 | **P1(本实施)**: 只改 `upload_r2.py cmd_upload_large_json` 内部, 不碰锁结构, 风险最小 |
| ④砍 fund_nav 清单 | P2: 需验证 nav_bucket(256 桶)信息量覆盖 fund_nav(26458 同源)后才能砍, 今晚来不及 |
| ⑤触发时机降噪 | P2 可选: 多次 deploy 多次触发; ②让锁内时间有界后触发时机不再是问题 |

## 三、P1 改动点(实际行号, 基于实施后文件)

`scripts/upload_r2.py` `cmd_upload_large_json`(函数体 L2196 起):

| # | 位置(实施后行号) | 改动 |
|---|---|---|
| 1 | L2276 | `s3_head(key, bucket=BACKUP_BUCKET)` → `s3_head(key, bucket=BACKUP_BUCKET, keep_alive=True)` |
| 2 | L2293 | `s3_request("PUT", key, payload, bucket=BACKUP_BUCKET, content_type="application/gzip")` → 追加 `keep_alive=True` |
| 3 | L2239-2253 | 循环前读 env:`R2_LARGE_JSON_BUDGET`(默认 10800s, `float` 非法值回退)/ `R2_LARGE_JSON_FAIL_LIMIT`(默认 30 次, `int` 非法值回退);`_start=time.monotonic(); _fail_streak=0` |
| 4 | L2256-2260 | 每文件开头查**整体预算**:超 → print `预算耗尽, 剩余 N 未传` + `break` |
| 5 | L2277-2287 | `s3_head` 返 `(0,None)`(5 次重试耗尽) → `_fail_streak+=1`, ≥limit → print `熔断` + `break`; **低于阈值 → 降格 `st=404; etag=None` 继续走 PUT**(2026-09-29 评审修正: 恢复旧代码「HEAD 失败仍试 PUT」韧性, 瞬时 HEAD 失败网络恢复时 PUT 自救成功, 不无谓 exit 1 制造告警噪音) |
| 6 | L2288-2293 | `s3_head` ETag 命中(内容未变) → `_fail_streak=0`, 走既有跳过 PUT 成功分支(⚠ **`elif` 改为独立 `if`**(评审修正): Python 中首个匹配分支执行后 elif/else 不再判, 不改则 L2286 `st=404` 的降格永不生效) |
| 7 | L2296-2307 | PUT 抛异常(5 次重试耗尽, `ssl.SSLError/OSError/http.client.HTTPException`) → 捕获计 `_fail_streak`, 不崩整循环, ≥limit → break |
| 8 | L2308-2313 | PUT 200 → `_fail_streak=0`, 走既有成功分支 |
| 9 | L2314-2323 | PUT 非 200 → `_fail_streak+=1`, ≥limit → break(既有 ✗ 打印保留) |

> 行号已按评审修正后文件刷新(修正使 HEAD 分支 +2 行)。

预算/熔断任一触发 → `ok != len(entries)` → 既有 `sys.exit(1)` → `staticdata_backup_async.sh`
`STATICDATA_FAIL=1` → heartbeat fail + `notify --severe`(既有链路, 无需新告警)。
数据已磁盘留档(rsync step1-3), 次日 rsync 全量追平 + `upload-large-json` HEAD ETag 幂等补传,
**灾备第 1/2 层不丢**。

### keep_alive 失败兜底(读代码确认)

`s3_request`/`s3_head` 的 keep_alive 分支已实现**失败自动 drop + 重建 + 5 次重试**(s3_request:
L395 `_get_keepalive_conn()` / L415·L424 `_drop_keepalive_conn()`; s3_head: L479 / L493·L502),
同一连接连续请求复用(线程局部 `_KA_TLS`, L258), 任何失败先 `_drop_keepalive_conn()` 丢弃失效连接,
下一次请求 `_get_keepalive_conn()` 新建 HTTPSConnection, 不影响正确性。该分支已被
verify-r2/层2 对账/multipart 在生产大量使用(L549/L647/L764/L774/L2460 等 `keep_alive=True`),
非新路径。

## 四、自测/验收(P1 实施侧, 2026-09-29)

1. `python3 -m py_compile scripts/upload_r2.py` → **PASS**。
2. 预算分支(fake 仓零 R2 接触, 真实 CLI dry-run):
   `STATICDATA_REPO=/tmp/staticdata-fake-129 R2_LARGE_JSON_BUDGET=0.000000001 ... upload-large-json --dry-run`
   → `⚠ 整体预算耗尽(R2_LARGE_JSON_BUDGET=1e-09s), 剩余 5 未传` + `[dry-run] ... 计划上传 0/5`, exit 0。
3. 熔断分支(monkeypatch harness `/tmp/test_129_fuse.py`, 零 R2 接触, **评审修正后重测**):
   `s3_head` 恒 `(0,None)` + `s3_request` 恒抛 OSError + `R2_LARGE_JSON_FAIL_LIMIT=3` →
   每文件 HEAD+P 各计 1 次失败, 第 2 个文件触发 `⚠ 连续 3 次网络失败(≥R2_LARGE_JSON_FAIL_LIMIT=3), 判定网络劣化, 放弃本轮`,
   `ok=0≠5` → SystemExit code=1(熔断语义保留)。
4. **自救分支(评审修正核心验证)**: `s3_head` 恒 `(0,None)`(瞬时 HEAD 失败)+ `s3_request` 恒 200(PUT 网络已恢复)
   → 5 文件全 PUT 成功, `large-json 上传 5/5`, **无 SystemExit(exit 0)**——「HEAD 失败但 PUT 能成功」不再整轮 exit 1。
5. 成功路径无回归(同一 harness `success` 场景): `s3_head` 恒 404 + `s3_request` 恒 200 →
   5 文件全 PUT 成功, `_fail_streak` 每成功清零, `ok=5=5`, 无 SystemExit(exit 0)。dry-run 默认阈值 → `计划上传 5/5`。
5. 改动只在 `cmd_upload_large_json` 内, 其它 `upload_*` 通道零影响; 生产 deploy 正常路径由明晚 17:50
   update_all 全链回归验证(§8 三查)。

## 五、回滚

改动集中在 `scripts/upload_r2.py` 一个函数, revert 该 commit 即回滚; 无 DB/数据产物变更;
两阈值均 env 可配, 熔断阈值过低误伤偶发波动可直接调大 `R2_LARGE_JSON_FAIL_LIMIT` 不必回滚。

## 六、P2 待办(勿销账, 需主控排期)

- ① 锁分离: `staticdata_backup_async.sh` step3.5b 移出 `trade_deploy.lock`(子 shell/后台独立进程跑
  upload-large-json), 前提 = P1 已让 R2 上传有界; 风险 = 备份占 R2 锁期间生产 R2 段排队(7300s fail-closed),
  可加 `--skip-if-locked` 让灾备抢不到锁就跳过。
- ④ 砍 `fund_nav` 清单: 验证 nav_bucket(桶化脚本输入源)信息量覆盖后, `DIR_EXCLUDES` 或清单去重,
  3.2 万文件 → ~6000, keep_alive 后 ~30min。
- ⑤ 触发时机降噪(可选): 多次 deploy 多次触发可加 dedup(1h 内已跑过则跳过)。
