# §0 生产验证报告:restore-r2-backup.sh 默认桶修复(云上真跑)

> 验证者:tester agent(独立上下文,只读;不 commit)。日期 2026-10-08。
> 验证对象:main tip **`e4fecce2c`**(= 云上 `origin/main`),文件 `scripts/restore-r2-backup.sh` sha256 `de79deab7f4965903146614fed4af1bebc021393ae7db0fe3db0d9eb45826af6`。
> **为什么在云上验**:本机 mac bash 3.2.57 + python3(develop 环境);生产是 Ubuntu bash 5.1.16 → DR 脚本必须在生产形态下真跑一遍。
> 环境:云上 `ubuntu@122.51.111.173`,代码树 `/home/ubuntu/code/trade-data-signal`(tip e4fecce2c,工作树干净),
> 运行仓 `/home/ubuntu/code/trade-data`(`.env` 与真实 `data/` 在此;`scripts/` 是前者的 symlink),bash 5.1.16。
> 生产调用形态(照 systemd 单元:`EnvironmentFile=/home/ubuntu/code/trade-data/.env` + `REPO=/home/ubuntu/code/trade-data` + `GIT_REPO=/home/ubuntu/code/trade-data-signal`)。
>
> **零副作用声明**:全程只有 R2 **GET/list**(无 PUT/DELETE);所有脚本实跑落在 `mktemp -d` + `--out-dir` 临时目录;
> 真实 `data/` 两处(`trade-data` 70 文件 / `trade-data-signal` 95 文件)`名称|大小|mtime` 快照前后 **diff 空**;
> `git status --porcelain` = 0;无邮件/飞书/告警外发;`/tmp/restore-0verify*` 全部删除(`TMP_CLEAN_PASS`)。
>
> **总判定:必查 7 项全 PASS**(含 red→green 云上对照);**发现 1 条与本次修复无关但影响云上 DR 可用性的既有缺口**(§4.1)+ 若干未测项(§4)。

---

## 一、逐项判定

| # | 必查项 | 判定 | 关键证据 |
|---|---|---|---|
| 1 | 代码到位(三类 sha256 一致 + 工作树干净) | **PASS** | 云上文件/云上 commit blob/本机 commit blob 三处 sha256 均 `de79deab…`;`git log -1` = `e4fecce2c` = `origin/main`;porcelain 0 行 |
| 2 | 老桶 key 真能恢复(核心) | **PASS** | 默认探测 `✓ 命中桶 signal-backup`,exit=0,落 47,104 B `.tar`;md5 三源闭合(见 §2.2) |
| 3 | 新桶路径未被破坏 | **PASS** | `✓ 命中桶 signal-backup2`(首选即命中),exit=0,md5 == ETag;同 key 在老桶 404(证明非回落命中) |
| 4 | 负控(响亮失败) | **PASS** | 不存在 key:exit=1 + 两桶 404 明细 + 零落文件;钉错桶:exit=1 + 零落文件 |
| 5 | 非 404 不误回落 | **PASS** | 首选/回落位凭据置坏 → `status=400 InvalidArgument` **直接失败**,exit=1,零落文件,未回落、未伪装成「全部 404」 |
| 6 | 生产无副作用 | **PASS** | data/ 两处前后 diff 空;R2 两桶清单逐字段不变 + 今日(2026-10-08)LastModified = 0 条;无写/无通知通道;临时目录全清 |
| 7 | 诚实标注 | **PASS(带缺口)** | 见 §4(云上裸调用缺口 / 未构造 403·5xx / 大件验法 / bash 版本面) |

**附加(超出必查项)**:①**red 先验**(旧版 `d86527912` blob 在云上跑同一 key → `404 NoSuchKey` exit=1 零落文件 ⇒ 修复确为行为分水岭);②env 旋钮云上复测;③CLI 边界;④37M 生产件恢复 + sqlite 完整性。

---

## 二、原始证据(命令 + 输出)

