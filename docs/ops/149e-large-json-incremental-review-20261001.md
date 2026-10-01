# #149e 独立审查报告(2026-10-01, reviewer agent)

> 审查对象: commit `44b6679e7`(分支 `feat/149e-large-json-incremental-20261001`,已 push origin,未合 main)
> 审查范围: `scripts/upload_r2.py` cmd_upload_large_json 本地快照增量改造 + 报告 `docs/ops/149e-large-json-incremental-20261001.md`
> 审查方式: 独立提取 commit 到 /tmp/rev149e + 复跑实施自测 + 新增 6 组补测(mock 桶 demo-nowhere, 零 R2 生产接触)+ 真实 CLI dry-run --full 复现

## 结论: **PASS-with-caveat**

核心 5 条不变量(清单权威/跳过判据可自证/退化安全/周期全量/原子写 fail-loud)**全部经独立实测确认成立**,未发现「本来该传却被跳过」的静默漏传路径,未发现任何真实生产桶写入。2 个 caveat(均不阻断上线): ① 源缺失文件语义从「整轮失败」变成「静默跳过」且注释声称「语义不变」有误(该路径在真实清单下几乎不可达)② 报告「36.5s」为采样推算值(真实全量实测 37.4s 佐证,数字口径需标注)。

---

## 逐条审查证据

### 审查点 1【最高风险】静默漏传 — 不存在漏传路径(实测+代码双证)

**跳过判据**: `old[1] is not None and old[1] == md5`(scripts/upload_r2.py:2579),纯 md5 比对,**不涉 mtime / size / 时区**。指纹 = gzip payload md5(mtime=0 固定)。

- **gzip 确定性实测(T1)**: 同内容两次 `gzip.compress(raw, compresslevel=6, mtime=0)` 字节相同(md5 一致)。故「内容变 → raw 变 → payload 变 → md5 变」无例外。
- **touch/时区场景**: 判据不含 mtime,mtime=0 已固定,`touch` 改时间戳不改 md5 → 不会误判;时区无关。
- **内容变 → 必重传实测**: 实施自测③「本地改一个文件」→ 只重传该文件(PUT=1 且 key 尾 a.json.gz, HEAD=1 只查 a)复跑 PASS。
- **状态自证闭环**: 状态只在**全部上传成功后** tmp+os.replace 原子写(代码 L2632-2645),「状态记录 + md5 一致」= 上次成功上传后内容未变 → 远端必有同内容副本。
- **唯一理论漏传路径 = md5 碰撞(2^-128,不可行)**。结论: 「磁盘文件变了但被判为没变」无构造路径。

### 审查点 2 清单权威性 — PASS(实测)

- `entries` 仍由子进程 `large_json_excludes.py --print` **全量**生成(代码 L2389-2401),状态只存指纹做跳过判定,**不是第二份清单集合源头**;空清单直接 `return`(L2404-2405)。
- **实测(T2)**: 首跑建状态(a/b)后,清单新增 `c.json`(状态无记录)→ 增量跑 PUT 仅 `large-json/c.json.gz`(a/b 未重传),状态 `files` 更新含 c。新增文件不会被漏。

### 审查点 3 退化安全 — PASS(实测三种形态,最想排掉的「损坏当没文件传」不存在)

| 形态 | 代码路径 | 实测 |
|---|---|---|
| 状态缺失 | `state_path.exists()` False → state_ok=False → force_full | HEAD=2 全量 ✓ |
| JSON 损坏 `{BROKEN` | `except (OSError, ValueError)` → 打印警告 → state_ok=False → force_full(JSONDecodeError 是 ValueError 子类,必被捕获;except 后**退化全量非吞错空跑**) | HEAD=2 全量 ✓ |
| 结构不认(files 非 dict) | `isinstance(st.get("files"), dict)` 判定 → state_ok=False → force_full | HEAD=2 全量 ✓ |
| marker 残留 | `marker_path.exists()` → force_full(fail-closed) | 实测 T3: HEAD=2 全量 ✓ |

四种形态全部「必然退化全量 HEAD」,无「状态坏了当没变化」路径。

### 审查点 4 原子写 + fail-loud — PASS(实测)

