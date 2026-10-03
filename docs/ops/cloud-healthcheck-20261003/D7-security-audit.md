# D7 安全/密钥/权限体检(2026-10-03)

> 触发:2026-09-12 迁云后首次完整安全体检(D0-D6 已出,本文 D7)。只诊断不治疗。
> 本机 + 云上(ubuntu@122.51.111.173,阿里云 Ubuntu 22.04)只读取证;报告全文脱敏,不含任何密钥明文。

## 0 结论速览

- **P0 #1:PURGE_SECRET 未轮换,现值 = 2026-09-12 public 仓泄漏值**(值 hash `ef0f839a043144bf`,64 位 hex,下同)。09-12 用户拍板「不轮换」的决策当时成立,但该值现仍可在 public github 历史(2 个 commit:6f7e5b13a 引入/fd95be096 删除)被任何人提取,且**当前仍是线上在用值**(purge 今日全量成功 = CF Worker 侧 secret 就是它)。建议重新评估是否补轮换(清理缓存凭证,危害有限但已公开 21 天)。
- **P0 #2(按任务规则「644 的私钥/含密文件 = P0」):本机 9 处含密文件/私钥权限过宽(644/444)**。云上侧全部 600 无此问题;风险集中在**开发机本机**。含:`trade/.env`、`trade-data/.env`、`config/{email,feishu,telegram,sub_pwd,brief_push}.json`、`~/Desktop/tdsignal.pem`(**444,生产服务器私钥同值副本**)、`~/Desktop/id_rsa`(644,孤儿私钥)、`~/Downloads/…/应用私钥2048.txt`(644,支付宝应用私钥)。
- **P1 #3:sshd `PermitRootLogin yes`**(root SSH 登录开放;密码登录已关,实际风险有限,建议收紧为 `no`)。
- **P1 #4:fail2ban 未启用**(14 天 81 次 Invalid user 爆破噪音、24 来源 IP;密码登录已关无 Failed password,但无入侵防护层)。
- **P1 #5:支付宝/163 邮箱 RSA 私钥以 644 散落在 `~/Downloads/hnflzfb01@163.com/`**(2022 年文件)。
- **反证项(安全):**云上含密文件全 600;外部暴露面**仅 22** 端口(DB/Redis/8080 全闭);密码登录关;14 天成功登录唯一来源 IP=1(用户本机);敏感配置本地+云上 git 历史零提交;当前 tracked 文件零处含泄漏值;.gitignore 受管块完整且本地/云上 md5 一致。

## 1 凭据清单(脱敏:位置/权限/tracked?)

### 1.1 云上(全部 600 属主 ubuntu,均未 tracked)
| 凭据 | 位置 | 权限位 | git tracked | 备注 |
|---|---|---|---|---|
| .env 24 键(DEEPSEEK/R2 S3×4/GITHUB_TOKEN/FEISHU_APP_ID+SECRET/SENSENOVA×7/PURGE_SECRET/FX8_DM/HITHINK/TRADE_HOST_TAG/R2_UPLOAD_HTTP_TIMEOUT) | `/home/ubuntu/code/trade-data/.env` | 600 | 否(`git ls-files` 空) | 真实文件,非 symlink,1869B,09-13 创建 |
| Resend/163 SMTP 密码(在 email.json `password` 字段) | `/home/ubuntu/code/trade-data/config/email.json` | 600 | 否 | smtp=smtp.resend.com,user=resend |
| 飞书 webhook_urls/app | `config/feishu.json` | 600 | 否 | |
| 订阅者邮箱/chat_id | `config/subscriptions.json` | 600 | 否 | |
| CF 订阅接口密码 | `config/sub_pwd.json` | 600 | 否 | |
| TG bot_token | `config/telegram.json` | 600 | 否 | |
| ssh 登录授权公钥 | `/home/ubuntu/.ssh/authorized_keys` | 600 | - | 1 行,09-12 |
| github deploy key | `/home/ubuntu/.ssh/id_ed25519` | 600 | - | 09-12,git remote 走 SSH 无 token URL |