### 2.1 代码到位(必查项 1)
```
$ cd /home/ubuntu/code/trade-data-signal
$ sha256sum scripts/restore-r2-backup.sh
de79deab7f4965903146614fed4af1bebc021393ae7db0fe3db0d9eb45826af6  scripts/restore-r2-backup.sh
$ git show e4fecce2c:scripts/restore-r2-backup.sh | sha256sum
de79deab7f4965903146614fed4af1bebc021393ae7db0fe3db0d9eb45826af6  -
# 本机(参照):git show e4fecce2c:… 与 工作树文件 md5/sha 同为 de79deab…
$ git log -1 --oneline                      → e4fecce2c fix(restore): restore-r2-backup.sh 默认桶失效 -> 跨桶候选探测…
$ git log -1 --oneline origin/main          → e4fecce2c(云上 main-merge 已同步,已核)
$ git status --porcelain | wc -l            → 0
$ bash --version | head -1                  → GNU bash, version 5.1.16(1)-release (x86_64-pc-linux-gnu)
$ bash -n scripts/restore-r2-backup.sh      → EXIT=0(shellcheck 云上未安装,跳过)
```

### 2.2 核心:老桶 key 默认探测恢复(必查项 2)
```
$ cd /home/ubuntu/code/trade-data && bash scripts/restore-r2-backup.sh --out-dir <mktemp-d> decommissioned-small-baks-20260903.tar.gz
还原 decommissioned/decommissioned-small-baks-20260903.tar.gz → /tmp/restore-0verify/t2.QJy2T5/ ...
✓ 命中桶 signal-backup | 还原 11259B(网络) → /tmp/restore-0verify/t2.QJy2T5/decommissioned-small-baks-20260903.tar (47104B)
T2 EXIT=0
-rw-rw-r-- 1 ubuntu ubuntu 47104 … decommissioned-small-baks-20260903.tar
bc3cc04496012907583d59b5eb4d0963  …/decommissioned-small-baks-20260903.tar
```
**独立取证(来源标明)**:①脚本输出行(上方);②不走脚本逻辑的独立直连 GET(同进程外单独调用 `upload_r2.s3_request("GET", …, bucket="signal-backup")`):
```
direct GET bucket=signal-backup key=decommissioned/decommissioned-small-baks-20260903.tar.gz status=200 bytes=11259
md5(network bytes) = 6f905c9b077884d1b17df39228865948     ← == R2 list ETag(第③源)
md5(gunzip .tar)   = bc3cc04496012907583d59b5eb4d0963     ← == 脚本落盘文件 md5(链条闭合)
```
> 口径说明(防误读):R2 `ETag 6f905c9b…` 是**压缩体(11,259 B)的 md5**,不是落盘 `.tar` 的 md5;落盘 47,104 B 的 md5 = 独立 gunzip 结果的 md5。三源(脚本输出 / 独立 GET / list ETag)一致。

### 2.3 新桶首选未破坏(必查项 3)
```
$ bash scripts/restore-r2-backup.sh --out-dir <mktemp-d> r2-cleanup-a-head-20261007.json
✓ 命中桶 signal-backup2 | 还原 4658B(网络) → …/r2-cleanup-a-head-20261007.json (4658B)      T3 EXIT=0
a9711b9c660b122ccba32363904fe851  …/r2-cleanup-a-head-20261007.json      ← == 该对象 list ETag(逐位)
独立直连: GET @signal-backup2 status=200 md5=a9711b9c660b122ccba32363904fe851
同 key 在老桶 status=404  ⇒ 命中确为新桶首选,不是「永远回落老桶」
```
(新账号凭据在云上 `.env` 齐备:`R2_BACKUP2_ENDPOINT/BUCKET/ACCESS_KEY_ID/SECRET_ACCESS_KEY` 均在,路由生效——见 2.5 首选桶报错显示新桶主机凭据被采纳。)

