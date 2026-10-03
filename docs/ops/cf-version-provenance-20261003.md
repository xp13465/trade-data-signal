# CF 未部署悬挂版本 b1f38e8c 溯源 + 其余 secret git 历史泄露扫描(2026-10-03)

> 触发:2026-10-03 晚轮换 PURGE_SECRET 时 `wrangler secret put` 被 CF 拒绝(报「the latest version of your Worker isn't currently deployed」),账户存在未部署悬挂版本 `b1f38e8c`(2026-10-03 20:47 创建,来源不明)。本报告回答:它是什么、谁创建、对线上有无影响、怎么根治;并顺带完成其余 secret 的 git 历史泄露扫描。
> 全程只读调研(不部署/不删除/不 secret put),处置方案只给不动手。
> 报告不含任何 secret 明文(扫描只记「有无 + commit + hash 前缀」)。

## 0 结论速览

- **b1f38e8c = Cloudflare Workers Git integration(Builds)对非 main 分支 push 自动触发的 preview build 产物**,非手工、非恶意、非空版本、非未审代码。
  - 时间线钉死:20:47:30 push 到 `feat/alertchain-hardening-20261003` 分支 → **22 秒后** 20:47:52 CF 创建版本 b1f38e8c,alias=分支名连字符化(`feat-alertchain-hardening-20261003`),has_preview=true。
  - 官方文档(Build branches)佐证:非生产分支 push → preview build(仅构建+preview 上传,**不部署**);生产分支 push → build+deploy。`wrangler preview` 的 `--name` 默认取当前 git branch,与 alias 命名吻合。
  - 本地/云上零手工痕迹:zsh_history 无 wrangler;implementer/reviewer 进度文件无 wrangler;云上 `which wrangler` 为空、journalctl 20:45-20:52 无 CF 动作。
- **对线上影响 = 无**:未部署(dangling),不接流量;内容=20:47 分支 HEAD(worker 代码 = 已审查的 alertchain 修复,后续经 rebase 以 c60b8b5af 形态并入 main,见 merge 3d2fa44e6),非「未审代码」。当前 latest version = 62ae9909(版号 8276,22:51,已部署)⇒ **当前 secret put 守卫已放行**(今晚轮换已因此成功)。
- **根治(方案,未执行)**:见 §4.2(治本=关 Preview Builds / 治标=改 secret 前检查 latest==deployed)。
- **secret 历史泄露扫描结论**:仅 **PURGE_SECRET 曾在 git 历史出现真实明文**(2026-09-12 20:07 commit 6f7e5b13a,24 处同一 64 字符 hex 值;同日 21:12 fd95be096 删除,现在 HEAD 无明文)。其余点名 secret(SUBSCRIBE_PASSWORD / SESSION_SECRET / _SESSION_SECRET / GITEE_CLIENT_SECRET / CLOUDFLARE_API_TOKEN)历史**零字面量**,均只以环境变量/`${{ secrets. }}` 引用或空模板形态出现。PURGE_SECRET 已于今日轮换(旧值失效)。

## 1 CF 侧事实(只读查询,原始输出见复现段)

### 1.1 版本链 `wrangler versions list`(2026-10-03 23:13 查询,10 条)
| 版号 | version id(前缀) | 创建时间 UTC | 北京时间 | 触发 | 备注 |
|---|---|---|---|---|---|
| 8267 | ff15acf7 | 12:34:41 | 20:34 | version_upload | 已部署(0d90e5fd) |
| **8268** | **b1f38e8c** | **12:47:52** | **20:47** | **version_upload** | **alias=feat-alertchain-hardening-20261003,未部署** |
| 8269 | 402c4455 | 14:26:24 | 22:26 | create_version_api | 「Updated secret PURGE_SECRET」(versions secret put 产物) |
| 8270 | a52cb0be | 14:30:30 | 22:30 | version_upload | 已部署(1285901e,今晚「先 deploy 解锁」) |
| 8271 | a0e5d628 | 14:30:48 | 22:30 | secret | 已部署(4824cd1c,secret triggered) |
| 8272 | 3a53f79b | 14:35:16 | 22:35 | version_upload | alias=feat-purge-secret-rotate-20261003,未部署 |
| 8273 | 514379a4 | 14:38:18 | 22:38 | version_upload | 已部署(80c3e272) |
| 8274 | d8b5982b | 14:47:57 | 22:47 | version_upload | alias=review-hc-timer-mount,未部署 |
| 8275 | 763e41d6 | 14:50:04 | 22:50 | version_upload | 已部署(80ebc37d) |
| 8276 | 62ae9909 | 14:51:08 | 22:51 | version_upload | 已部署(2118d4e5)=当前 latest==deployed |

- b1f38e8c 元数据:source=wrangler、author_email=sugas13465@gmail.com、has_preview=true、annotations=`workers/alias: feat-alertchain-hardening-20261003` + `workers/triggered_by: version_upload`。
- `wrangler deployments list`(10 条)中**无 b1f38e8c** ⇒ 未部署悬挂确认。轮换时(21 点档)latest=8268 ⇒ 触发「latest version isn't currently deployed」守卫(报错原文见 purge-rotate-20261003.md §3.1)。

### 1.2 内容归属
- 20:47:30 push 时分支 HEAD = 62a69f1d6(reviewer 报告 commit,基于 cf68c7270)。其 worker 代码 = cf68c7270(alertchain 云体检 D3/D7 加固,142 pytest PASS + 13 反例,reviewer 独立审查 PASS)。
- 该代码后续 rebase 为 c60b8b5af,经 `3d2fa44e6 merge(feat/feat/alertchain-hardening-20261003)` 并入 main——**b1f38e8c 内容 = 已审查、已并入 main 的规范代码**(快照时点的),非空版本、非未审代码、非异常内容。

## 2 溯源:谁在 20:47 动了 CF

### 2.1 证据链(时间线)
| 北京时间 | 事件 | 证据 |
|---|---|---|
| 20:13:36 | 分支 feat/alertchain-hardening-20261003 创建 | `.git/logs/refs/heads/feat/alertchain-hardening-20261003` |
| 20:30:09 | implementer 完成修复,commit cf68c7270 push origin | /tmp/agent-progress-hc-batchA.md |
| 20:33-20:46 | reviewer 独立审查(建 detached worktree /private/tmp/hc-review-feat @ cf68c7270,142 测试 PASS) | /tmp/agent-progress-hc-batchA-review.md + `git worktree list` |
| 20:47:02 | reviewer 报告 commit 62a69f1d6 完成,准备 push | 同上 |
| **20:47:30** | **reviewer push 62a69f1d6 到 origin/feat/alertchain-hardening-20261003** | 同上(「报告commit 62a69f1d6 已push到feat分支」) |
| **20:47:52** | **CF 创建版本 b1f38e8c(version_upload,alias=分支名,未部署)** | `wrangler versions list --json` |

### 2.2 人工 vs 自动的判定
- **排除本地手工**:zsh_history 无 `wrangler` 记录;implementer/reviewer 两个进度文件通篇无 wrangler 命令;主仓 reflog 20:47 前后无 main push(GH Actions deploy-cf 只监听 main,20:47 无 main 活动)。
- **排除云上**:云上无 wrangler 二进制;journalctl 20:45-20:52 仅盘后定时任务(brief-push/fetch-news/schedule-monitor)+ 腾讯云 stargate 心跳,无 CF 动作。
- **指向 CF Builds 自动触发**:push 后 **22 秒**创建版本(人做不到);alias=分支名连字符化;has_preview=true;官方「Build branches」文档:非生产分支 push → preview build;`wrangler preview --name` 默认=当前 git branch;仓库既有文档确认 Git integration 与 GH Actions 并存(deploy-cf.yml 注释:Git integration 作兜底)。
- 补强:purge-rotate-20261003.md §3.2 观察「当天 16:46-21:06 有多笔手工部署/上传活动」与该机制吻合(当日下午主仓连续 merge 多个分支 push main/feat,每次 push 触发 GH Actions 或 CF Builds)。

## 3 官方文档佐证(§5.1:外部系统先查官方)
1. **CF Workers Builds「Build branches」**(developers.cloudflare.com/workers/ci-cd/builds/build-branches/,抓取于 2026-10-03):「commits on the production branch produce a production build… build command, followed by the deploy command」「preview builds are builds for branches that are not your production branch… when enabled, every push to a branch that is not your production branch triggers a preview build(runs build command, followed by the Preview command)」⇒ 非生产分支 push 只构建+preview 上传,**不部署**。
2. **`wrangler preview --help`**(本机 wrangler 4.147.0):`--name: Name of the Preview (defaults to current git branch)` ⇒ preview 命名的 alias 与分支名对应。
3. **`wrangler versions upload --help`**:`--preview-alias: Name of an alias for this Worker version` ⇒ versions list 中 `workers/alias` 的来源机制。
4. **CF 服务端报错原文**(purge-rotate-20261003.md §3.1 实测记录):「…the latest version of your Worker isn't currently deployed. This limitation exists to prevent accidental deployment when using Worker versions and secrets together. To resolve: (1) use `wrangler versions secret put`… (2) deploy the latest version first, then modify secrets.」⇒ 守卫语义官方自述。
5. UNVERIFIED:社区搜索(WebSearch)在本环境无结果(US-only 限制),未取得第三方社区印证;「Enable Preview Builds 当前开关状态」需 dashboard 确认(CLI 不可查)。

## 4 影响面与根治(只给方案,未执行)

### 4.1 影响面
- b1f38e8c 未部署(dangling)⇒ 不接线上流量,对 ss.fx8.store 无影响。
- 唯一的实际影响 = 守卫效应:它是当时(21 点轮换时)的 latest 且未部署,挡住传统 `wrangler secret put`。**当前 latest=8276 已部署,守卫已不触发**(今晚轮换已成功验证新 200/旧 403)。
- 复发风险:未来每次 push 非 main 分支(Git integration preview build 开启时)都会再产生 dangling 版本,再次挡住 secret put ⇒ 必须根治或改 SOP。

### 4.2 根治方案(供主控拍板,未动手)
| 方案 | 动作 | 风险/回退 |
|---|---|---|
| **A 治本(推荐,需 dashboard)** | dashboard → trade-data-signal → Settings → Builds → 关「Enable Preview Builds」(或断开 Git integration,GH Actions 已是主路径) | 低;回退=重新勾选。副作用:feat 分支不再有 CF preview(业务目前无用例) |
| **B 治标(SOP)** | 改 secret 一律先 `wrangler versions list` 检查 latest==deployed;不等 -> 先 `wrangler deploy` 再 `secret put`(官方解法2,今晚已验证),或官方解法1 `versions secret put` + `versions deploy` | 无;就是今晚流程常态化。回退=仍可走 A |
| C b1f38e8c 处置 | **不做任何动作**(已是历史版本,无 CLI 删除;部署它会回退 worker 代码,禁止) | 无 |

> 若选 B,建议把「改 secret 前置检查」补充进 purge-rotate-20261003.md §3.1 教训的 SOP 段(该段已有同精神表述,补一条命令即可)。

## 5 其余 secret git 历史泄露扫描(git log -S 只读;不含值)

| secret | 是否曾明文进 git | 证据(commit/形态) | 现在是否在用 | 建议 |
|---|---|---|---|---|
| **PURGE_SECRET** | **是(唯一)** | 泄露点=`6f7e5b13a`(2026-09-12 20:07,launchd→systemd 迁移落档,24 处同一 64 字符 hex 真实值);清除=`fd95be096`(同日 21:12,24 行全删,改 EnvironmentFile);其余出现点(97b525690/8a36b4b82/c24286e0f/04ca82efb/935a15703/f9b76e0d6)= 占位符/说明文本。当前 HEAD 无明文(逐文件形态判定,0 个真实值形态) | 在用(Worker secret+本机两处 .env+云上 .env)→ **今日已轮换,旧值已失效** | 无需再动;git 历史中的旧值已失效,repo 为 private,风险可控(如需彻底清历史可评估改写历史,须先验证再删) |
| SUBSCRIBE_PASSWORD | 否 | `git log -S'SUBSCRIBE_PASSWORD='` 空(历史零「名字=值」);名字仅见于文档/错误文案/sync 脚本 `os.environ.get`;config/sub_pwd.json 不在 git 跟踪(ls-files 无) | 在用(sync_subscriptions_from_cf.py,env > config/sub_pwd.json) | 值不在 git,无需轮换 |
| SESSION_SECRET / _SESSION_SECRET | 否 | `-S'SESSION_SECRET='` 仅命中 4d6f7dcda(形态=`os.environ.get("SESSION_SECRET","")`,变量引用非字面量);.env.example 空模板 | 在用(worker/auth.js `env.SESSION_SECRET`) | 同上 |
| GITEE_CLIENT_SECRET | 否 | 同上(4d6f7dcda `os.environ.get` 引用;.env.example 空值) | 在用(worker/auth.js `env.GITEE_CLIENT_SECRET`) | 同上 |
| GITEE_CLIENT_ID | 否 | 同上 | 在用 | 同上 |
| CLOUDFLARE_API_TOKEN | 否 | `-S'CLOUDFLARE_API_TOKEN='` 空;出现点均为 `${{ secrets.CLOUDFLARE_API_TOKEN }}` 引用(deploy-cf.yml) | 在用(GH Actions repo secret) | 同上 |
| 私钥 .pem/.key/.p12 | 否 | `git log --name-only --diff-filter=A \| grep -E '\.(pem\|key\|p12)$'` 空 | - | - |
| .env 文件 | 否 | 历史仅 `.env.example`(空模板,含「真实 secret 不要提交 git」注);`.env` 本身从未 tracked | - | - |

- 扫描方法:`git log --all --reflog -S'<name>'`(名字出现点)逐 commit 判定值形态;`git log --all -S'<name>='`(赋值形态全集);值内容仅以「长度/hex/占位」分类统计,**全程未输出任何值**。

## 6 UNVERIFIED / 诚实标注
1. 「Enable Preview Builds」开关状态与 Git integration 连接配置:CLI 不可查,需 dashboard 人工确认(推断基于官方文档行为+22 秒自动触发强间接证据)。
2. b1f38e8c 与分支 code 的「逐位一致」未做(CF `versions view` 不可用,报告/purge-rotate 均实测过),内容归属系时间线+alias+后续 merge 推断,证据充分但非逐位对账。
3. 云上 journalctl 只查了 20:45-20:52 窗口;云上无 wrangler 二进制为全局事实(`which` 空)。
4. 历史中 8267(20:34,已部署)与 20:30 push 的关系未深挖(超出本任务,不影响结论——20:34 版本已部署,非悬挂)。
5. purge-rotate 报告 §3.2 曾猜测 b1f38e8c「与用户云体检实验时间吻合」——本报告证据指向更精确的机制:CF Builds preview build(20:47:30 push 触发),与用户云体检实验无关(implementer/reviewer 均为 alertchain 任务 agent;云体检文档提交发生在 18:47 批次)。

## 复现段(全部命令与关键原始输出,可重跑;输出已脱敏,无 secret 值)

```bash
# 1) 版本链(只读)
cd /Users/linhuichen/code/trade && npx --no-install wrangler versions list --json
# 关键行(脱敏):
#   {"id":"b1f38e8c-7a44-4baa-8f0b-7cac42716fa7","number":8268,"metadata":{"created_on":"2026-10-03T12:47:52.239488Z","source":"wrangler","author_email":"sugas13465@gmail.com","has_preview":true},"annotations":{"workers/alias":"feat-alertchain-hardening-20261003","workers/triggered_by":"version_upload"}}
# 最新版=62ae9909(8276, 14:51:08Z)

# 2) 部署链(只读)——b1f38e8c 不在其中
npx --no-install wrangler deployments list --json | grep -c b1f38e8c   # 0
# 当前部署=2118d4e5 -> 62ae9909 100%

# 3) push 时间线(证据: /tmp/agent-progress-hc-batchA-review.md)
#   20:47:02 报告写毕; 20:47:30 push 62a69f1d6 到 feat 分支; 20:47:52 CF 上传(22 秒间隔)

# 4) 官方文档(2026-10-03 抓取)
#   https://developers.cloudflare.com/workers/ci-cd/builds/build-branches/
#   「commits on the production branch produce a production build... followed by the deploy command」
#   「preview builds are builds for branches that are not your production branch... triggers a preview build」

# 5) 本机排除
grep -n 'wrangler' ~/.zsh_history          # 无输出
# 云上排除
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'which wrangler; journalctl --since "2026-10-03 20:45:00" --until "2026-10-03 20:52:00" -n 5 --no-pager'   # which 空;日志仅定时任务/stargate

# 6) secret 扫描(只读,输出只有 commit 列表,无值)
git log --all --reflog --format='%h|%s' -S'SUBSCRIBE_PASSWORD='          # 空
git log --all --format='%h|%s' -S'SESSION_SECRET='                        # 仅 4d6f7dcda(env 引用)
git log --all --format='%h|%s' -S'GITEE_CLIENT_SECRET='                   # 仅 4d6f7dcda(env 引用)
git log --all --format='%h|%s' -S'CLOUDFLARE_API_TOKEN='                  # 空
git log --all --reflog --format='%h|%s' -S'PURGE_SECRET=' --reverse | head -8
#   -> 最早 97b525690(占位) -> 6f7e5b13a(24 处真实值) -> fd95be096(删除) -> 935a15703(叙述)
git log --all --format='%h|%s' --name-only --diff-filter=A | grep -iE '\.(pem|key|p12)$'   # 空
git log --all --reflog --format='%h|%s' --name-only --diff-filter=AC -- '.env'               # 仅 .env.example
```