- 状态写: tmp + `os.replace` 原子写(代码 L2632-2645);写失败 `sys.exit(非零)` fail-loud。
- **实测(实施自测⑥复跑)**: 数据目录 chmod 555 → `✗ 状态文件原子写失败(...fail-loud)` exit code=1;marker 残留 → 下轮强制全量(fail-closed 兜底)。
- 半截 tmp 残留无害(下轮读旧 state 文件,不受 tmp 影响)。
- 上传失败 `ok != len(changed_rels)` → exit 1 + 不写状态 + marker 残留 → 下轮全量重传(宁多传不漏传)。
- 细节: marker 写入失败仅 print 不中断(L2595-2598)——但即使无 marker 保护,状态只在全成功下写、失败不写 → 下轮重传面更大,仍无静默缺口。

### 审查点 5 周期强制全量 — PASS(三种触发全部实测生效)

| 触发 | 实测 |
|---|---|
| 周日(weekday==6) | 独立补测 T5(monkeypatch datetime.datetime.now=2026-10-04 周日): 模式=周日强制全量校验, HEAD=2 全量, 内容未变 ETag 一致 0 PUT ✓ |
| `--full` | 实施自测⑦(--full dry-run 0 HEAD/0 PUT 契约不破)+ 真实 CLI dry-run --full ✓ |
| `R2_LARGE_JSON_FORCE_FULL=1` | 独立补测 T6: HEAD=2 全量, 0 PUT ✓ |

### 审查点 6 报告数字与代码对账(§5.4⑦) — 基本属实,1 处口径标注需补

| 报告数字 | 复现 | 判定 |
|---|---|---|
| 清单 --print 702.6ms | 复现 714.2ms | ✓(抖动) |
| 全集 30396 | 复现 30396 | ✓ |
| 总字节 1549.6 MB | 复现 1549.6 MB | ✓ |
| 全量 gzip+md5 36.5s | **报告值为采样 2000 推算**,非全量实测;我复现采样推算 43.5s(采样窗口波动);**真实全量指纹扫描实测 37.4s**(见下) | ✓ 数字方向属实,口径需标注 |
| 真实 CLI dry-run --full 输出 | 复现「模式=--full 手动强制全量校验 全集 30396 / 跳过 0 / 待传 30396(指纹扫描 37.4s, 纯本地)」,报告写 37.9s | ✓ |
| 26~105min | 出处 = 根因报告 149-deploy-lock-queue-rootcause-20261001.md §4(09-29 8 线程并行实测) | ✓ |
| 「平时增量 0 HEAD/0 PUT」 | 实施自测② + 复跑: 二次跑无变化 0 HEAD/0 PUT ✓ | ✓ |
| 「26~105min→分钟级」 | 报告已标「预期」;实测增量 0 R2 接触 + 本地扫描 37.4s,预期成立 | ✓(预期非实测,标注清楚) |

真实 CLI 复现细节: `REPO=/tmp/149e_tr R2_BACKUP_BUCKET=demo-nowhere STATICDATA_REPO=<真实staticdata仓> python3 scripts/upload_r2.py upload-large-json --dry-run --full`,全程 0 PUT/0 HEAD;复现前后 staticdata 仓库 `.gitignore` md5 未变(幂等,未被改写)。

### 审查点 7 同类错误面核查(§23.2③)— PASS(独立验证报告结论)

grep 全仓 s3_head 调用点,逐一排除:

| 位置 | 模式 | 是否同类慢路径 | 处置 |
|---|---|---|---|
| `cmd_upload_large_json._upload_one`(:2477) | 逐文件 pre-PUT HEAD | 本次已改: 只对 changed_rels 走 HEAD 幂等 | ✓ 已增量 |
| `_upload_glob`(:804) | **PUT 后** HEAD 对账 ETag(层2 正确性对账,只对本次 PUT 的文件) | 非 pre-PUT 全量比对 | 不动正确 |
| `_incremental_upload` 引擎(12/15 通道) | 本地状态增量 | 已增量 | 不动正确 |
| `cmd_verify_r2`(:2831/2875) | 周日全量对账 + 平日增量抽样 | 非每日慢路径 | 不动正确 |
| `_light_check`(:2878) | 轻量抽查 20 个 | 非慢路径 | 不动正确 |

`_R2_CHANNELS` 表(15 通道: lab/trade-sim/trade-sim-json/index/etf-hist/fund-nav/accum-nav/industry/public-fund/etf-score/kelly-parts/kelly-parts-sdc/kelly-snapshots/data-large/all-data)中**无 large-json**——报告「large-json 不登记在 verify-r2 公共桶对账表」属实(私有桶 signal-backup 走 --full/周日自校验)。报告「唯一逐文件全量跨境比对慢路径实例 = cmd_upload_large_json,本次已根治」**成立**。

### 审查点 8 R2 生产零接触 — PASS(声明属实)