### 2.4 负控(必查项 4)
```
① 不存在 key(默认探测):
还原 decommissioned/no-such-key-xyz-20261008.gz → …
✗ 目标对象在所有候选桶均不存在(全部 404): decommissioned/no-such-key-xyz-20261008.gz
  探测结果: signal-backup2=404, signal-backup=404      T4A EXIT=1     tempdir 空(零落文件)
② --bucket 钉错桶(实体在老桶,钉新桶):
✗ 目标对象在所有候选桶均不存在(全部 404): … 探测结果: signal-backup2=404   T4B EXIT=1   tempdir 空
③ 补测(--bucket signal-backup + 不存在 key):EXIT=1,零落文件
```

### 2.5 非 404 不误回落(必查项 5)
```
① 首选桶(新账号)凭据置坏 R2_BACKUP2_ACCESS_KEY_ID=bogus-ak-0verify(16 字符,真 AK 32 字符):
✗ 下载失败 signal-backup2/decommissioned/… status=400 <Error><Code>InvalidArgument</Code>
  <Message>Credential access key has length 16, should be 32</Message></Error>        T5A EXIT=1
  ⇒ 未回落老桶(输出里无「命中桶 signal-backup」),tempdir 空
② 回落位(老账号)凭据置坏 R2_S3_ACCESS_KEY_ID=bogus-ak-0verify(首选新桶正常→404,回落位非404):
✗ 下载失败 signal-backup/decommissioned/… status=400 <Error><Code>InvalidArgument</Code>…  T5B EXIT=1
  ⇒ 未把硬错误伪装成「全部 404」(输出里无「均不存在」字样),tempdir 空
```
> 构造局限(诚实标注):非 404 是用「凭据置坏 → 400」构造的;真·403 无权限、5xx 未构造(无从造出)。

### 2.6 生产无副作用(必查项 6)
```
data/ 快照判据 = find data -maxdepth 1 -type f -printf '%f|%s|%T@\n' | sort,运行前(07:40)与收尾(07:44)各抓一次:
  diff → TD_DATA_END_DIFF_EMPTY_PASS (70 files) / TDS_DATA_END_DIFF_EMPTY_PASS (95 files)
  (trade-data 非 git 仓,故只做快照 diff;trade-data-signal git status --porcelain = 0)
R2 无写:两桶 decommissioned/ 清单在 07:38(运行前)、07:41、07:44 三次抓取逐字段一致
  old: 2 keys(small-baks 11259 / 6f905c9b… ; etf db 10968910 / 1b82c2dd…)
  new: 6 keys(含 558,045,538×2 .zst、20,456,524 tar.gz、4658 json、4,346,185 json、159 json)
  LastModified 含「2026-10-08」条数 = 0 / 0   ⇒ 无任何对象被今次会话写过
无外发:grep -nEi "notify|feishu|mail|sendmail|curl|smtp|requests\.post|PUT|DELETE" scripts/restore-r2-backup.sh → 无命中
        脚本内 s3_request 仅 1 处且 method="GET"(L109)
临时目录:rm -rf /tmp/restore-0verify* → TMP_CLEAN_PASS(零残留)
```

### 2.7 red 先验(旧版在云上真失败,证修复是行为分水岭)
```
$ git show d86527912:scripts/restore-r2-backup.sh > /tmp/…/oldmirror/scripts/(sha256 822c84d1…)
$ cd /tmp/…/oldmirror && REPO=… GIT_REPO=… bash scripts/restore-r2-backup.sh decommissioned-small-baks-20260903.tar.gz
从 signal-backup/decommissioned/decommissioned-small-baks-20260903.tar.gz 还原 → data/ ...   ← 旧版打印老桶名…
✗ 下载失败 … status=404 <Code>NoSuchKey</Code> …                                            ← 实际查的是 BACKUP_BUCKET(=新桶)
旧版 EXIT=1;镜像 data/ 未创建(零落文件)
```
旧版代码事实:`s3_request("GET", key, bucket=upload_r2.BACKUP_BUCKET)` 单桶写死 + echo 标签硬编码 `signal-backup`(名实不符的 404 症状)。
新版同一 key、同一环境 → exit=0 命中老桶(§2.2),并复跑一次结果逐位一致(§2.8 C4)。

