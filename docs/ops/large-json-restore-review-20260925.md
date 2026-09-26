# 大 JSON 恢复侧收尾审查报告（2026-09-26，feat/large-json-r2-restore 第三任）

> 前置:分支 `feat/large-json-r2-restore` 起点 commit `3c34a6031`(恢复脚本 + 灾备文档骨架),
> 前两任已交付 P1-1(多日期 manifest 不串日期)+ P1-2(路径穿越防御)+ 改动②(默认恢复目标 =
> 生产数据目录 trade-data/data/)。本文档是**收尾三项**(③网络超时/④polish/⑤本审查报告)的落档。
> 复现命令与测试环境:`/tmp/restore-test`(mock upload_r2 + mock manifest,禁 rm 通配符纪律)。

---

## 一、收尾改动清单

| 文件 | 改动 | 说明 |
| --- | --- | --- |
| `scripts/restore-large-json.sh` | ③ 网络超时强制注入 + ④ skipped 非 0 退出 + 输出顺序修复 + list 错误打印 200 字符裁剪 | 见下节逐条 |
| `docs/backup-restore.md` 第八节 | 恢复目标改为生产数据目录 + `--target` 参数 + .bak copy2 语义 + 超时/路径安全说明 | 与脚本实际行为对齐 |
| `docs/large-json-backup-manifest.md` | 恢复命令行加 `--target` + 默认目标说明 + 列名「还原到目标目录对应位置」 | 与脚本实际行为对齐 |
| `docs/ops/large-json-restore-review-20260925.md` | 新建 | 本报告(§23.5 落档) |

## 二、③ 网络超时(本次核心)

### 背景
原脚本(HEAD 3c34a6031)两处 `upload_r2.s3_request(...)` 调用无超时保护:`_list_all`(list
分页)与 `restore_one`(下载)。虽然 `upload_r2.s3_request` 内部内置连接超时(`R2_UPLOAD_HTTP_TIMEOUT`
默认 30s + 5 次退避重试),但对**灾难恢复工具** 30s 仍偏长;且恢复侧若继承调用环境里
`R2_UPLOAD_HTTP_TIMEOUT=600` 的更大值(云上为上传设的),网络不可达时会等 600s×5 重试=分钟级挂死。

### 修复内容(3 处)
1. **强制注入超时(import 前)**:恢复侧在 `import upload_r2` 之前把 `R2_UPLOAD_HTTP_TIMEOUT` 设为
   `min(外部值 or 10, 10)`,无论调用环境是否已有该变量,恢复侧连接超时都不会超过 10s;
   外部若设更小值(网络好想更快失败)则尊重。非法值回退 10。
   ```
   try:
       _r2_tmo = int(os.environ.get("R2_UPLOAD_HTTP_TIMEOUT") or "10")
   except ValueError:
       _r2_tmo = 10
   os.environ["R2_UPLOAD_HTTP_TIMEOUT"] = str(min(_r2_tmo, 10))
   ```
   必须 import 前设置的原因:`upload_r2.py` 模块级常量 `R2_UPLOAD_HTTP_TIMEOUT` 在 import 时读取
   env(文件名行号:`scripts/upload_r2.py:219`)。
2. **list 网络失败快速失败**:`_list_all` 的 `s3_request` 包 try/except,异常 → `sys.exit`(非 0)
   报"已设 Ns 超时"。
3. **下载网络失败快速失败**:`restore_one` 的 `s3_request` 包 try/except,异常 → 返回错误字符串
   (跳过该文件,不中断同批其他文件),最终汇总 skipped + 非 0 退出。

### 自测证据(mock 在 /tmp/restore-test,均落文件 + tail)

| # | 用例 | 命令 | 结果 |
| --- | --- | --- | --- |
| 1 | list 网络失败快速失败 | `RESTORE_TEST_NETFAIL=1 … --list` | `exit=1`;报错「列出 … 网络调用失败(快速失败,已设 10s 超时): TimeoutError」 |
| 2 | 下载网络失败跳过 + 非0 | `RESTORE_TEST_NETFAIL_DOWNLOAD=1 … --date 2026-09-25` | `exit=1`;2 个对象跳过,每个报「已设 10s 超时」,正常文件不受影响 |
| 3 | 超时注入链路(真实 upload_r2) | `python3 -c "import upload_r2; print(R2_UPLOAD_HTTP_TIMEOUT)"` | 外部 env=600 时注入后 `upload_r2.R2_UPLOAD_HTTP_TIMEOUT == 10`(min() 生效) |

