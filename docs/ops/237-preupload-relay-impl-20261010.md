# #237 覆盖前备份护栏修复 —— 实施报告(本期只做 A+D,不开 C)

- 日期: 2026-10-10(周六,休市)
- 分支: `feat/237-preupload-relay`
- 依据: `docs/ops/237-r2-overwrite-backup-guard-design-20261009.md`(设计文)+ `docs/ops/preupload-copy-rootcause-20261008.md`(根因文)
- 基线核对: 开工 `md5(scripts/upload_r2.py) == bc0a646905d24c462e473852582d2a09` **PASS**(不符即停下上报,见设计文 §5 锚点前提)

---

## 0. 一句话结论

跨账号服务端 COPY 换成**客户端中转**(老账号 GET → 校验 → 新账号 PUT → 回读校验),护栏从
「100% 失效且不可观测」变成「**实测真落地 + 机器可观测**」:真实规模 256 key / 536 MiB 备份段
实测 **copied=256 / skipped=0 / failed=0 / 186.0s**,R2 只读 LIST 独立复核**落地 256 == copied**
(§5.2-7 对账一致)。同时 D①(凭据缺失 fail-loud)+ D③(当日存活观测进 15min 巡检)一并落地。
**C(阻断)一行未加,retention 未动,看门狗未动**。

---

## 1. 改动清单(file:line,行号为改后)

| # | 文件:行 | 改动 | 级别 |
|---|---|---|---|
| 1 | `scripts/upload_r2.py:1138-1330`(`_backup_overwritten_keys` / 内嵌 `_backup_one`) | COPY 段整体替换为 **P1~P6**;失败改 `failed += 1` + 结构化样本;返回 `(copied, skipped, failed, samples)` | A 主体 |
| 2 | `scripts/upload_r2.py:1533-1545`(L5 调用点 `_incremental_upload`) | 接住 4 元组 + 打结构化行 `[label] 备份完成 copied=X skipped=Y failed=Z`;异常路径打 `failed=-1`;**全程不阻断**(无 raise / 无 sys.exit / 无 `failed>0` 分支) | A 配套 |
| 3 | `scripts/upload_r2.py:404-424`(`_route_bucket`) | **D①**:`BACKUP2_BUCKET` 凭据缺失 ⇒ `RuntimeError`(不再静默回退老账号);老账号桶回退语义不变 | D |
| 4 | `scripts/upload_r2.py:833-870`(`_upload_multipart`) | 新增可选 `bucket=` 并透传到 4 处 `s3_request`(create/part PUT/abort/complete)。**不改就等于把大文件备份写到主桶**(潜伏正确性缺口,已修) | A 配套 |
| 5 | `scripts/upload_r2.py:283-285 / 531-535` | 注释同步:删「env 缺失→回退老账号」的过时兼容说明;`extra_headers` 注记 COPY 已从 L5 移除 | 一致性 |
| 6 | `scripts/check_preupload_backup.py`(**新增**) | **D③** 当日存活观测巡检(dry 默认 / `--notify` 入聚合队列) | D |
| 7 | `scripts/schedule_monitor.sh:2912-2946` | 把 D③ 挂进既有 15min 巡检链(紧随 check_s06_freshness 块,同族写法) | D |
| 8 | `scripts/tests/test_237_preupload_relay_pytest.py`(**新增**,12 例) | A/D① 的 static-only 单测 | 测试 |
| 9 | `scripts/tests/test_237_check_preupload_backup_pytest.py`(**新增**,18 例) | D③ 判定口径/通道/端到端 dry/零外发单测 | 测试 |
| 10 | `scripts/tests/test_212_upload_onfail_loud_pytest.py:167`、`scripts/test_204_etfscore_loud.py:104` | 打桩跟随新返回契约(4 元组)。**原打桩返回 None ⇒ 调用点解包抛 TypeError 被 except 兜成 `failed=-1`** 的同类面,已修 | 同类面 |

未动(有意): `_PREUPLOAD_RETENTION_DAYS = 7`(`:1088`)、`scripts/r2_upload_async.sh`(看门狗)、无新增 systemd unit。

---

## 2. P1~P6 落地映射(设计文 §4.2(a)/§4.3 逐条对照)

