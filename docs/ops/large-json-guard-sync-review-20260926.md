# large-json 守卫下沉单一源 + sync 补守卫 — 独立审查报告(feat/large-json-guard-sync, 2026-09-26)

> 审查对象: commit `7be5da14e`(base `ebec809ea`), 3 代码文件 + 1 实施报告。
> 审查方式: 全部 8 项必查逐项实跑验证(临时 git 仓 + 假 app 仓集成, 未碰生产 staticdata/R2)。
> 结论: **PASS(可 merge)** — 无阻断项; 1 个中危缺口(建议本次合并在同域整改, 不阻塞) + 3 个低分项。

## 〇、必查项结论速览

| # | 必查项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 等价性独立复核 | **判定口径逐项一致**; 降级路径()有差异见 F2 | 见 §一 |
| 2 | D 自锁回归 | **通过** rc=0 | 21MB 已提交→rm --cached(磁盘仍在)→`--check-staged` rc=0 |
| 3 | 缺口 B 闭环 | **通过** | 未跟踪 21MB→default_mode 纳入 .gitignore→add -A 后不在暂存(单测+sync 端到端双验) |
| 4 | bash 3.2 空数组 | **通过** 三处全改 | 空数组→0 参无 unbound; 非空→正常展开; 旧 idiom 复现 unbound |
| 5 | 退出码契约 | **通过** sync 恒 exit 0; async 失败 exit 1 | 集成测试 4 场景(clean/oversize/缺口B/锁忙) |
| 6 | 影响面 | **--check-staged 只读确认**; NONBLOCK 路径不变; --all 无活调用方 | index/mtime/log 三不变; with_lock --nb 锁忙 rc=0 |
| 7 | 遗漏入口 | **无第三方入口** | 全仓 grep: 唯一自动提交入口 = sync + async(migrate 脚本明确人工 commit) |
| 8 | R2 测试污染 | **真缺口, 已发生** | 见 F1(中危) |

## 一、等价性复核(必查项 1 独立对照, 不信实施报告表)

对照 `ebec809ea:scripts/staticdata_backup_async.sh` 内联守卫 vs `large_json_excludes.py check_staged_mode`, 逐项:

| 判定项 | 原版 | 新版 --check-staged | 结论 |
|---|---|---|---|
| 清单 | `git diff --cached --name-only --diff-filter=d` | 同(含 `--diff-filter=d` 小写 d, 排 D) | 一致(已实跑: D 场景 rc=0) |
| 文件数>5000 | `_N>5000` 短路, reason=backlog, 不统计字节 | `n>BACKLOG_FILE_COUNT` 短路, 同 | 一致(实跑: 5001 文件 → rc=1/backlog/字节=0) |
| 单文件>20MB | `_sz>_LJE_THRESHOLD` → largejson | `sz>THRESHOLD(20e6)` → largejson | 一致(实跑: 21MB → rc=1/largejson) |
| 总字节>500MB | `_BYTES>500000000` → backlog(未置 largejson 时) | 同(BACKLOG_BYTES_THRESHOLD=500_000_000) | 一致(实跑: 510MB 小文件堆 → rc=1/backlog) |
| 原因优先级 | largejson 优先于 backlog | 同(backlog 只在 reason 空时置) | 一致(实跑: 大文件+总字节双超 → largejson) |
| 缺失文件处理 | `[ -f ]` 为假不计字节 | `os.path.isfile` else 0 | 一致 |
| 心跳 _N/_BYTES | 直接计算 | 从守卫输出 sed 解析 | 值一致(集成 D 场景心跳 files=43/bytes=85772 正确) |
| import 失败 | `_LJE_THRESHOLD=999999999999`(单文件守卫失效, 积压守卫仍兜底)+ FAIL=1 | `_LJE_THRESHOLD=20000000`(仅提示文案)+ FAIL=1; 判定本身走 --check-staged 独立模块不依赖该 import | **改进**(守卫不再因 import 失败部分失效) |
| 判定脚本整体挂 | (无此场景, 内联无单点) | rc=2: _CS_OUT 空 → FAIL=1 + 继续 commit, **无字节兜底** | **差异**, 见 F2 |