### 1.2 本机(问题集中处)
| 凭据 | 位置 | 权限位 | git tracked | 判定 |
|---|---|---|---|---|
| R2 S3 key + PURGE_SECRET + HITHINK(.env 7 键) | `/Users/linhuichen/code/trade/.env` | **644** | 否(历史零提交) | **P0 过宽** |
| 同上副本 | `/Users/linhuichen/code/trade-data/.env` | **644** | 非 git 仓 | **P0 过宽** |
| SMTP/Resend 密码 | `config/email.json` | **644** | 否 | **P0 过宽** |
| 飞书 webhook(带 token 能力 URL) | `config/feishu.json` | **644** | 否 | **P0 过宽** |
| TG bot_token | `config/telegram.json` | **644** | 否 | **P0 过宽** |
| CF 订阅密码 | `config/sub_pwd.json` | **644** | 否 | **P0 过宽** |
| admin_key | `config/brief_push.json` | **644** | 否 | **P0 过宽** |
| 生产服务器私钥(在用) | `~/tdsignal.pem` | 600 | - | 合格 |
| 生产服务器私钥**同值副本** | `~/Desktop/tdsignal.pem` | **444** | - | **P0 私钥过宽**(hash 与在用值一致) |
| ssh 主私钥 | `~/.ssh/id_rsa` | 600 | - | 合格;`~/.ssh` 700 |
| ssh 副本(另一把,孤儿) | `~/Desktop/id_rsa` | **644** | - | **P0 私钥过宽**(hash ≠ 主钥) |
| 支付宝应用私钥 + 163 RSA 私钥(3 文件+txt) | `~/Downloads/hnflzfb01@163.com/` | **644** | - | **P0 私钥过宽**(2022 年遗留) |
| mbair.pem | `~/Downloads/mbair.pem` | 400 | - | 合格(owner-only) |
| Claude 会话加密 key | `~/.claude/sessions/*.key`、`~/.claude/daemon/control.key` | 600 | - | 合格 |

> 本机用户面 = 单用户(仅 `linhuichen`),故 644 的实际可利用者 = 其他本地账户/以后新增用户/后台进程,风险被环境缓和但违反权限最小化原则;修复成本 = 一键 chmod 600。

## 2 PURGE_SECRET 事件收口复核

**结论:未轮换,现值 = 泄漏值,泄漏敞口仍在(降级为「公开 21 天 + 仍为在用值」)。**

### 2.1 证据链
| 项 | 证据 |
|---|---|
| 历史泄漏值 | git `6f7e5b13a`(`docs/deploy/systemd-units-20260912.md`)含 24 处 `Environment=PURGE_SECRET=<值>`,值 hash=`ef0f839a043144bf`、64 位 hex;提交说明确认「PURGE_SECRET 实际嵌 24 plist」 |
| 去明文 commit | `fd95be096` 将 24 处改 `EnvironmentFile`;该 commit 提交信息称「删掉 Environment=PURGE_SECRET=<hex> 明文」 |
| 当前在用值 | 本地 `trade/.env` + 云上 `/home/ubuntu/code/trade-data/.env` 值 hash **均为 `ef0f839a043144bf`** = **与泄漏值相同** |
| Worker 侧匹配 | 云上今日 deploy(`deploy_20261003_1640.log`)`✓ Cache purge 完成:全部 5 批成功,共 purged 124/124 keys` → CF Worker 侧 secret == 现值 == 泄漏值 |
| 当前树残留 | 全树(含 .venv)grep 仅 1 文件含该值 = `.env`(gitignored);**当前 tracked 文件 0 处含该值** |
| git 历史残留 | 2 commit 含该值:`6f7e5b13a`(引入)/`fd95be096`(删除);**仓 public**(github.com/xp13465/trade-data-signal HTTP 200),历史可提取 |
| 云上 systemd | `/etc/systemd/system/*.service` grep `Environment=PURGE_SECRET=` = **0** 处;37 个 unit 全走 `EnvironmentFile=/home/ubuntu/code/trade-data/.env` |

### 2.2 与 09-12 处置对照
- 09-12 处置:文档去明文 ✅ 已完成;轮换 ❌ 用户拍板跳过;force push 清历史 ❌ 跳过。
- 现核实:**轮换确实没做**,且该值至今仍在用。当时的评估(「清缓存会自动重建、实际危害小;敞口可随时关闭」)逻辑仍成立,但「敞口可随时关闭」从 09-12 至今 21 天未执行,且 public 历史任何人都能拿到该值去调用 CF `/api/purge-cache`(影响=可清公开站点缓存,无数据篡改/泄露)。
- **P0 建议:轮换该值**(`upload_r2.py` 读 `.env` → 改值 + 同步本地/云上 `.env` + CF Worker `wrangler secret put`),或接受风险长期保留(需用户重新拍板并给「关闭敞口」时点)。