| 环节 | 设计判据 | 实现(改后行号) |
|---|---|---|
| P1 源 HEAD | `st==200` 取 `etag_s`/`size_s`;非 200 ⇒ 无覆盖必要跳过(现状语义) | `s3_head(key, bucket=BUCKET, with_len=True)`;`st!=200 → return`(不计 failed) |
| P2 减量 | `bk_st==200 且 etag==local_md5` ⇒ skipped | 保留 #176 判据原样 |
| P3 GET 源体 | `gst==200` 且 `len(body)==size_s` | 短读/非 200 ⇒ `_fail(key,"GET",…)` |
| P4 源 md5 | 单 PUT:`md5(body)==etag_s`;multipart 源(etag 含 `-`)只比长度 | `src_multipart = "-" in etag_s` |
| P5 PUT 目标 | `<100MB` 单 PUT(新账号);`>=100MB` `_upload_multipart(bucket=BACKUP_BUCKET)` | 两分支都带 `bucket=BACKUP_BUCKET` |
| P6 目标回读 | 单 PUT `etag_t==md5(body)`;multipart `Content-Length==len(body)` | `s3_head(backup_key, bucket=BACKUP_BUCKET, with_len=True)`;含「PUT 200 但没落地」兜底 |
| 汇总 | 返回 4 元组 + 前 5 条样本进日志 | 样本上限 50(锁保护),调用点打前 5 条到 stderr |

并行/减量不回归: `ThreadPoolExecutor(max_workers=8)` + 64-key 进度行原样保留;备份段整体仍在
`_upload_glob`(真 PUT 批)之前 ⇒ §25「整批备份完 → 整批 PUT」语义不变。

---

## 3. 自验:设计文 §5.2 七条逐条证据

### 3.1 ① 同构对账(PASS)
真实规模一轮(`nav_bucket/` 256 key)后 R2 只读 LIST:
`copied=256` / `PREUPLOAD landed=256` ⇒ **对象数 = 期望覆盖数 − 减量跳过数 = 256 − 0**,逐位一致。
对账命令见 §5 复现段。

### 3.2 ② 对照矩阵 4 场景(PASS,12 例单测)
- (a) 正常 key ⇒ `(1,0,0,[])` 且发生 GET + PUT 到 `pre-upload/<今日>/<key>`(`test_scenario_a_normal_copied`)
- (b) 已备同内容 ⇒ `(0,1,0,[])` 且 **GET/PUT 均为 0 次**(减量不回归,`test_scenario_b_skip_when_backed_and_same`)
- (c) 源缺失 ⇒ `(0,0,0,[])`,**不误报 failed**(`test_scenario_c_source_missing_not_failed`)
- (d) 失败四形态 ⇒ 均 failed + 样本完整:`d1 GET 短读` / `d2 PUT 403` / `d3 PUT 200 但未落地(P6 兜住)` / `d4 源 md5 不一致`
- multipart 源(ETag `abc123-2`)⇒ 只比长度、不误判(`test_multipart_source_len_only`)
- 返回值契约(含空输入 `(0,0,0,[])`)与 8 线程/减量判据/无 `x-amz-copy-source` 调用(`test_return_contract_empty` / `test_parallel_and_dedup_kept`)

### 3.3 ③ 失败语义(第一阶段=PASS)
- 上传照常: 调用点 ±窗口静态核 —— 无 `raise` / 无 `sys.exit` / 无 `failed>0` 分支(`test_call_site_structured_line_and_non_blocking`);异常路径也只打 `failed=-1` 行后继续。
- 结构化日志: `[label] 备份完成 copied={_bc} skipped={_bs} failed={_bf}` 字面量在位(同例)。
- **真实通道实证**: 实测轮 `failed=0`、samples 空;失败形态由 (d1~d4) 打桩覆盖。
- 第二阶段(C)证据链**未触发**: C 未开 ⇒ 无「PUT 批未发生 / marker 清理 / severe 实发」三项(属设计文 §4.4 顺序硬约束,见 §7)。

### 3.4 ④ 看门狗时长实测(休市日真实规模,结论见 §4)

### 3.5 ⑤ §22 无回归(PASS)
pre-upload 是**私有回滚层**,不属任何展示位数据源 ⇒ 无 N 文件+N 缓存同步动作(设计文 §4.5)。
主数据上传路径的键集/内容/顺序未改: 备份段是 `_upload_glob` **之前**的独立段,只改该段**内部**
实现(COPY→中转),`_upload_glob` 调用签名与批内容零改动(L1538 备份 → L1554 `_upload_glob`,同前)。
本地全量回归(CI 等价命令 `pytest -q scripts/tests/`,并按 CI 情形置空 `R2_BACKUP2_*`):
**提交后复跑 = 669 passed / 2 skipped / 0 failed**(提交前那 1 例 failed 见 §6.2 = 脏工作区固有前提,提交态自动 skip)。