## 二、实跑复现段(全部通过, 可复现)

```bash
# ① D 自锁回归(core)
rm -rf /tmp/ljgreview && mkdir -p /tmp/ljgreview/data && cd /tmp/ljgreview && git init -q -b main . \
  && git config user.email t@t.com && git config user.name t && echo x > data/small.json \
  && git add . && git commit -qm init
dd if=/dev/zero of=/tmp/ljgreview/data/big.json bs=1048576 count=21 2>/dev/null \
  && git add data/big.json && git commit -qm add_big && git rm --cached -q data/big.json
python3 scripts/large_json_excludes.py --check-staged --repo /tmp/ljgreview; echo rc=$?   # rc=0 ✓

# ② 单文件>20MB 已暂存 → rc=1 原因=largejson ✓ / 双超(large+字节)→ largejson 优先 ✓
#    仅总字节>500MB → backlog ✓ / 5001 文件 → backlog 短路(字节=0)✓
# ③ 缺口B: 新建未跟踪 21MB → default_mode 纳入 ignore(/data/huge_new.json)✓
#    → git add -A 后暂存清单无 huge_new ✓(单测 + sync 端到端双验)
# ④ bash3.2 空数组: bash -c 'set -u; _NOTIFY_DRY=(); f(){ echo ARGS[$#]; }; f "${_NOTIFY_DRY[@]+"${_NOTIFY_DRY[@]}"}"'
#    → ARGS[0] rc=0(旧 idiom → unbound variable 复现); 非空 → ARGS[1]: --dry-run ✓
# ⑤ sync 集成(假 REPO/GIT_REPO/STATICDATA_REPO 三件套 + STATICDATA_SYNC_NONBLOCK=1):
#    clean → commit+push + exit 0 ✓ / 已跟踪 21MB → 跳过 commit + 告警 + exit 0 ✓
#    未跟踪 21MB+小文件 → 小文件正常 commit, 大文件不暂存 + exit 0 ✓
# ⑥ async 集成(假仓 + R2_BACKUP_BUCKET=ljg-test-doesnotexist 隔离桶 + NOTIFY_DRY):
#    clean → commit+push + 心跳 ok(files/bytes 从守卫输出解析)✓
#    已跟踪 21MB → 跳过 commit + 心跳带 3/22022470 ✓(step3.5b 因隔离桶 404 置 FAIL → 心跳 fail, 预期)
# ⑦ --check-staged 只读: index md5 / file mtime / git log 三不变 ✓
```

## 三、Findings(按严重度)

### F1(中危, 建议本次同域整改): async 集成测试必然污染生产 R2, 且已实际发生
- **trace**: `staticdata_backup_async.sh L147-163`(step3.5b 无条件调 `upload_r2.py upload-large-json` 写真实私有桶 `signal-backup`); `upload_r2.py L203 BACKUP_BUCKET`(env 可覆盖但无 SKIP/--dry-run)。
- **已发生**: 实施测试把 20MB 零文件传到了 `signal-backup/large-json/2026-09-26/small.json.gz`(gzip ~0B, 内容无害, 占日档位; 删除已上报等用户拍板或 14 天自动过期)。
- **本轮实证**: 我用 R2_BACKUP_BUCKET=不存在桶跑 async, PUT 全部 404 NoSuchBucket → 无污染; 但同时也证明**不带该 env 就会写生产桶**(实施测试踩的正是这个)。
- **连带**: upload-large-json 即使全部上传失败也会重写 `docs/large-json-backup-manifest.md` + 跑 `_prune_large_json`(列/删生产桶过期对象)——我的测试就把 worktree manifest 重写成了 0 行(已还原), 测试再小心也会碰侧车。
- **verifier**: command=`不带 R2_BACKUP_BUCKET/无隔离 跑含>20MB 文件的 async 集成测试`; expected=应有 dry-run/SKIP 闸; observed=已发生 20MB 零文件误传 + 测试必触发。
- **最小修法建议(不实施, 供主控/用户拍板)**: ①给 async 加 `STATICDATA_BACKUP_SKIP_R2_UPLOAD=1` 跳过 step3.5b(测试/演练用); ②或 upload_r2.py `cmd_upload_large_json` 加 `--dry-run`; ③文档化 `R2_BACKUP_BUCKET` 隔离桶用法(env 已存在, 零成本); 三选一, 推荐①②任一 + ③。