### 2.8 附加:env 旋钮 / CLI 边界 / 37M 生产件(云上)
```
[P2] R2_LEGACY_BACKUP_BUCKET=bogus-legacy-xyz → ✗ 均不存在; 探测结果: signal-backup2=404, bogus-legacy-xyz=404; EXIT=1
[P3] 同上 + R2_RESTORE_BUCKET_FALLBACKS=signal-backup → ✓ 命中桶 signal-backup; EXIT=0; md5 bc3cc044…(第三桶零代码追加成立)
[C1] --help            EXIT=0
[C2] --bogus           EXIT=2(✗ 未知选项: --bogus)
[C3] --bucket 缺参      EXIT=2(✗ --bucket 缺参数 + usage)
[C5] 无参数            EXIT=2(usage)
[C4] 等号形式 --bucket=signal-backup --out-dir=… → EXIT=0,md5 bc3cc044…(与空格形式一致)
[S4] 37M 主归档 etf_national_team.db.bak-backfill-20260728-232308.gz:
     ✓ 命中桶 signal-backup | 还原 10968910B(网络) → 38793216B; EXIT=0
     体积 38,793,216 B == manifest 原始体积;python sqlite3 pragma integrity_check = ('ok',) / 4 张表
     (云上 .env R2_UPLOAD_HTTP_TIMEOUT=600,大件不被 30s 默认连接超时卡)
```
> ⚠️ 量 exit code 时**不要接 `| head`**:我第一版用管道截断,`PIPESTATUS` 被 SIGPIPE 污染得 141;去掉管道复测真值 = 2(§2.8 C3/C5)。记此防后来者误读。

---

## 三、复现命令段(云上,只读,可直接重跑)

```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173
TD=/home/ubuntu/code/trade-data; TDS=/home/ubuntu/code/trade-data-signal
export REPO=$TD GIT_REPO=$TDS          # 生产形态(照 systemd 单元;缺此则报「无 .env」,见 §4.1)

# ① 代码到位
cd $TDS && sha256sum scripts/restore-r2-backup.sh && git log -1 --oneline && git status --porcelain

# ② 核心:老桶 key 默认探测(落临时目录,绝不写真实 data/)
D=$(mktemp -d); cd $TD && bash scripts/restore-r2-backup.sh --out-dir $D decommissioned-small-baks-20260903.tar.gz
md5sum $D/*          # 期望 bc3cc04496012907583d59b5eb4d0963

# ③ 新桶首选
D2=$(mktemp -d); bash scripts/restore-r2-backup.sh --out-dir $D2 r2-cleanup-a-head-20261007.json
md5sum $D2/*         # 期望 a9711b9c660b122ccba32363904fe851

# ④ 负控 / 非404
D3=$(mktemp -d); bash scripts/restore-r2-backup.sh --out-dir $D3 no-such-key-xyz.gz; echo $?   # 期望 1
R2_BACKUP2_ACCESS_KEY_ID=bogus R2_BACKUP2_SECRET_ACCESS_KEY=bogus \
  bash scripts/restore-r2-backup.sh --out-dir $D3 decommissioned-small-baks-20260903.tar.gz    # 期望 400 硬失败, exit 1

# ⑤ 无副作用核对
find $TD/data -maxdepth 1 -type f -printf '%f|%s|%T@\n' | sort > /tmp/a; # …跑完后再抓 → diff 应空
python3 scripts/upload_r2.py list decommissioned/ signal-backup
python3 scripts/upload_r2.py list decommissioned/ signal-backup2   # 看 LastModified 无今日
```

---

## 四、诚实缺口 / 未测项(§5.1④)