### 3.6 ⑥ 门控(无半开开关,PASS)
- 代码级零 C: 调用点无任何 `failed>0` 判断(单测卡住该字面量)。
- 观测点不半开: `check_preupload_backup.py` 默认 dry(**不 notify**),只有 `--notify` 才入聚合队列;挂载点显式传 `--notify`(生产)⇒ 语义确定,无「有时发有时不发」的开关态。

### 3.7 ⑦ R2 只读 LIST 实证(PASS)
`pre-upload/20261010/` 实测前 `n=0`(干净基线)→ 实测后 `n=256` → 自清后 `n=0`。
对象数与日志 `copied` 对账一致(§3.1),**不采信日志自证**。

---

## 4. 真实规模备份段时长实测(§5.2-4 必做)

| 项 | 值 |
|---|---|
| 场景 | `nav_bucket/` **256 key / 536.0 MiB**(设计文 §4.1 点名的「fund-nav 256 个 key 是大头」场景) |
| 结果 | `copied=256 skipped=0 failed=0` |
| 备份段墙钟 | **186.0 s**(含源 HEAD + 备份桶 HEAD + GET + PUT + 回读 HEAD 全链,8 线程) |
| 单 key 均值 | **0.727 s/key** |
| 落地复核 | R2 LIST `landed=256` == copied |
| 基线对照 | 老 COPY 实现同场景因跨账号 404 为**零落地**(护栏能力 0) |

**看门狗闸评估(不建议本期动 `r2_upload_async.sh`,按 §5.1 改点 6「未实测前不动」):**

- 现行看门狗 = **停滞判据**(日志 mtime 超 `R2_UPLOAD_STALL_SECS`,默认 900s;若与
  `R2_UPLOAD_HTTP_TIMEOUT+300` 倒挂则自动抬到后者)+ **低速判据**(仅认 `[N/M]` 方括号 +
  `(sizeB)` 字节形态的批内行,且批 >10、5×60s 采样 <1MiB)+ **7200s 总时长硬闸**。
  (设计文 §4.5 写的「900s 总时长硬闸」是 10-05 事故期的旧表述,以代码为准。)
- **实测 186s = 900s 停滞阈的 20.7%**,且备份段每 64 key 打一行进度(**无方括号、无字节**⇒
  不触发低速判据误杀,同时持续刷新"有输出"⇒ 停滞判据放行)。**PASS,无需调闸**。
- 外推云上: 云上跨境带宽(~1.2-1.6 Mbps 级)比本机慢 ⇒ 同规模备份段可能达 **数十分钟级**,
  仍远低于 7200s 硬闸;若某日 `force_full`+多通道叠加贴近停滞阈,届时**由实测数据再议**
  (本报告不改闸,避免无实测依据的调参)。

---

## 5. 复现命令(本次实测用的只读/自清通道)

```bash
# 基线核对
md5 -q scripts/upload_r2.py            # 期望 bc0a646905d24c462e473852582d2a09(改前)

# 单测(static-only,零外发)
python -m pytest -q scripts/tests/test_237_preupload_relay_pytest.py \
                    scripts/tests/test_237_check_preupload_backup_pytest.py

# 真实规模备份段实测(nav_bucket 256 key;测试对象跑完自清)
#   见本报告 §7 残留清理记录;脚本曾用 /tmp/meas237_relay.py(临时,未入库)
#   R2 LIST 对账: pre-upload/<YYYYMMDD>/ 对象数 == 日志 copied
```

---

## 6. §23.2 同类错误面 + §23.3 举一反三(同模式/同数据源/同组件扫描)

### 6.1 §23.3 同模式扫描清单(逐项覆盖结果)

