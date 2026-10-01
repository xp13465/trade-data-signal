# #149e upload-large-json 改「本地快照增量」实施方案与自测报告(2026-10-01)

> 对应根因报告 `docs/ops/149-deploy-lock-queue-rootcause-20261001.md` §5⑤(长任务本身缩短)。
> 分支 `feat/149e-large-json-incremental-20261001`;功能: `upload_r2.py upload-large-json` 从「每次对 3.1 万文件逐个跨境 HEAD」改为「状态文件本地判定增量」。

## 0. 核心不变量声明(最重要,改动设计一切服从这里)

这批文件是 **git 排除的大 JSON**,`staticdata/` 的 `data/` 下 `.gitignore` 受管区块排除(共 30396 个,1.5GB,9-25 起不再进 staticdata git)。**R2 是它们唯一的异地备份**(见 memory `r2-large-json-backup-never-complete`)。任何「本来该传却被跳过」= 备份静默缺失 = 事故。

因此本改动 5 条不变量(每条都有对应代码实现,见 §2):

1. **清单权威**:每次仍以 `scripts/large_json_excludes.py --print` 输出为**全集**,增量只在该全集上做「跳过」决策,**不得因状态文件而缩小全集**。实现:`entries` 仍由子进程 `--print` 全量生成;状态只记录 `files` 指纹用于比对,never 当集合源头。
2. **跳过判据可自证**:只允许跳过「状态文件有记录 + 本地 gzip md5 == 状态记录 md5」的文件。状态只在**全部上传成功后原子写**(tmp+os.replace),所以「状态+md5 一致」即自证「上次成功上传时远端 HEAD 一致,内容没变远端必仍在」。任一不匹配(`md5` 对不上 / 状态无该文件)→ 必须重传。实现:`old[1] is not None and old[1] == md5` 才 skip,否则进 `changed_rels` 走原 HEAD 幂等路径。
3. **退化安全**:状态文件缺失 / 损坏(JSON 解析失败)/ marker 残留 / 首跑 → **退化全量**(`changed_rels` = 全集,每个文件走原 s3_head + PUT 幂等)。绝不「状态坏了就当没变化」。
4. **周期全量校验**:保留强制全量 HEAD 开关 —— ① 每周日自动(`today_weekday == 6`) ② `--full` 参数 ③ `R2_LARGE_JSON_FORCE_FULL=1` 环境变量。任一触发 → 全量 HEAD 比对,防状态与 R2 长期 drift。首跑/损坏也走全量 HEAD(等同全量校验一次)。
5. **原子写状态 + fail-loud**:状态文件 tmp+os.replace 原子写;**写失败必须 fail-loud**(sys.exit 非零)。marker 上传前写、全成功后删(进程 kill 残留 → 全量 fail-closed)。

## 1. 改造前基线(现状计时取证)

取证脚本(纯本地,零 R2 接触):读 `--print` 全集,逐文件本地 gzip(compresslevel=6, mtime=0)+ md5 计时,HEAD 调用次数 = 全集数。

| 项 | 数值 |
|---|---|
| 清单 `--print` 子进程调用 | 702.6ms |
| 全集文件数 | 30396 |
| 全集原始总字节 | 1549.6 MB |
| 全量 gzip+md5 本地耗时 | **36.5s 为采样 2000 文件推算**(非全量实测;真实全量实测 37.4s,见审查报告;另本机 CLI dry-run 复现 37.9s,两次运行抖动)(vs 单段跨境 HEAD 26~105min) |
| 现状每次运行的远端 HEAD 调用次数 | ≈30396(每个文件 1 次 pre-PUT HEAD) |
| 现状单段耗时(实测,见根因报告 §4) | 26~105 分钟 |

取证命令:

```bash
python3 /tmp/large_json_baseline.py   # 见复现段,纯本地
```

结论:本地 gzip 指纹计算全量仅 **≈37.5s(36.5s 为采样推算,真实全量实测 37.4s/37.9s)**≈原跨境 HEAD 时间(26~105min)的 **1% 量级**。把「远端 HEAD」外移为「本地状态判定」是最大杠杆。

## 2. 改动前后对照

### 复用说明
**复用了既有引擎 `_incremental_upload`(scripts/upload_r2.py:963)的状态文件机制**:
- 状态清单命名/结构与引擎同构:`data/.r2_large_json_state.json`,`{version, updated_at, mode, count, files:{rel:{size,md5}}, changed:[rel]}`(与 `.r2_accum_nav_state.json` 等 12 通道同款,同仓 untracked 不进 git)。
- marker fail-closed(`.r2_large_json_uploading.marker`)、原子写状态(tmp+os.replace)、首跑/损坏退化全量、周日强制全量、dry-run 契约 —— 全部照引擎语义抄。

**未直接调用 `_incremental_upload` 函数的原因**(文档化在代码注释):
1. 清单来源是 `large_json_excludes.py --print` 子进程输出(非本地 glob);
2. 上传 payload 需 gzip 变换(引擎 `_upload_glob` 传原始字节);
3. 本通道独有预算(R2_LARGE_JSON_BUDGET)/熔断(R2_LARGE_JSON_FAIL_LIMIT)/并行(R2_LARGE_JSON_WORKERS)定制。