## 3 误 tracked 敏感文件全量扫描

**结论:无。**

- 云上 `git ls-files`(1671 文件)敏感路径匹配仅 2 个:**`scripts/api_key_mgmt.py`、`scripts/token_cache_stats.py`**(均为读 env 的管理脚本,非凭据文件;核实其行 = `line.startswith("SENSENOVA_KEY1=")` 式前缀读取,无内嵌值)。
- 云上 tracked 文件按键名前缀扫疑似真值(`DEEPSEEK_API_KEY=\S` 等 8 组):DEEPSEEK/GITHUB/R2/PURGE/FX8 → 0 文件;SENSENOVA=3/FEISHU=1/HITHINK=4 的匹配逐行甄别后**全部为代码/文档引用假阳性**(值形态=`"):`、`$(gr`、占位符`<填入>`等),非真实凭据。
- **当前 tracked 文件含泄漏 PURGE_SECRET 值:0**(本机全树+云上双验)。
- 敏感配置历史提交审计(本地+云上,`git log --all --diff-filter=A`):`config/email.json`、`feishu.json`、`telegram.json`、`subscriptions.json`、`sub_pwd.json`、`brief_push.json`、`.env`、`easytrader_local.json` **全部 = 0 次提交**。
- `.gitignore` 受管块(本地 293 行/云上同源)覆盖:`config/{email,telegram,feishu,subscriptions,sub_pwd}.json`、`.env`、`easytrader_deploy/easytrader_local.json`、`static-site/data/lab/`、`scripts/plists/`、`config/email.json.bak*`、`data/feishu_requests/` 等;本地与云上 `.gitignore` **md5 一致(`565fd9a87039c8835e5916f1e691f78a`)**。
- worktree 隔离副本(`/Users/linhuichen/code/trade/.claude/worktrees/*`)**未夹带** `.env`/含密 config(仅 tracked 文件)。

## 4 暴露面(端口/sshd/爆破尝试/防火墙)

### 4.1 监听端口(云上 `ss -tlnp`)
| 端口 | 绑定 | 判定 |
|---|---|---|
| TCP 22(0.0.0.0 + [::]) | sshd | 唯一对外,需开 |
| TCP 53(127.0.0.53) | systemd-resolved | 本机,无需开 |
| UDP 53/68/123(lo/eth0) | resolver/dhcp/ntp | 本机,无需开 |

**无任何意外/多余 LISTEN 端口。** 外部探针(本机 nc 扫 22/80/443/8080/3000/3306/5432/6379/27017/11211/9000/8888):**仅 22 OPEN,其余全 closed** → 数据库/缓存/HTTP 均未从安全组放行。memory「#143 relay 需开云上 8080 安全组」:8080 **未监听**也**未对外** → 该计划项未实施,无敞口。

### 4.2 sshd 配置(`/etc/ssh/sshd_config`,sshd_config.d 为空)
- `PermitRootLogin yes`(**P1**,建议 `no`)
- `PasswordAuthentication no` ✅
- `PermitEmptyPasswords no` ✅
- Port = 默认 22(未显式改)

### 4.3 登录与爆破(14 天窗口)
- 成功登录:`Accepted` 1300 次,**唯一来源 IP = 1 个**(用户本机;1300 次主要来自 deploy/rsync/scp 多次 ssh 往返);全部同一 RSA key 指纹。
- 爆破:`Failed password = 0`(密码登录已关);`Invalid user = 81 次`,来源 **24 个唯一 IP**(botnet 噪音,非定向)。
- 最后一条 `last` 正常:仅 ubuntu 从阿里云控制台 IP 登录 + 迁云期 root/orcaterm(09-13)。
- `lastb` 无权限读(未取到,标注)。