| 同模式对象 | 扫描结果 | 处置 |
|---|---|---|
| 全仓 `x-amz-copy-source` / `CopyObject` 调用点 | **仅剩 3 处注释/docstring**,无任何活的 COPY 调用(`grep -rn` 见 upload_r2.py:531/534/1139) | 无需改(已无实现面) |
| `_backup_overwritten_keys` 调用方 | 生产仅 `upload_r2.py:1538` **一处**(其余为测试打桩) | 改点 2 单点收口 |
| `_route_bucket` 调用方 | `upload_r2.py:545`(s3_request)/`:654`(s3_head)两处,均按 `bucket=` 参数路由 ⇒ D① 对全部桶操作生效 | 覆盖 |
| 同「第二套端点/凭据」登记点 | `r2_upload_async.sh:73`(事故注释)、`restore-r2-backup.sh:19`、`check_r2_channel_coverage.py:32` 均为**说明性文字**,无重复常量副本;桶名单一事实源 = `upload_r2.py` | 无漂移 |
| 同「静默回退老账号」模式 | `_route_bucket` 是唯一回退点(旧代码「BACKUP2_HOST=None → 全部回退老账号,不崩」);`upload_r2.py:283` 过时注释已同步删除 | 已修 + 注释对齐 |
| `_upload_multipart` 其他调用方 | `_upload_glob`(主桶,不带 bucket ⇒ 默认主桶,语义不变)与新备份段(带 `bucket=BACKUP_BUCKET`) | 新增参数向后兼容,老调用零影响 |
| 观测点同族(巡检挂载) | 同族 = `check_s06_freshness.py`(schedule_monitor 子进程调用、`--tier warning` 入聚合队列、`notify_sent` 判落签)。D③ 完全复用该形态,**不新增 systemd unit**(避免云上/snapshot 双源漂移,main-merge `--check-doc` + `cloud_unit_patrol` 比对会挡) | 复用既有链 |
| 同类「备份先于覆盖」其他通道 | 15 条通道**全部**经 `_incremental_upload` 的 L5 段 ⇒ 单点修复覆盖全部(设计文 §3.2 通道全景) | 全覆盖 |

### 6.2 §23.2 同类错误面清单(逐项自测结果)

| 同类错误面 | 症状/风险 | 自测结果 |
|---|---|---|
| 测试打桩未跟随新返回契约 | `test_204_etfscore_loud.py`(返回 `None`)/`test_212_upload_onfail_loud_pytest.py`(`lambda: None`)⇒ 调用点解包 4 元组抛 TypeError,被 except 兜成 `failed=-1` 假失败行 | **已修**为返回 4 元组;两文件重跑 **43 passed** |
| `_upload_multipart` 无 `bucket` 参数 | ≥100MB 备份会写到**主桶**(静默错桶) | 已加参数并透传 4 处签名;单测 multipart 分支覆盖 |
| `_list_keys` 对非 200 **吞掉返回 []** | 观测点把 R2 临时不可达误判成「护栏空转」假 FAIL ⇒ 巡检自身抖动惊动用户 | D③ 先做 `max-keys=1` 探针,非 200 ⇒ `RuntimeError` ⇒ exit 2 **不告警**(`test_count_landed_probe_failure_raises`) |
| 「用候选数判空转」的假阳面 | 首次全量上传:源侧 404 = 无备份必要 ⇒ copied=skipped=0 且 landed=0,用候选数判会**每周首次全量必假 FAIL** | 判定改「日志自称(claimed) vs R2 实见(landed)」矛盾才报(`test_judge_all_new_keys_no_alarm`) |
| 「只有进度行(无 完成 行)」的在飞窗口 | 15min 巡检撞上在飞备份段 ⇒ 假 FAIL | 归 NO_RUN **不判定**(`test_judge_progress_only_is_no_run_not_false_alarm`) |
| `failed=-1`(备份段整体异常早退)被判成「0 失败」 | 观测点漏报 | 判据 `failed != 0`(不是 `> 0`)(`test_judge_failed_minus_one_fails`) |
| 观测点进度行正则污染看门狗低速判据 | 方括号/字节形态被 `r2_upload_async.sh` 当批内行 ⇒ 误杀 | 正则只认 `备份 N/M 已备份 …`,显式断言不匹配 `[N/M] (sizeB)`(`test_progress_regex_does_not_match_watchdog_bracket_form`) |
| 唯一未过项(**与本次改动无关,已实证自愈**) | `test_212::test_e_pre_change_source_static` 在**脏工作区**下 FAIL | 该测试假设「工作区要么干净(skip)要么只含 #212 未提交改动」;本分支未提交态 ⇒ `git show HEAD:` 取到的不是改前版。**提交后 `HEAD==工作区` ⇒ 自动 skip**(提交后实测: 该例 `1 skipped`;全量 669 passed / 2 skipped / 0 failed);CI(提交态)不受影响(设计缺陷已在 §9 登记,不在本任务范围) |

---

## 7. 未做项与残留清理

### 7.1 为什么不开 C(阻断)
设计文 §4.4 **顺序硬约束**:现状 COPY 100% 失败,若先开 C 再修 A(或同批),A 一旦有 bug ⇒
`failed>0` 会中止**全部 15 条通道**的上传 = **全站上传当场停摆**。要求「A 上线并观测到 failed≈0
之后才允许开 C」,且开 C 需用户拍板(改生产行为,§23.7)。本期按派单「明确不开 C」执行:
调用点**一行阻断逻辑都没有**(单测卡字面量)。第二阶段 C 落地时须同步:清 marker(防复刻
10-05 死循环)+ 强制点在 PUT 批**之前**。

