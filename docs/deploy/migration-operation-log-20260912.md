# 迁移操作记录(2026-09-12 起)

> 用途:记录云上部署每一步操作,既当操作备份,也是下次迁移(换机/重装)的参考凭据。
> 配套:资源实测 `resource-benchmark-20260912.md` / 迁移清单 `migration-checklist-20260912.md` / 盘点 `migration-inventory-20260912.md`。

## 服务器信息(实测)

| 项 | 值 |
|---|---|
| IP:端口 | 122.51.111.173:22 |
| 登录名 | **ubuntu**(不是 root),sudo 免密 |
| 密钥 | 本机 `~/tdsignal.pem`(chmod 600);桌面快捷方式 `连接云服务器.command` |
| 规格 | 4核 AMD EPYC 7K62 / 4G(3.6G)/ 40G盘可用34G / Ubuntu 22.04 / python3.10(需升 3.11) |
| 主代码仓 | `git@github.com:xp13465/trade-data-signal.git` |
| 数据仓(开源快照) | `git@github.com:xp13465/trade-data-signal-staticdata.git`(8.4G) |

## 关键结论(坑,下次直接照做)

1. **登录名是 ubuntu,不是 root**
2. **访问 GitHub:HTTPS 被墙,SSH 协议通**(22 端口 + `ssh.github.com:443` 都通)。clone 必须走 SSH + 配密钥,不能用 HTTPS(HTTPS clone 卡 150s 超时)
3. **服务器 Python 3.10 不够,必须装 3.11**(pandas 3.0.3 / numpy 2.4.6 要求 >=3.11)
4. **数据起盘从 R2 `signal-backup` 桶拉,不拷本地 13.2G 双仓备份**
5. **定时任务:35 迁 / 5 不迁(thinking-proxy 等)/ 1 拍板(feishu-listener)/ 3 未加载不迁**
6. **`pkill -f` 会匹配自己命令行导致自杀**,杀进程用 PID 或精确 pattern
7. **迁移标准 = 照搬本机一模一样**(采集/推送/数据仓git/R2 全照搬,不重新设计)。大 DB(public_fund.db 2.3G 等)是 untracked 不进 git,staticdata 仓只 push 小 JSON + 2 个 74MB 凯利记录,无"push 大文件"风险
8. **数据仓 staticdata 也用 `--depth 1` 浅 clone**(避开 8.4G 完整下载)
9. **云上→github 限速 33-50KB/s**(SSH 22 端口已是云上最快通道;HTTPS 直连 3.2KB/s / ghfast 镜像 2.4KB/s / github.com:443 超时 / ssh.github.com:443 更慢)。clone 与未来每天 push staticdata 开源数据都受此影响,后续需配代理(checklist §7)

## 操作时间线(2026-09-12)

| 时间 | 操作 | 命令/结果 |
|---|---|---|
| 17:05 | 收紧密钥权限 | `chmod 600 ~/tdsignal.pem` |
| 17:05 | 探测服务器 | `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173` → 确认 4核4G/40G/ubuntu |
| 17:06 | 测 GitHub 连通 | SSH 22/443 返回 `Permission denied (publickey)` = 网络通只差密钥 |
| 17:11 | 加 swap 4G | `fallocate+mkswap+swapon` + 写 fstab → `free -h` 显示 Swap 4.0Gi |
| 17:12 | 装系统依赖 | `apt install build-essential python3-dev`(已是最新) |
| 17:20 | 生成 SSH 密钥 | `ssh-keygen -t ed25519 -C trade-cloud` → 公钥给用户加到 GitHub |
| 17:24 | 建桌面快捷方式 | `~/Desktop/连接云服务器.command` |
| 17:31 | clone 代码仓 | `--depth 1` 浅 clone → `/home/ubuntu/code/trade-data-signal`(SSH 协议),.git 仅 26M |
| 17:45 | 装 Python 3.11 | deadsnakes PPA + `python3.11-venv`(3.10 不够,pandas/numpy 要 ≥3.11) |
| 18:00 | 建单 venv + 装依赖 | `/home/ubuntu/code/trade-data-signal/.venv`,Python 3.11.15,pip 26.2.1(清华源),86 个包(pandas 3.0.5/numpy 2.4.6/akshare 1.18.64/pyarrow 25.0.1/baostock 0.9.3/mootdx 0.11.7/mini-racer 0.14.1 等),`pip check` 无 broken,MiniRacer eval 正常 |

| 19:38 | scp 敏感配置 | 6 json + 合并 .env(**取并集 21 键**:trade-data 15 键全量 + trade 独有 6 键 R2 S3/HITHINK),md5 7/7 一致,chmod 600 |
| 19:40 | clone staticdata | 云上 SSH 浅 clone 限速 33-50KB/s(约 2h),后台跑不阻塞主线 |
| 20:10 | 数据起盘完成 | scp 19 文件(public_fund 2.4G + stock_daily 112M + A/B 级状态文件)md5 19/19 一致 + download-db 拉 sentiment 126M/etf_national_team 177M(20260911),云上 data/ 共 2.9G |

## 阶段1 打地基 ✅ 完成(swap 4G + 代码仓 clone + Python3.11 + 86 依赖包)

## 待办(后续追加)

- [x] 装 Python 3.11
- [x] 装依赖(单 venv,researcher 清单)
- [x] 数据起盘(scp 19 文件 + R2 拉 2 库,md5 全一致,云上 2.9G)
- [x] 迁定时任务 35 个(systemd 配置落档 + macOS 适配 review/fix,两 feat 已 merge 到 main)
- [x] feishu-listener **留本地不迁**(需求入口依赖本机 Claude;云上发飞书抄送通知 = notify.py,config/feishu.json + lark-oapi 已就位照搬)
- [x] systemd 文档拿掉 feishu service 段(commit 1827ed9a0,改不迁说明)
- [ ] staticdata clone(19:40 后台 clone 被 SSH 断连 SIGHUP 杀掉,目录/进程消失;延后配代理后重跑)
- [x] merge 两个 feat 后云 pull(main 9ef5b0b,云上已 pull 同 HEAD)
- [ ] 阶段4a:云上 systemd 落地(35 timer/service 写 /etc/systemd/system + daemon-reload)
- [ ] 阶段4b:云上跑通采集→export→R2 上传,curl 验证线上
- [ ] 阶段4c:停本地 launchd(备份 plist + 一键还原脚本),观察云上稳定后由用户拍板停本地

## 阶段1 收尾小隐患(不影响当前,后续 requirements.txt 补约束)

1. **mini-racer 顺序依赖隐患**:mootdx 强拉 sqreen `py-mini-racer 0.6.0`,实测 bpcreech `mini-racer 0.14.1` 后装覆盖胜出(能 import + eval 正常)。但这是"安装顺序决定"的,以后重装若顺序反转可能拿错版。→ 建议后续 requirements.txt 显式 pin `mini-racer==0.14.1`。
2. **pandas 版本漂移**:装到 3.0.5(清单记 3.0.3),补丁差异非破坏(都 ≥3.11),后续 pin 对齐 3.0.3 或统一升 3.0.5 均可。
