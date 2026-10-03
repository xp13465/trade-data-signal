# PURGE_SECRET 轮换执行记录(2026-10-03)

> 触发:用户 2026-10-03 拍板**翻案**(推翻 2026-09-12「不轮换、不 force push 清历史」决定),趁国庆休市窗口执行轮换。本记录只写「改了哪处/验证结果/回退方法」,**不含任何密钥明文**(新旧值只活在 `.env` / CF Worker secret / 600 权限临时文件)。
> 前置调研与危害边界复核全文:`docs/ops/hc-secret-purge-and-db-bak-research-20261003.md`(能力边界=仅清缓存,碰不到 R2,与 9 月 $4.50 R2 账单无因果)。

## 0 结论速览

- **4 处轮换全部完成并验证**:Worker secret + 本地 `trade/.env` + 本地 `trade-data/.env` + 云上 `/home/ubuntu/code/trade-data/.env`。
- **验证两码**:线上 `POST /api/purge-cache` 新值 = **200**、旧值 = **403**(旧值已全部失效)。
- 三处 `.env` 新值逐字符一致(sha256 校验),Worker 与三处 `.env` 全部对齐。
- 过程中遇到 **CF version-scoped secrets 新行为拦截**(`wrangler secret put` 报「latest version isn't currently deployed」),按官方报错解法 2(先部署最新版再改 secret)解决,详见 §3。

## 1 改动清单(4 处)

| # | 位置 | 动作 | 结果 |
|---|---|---|---|
| 1 | CF Worker `trade-data-signal` `PURGE_SECRET` | 部署规范代码(v_a52cb0be)解锁 → `wrangler secret put` 写新值 | ✅ 线上新值 200 / 旧值 403 |
| 2 | 本地 `/Users/linhuichen/code/trade/.env` | 原地替换 `PURGE_SECRET=` 行为新值 | ✅ hash 与新值逐字符一致 |
| 3 | 本地 `/Users/linhuichen/code/trade-data/.env` | 同上 | ✅ 同上 |
| 4 | 云上 `/home/ubuntu/code/trade-data/.env` | scp 新值到云临时文件(600)→ python 原地替换 → shred 临时文件 | ✅ 同上 |

> 顺序铁律遵守:Worker 最先 → 本地两处 → 云上最后;全程无「新值调旧 Worker → purge 403」窗口(休市夜无 deploy/purge 定时任务,16 项 systemd timer 无撞车)。

## 2 验证(两码)

- 新值 `POST https://ss.fx8.store/api/purge-cache`(测试 key 不存在,幂等无害)= **HTTP 200**
- 旧值同请求 = **HTTP 403 `Forbidden`**
- 最后一次全量验证在步骤 4(云上 .env)完成后重跑,两码依旧 200/403。

## 3 过程中的环境障碍与解法(重要,防再犯)

### 3.1 CF version-scoped secrets 拦截
- **现象**:首次 `npx wrangler secret put PURGE_SECRET` 失败:账户存在一个**未部署的 latest version**(`b1f38e8c`,2026-10-03 20:47 手工 upload),CF 守卫导致传统 `secret put`(改当前部署版 secret)被拒,报错:
  - *"You attempted to modify a secret, but the latest version of your Worker isn't currently deployed. This limitation exists to prevent accidental deployment when using Worker versions and secrets together. To resolve: (1) use `wrangler versions secret put`... (2) deploy the latest version first, then modify secrets."*
- **尝试过的中间路径**(诚实记录):
  - `wrangler versions secret put` 成功但**新建了带新 secret 的版本且不部署**(输出明说需要 `wrangler versions deploy` 才上生产流量)→ 实测线上仍是旧值(旧 200 / 新 403),证明**version-scoped secret 是随版本生效,不改部署中的版本就影响不了线上**。
  - `wrangler versions view <id>` 对已部署/新建版本均报「version not found」(账户 API 限制),无法用其比对版本代码。
- **最终解法(官方报错解法 2)**:
  1. `wrangler deploy` 从**与 origin/main 逐位一致的干净 worktree** 部署规范代码(新版本 `a52cb0be`,Latest == Deployed)——
     - 部署前已机检:`git merge-base --is-ancestor origin/main HEAD` = base-fresh;**对 `worker/ wrangler.jsonc static-site/ app/` 的 diff 为空**(部署的代码 = main 规范代码 = CI 一直在部署的内容,内容与线上同源,`worker/headers.js` 源码一行未动)。
  2. 部署后重跑 `wrangler secret put PURGE_SECRET ` → 成功(守卫放行)。
  3. 立即线上验证新 200 / 旧 403。
- **教训**:2026-10 起 CF 对已启用 version-scoped secrets 的 Worker,`wrangler secret put` 有「latest==deployed」前置约束;改此类 Worker 的 secret 前先 `wrangler deployments list` / `wrangler versions list` 检查有没有未部署的 dangling version,有则先解决(部署或清理),否则直接遇到守卫。

### 3.2 遗留观察(超出本任务范围,上报主控)
- 账户内存在**未部署的手工版本 `b1f38e8c`(2026-10-03 20:47 version_upload)**,来源不明(当天 16:46-21:06 有多笔手工部署/上传活动,与用户云体检实验时间吻合)。其内容未比对(versions view 不可用)。**后续建议按 D7 同法核查**该版本的代码内容,排除实验残留。
- 报告 `hc-secret-purge...` §1.5 提示的其余 secret(`SUBSCRIBE_PASSWORD`/`_SESSION_SECRET`/`GITEE_CLIENT_SECRET`)未核查是否曾泄漏,建议后续 `git log -S` 扫一遍纳入轮换评估——**不在本任务范围,未动**。

## 4 回退方法(如需回退,逐处逆操作)

> 顺序倒过来回退:云上 → 本地 → Worker。每处回旧值即可,**旧值保存在回退锚点**(600 权限临时文件,已按 §25 留存于本机 `mktemp` 文件,位置:实施进度报告已向主控口头交接,不入 git/不写字面)。

1. **Worker 回旧值**:`npx wrangler secret put PURGE_SECRET`(输入旧值,stdin/重定向=不回显)。
2. **本地 `trade/.env` / `trade-data/.env` 回旧值**:原地替换 `PURGE_SECRET=` 行为旧值(ppo 同 §1 的第 2/3 处写法)。
3. **云上 `.env` 回旧值**:scp 旧值到云临时文件 → 远端 python 原地替换 → `shred -u` 临时文件。
4. 回退后验证:线上旧值 200 / 新值 403,即回到轮换前状态。

## 复现段(全部证据命令,可重跑;**无值,值一律从 600 临时文件/`.env` 读取,不回显**)

```bash
# === 侦察 ===
git grep -n 'PURGE_SECRET' | cut -d: -f1,2        # 全仓消费方(文件:行号)
git grep -nE 'PURGE_SECRET=[0-9a-f]{40,}' | wc -l  # 硬编码值数(=0)
npx wrangler whoami                                  # 登录态/OAuth 权限(workers write)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep -rn "EnvironmentFile" /etc/systemd/system/trade*.service'   # 云上全部指向 /home/ubuntu/code/trade-data/.env

# === 轮换 ===
npx wrangler secret put PURGE_SECRET < /tmp/purge-rotate-work/new.value   # Worker 最先(新值经重定向,不进 stdout)
# 本机两处 .env:python3 读 /tmp/purge-rotate-work/new.value → 原地替换 PURGE_SECRET= 行(不打印值)
# 云上 .env:scp 新值到云 /tmp(600)→ 远端 python 原地替换 → shred -u 删远端临时

# === 验证(curl 不带 -v/-i,防 token 进日志) ===
# 新值:curl -s -X POST -o /dev/null -w "%{http_code}" https://ss.fx8.store/api/purge-cache -H 'Content-Type: application/json' -d @<新值payload文件>  → 200
# 旧值:同上带回旧值payload文件 → 403
# 三处 .env 一致性:分别取 PURGE_SECRET= 值 sha256 比对(只比 hash,不比明文字面)

# === 障碍与解锁 ===
npx wrangler deployments list | grep -E '\(100%\)' # 部署链版本
npx wrangler versions list                          # 版本链(找未部署 latest)
npx wrangler deploy                                  # 部署规范代码(latest==deployed)后可 secret put
```

## 诚实标注

1. **过程中产生的版本噪声**:`wrangler deploy` 创建了新版本 `a52cb0be`,以及 `versions secret put` 创建的 `402c4455`(未部署,已被后续 deploy 的版本链覆盖为历史);线上代码内容与 origin/main 逐位一致(部署前 diff 为空),`worker/headers.js` 未动。
2. **遗留未部署版本 `b1f38e8c` 未处置**:非本任务范围(不动部署中的 worker 之外的版本),已上报主控,建议后续核查内容后清理。
3. 报告含任何 secret 明文字段即视为事故差错,已全程遵守(值只在 600 临时文件/`.env`/CF 内流转)。