### 7.2 为什么不动 retention
`_PREUPLOAD_RETENTION_DAYS` 7→3~5 属**容量/保留策略**(设计文 §4.6),是拍板项,不在本期范围。
现状风险已登记: 修复后 pre-upload ~1.1 GiB/天 × 7 天 ≈ 7.7 GiB ⇒ 与主桶 4.226 GiB 合计
**~12 GiB 越过 10 GB 免费线**,需用户拍板(retention 或 lifecycle 取其一)。

### 7.3 测试对象自清记录(§25 可逆性)
- 写入: `signal-backup2/pre-upload/20261010/nav_bucket/*` 共 **256** 个对象(测试对象)。
- 删除前留证: LIST `n=256`,`sample=["pre-upload/20261010/nav_bucket/00.json", ".../01.json", ".../02.json"]`。
- 删除: 并行 DELETE `ok=256 fail=0`;删除后**回读 LIST `n=0`** ⇒ 零残留。
- 恢复路径: 无需恢复(测试对象,来源 = 主桶 `nav_bucket/` 现有对象,可随时重跑产生)。
- 说明: 未额外加自定义前缀 —— 目标 key 由代码固定在 `pre-upload/<当日>/` 下,当日该前缀
  **在实测前实测为空**(`n=0`),故「本次写入 = 本次删除」可逐位对账(见 §3.7);若加前缀需改
  生产代码的 key 构造,反而扩大改动面。

---

## 8. 回滚路径

| 回滚粒度 | 操作 | 说明 |
|---|---|---|
| 整分支 | `main` 上 `git revert <merge/squash 后的提交>`(或合并前直接弃用分支) | 无状态、无 DB 迁移、无 unit 变更 ⇒ revert 即恢复 |
| 仅 D① | 还原 `_route_bucket` 旧行为(返回 `HOST, AK, SK`) | **不建议**:旧行为 = 拿老账号凭据访问只存在于新账号的桶 = 必 404 |
| 仅 D③ | 从 `schedule_monitor.sh` 删除 D③ 块 | 纯观测,删掉不影响上传链(无数据依赖) |
| 仅观测告警 | `notify.py --dedup-key preupload_backup_fail` 已有 6h 窗;必要时在 `check_preupload_backup.py` 去掉 `--notify`(或去掉挂载点 `--notify` 参数) ⇒ 退回只打印 | 分级降噪,不动判定逻辑 |
| A 的降级形态 | **无**。设计文 §4.4(E 方案):A 直接替换后没有 COPY 路径,不做「运行时双路径 fallback」(双路径=双份维护面) | 回滚=整体 revert,不做半开降级 |

`pre-upload/` 内的历史备份对象本身即回滚层:任一被覆盖 key 的旧版本可从
`signal-backup2/pre-upload/<日期>/<key>` 取回(7 天内)。

---

## 9. 交接/后续(不在本期范围,供主控排期)

1. **第二阶段 C**(阻断):须用户拍板;落地时清 marker + 强制点在 PUT 批前 + severe 告警。
2. **容量拍板**(§7.2):retention 7→3~5 或 pre-upload 上 lifecycle。
3. **观测点升档**:如需「连续 N 天仍异常 → critical」,按 #196③ 家族模式把
   `preupload_backup_fail` 登记进 `alert_denoise_rules.py` 的 escalate 通道(本期只做首报 + 6h 去重)。
4. **`test_212::test_e_pre_change_source_static` 的脆弱前提**(§6.2 末行):该 static 对照只在
   「工作区干净」或「工作区恰含 #212 未提交改动」两种态下有意义,任何其他脏工作区都会误红。
   建议改为锚定 `git show <该批合并提交>^:` 的固定 rev(或改用 fixtures 固化改前片段)。
5. **云上落点**: 上线后 `check_preupload_backup.py` 随 15min `trade-schedule-monitor.timer` 自动生效
   (`.env` 有 `R2_BACKUP2_*`);首日应看到 `PREUPLOAD_OK ... landed>0`(交易日 17:50 全量后)。

## 落档信息

- 报告: `docs/ops/237-preupload-relay-impl-20261010.md`(随 `feat/237-preupload-relay` commit)
- 设计/根因: `docs/ops/237-r2-overwrite-backup-guard-design-20261009.md`、`docs/ops/preupload-copy-rootcause-20261008.md`
- 代码: `scripts/upload_r2.py`、`scripts/check_preupload_backup.py`、`scripts/schedule_monitor.sh`
- 测试: `scripts/tests/test_237_preupload_relay_pytest.py`、`scripts/tests/test_237_check_preupload_backup_pytest.py`