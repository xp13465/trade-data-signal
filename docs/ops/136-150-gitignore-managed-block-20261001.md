# #136 修复 + #150 核查:staticdata `.gitignore` 受管区块 fail-loud 保护

- 日期:2026-10-01
- 分支:feat/136-150-gitignore-block-20261001
- 改动文件:`scripts/large_json_excludes.py`(default_mode 加 fail-loud 保护)
- 对应台账:`docs/pending-features-index.md` #136 / #150

## Part A:#150 三问结论(证据带行号)

### 问1:受管区块是「静态逐文件精确路径列举」还是「每次备份重生成」?

**结论:每次备份重生成**(写法是逐文件精确路径 `/data/...`,但内容每次由 `default_mode` 从磁盘重算,非静态快照)。

证据链:
- `scripts/large_json_excludes.py:241 def default_mode(repo)` 每次运行都重算 `desired`;`L252` `desired = set(tracked) | set(existing) | set(untracked) | set(direx)`。
- 四个来源逐一核对(backlog 记为「tracked ∪ 区块已有 ∪ 未跟踪大文件 ∪ 9 目录枚举」——**结构属实,但全部依赖磁盘文件存在性**):
  1. `tracked = large_tracked(repo)`(`L243` → `L121-135`):git ls-files 中 `data/` 下 >20MB 文件,**必须 `os.path.isfile(p) and os.path.getsize(p) > THRESHOLD`(`L133`)** —— 磁盘无文件 → 空。
  2. `existing = block_entries_exist(repo)`(`L244` → `L204-219`):区块已有条目,**必须磁盘 `os.path.isfile`(`L215-216`)** —— 磁盘无文件 → 空。
  3. `untracked = untracked_large_in_data(repo)`(`L245` → `L158-184`):`git ls-files --others --exclude-standard -- data/` 中 >20MB,**同样 `os.path.isfile`(`L182`)** —— 磁盘无文件 → 空。
  4. `direx = dir_exclude_files(repo)`(`L246` → `L137-156`):DIR_EXCLUDES 9 目录(`L69-80`)下 **`os.path.isdir` + `os.walk`(`L146-150`)** 现存文件 —— 磁盘无目录 → 空。
- 触发链:「每次备份重生成」是因为上传/备份链路每次都会调用:
  - `scripts/upload_r2.py:2374-2378` 每次 `upload-large-json` 跑 `--print`;`large_json_excludes.py:280-296 print_mode` 的 `L285 rel_paths = default_mode(repo)` **先跑 default_mode(写)**。
  - `scripts/staticdata_backup_async.sh:176` / `scripts/staticdata_sync.sh:195` 每次备份直接跑默认模式(=`default_mode`)刷区块。