> ⚠️ 超时是**连接超时**(http.client.HTTPSConnection timeout),不是整组 5 次重试的总时长上限;
> 最坏场景 5 次重试 × 退避(1/2/4/8s)≈ 15s+ 单文件可能累计到 ~1 分钟内,这是 upload_r2 重试语义
> 的一部分(偶发断连重试是特性),非本次范围。**已列未决项**,如需「整组总时长硬上限」另议。

## 三、④ polish 项

1. **skipped 非 0 退出(行为修复,原为静默 exit 0)**:恢复类模式完成后若有对象被跳过(网络失败/
   非法路径/sha 不匹配/解压失败),汇总打印后 `sys.exit(1)`——恢复不完整=失败,不许静默当成功。
2. **stdout 行缓冲**:重定向到文件时 stdout 块缓冲会与 stderr 顺序颠倒(skipped 汇总跑到进度前),
   加 `sys.stdout.reconfigure(line_buffering=True)` 修复。
3. **list 错误打印裁剪**:`data.decode(...)[:300]` → `[:200]`(任务要求前 200 字符+字节数,禁整文件 cat)。
4. **文档对齐**:backup-restore.md 第八节 / manifest.md 更新为「默认恢复目标=生产数据目录」+
   `--target` 参数 + copy2 备份语义 + 超时说明,消除「写回 data/ 下」旧表述。

## 四、回归自测(复用 /tmp/restore-test mock,全部落文件)

| 自测项 | 命令 | 结果 |
| --- | --- | --- |
| bash -n 语法 | `bash -n scripts/restore-large-json.sh` | exit=0 |
| 多日期 sha 不串 | `--date 2026-09-25` / `--date 2026-09-24` | 25 日取 `fed892cc…`(内容 sep25)、24 日取 `498d6cef…`(内容 sep24),各取各日期行 |
| 默认目标 | 不传 STATICDATA_REPO 跑 `--list` | 打印「恢复目标目录: /Users/linhuichen/code/trade-data/data」= 生产数据目录 |
| --target 警告 | `--list --target /tmp/restore-test/custom` | 打印醒目警告「不是默认的生产数据目录…请确认后继续」 |
| 路径穿越(evil key) | `RESTORE_TEST_EVIL_KEY=1 --list` / `--all` | list 排除「1 个对象格式/路径非法」;--all 跳过硬跳过 + exit=1 |
| 路径穿越(symlink 逃逸) | data/foo_parts → 指向目标外的 symlink,`--date` | restore_one realpath 校验拦截,报「目标 … 不在根目录 … 内,已跳过」,目标外目录保持空,exit=1 |
| sha 不匹配 | mock 快照内容改版 + 已有旧文件 | 中止「sha256 不匹配 … 已中止(勿覆盖)」,原文件不变、无 .bak(中止在备份前),exit=1 |
| 旧文件 .bak | 预置 `{"old":true}` 再还原 | 生成 `foo.json.bak-<时间戳>`,新内容到位,exit=0 |
| 四种模式回归 | --list / --all / 单文件 / 子目录相对路径 | 全部正常,sha 全对,exit=0 |

### 测试隔离说明
- 全部测试在 `/tmp/restore-test`;默认目标例外(测试默认目标时确认打印生产目录路径,但只 --list 只读,
  不实际写入)。
- ⚠️ 曾有一次 `--date 2026-09-25` 未带 `STATICDATA_REPO` 覆盖时实际写入了
  `/Users/linhuichen/code/trade-data/data/foo.json`(+空目录 foo_parts)——已立即删除,生产数据目录
  已确认无残留(foo.json / foo_parts 均不存在)。后续测试全部用 `STATICDATA_REPO=/tmp/restore-test` 隔离。

## 五、commit

- 分支 `feat/large-json-r2-restore`,base = origin/main(开工时 a1d1066cd,收尾已 rebase)
- 本次 commit 覆盖:脚本 + 两份文档 + 本报告

## 六、未决项

1. **超时=连接超时非整组总时长上限**:当前 `R2_UPLOAD_HTTP_TIMEOUT=10` 是每次 HTTPS 连接的 socket
   超时;upload_r2 内部 5 次重试+退避仍会导致单文件最坏 ~1 分钟内失败而非严格 10s 内。若要求「整组
   调用总时长硬上限」,需在脚本侧对 s3_request 加外层时钟(time.monotonic 判定),超出即放弃该文件。
   考虑:对恢复工具,10s 连接超时 × 5 重试已能覆盖「网络不可达快速失败」核心诉求;总时长硬上限会
   牺牲偶发重连自愈,倾向不额外加。**待 reviewer/主控定夺。**
2. **`--all`/`--date` 部分文件失败的进度输出**:当前跳过文件也打印「还原了 N 个文件」的概要行
   (进度行不含 counts),失败明细在 stderr 汇总。可见性 OK,但「成功/失败各 N」的汇总计数是增强项,暂未加。