### 4.4 防火墙
- fail2ban:`inactive`(未装/未启用)**P1**。
- ufw:无权限读(未取到)。
- iptables INPUT policy ACCEPT,`YJ-FIREWALL-INPUT` 链对 6 个已知攻击 IP 做 tcp/udp:22 REJECT(阿里云安全组件注入的黑名单)。
- 阿里云安全组本身不可从盒内枚举(标注未取到);外部探针已证仅 22 可达。
- `/etc/cron.d` 有 `yunjing`/`sgagenttask`(阿里云安全 agent,正常);ubuntu crontab 另有 `hdszf` 项目每小时 job(与 trade 无关,同机观察项)。

## 5 文件权限审计(云上项目目录)

- **真实普通文件 `-perm -o+w`:0 个**(36 个命中全为 symlink——trade-data/static-site/* 按架构指向 trade-data-signal/static-site,`lrwxrwxrwx` 是 symlink 常态,非漏洞)。
- `static-site/*.js` 等:664 ubuntu:ubuntu(组内可写,组=ubuntu 仅自己,合格)。
- 日志目录 `data/logs/`:775/644,合格。
- **数据文件**:
  - `public_fund.db`(2.7G)`-rw-r--r--` ✅ owner-only
  - `etf_national_team.db`(254M)`-rw-rw-r--`(664,组可写,P2 观察)
  - `alert_state.json` `-rw-rw-r--`(664,P2 观察)
  - `.env` 600 ✅
- **云上本机侧**:`/home/ubuntu/.ssh` 700、`authorized_keys` 600、`id_ed25519` 600 ✅;lighthouse 用户 home 为空(`drwxr-x---`,镜像自带遗留,无 .ssh,P2 清理候选)。

## 6 本机侧

- `~/.ssh` 700;`id_rsa` 600;`known_hosts` 600 ✅;`id_rsa.pub` 644(公钥,合格)。
- `~/tdsignal.pem` 600 ✅(在用生产 key)。
- 无 `~/.aws`、`~/.config/rclone`、`~/.netrc`、`~/.wrangler`、`~/.config/gh`、`~/.git-credentials`、`~/.config/gcloud`、`~/.azure` ✅。
- `~/.gitconfig` 无 credential helper、无带 token 的 remote URL ✅。
- **过宽项见 §1.2(9 处,全部 chmod 600 可一键修复)**;其中 `Desktop/tdsignal.pem`(444)与 `Downloads/hnflzfb01@163.com/应用私钥2048.txt`(644)是「私钥以明文可读散落在桌面/下载目录」的典型反模式。
- 密钥均不在 git 仓内(Desktop/Downloads 非仓路径)。

## 7 反证项(确认安全的项)

1. **云上含密文件权限全 600**(.env + config 5 件)且属主 ubuntu,未 tracked。
2. **外部暴露面仅 22**;数据库/缓存/应用端口全闭(本机探针实测)。
3. **密码登录关闭**,14 天爆破无一次 `Failed password`;成功登录来源唯一(用户本机)。
4. 敏感配置(.env/email/feishu/telegram/subscriptions/sub_pwd/brief_push/easytrader_local)**本地+云上 git 历史零提交**。
5. **当前 tracked 文件零处含泄漏值**;systemd 单元零内嵌明文(37 个全走 EnvironmentFile)。
6. `.gitignore` 受管块完整,本地/云上 md5 一致。
7. 云上 git remote 用 SSH deploy key(`git@github.com:xp13465/trade-data-signal.git`),URL 无 token;无 git credential helper/netrc。
8. 无云厂商之外的凭据文件(AWS/rclone/gh/gcloud/azure 全无)。

## 8 分级问题表

### P0(立即)
| # | 现象 | 证据命令 | 影响 | 建议 |
|---|---|---|---|---|
| 1 | PURGE_SECRET **未轮换**,现值=public 仓泄漏值 | `git log --all -S <值>`=2 commit(6f7e5b13a/fd95be096);本地+云上 .env 值 hash 均 `ef0f839a043144bf`;github.com/xp13465/trade-data-signal HTTP 200(public);今日 purge 124/124 成功=Worker 在用该值 | 公开 21 天且仍为在用凭证;任何人可从 public 历史提取调用 CF /api/purge-cache(可清缓存,无数据篡改/泄露) | 轮换:改本地+云上 .env → `wrangler secret put` → purge 回归验证;或用户重新拍板长期保留并给关闭时点 |
| 2 | 本机 9 处含密文件/私钥权限过宽(644/444) | `stat -f "%Lp"` 逐一确认(§1.2 表) | 本机单用户,实际利用者=其他本地账户/未来新增用户/后台进程;违反最小权限 | 一键 `chmod 600` 全部;Desktop/Downloads 私钥副本删除或移入加密卷 |
| 3 | 生产私钥同值副本 444 散落 Desktop | `~/Desktop/tdsignal.pem` hash=`d0e2992af6cc` = `~/tdsignal.pem`(在用) | 生产服务器 root 权限等价物以明文可读存桌面 | 删除副本或 600+移入安全位置;若怀疑已暴露则轮换服务器密钥 |

### P1(本周)
| # | 现象 | 证据命令 | 影响 | 建议 |
|---|---|---|---|---|
| 4 | sshd `PermitRootLogin yes` | `grep PermitRootLogin /etc/ssh/sshd_config` | root SSH 通道开放(密码登录已关缓解) | 改 `no`,root 走 ubuntu+sudo |
| 5 | fail2ban 未启用 | `systemctl is-active fail2ban`=inactive | 爆破噪音(14 天 81 次/24 IP)无主动拦截层 | 装并启用 fail2ban(限 22 端口,可观察期后决定) |
| 6 | 支付宝应用私钥/163 RSA 私钥 644 散落 Downloads(2022 年) | `ls -la ~/Downloads/hnflzfb01@163.com/` | 第三方支付密钥明文可读 | 600 + 移入加密卷;确认是否仍在使用,不用则归档加密 |

### P2(观察)
| # | 现象 | 证据命令 | 影响 | 建议 |
|---|---|---|---|---|
| 7 | 云上 data 文件 664 组可写(etf_national_team.db/alert_state.json) | `stat -c "%a"` | 组=ubuntu 仅自己,风险≈0 | 顺手 644/600 |
| 8 | lighthouse 空遗留用户 | `ls -la /home/lighthouse` 空 | 无用账户 | 用户拍板后禁用/删除 |
| 9 | 迁移文档路径漂移:systemd-units-20260912.md 写 `/opt/trade/.env`,实际 unit 用 `/home/ubuntu/code/trade-data/.env` | 文档 vs `grep -h ^EnvironmentFile= /etc/systemd/system/trade-*.service` | 文档误导后续运维 | 落档订正 |
| 10 | 爆破 Invalid user 噪音持续(81 次/14天,24 IP) | `journalctl -u ssh --since "14 days ago" \| grep -c "Invalid user"` | 无 Failed password=无实际破解风险 | 观察;与 #5 联动 |
| 11 | hdszf 项目与 trade 同机(每小时 cron) | `crontab -l`(hdszf 段) | 同机另一项目,审计边界外 | 观察,确认其无 trade 数据访问 |

## 复现段
# 复现段
> 全部命令均在只读模式执行(云上仅 cat/ls/stat/tail/grep/find/du/journalctl/systemctl status|list-timers/ss/last/who/ps;本机仅只读)。可复核路径:报告 § 标注命令可直接重跑。

- 云上 `.env` 权限/键名:`ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'stat -c "%a %U:%G" /home/ubuntu/code/trade-data/.env; grep -E "^[A-Za-z0-9_]+=" /home/ubuntu/code/trade-data/.env | sed -E "s/=.*/=<值>/"'`
- 值 hash 复核(仅出 hash 不出值):`grep "^PURGE_SECRET=" <path> | python3 -c "import sys,hashlib; [print(hashlib.sha256(l.split('=',1)[1].strip().encode()).hexdigest()[:16], len(l.split('=',1)[1].strip())) for l in sys.stdin]"`
- 泄漏值 git 历史:`git log --all --oneline -S '<值>'`(值来自 .env,勿外发)
- purge 成功证据:`tail -20 /home/ubuntu/code/trade-data/data/logs/deploy_20261003_1640.log`
- 外部探针:`for p in 22 80 443 8080 3000 3306 5432 6379 27017; do nc -z -G 3 122.51.111.173 $p; done`(仅 22 OPEN)
- 本机权限:`stat -f "%Lp %N" <含密文件>`
- 复现注意:**切勿把 `<值>` 明文写入任何报告/日志/剪贴板**;本报告所有值仅以 hash 前 16 位 + 长度指代。