### 4.1 云上「裸调用」不可用(既有缺口,非本次修复引入 → 但影响云上 DR 可用性,建议上报拍板)
- 现象(实测):不设 `REPO`/`GIT_REPO` 时,`bash scripts/restore-r2-backup.sh …` → `无 .env: 尝试过 ['/home/ubuntu/code/trade-data-signal/.env', '.env']`,**exit=1**。VD 从两个目录(代码仓 `trade-data-signal`、运行仓 `trade-data`)调用均如此。
- 根因:`.env` 在 `/home/ubuntu/code/trade-data/`(运行仓),而 `upload_r2.ROOT = Path(__file__).resolve().parent.parent` 经 symlink 解析到 `trade-data-signal`;`_find_env()` 顺序 = `ROOT/.env → $GIT_REPO/.env → $REPO/.env → /Users/linhuichen/code/trade/.env`(最后一条是 mac 专属硬编码)→ 云上必须靠 `REPO`/`GIT_REPO` 指路。
- **既有行为佐证**(非本次引入):旧版 `d86527912` blob 在同一云环境裸调用同样 `无 .env`(exit=1)。
- 影响:`docs/decommissioned-backups.md` 恢复节给的是 mac 路径命令;云上按文档原样跑**必失败**。云上正确调用 = `cd /home/ubuntu/code/trade-data && REPO=$PWD GIT_REPO=/home/ubuntu/code/trade-data-signal bash scripts/restore-r2-backup.sh …`(systemd 单元已如此设)。
- 处置建议(未实施,交主控/用户定):①文档补云上调用示例一行;或 ②`_find_env()` 增候选 `TRADE_DIR/.env`/运行仓回退。**本次未改任何代码**(§23.7 冻结契约 + 本任务只验)。

### 4.2 未实测 / 推断项
1. **非 404 只覆盖 400**:真 403 无权限、5xx 服务端错未构造(无从造出);「非 404 一律不回落」的成立边界 = 代码路径 L114-118(读码确认 + 400 实测),403/5xx 属同分支推断。
2. **大件验法**:37M 件用「体积 == manifest 原始体积 + sqlite `pragma integrity_check=ok` + 表数 4」验,未做网络字节 md5 vs ETag(等价于再拉 10.9MB);两桶的 2 个 558MB `.zst` 未测(非 `.gz` 走原样落盘分支,与本次修复无关)。
3. **同名 key 跨桶优先取新桶**未测:当前两桶 `decommissioned/` key 集不相交(实测 old=2 / new=6),无实验样本。
4. **bash 版本面**:本轮云上实测 = bash 5.1.16(生产形态);mac(bash 3.2.57)侧由 reviewer 早前跑过,我未复跑,「两版本行为一致」属跨报告推断(脚本无 3.2 不兼容语法:case/数组 `${1#*=}` 均可)。
5. `shellcheck` 云上未安装(仅 `bash -n` PASS);`env -u` 类清理在 mac/zsh 与 bash 下写法不同,不影响脚本本体。
6. **R2 无写的判据**=清单 LastModified/ETag 不变 + 代码只发 GET;未用 Cloudflare 审计日志(账号侧无此通道),理论上「写入后回滚到原值」无法被本判据区分(实际不可能,脚本无写路径)。

---

## 五、结论

- **必查 7 项全 PASS**,含核心链路(老桶恢复 exit=0 + md5 三源闭合)、新桶首选、负控响亮失败、非 404 不回落、零副作用。
- 云上 red→green 对照成立:旧版 `404 NoSuchKey` / 新版 `✓ 命中桶 signal-backup`(同环境同 key)。
- 唯一新发现是 **§4.1 云上裸调用缺 env → 「无 .env」**(既有行为,不阻断本次修复,但 DR 脚本在云上"照文档跑"必失败。建议主控决定是否补文档/改 `_find_env`。
- 本报告**不 commit**(未跟踪文件);云上 `/tmp/restore-0verify*` 已全清。