### F2(低): "逐项等价"表在降级路径上略夸大 — rc=2 时原版积压字节兜底消失
- 原版 import 失败: 单文件守卫失效(999999999999)但 500MB 字节守卫仍兜底; 新版 rc=2(判定脚本整体挂): _CS_OUT 空 → FAIL=1 + 继续 commit, _BYTES=0, **无积压兜底**。
- 差异是有意识设计变更(注释明确 "best-effort, 不为判定脚本 bug 阻塞灾备"), FAIL=1 会触发 severe 告警, 风险可控(判定脚本挂的触发条件极罕见)。
- 建议: 不改代码; 若在意可给 rc=2 分支补一个内存版 `_N>5000` 快速兜底, 但当前告警链路已足够。

### F3(低): staticdata_sync.sh 的 --all 模式无活调用方(文档/代码债务, 非本次引入)
- grep 全仓: deploy.sh 只调 async; 三个 sync 调用方(intraday/fetch_news/gen_daily_brief)全部文件列表模式。--all 仅注释声称"默认"。
- 本次改动在 sync 上加守卫对所有模式生效, 不引入新问题; 建议后续单独清债务(不阻塞)。

### F4(低): 操作文档未同步 sync 守卫描述
- `docs/ops/large-json-out-of-git-20260925.md` 只写 async"提交前单文件守卫", 未提 sync 已补守卫 + --check-staged 单一源; `docs/staticdata-daily-brief-sync.md` 描述的是已废弃的 deploy.sh L507-558 旧机制(pre-existing 过时)。
- 本次实施报告已落档(§23.5 本体在), 操作文档是非阻断性滞后; 建议合并后顺手同步 large-json-out-of-git 文档的守卫描述。

## 四、其他核查记录

- §21 公示: 本次为备份守卫机制改动, 不涉及算法/评分 → 无须公示同步。✓
- §22 一致性: BACKLOG 阈值已下沉 py 单一源, sh 无写死数字(_LJE_THRESHOLD=20000000 仅提示文案兜底); D 排除 `--diff-filter=d` 在 async/sync 双入口 + py 三处注释都标了"别改回去"。✓
- 数据完整性/C 级数据: 本次不动数据产物内容, 无 check_data_integrity 需求。✓
- 日志口径差异(实施报告已标注): 原"原因=无" → 现"原因=", 信息量等价。✓
- 心跳: 守卫输出回填 _N/_BYTES 正常(集成实测 files=43/bytes=85772; oversize 时 3/22022470); schedule_monitor 只消费 result/ts, 不依赖数值。✓
- 性能: sync 每轮新增 default_mode + --check-staged, 实施报告实测 ~0.25s; 未复测但组件为 git ls-files/stat, 量级可信; intraday 高频路径增量可忽略。✓
- pending-features-index #110 已是"已完成"态, 本改动属 #110 后续完善, 无待办被改死。✓
- 测试清洁度: 所有测试用 /tmp 临时仓 + 隔离桶(404 无污染); 测试期间 worktree manifest 被 upload_r2 重写已 checkout 还原, 分支工作区干净(仅本报告文件新增, 未 git add/commit)。✓

## 五、结论

**可 merge(PASS)**。改动 5 项全部实现且自洽: 守卫单一源下沉正确、双入口覆盖、D 自锁不回退、缺口 B 闭环、bash 3.2 修法正确、退出码契约保持。
合并前建议(不阻断): 处理 F1(R2 测试污染隔离钩子, 实施已上报用户, 删除或自动过期二选一)+ 顺手同步 F4 文档。
