# Cloudflare 凭据索引(不含任何密钥值)

> **本文件只记录「凭据是什么、放在哪、怎么验」,绝不记录凭据本身的值。**
> 建立于 2026-10-27,起因:云上 wrangler OAuth 登录态过期(2026-10-25T11:27:30Z),导致
> `sync_fund_score_to_d1.sh` / `sync_fund_screener_to_d1.sh` 连续失败;这不是第一次
> (2026-10-01~10-22 同样原因连挂 39 次、D1 `fund_score` 静默停更 20 天)。

## 两个 Cloudflare 账号

| 账号 ID | 对应配置键 | 用途 |
|---|---|---|
| `9be954e87f3d28f9c0faaa9e2b3a78b7` | `R2_S3_ENDPOINT` | **数据桶主账号**:staticdata 数据桶、D1 库(`trade-fund-score` 等)、平台 API |
| `2455352499fc04ddbd92d33e0a0e8614` | `R2_BACKUP2_ENDPOINT` | **备份桶第二账号**:R2 备份(见 memory `r2-backup-bucket-second-account`) |

> ⚠️ 别搞混:本仓脚本里 grep 到的第一个 32 位 hex **不一定**是主账号。以 `.env` 里
> `R2_S3_ENDPOINT` / `R2_BACKUP2_ENDPOINT` 的实际取值为准。

## 凭据类型:三套互不相通

| 类型 | 前缀/形态 | 能做什么 | 存在哪 |
|---|---|---|---|
| **API Token**(本文件主角) | `cfut_` 开头,35 字符 | 平台 API:wrangler、D1、R2 管理 API(需勾对应权限) | 见下「存放位置」 |
| **R2 S3 凭据** | Access Key ID + Secret(32/64 字符对) | 只走 S3 兼容协议(aws cli / boto3),**不能调 D1** | 云上 `.env` 的 `R2_S3_*` / `R2_BACKUP2_*` |
| **OAuth 登录态** | `~/.config/.wrangler/config/default.toml` | wrangler 交互登录,**会过期**(就是这次事故根因) | 云上 `ubuntu` 用户目录 |

## API Token 存放位置(两把,2026-10-27 建齐)

| 账号 | 位置 | 键名 / 服务名 | 备注 |
|---|---|---|---|
| A `9be954e8…` | 云上 `.env` | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | 生产链路用。unit 有 `EnvironmentFile=` 自动加载,**脚本无需改动** |
| A `9be954e8…` | 本机钥匙串 | service=`trade-cf-api-token-accountA-data-d1` | |
| B `24553524…` | 云上 `.env` | `CLOUDFLARE_API_TOKEN_BACKUP2` + `CLOUDFLARE_ACCOUNT_ID_BACKUP2` | **带 `_BACKUP2` 后缀,wrangler 不会自动读**,避免误用 |
| B `24553524…` | 本机钥匙串 | service=`trade-cf-api-token-accountB-backup2` | |

两把均 `expires_on=None`(永不过期),实测 date 2026-10-27。

取用(本机):
```bash
security find-generic-password -s "trade-cf-api-token-accountA-data-d1" -w   # 主账号
security find-generic-password -s "trade-cf-api-token-accountB-backup2" -w   # 备份桶账号
```

## 当前权限范围(2026-10-27 实测,两把完全一致)

| 能力 | 账号 A | 账号 B |
|---|---|---|
| 账户列表 | ✅ | ✅ |
| D1 列表 | ✅ `trade-fund-score` | ✅ (0 个库,该账号没建库) |
| D1 执行 SQL | ✅ `SELECT COUNT(*) FROM fund_score` 成功,3520 行 | 未测(无库) |
| R2 管理 API | ❌ `code: 10000` | ❌ `code: 10000` |
| User Details / Memberships | ❌ whoami 提示缺(不影响 D1) | ❌ 同 |

> 两把 token 建的时候都只勾了 D1 相关权限,**都没勾 R2**。

> **不影响现有链路**:R2 走的是 `R2_S3_*` S3 密钥,不依赖这把 token。
> 若将来要在云上用 API Token 直接调 R2,需回控制台补 `Workers R2 Storage` 权限。

## 验证方法(不打印值)

```bash
# 云上:必须先手动加载 .env(systemd 会自动加载,手动 ssh 不会)
ssh -o ConnectTimeout=10 -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'set -a; . /home/ubuntu/code/trade-data/.env 2>/dev/null; set +a; \
   cd /home/ubuntu/code/trade-data && npx wrangler whoami 2>&1 | tail -15'
```

期望看到:`The API Token is read from the CLOUDFLARE_API_TOKEN environment variable`
+ 账户表里出现 `9be954e8…`。

## 排查提示

- **`wrangler` 报 Authentication error / code 10000** ⇒ 先跑上面的 whoami,确认 token 是否被读到;
  注意手动 ssh 不加载 `.env`,90% 的"云上明明配了却不生效"是这个原因。
- **`expiration_time` 已过** ⇒ 那是 OAuth 登录态,与我这里的 API Token 无关;API Token 永不过期
  (本次实测 `expires_on=None`)。
- **R2 上传失败但 D1 正常** ⇒ 两套凭据独立,R2 查 `R2_S3_*`,别查 token。
- **换 token 后** ⇒ 云上改 `.env` + 本机 `security add-generic-password -U` 两处同改,并各验一次。

## 待办

- [ ] 若将来要在云上用 API Token 直接调 R2(目前不需要,走 S3 密钥),两把都要回控制台补 `Workers R2 Storage` 权限