- 推论:sparse-checkout 镜像(`data/` 未 checkout、磁盘无大文件)上四路全空 → 区块被写成空(这就是 #136 根因,2026-09-30 已实测命中一次 mac 侧镜像仓)。

### 问2:staticdata 备份提交走精准 add 还是 `git add -A`?

**结论:默认 `git add -A`(生产机);非生产机显式放行(`STATICDATA_ALLOW_PUSH=1`)走数据闸门精准 add(只 add 放行清单)。**

证据:
- `scripts/staticdata_backup_async.sh:329 git -C "$STATICDATA_REPO" add -A`(生产机/守卫降级分支);`L307-323` 非生产机显式放行分支 `git add -- "$_f"` 逐文件精准 add。
- `scripts/staticdata_sync.sh:227 git -C "$STATICDATA_REPO" add -A`;`L221` 数据闸门分支精准 add。
- 生产机判定 = `scripts/staticdata_write_guard.py --check-write-auth`(仓库路径前缀 `/home/ubuntu/` = 生产机,`L17`),backup_async.sh:237-289 消费;守卫 rc=0 时生产机走原逻辑(add -A)。
- 头注佐证:backup_async.sh:25「幂等: rsync + git add -A」。

### 问3:「#126 收口效果被随时间侵蚀」判断是否成立?

**结论:作为普适判断不成立;仅在「刷区块环节失效」的场景下退化成立。** 真正的风险不是「随时间渐进侵蚀」,而是两条已识别的异常路径(瞬时灾难)。

判据(成立 ⇔ 下条件):
- **成立**⇔ 刷区块环节在 `git add -A` 前失效:①sparse-checkout 镜像上 desired 四路全空 → 区块被写空(#136,26k `fund_nav` 回流);②`large_json_excludes.py` 运行失败但调用方 best-effort 继续(backup_async.sh:179 / sync.sh:196 置 FAIL 继续 add -A)。
- **不成立(反例)**⇔ 刷区块正常:每次备份先 `default_mode` 重生成区块(backup_async.sh:176 → L329 add;sync.sh:195 → L227 add),9 目录每日新增文件**在下一次备份时被纳入区块**,`git add -A` 时已 ignore、不会被暂存 → 新文件不会回流 git,收口效果不被侵蚀。且 `existing` 路(区块已有 ∪ 磁盘仍在)保证 `git rm --cached` 后的文件持续被 ignore 直到磁盘消失。
- 实测佐证(不成立反例):正常生产机磁盘文件齐全时 desired 非空 → 每次重生成覆盖全部现存文件(2026-09-29 实测区块 31708 行与磁盘文件数相等)。

**关键含义**:修复重点不是「改成静态列举」(静态反而更易随时间过期),而是保证「每次重生成」在异常数据源(sparse 镜像)上不把区块写空 —— 即 #136 的 fail-loud。

## Part B:#136 fail-loud 保护

### 改动前后对照

改动点:`scripts/large_json_excludes.py:258-269`(default_mode 内,写回前)。

- 改前:`before, after, _ = _parse_gitignore(text)` → 直接 `new_text = before + _render_block(desired) + after`;desired 空时区块被写成只有注释的空块并写回。
- 改后:
  - `before, after, entries = _parse_gitignore(text)`;
  - 计算 `block_excludes = [e for e in entries if e and not e.startswith("#") and e.startswith("/data/")]`(区块内非注释 `/data/` 排除条目);
  - `if block_excludes and not desired: sys.exit(...)` —— **原区块有排除条目但 desired 空 = 数据源异常 → 拒绝写 + 非零退出 + stderr 打印明确原因**;
  - `block_excludes` 空 + desired 空 = 幂等放行(正常,首次/空区块),行为不变。

### 退出码传播确认

- 调用方仅区分「零/非零」:
  - `scripts/upload_r2.py:2377-2378` 已有 `if r.returncode != 0: sys.exit(f"✗ large_json_excludes.py --print 失败: {r.stderr[:500]}")` —— fail-loud 的 stderr 原因会随 `r.stderr[:500]` 带出,传播正确,不会被误判为其它失败(消息明确)。
  - `scripts/staticdata_backup_async.sh:176-180` / `scripts/staticdata_sync.sh:195-196` 已有失败分支(置 STATICDATA_FAIL/SYNC_FAIL + 明确日志,不再静默继续)。fail-loud 让刷区块失败**至少置 FAIL**,告别静默。
- 退出码用 `sys.exit(msg)`(默认 1),与 `--check-staged` 的 rc 语义(0/1/2)不冲突——本路径调用方只看非零。

### 同类错误面清单(§23.2)

全仓所有会写受管区块/走 `default_mode` 的路径(一个根因点全覆盖,无逐 caller 补丁):

| 路径 | 调用形态 | 会写区块? | fail-loud 覆盖 |
|---|---|---|---|
| `staticdata_backup_async.sh:176` | 默认模式 → default_mode | 是 | ✓ |
| `staticdata_sync.sh:195` | 默认模式 → default_mode | 是 | ✓ |
| `upload_r2.py:2374-2378`(upload-large-json) | `--print` → print_mode → default_mode | 是 | ✓ |
| `migrate_large_json_out_of_git.sh:37` | `--print` → print_mode → default_mode | 是 | ✓ |
| `check_large_json_excluded.py:47` | `--check` → check_mode | 否(只读) | 不适用 |
| `backup_async.sh:365` / `sync.sh:239` | `--check-staged` → check_staged_mode | 否(只读) | 不适用 |
| `staticdata_write_guard.py` | `--check-write-auth`/`--check-fresh` | 否(纯读) | 不适用 |

- `--check` / `--check-staged` 在 `large_json_excludes.py` main() 分派(`L366-373`)直接走只读模式,不经 default_mode/print_mode,**不受 #136 影响**(已 grep 确认)。
- 其余 `.gitignore` 写点(`notify.py`/`backup_db.sh`)只读/引用 trade 仓的 data/backups 忽略,不碰 staticdata 受管区块,无关。

## 自测结果(全在 /tmp 临时仓,零接触生产 staticdata)

| # | 场景 | 预期 | 实际 | PASS |
|---|---|---|---|---|
| ① | 区块非空 + desired 空(模拟 sparse 镜像) | 拒绝写 + 非零退出 + `.gitignore` 逐字节未变 | exit=1,stderr 打原因,`cmp` = SAME | ✓ |
| ② | 区块无 `/data/` 条目 + desired 空 | 幂等放行 exit 0 | 首跑 exit=0(补注释),复跑 exit=0(无变化) | ✓ |
| ③ | 区块非空 + desired 非空(tracked 21MB 文件) | 正常写回 exit 0(回归不破) | exit=0,写回 1 条目(磁盘现存),`--print` 形态 exit=0 + 正常清单 `fund_nav/000002.json 22020096` | ✓ |
| ④ | `--print`(upload_r2.py:2374 同款调用)在失败场景① | 非零退出 + stderr 原因可被上层捕获,非静默 | exit=1,stderr 含完整原因,stdout 空(清单未产出) | ✓ |

PASS 数:4/4(场景②含幂等复验)。

## §23.5 复现段(可直接粘的命令)

```bash
PY=/Users/linhuichen/code/trade/.venv/bin/python
EXC=/path/to/scripts/large_json_excludes.py   # 替换为实际路径
TMP=/tmp/lje136_repro
rm -rf $TMP && mkdir -p $TMP

# 场景① 区块非空 + desired 空 → 拒绝写 exit 1
mkdir -p $TMP/s1 && git -C $TMP/s1 init -q
cat > $TMP/s1/.gitignore <<'EOF'
# >>> large-json auto-generated >>>
# 由 scripts/large_json_excludes.py 自动维护(2026-09-25), 勿手改。
/data/fund_nav/000001.json
# <<< large-json auto-generated <<<
EOF
cp $TMP/s1/.gitignore $TMP/s1/.gitignore.bak
$PY $EXC --repo $TMP/s1; echo "exit=$?"; cmp $TMP/s1/.gitignore $TMP/s1/.gitignore.bak && echo SAME

# 场景② 区块无 /data/ 条目 + desired 空 → exit 0
mkdir -p $TMP/s2 && git -C $TMP/s2 init -q
cat > $TMP/s2/.gitignore <<'EOF'
# >>> large-json auto-generated >>>
# <<< large-json auto-generated <<<
EOF
$PY $EXC --repo $TMP/s2; echo "exit=$?"

# 场景③ 区块非空 + desired 非空(tracked 21MB) → 正常写回 exit 0
mkdir -p $TMP/s3/data/fund_nav && git -C $TMP/s3 init -q
cat > $TMP/s3/.gitignore <<'EOF'
# >>> large-json auto-generated >>>
# <<< large-json auto-generated <<<
EOF
dd if=/dev/zero of=$TMP/s3/data/fund_nav/000002.json bs=1M count=21 2>/dev/null
git -C $TMP/s3 add data/fund_nav/000002.json
git -C $TMP/s3 -c user.email=t@t -c user.name=t commit -q -m init
$PY $EXC --repo $TMP/s3; echo "exit=$?"

# 场景④ --print 调用形态(同 upload_r2.py:2374)在场景① → exit 1 + stderr 原因
$PY $EXC --print --repo $TMP/s1 >/dev/null; echo "exit=$?"
```

## 后续(遗留)

- #150 问3 的结论意味着无需把区块改静态列举;但「刷区块失败被 best-effort 吞」的路径已由 FAIL 标志兜底,可观察云上心跳确认刷区块环节不再静默。
- 建议 #126 收口后的下一个备份 commit 出现后,抽查 staticdata 仓 `git log origin/main -1` 确认备份提交恢复(已在台账 #126 遗留②列出,不属本任务)。