- 实施自测: `R2_BACKUP_BUCKET=demo-nowhere`(不存在桶, 404 零污染)+ `REPO=/tmp/149e_tr` + 假 staticdata 仓 `/tmp/149e_sd` + mock s3(`u.s3_head/u.s3_request` 全部内存桶)+ 假 large_json_excludes.py。零生产接触。
- 真实 CLI 复现: 仅 dry-run + demo-nowhere 桶,全程 0 PUT/0 HEAD。
- 未发现任何一次真实生产桶(signal-backup)写入。

---

## 发现的问题(带文件:行号)

### P2-1 源缺失文件: 语义从「整轮失败」变成「静默跳过」,且注释声称「语义不变」有误
- 位置: `scripts/upload_r2.py:2576-2577`(commit 44b6679e7 版)
- 现象: 新版 `if not src.is_file(): skip_rels.append(relpath)` 把源缺失文件计入 skip,整轮继续成功并写状态(该文件从状态 `files` 抹除)。注释写「原逻辑也当『跳过(源不存在)』计入 ok, 语义不变」。
- **实测(T4)**: 删掉磁盘 b.json 后跑 → 整轮不 exit,a 正常上传,b 静默跳过,状态 files 仅剩 a。
- **旧版对照**(44b6679e7^): `_upload_one` 对源缺失 `return "skip"`(**不** `_note_ok`)→ 最终 `ok != len(entries)` → 整轮 `sys.exit(1)`(告警暴露)。注释「计入 ok, 语义不变」**错误**,行为确实变了。
- **影响面**: 真实清单由 `--print` 生成(`print_mode` 只输出磁盘存在的文件),故源缺失几乎不可达;即使发生,R2 保留旧副本不丢数据。属**低风险但注释误导**,建议修注释或维持 fail 语义。
- 处理: 不阻断上线(caveat)。

### P3-1 报告「36.5s」口径未标注为采样推算
- 位置: `docs/ops/149e-large-json-incremental-20261001.md` §1「全量 gzip+md5 本地耗时 | 36.5s」
- 现象: 基线脚本 `/tmp/large_json_baseline.py` 实际**采样前 2000 个文件推算**全量,非全量实测;我复现采样推算 43.5s(采样窗口波动大)。但真实 CLI 全量指纹扫描实测 37.4s(报告 §3 写 37.9s),数字方向可信。
- 处理: 建议标注「采样推算,全量实测 ≈37.5s」;不阻断。

---

## 另滤低分项(置信度 <80, 已滤)
- 状态结构注释「verify-r2 对账同通道可读」措辞(实际 large-json 未登记 _R2_CHANNELS,将来登记可读)→ 属预期兼容声明,非问题。
- marker 写失败仅 print 不 fail(已论证无静默缺口,见审查点 4)。
- 内存峰值(最大单文件 87.6MB signal_kelly_trades_sdc.json, read_bytes+gzip 峰值 ~90MB)→ 旧版同行为,非本次引入。
- `size` 字段在 skip 判据中未参与比对(纯 md5)→ 设计如此,md5 已足够,非问题。

---

## 复现段(§23.5)
```bash
# 1) 独立提取审查对象
git -C /Users/linhuichen/code/trade archive 44b6679e7 | tar -x -C /tmp/rev149e
# 2) 复跑实施自测(mock, 零生产接触; 已改 WT 指向 /tmp/rev149e)
python3 /tmp/149e_test_review.py     # 21 项 PASS
python3 /tmp/149e_test2_review.py    # manifest 完整性 PASS
# 3) reviewer 新增补测(mock 桶 demo-nowhere, 零生产接触)
python3 /tmp/149e_review_extra.py    # T1 gzip确定性/T2 清单新文件/T3 marker/T4 源缺失/T6 dry-run PASS
python3 /tmp/149e_t5.py              # T5 周日强制全量 PASS
python3 /tmp/149e_t_envfull.py       # R2_LARGE_JSON_FORCE_FULL=1 PASS
python3 /tmp/149e_t_deg.py           # 损坏/结构不认/缺失→全量 PASS
# 4) 真实 CLI dry-run --full 复现(隔离桶, 零 R2 写, .gitignore 幂等)
REPO=/tmp/149e_tr R2_BACKUP_BUCKET=demo-nowhere \
STATICDATA_REPO=/Users/linhuichen/code/trade-data-signal-staticdata \
python3 /tmp/rev149e/scripts/upload_r2.py upload-large-json --dry-run --full
# → 模式=--full 手动强制全量校验 全集 30396 / 跳过 0 / 待传 30396(指纹扫描 37.4s, 纯本地)
```
