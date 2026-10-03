# SOP:CF Worker secret 轮换前置守卫检查 + Preview Builds 根治(2026-10-03)

> 触发点:任何 `wrangler secret put` / `wrangler versions secret put` 改 CF Worker secret 之前。
> 背景:2026-10-03 晚轮换 PURGE_SECRET 时,`wrangler secret put` 被 CF 拒绝(报「the latest version of your Worker isn't currently deployed」),根因=CF Workers Git integration 的 **Preview Builds** 在每次推非 main 分支时自动创建 `has_preview=true` 的悬挂版本(未部署),使守卫「latest 未部署」成立。溯源全文:`docs/ops/cf-version-provenance-20261003.md`。
> **本 SOP 不含任何 secret 值**;secret 值一律从 600 权限临时文件 / `.env` 读取,经 stdin 重定向/环境变量注入,不进 stdout、不进命令历史明文。

## 0 现状(snapshot 2026-10-03 北京 ~23:35,关闭 Preview Builds 之前)

- **Preview Builds 开关 = 开启中**(证据见 §3):latest 10 条 version 全部 `has_preview=true`,最近几条 alias 对应非 main 分支(`feat-hc-docs-registry` / `feat-cf-version-provenance` / `feat-r2-retention-14d`)。
- **当前守卫状态 = 放行**:latest version = `10df9a1d`(版号 8281),已部署(deployment `873865b5`)。
- 该开关**仅 dashboard 可操作,无 CLI/API**(官方 API 参考 workers_builds 只有 repo connections/triggers/limits,trigger schema 仅 `trigger_name/trigger_uuid/repository_directory`,无 Enable Preview Builds 字段;wrangler OAuth token 对 `/builds/*` 端点返回 Authentication error 10000=缺 Workers Builds 权限)→ 关闭=用户 dashboard 手点,见 §3。

## 1 改 secret 前置检查(必做,优先级最高)

改任何 CF Worker secret 前,先确认「latest version == 已部署」,不平则 guard 会拦 `wrangler secret put`:

```bash
cd /Users/linhuichen/code/trade
npx --no-install wrangler versions list        # 看最新 version id(列表第 1 行)
npx --no-install wrangler deployments list     # 看当前 active deployment(顶部)对应 version id
```

**判定**:latest version id 出现在 deployments list 顶部(已部署)→ 守卫放行,可直接 `secret put`。
**不出现**(存在 dangling latest,典型=preview build 的 `has_preview=true` 版本)→ 两种解法二选一:

- **解法 A(推荐,官方「deploy the latest version first」方案,2026-10-03 晚已验证)**:先部署规范代码再改 secret。
  ```bash
  git fetch origin
  git merge-base --is-ancestor origin/main HEAD && echo base-fresh   # 机检 1:分支不落后
  git diff origin/main -- worker/ wrangler.jsonc static-site/ app/   # 机检 2:待部署代码与 origin/main 零 diff(部署内容=CI 一直在部署的规范代码)
  # 机检全过(git status 干净 + 无 diff)才允许:
  npx --no-install wrangler deploy
  # 部署后 latest==deployed,再执行 secret 操作:
  npx --no-install wrangler secret put <SECRET_NAME> < /path/to/600-perm/value.file   # 值走 stdin 重定向,不进 stdout
  ```
- **解法 B(官方「use wrangler versions secret put」方案)**:`npx wrangler versions secret put <NAME> <value>` + `npx wrangler versions deploy <version-id> --yes`。
  ⚠️ 实测注意:version-scoped secret **随版本生效**,只 `versions secret put` 不 deploy 不改变线上(2026-10-03 晚实测线上仍是旧值)→ **必须跟 `versions deploy`** 才影响线上。

改完立即验证(以 PURGE_SECRET 为例,不带 -v/-i 防泄漏):
```bash
curl -s -X POST -o /dev/null -w '%{http_code}' https://ss.fx8.store/api/purge-cache -H 'Content-Type: application/json' -d @new.payload  # 期望 200
# 同请求带旧值 payload → 期望 403
```

## 2 回退方法

任何轮换保留旧值于 600 权限临时文件(不入 git/不写字面)。回退顺序=云上 → 本地 .env → Worker:
1. Worker 回旧值:`npx wrangler secret put <SECRET_NAME>`(输旧值)
2. 本地/云上 `.env` 原地替换旧值
3. 回退后验证旧值效果恢复(如 purge 走旧值 200)。

## 3 根治:关闭 Preview Builds(dashboard,唯一步骤)

> 关闭后,推非 main 分支不再触发 preview build,不再产生 `has_preview=true` 悬挂版本,「latest==deployed」守卫长期满足,改 secret 不再被拦。

**精确 dashboard 路径**(源:官方文档 Builds 配置页 + Build branches 页,2026-10-03 抓取):
1. Cloudflare dashboard → **Workers & Pages**(左侧或首页入口)
2. 选中 Worker:**trade-data-signal** → 顶部 **Settings** 页
3. 左侧/页内 **Builds**(新版 UI 文案可能为 **Build**)
4. 找 **Branch control** 区块(分支控制:production branch 下拉 + 勾选框)
5. 取消勾选 **Enable Preview Builds**
6. **保存后生效**(可选:确认页面提示已保存)

> 副作用:非 main 分支不再有 CF preview(项目部署主路径已是 GH Actions `deploy-cf` 只监听 main,无业务损失)。Git integration 仍保留=生产 main push 双保险兜底(GH Actions 失败时 build+deploy 仍会跑)。**不要**点「Disconnect」断掉整个 Git integration(断开会同时失去 main 生产兜底)。

**关闭后的决定性验证(动手前先做)**,必须真推到远端验证,不认「设置显示已关」:
```bash
# 1) 记当前最新版本数/号,作为基线
npx --no-install wrangler versions list | head -3
# 2) 推一次性测试分支(feat 分支名连字符化=可能出现的 preview alias,如 test-preview-off-verify)
git checkout -b test/preview-off-verify  &&  git commit --allow-empty -m "test: preview builds verification"  &&  git push origin test/preview-off-verify
# 3) 等 60 秒(历史实测 CF 在 push 后 ~22 秒内创建 preview 版本),再查:
npx --no-install wrangler versions list | head -3
#    PASS = 没有出现 alias=test-preview-off-verify 的 has_preview=true 新版本(新增版本号数量=0)
#    FAIL  = 出现了新 preview 版本 → 开关未生效/另有来源,停下上报,不继续
# 4) 清理测试分支(必经):
git push origin --delete test/preview-off-verify
git checkout feat/cf-preview-off-20261003 && git branch -D test/preview-off-verify
```

## 复现/自查命令(全部门禁输出为空或为判定行,无值)

```bash
npx --no-install wrangler versions list          # 版本链,找 has_preview=true / 未部署 latest
npx --no-install wrangler deployments list       # 部署链,顶部=active deployment
npx --no-install wrangler deploy                  # 部署规范代码(前置机检见 §1)
curl -s -X POST -o /dev/null -w '%{http_code}' ... # 改 secret 后两码验证(200/403)
```

## 关联文档

- 根因溯源:`docs/ops/cf-version-provenance-20261003.md`(悬挂版本 b1f38e8c = preview build 产物,时间线钉死)
- 轮换实操记录:`docs/ops/purge-rotate-20261003.md`(§3.1 首次遇守卫的完整处置)