### 改动文件
`scripts/upload_r2.py`(+111/-7)仅 `cmd_upload_large_json()` 及其 docstring,dispatch 注释补充。

| 阶段 | 改动前 | 改动后 |
|---|---|---|
| 判定 | 每文件先跨境 s3_head 比对 ETag | 先本地指纹扫描(读+gzip+md5,实测 ~37s):状态 md5 一致 → skip(0 HEAD/0 PUT);否则进 `changed_rels` |
| 清单 | `--print` 输出 → 全部进 upload | `--print` 输出 → 全集,增量跳过不走上传,不缩小全集 |
| 状态 | 无 | `data/.r2_large_json_state.json`(原子写,只全成功写)+ `.r2_large_json_uploading.marker`(fail-closed)|
| 退化 | 每次都是全量 HEAD | 首跑/状态缺失/损坏/marker 残留 → 退化全量(同现状时序) |
| 强制全量 | 无(永远全量) | 周日自动 / `--full` / `R2_LARGE_JSON_FORCE_FULL=1` |
| 状态写失败 | 无状态可写 | sys.exit 非零(fail-loud) |
| dry-run | 不 PUT/不 HEAD | 不变 + 0 HEAD 0 PUT 契约保持(指纹纯本地) |

### 预期耗时降幅
- 平日增量(内容无变化,最常见场景): 3.1 万跨境 HEAD + gzip → **仅本地指纹扫描 ~37s(实测)+ manifest/prune 收尾**,R2 接触 ≈ 0。预期 **26~105min → ~1 分钟级**。
- 首跑/周日/--full: 全量 HEAD 32(min 级同现状)但只每周一次或显式触发,不阻塞每日链。

## 3. 逐项自测(mock 环境,零 R2 生产接触)

自测环境: `REPO=/tmp/149e_tr`(隔离 trade 树,状态文件落这里)+ `R2_BACKUP_BUCKET=demo-nowhere` + 假 staticdata 仓库 + mock s3(s3_head/s3_request 全部内存桶,记 HEAD/PUT 调用)。`subprocess.run` 打桩为假 `--print` 输出(a.json + sub/b.json)。

自测脚本 `/tmp/149e_test.py` + `/tmp/149e_test2.py`,最终 **PASS 21 项**(含 7 大场景覆盖)。

| # | 场景 | 断言 | 结果 |
|---|---|---|---|
| ① | 首跑 dry-run(无状态) | 0 HEAD / 0 PUT / 不写状态 / 打印「全集 2 / 跳过 0 / 待传 2」 | PASS |
| ①b | 首跑非 dry-run | 退化全量,PUT=2,HEAD≥2,状态文件写入 count=2 含两文件,无 marker 残留 | PASS |
| ② | 二次跑无变化 | 0 HEAD / 0 PUT,打印「模式=增量 全集 2 / 跳过 2 / 待传 0」 | PASS |
| ②b | manifest 完整性专项 | 首跑与全 skip 二次跑 manifest rows 均 = 2(全集),skip 也进 manifest | PASS |
| ③ | 本地改一个文件 | 只重传它:PUT=1 且 key 尾 `a.json.gz`;HEAD=1 只查 a | PASS |
| ④ | 状态文件损坏(`{BROKEN`) | 退化全量 PUT=2 / HEAD≥2,不静默 | PASS |
| ⑤ | 远端 HEAD 与本地不一致(drift) | 状态+本地一致时增量仍跳(0 PUT);`--full` 强制全量 HEAD 发现漂移重传 a | PASS |
| ⑥ | 状态写失败(数据目录 chmod 555) | fail-loud sys.exit 非零,打印「✗ 状态文件原子写失败」 | PASS |
| ⑦ | `--full` dry-run | 仍 0 PUT / 0 HEAD(契约不破) | PASS |

真实 CLI 参数路径验证(读真实 staticdata 仓,隔离桶 demo-nowhere,dry-run,零 R2 写):

```bash
REPO=/tmp/149e_tr R2_BACKUP_BUCKET=demo-nowhere \
STATICDATA_REPO=/Users/linhuichen/code/trade-data-signal-staticdata \
python3 scripts/upload_r2.py upload-large-json --dry-run --full
# → [large-json] 模式=首次/无状态退化全量 全集 30396 / 跳过 0 / 待传 30396 / 缺失 0(指纹扫描 37.9s, 纯本地;审查方独立复现 37.4s, 抖动一致)
```

### 3.3 P2-1 补修(2026-10-01 独立审查后)

独立审查实测发现 P2-1:源缺失文件从旧版「整轮 sys.exit(1)」(fail-loud)漂成新版「静默跳过」,且注释误写「语义不变」。本次补修:

- **语义选择:零星告警不阻断 + 批量/全量升格非零退出**(不退回旧版整轮 fail)。理由:真实清单由 `--print` 生成(只输出磁盘存在的文件),源缺失几乎不可达,唯一可达形态是 ①良性竞态(双进程并发/文件替换窗口,缺 1-2 个)——旧版整轮 exit 1 会让一次良性竞态打断整条灾备链,反而更糟;②目录级异常(sparse-checkout 配错/路径挂错/目录损坏,全缺或批量缺)——必须 fail-loud。参照 #136 fail-loud 先例「数量异常 ⇒ 拒绝」,用「全量缺失 / ≥50 个 / ≥5% 比例(全集≥50 时)」三判据升格非零退出。
- **逐条告警 + 汇总计数**:每条缺失打印 `⚠ 源文件缺失(计入缺失计数): data/<relpath>`(stderr);模式行加 `/ 缺失 N`。缺失文件不进状态 files(无指纹可算,R2 旧副本保留不丢数据)。
- **注释订正**:写明新旧语义实际差异(旧=整轮 fail;新=零星告警+批量升格),不再写「语义不变」。

自测(mock,零 R2 接触,`/tmp/149e_p21.py`)**18/18 PASS**:

| 场景 | 观测 | 结果 |
|---|---|---|
| S1 零星缺失(2缺1) | 逐条告警可见 + 汇总「缺失 1」+ 整轮不中断 + a 仍上传 | PASS |
| S2 全量缺失(2缺2) | exit=✗ 源文件缺失异常(2/2)…,PUT=0,未写状态 | PASS |
| S3 正常全量 | 缺失 0 / 全传 2 / 状态含两文件 / 无 marker / 二次跑 0 HEAD 0 PUT(五条不变量不回退) | PASS |
| S4 批量缺失(60缺10, >5%) | exit=✗ 源文件缺失异常(10/60)… 比例升格 | PASS |
| S4b 零星缺失(60缺1) | 逐条告警可见 + 整轮不中断 | PASS |

审查方补测脚本重跑(指向当前代码):`/tmp/149e_review_extra_cur.py`(T1-T4/T6 PASS)、`/tmp/149e_t5_cur.py`(周日全量 PASS)、`/tmp/149e_t_envfull_cur.py`(R2_LARGE_JSON_FORCE_FULL PASS)、`/tmp/149e_t_deg_cur.py`(退化三形态 PASS)——原 P1/P2 PASS 项全部保持 PASS,无回退。

## 4. 同类错误面(§23.2 修 bug 三铁律 ③)

排查对象:`upload_r2.py` 内全部逐文件远程比对点 + 灾备链:

| 位置 | 模式 | 是否同类慢路径 | 处置 |
|---|---|---|---|
| `cmd_upload_large_json`(本改动) | 逐文件 pre-PUT s3_head | **是(元凶)** | 本次已改增量 |
| `_upload_glob`(:804) | PUT 后 HEAD 对账 ETag | 否(层2 上传正确性对账,只对本次 PUT 的文件,非 pre-PUT 全量比对) | 不动 |
| `_incremental_upload` 引擎(12 通道) | 本地状态增量,0 R2 接触 | 否(已是增量) | 不动 |
| `verify-r2` 通道登记表 `_R2_CHANNELS` | 周日全量对账/平日增量 | 否(large-json 不登记在该表 —— 私有备份桶走 `--full`/周日自校验,不在公共桶对账范围) | 不动 |
| `staticdata_backup_async.sh` step3.5b | 调 `upload-large-json` | 是(长跑主因调用方) | 本改动后该调用变增量,无需改脚本 |
| `large-json-backup-manifest.md` 恢复侧 | 读 manifest 恢复 | 否 | manifest 完整性已验(§3 ②b) |

**结论:全仓「逐文件全量远程比对」慢路径唯一实例 = `cmd_upload_large_json`,本次已根治。灾备链复用同一函数,自动获得增量收益。**

## 5. 复现段(§23.5)

报告 + 改动同 commit,复现可直接粘:

```bash
# 1) 基线取证(纯本地,零 R2 接触)
python3 /tmp/large_json_baseline.py
# -> 全集 30396, 本地 gzip+md5 36.5s(采样 2000 推算;全量实测 ≈37.5s), 现状每次 ≈30396 次跨境 HEAD(单段 26~105min)

# 2) 自测(mock 环境,零 R2 接触;隔离 REPO + 隔离桶 + mock s3)
python3 /tmp/149e_test.py        # 21 项 PASS
python3 /tmp/149e_test2.py       # manifest 完整性专项 PASS

# 3) 真实 CLI 参数路径验证(读真实 staticdata 仓,隔离桶,纯 dry-run 零 R2 写)
REPO=/tmp/149e_tr R2_BACKUP_BUCKET=demo-nowhere \
STATICDATA_REPO=/Users/linhuichen/code/trade-data-signal-staticdata \
python3 scripts/upload_r2.py upload-large-json --dry-run --full

# 4) 生产命令(主控/部署链,开盘后由部署正常触发)
python3 scripts/upload_r2.py upload-large-json          # 平日增量(~1min)
python3 scripts/upload_r2.py upload-large-json --full   # 手动全量校验(周日自动)
```

复现段依赖的自测脚本已在本机 `/tmp/149e_test.py`、`/tmp/149e_test2.py`、`/tmp/large_json_baseline.py` 留档(mock 环境完全自包含,不 contact 生产)。