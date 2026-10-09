# #234 剩余批(第二批)执行报告 —— p0 去重 + 107/109 html 归属核查 + stash 审阅

> 执行: tester agent,2026-10-09。上轮背景:`docs/ops/disk-cleanup-executed-20261009.md` §四(乙1 p0 / 107 html)+ §七(待拍板 1/5/6)。
> 本批范围:①删「逐位重复」的 p0 快照副本 ②107 html 只核查分类(不删) ③stash ×3 只读审阅呈用户。

## 一、① 乙1 p0 快照 ×3 —— md5 自复核 + 去重删除

### 1.1 现场三对象(删前实测,绝对路径 + inode)

| # | 路径 | 字节 | mtime | inode | linkcnt |
|---|---|---|---|---|---|
| A | `/Users/linhuichen/code/trade/data/etf_national_team.db.bak-p0-20260909` | 184,610,816 | 2026-09-09 09:46:37 | 251765202 | 1 |
| B | `/Users/linhuichen/code/trade-data/data/etf_national_team.db.bak-p0-20260909` | 184,610,816 | 2026-09-09 09:46:37 | 251648643 | 1 |
| C | `/Users/linhuichen/code/trade/data/etf_national_team.db.bak-p0-20260909-1345` | 184,610,816 | 2026-09-09 13:45:26 | 251719940 | 1 |

- 三份合计 553,832,448 B = **528.2 MiB**(与上轮 528M 吻合)
- 两树均为**真实目录**(`trade-data/data` 非 symlink;inode 各异,非硬链接;`ls -ld` 实测),故「跨树重复」是**两份独立实体**而非同一文件

### 1.2 md5 复核(删前同刻双向对账,独立复算,未采信上轮结论)

```
A data/etf_national_team.db.bak-p0-20260909              55926b744cca11d69ed32e90e91d6eb1
B trade-data/data/etf_national_team.db.bak-p0-20260909   55926b744cca11d69ed32e90e91d6eb1   ← 与 A 逐位一致
C data/etf_national_team.db.bak-p0-20260909-1345         e79d3cc8003106f4bea86e78339c2c85   ← 另一版本
```

⇒ **与上轮报告一致**:A ∩ B 逐位重复(md5 `55926b74…`),实际 2 个不同版本。

### 1.3 删前安全闸门(逐项实测)

| 闸门 | 结果 |
|---|---|
| git tracked? | `git ls-files -- data/etf_national_team.db.bak-p0-*` **零命中**;`git check-ignore -v` = `data/.gitignore:1:*` 覆盖 ✓ |
| trade-data 侧 git? | `git -C trade-data rev-parse` = **not a git repository**(纯本地目录,B 同样非 tracked) |
| 进程持有? | `lsof` 三文件 **零命中**(exit=1) ✓ |
| 脚本/文档引用? | `grep -rn "bak-p0" scripts docs .claude` 仅命中**审计/清理报告自身**,无任何脚本、无管线读取 ✓ |
| 对象存在性/预期性 | `ls -la` 逐个确认存在且为预期文件名(§25 要求)✓ |

### 1.4 删除动作与结果

- 动作:`rm -v /Users/linhuichen/code/trade/data/etf_national_team.db.bak-p0-20260909`(**A**,trade 侧重复副本),exit=0
- 删后核验:A `No such file or directory` ✓;B、C 在位且大小/时间戳未变 ✓
- 删后再次 md5 复核保留份 B = `55926b744cca11d69ed32e90e91d6eb1`(**与删前一致,恢复路径完好**)✓
- 释放空间:**184,610,816 B = 176.1 MiB**

### 1.5 §25 恢复路径(写得出,故可逆)

- **保留的那一份(唯一恢复源)**:`/Users/linhuichen/code/trade-data/data/etf_national_team.db.bak-p0-20260909`(md5 `55926b744cca11d69ed32e90e91d6eb1`,184,610,816 B)
- 恢复命令(如需回填 trade 侧):`cp /Users/linhuichen/code/trade-data/data/etf_national_team.db.bak-p0-20260909 /Users/linhuichen/code/trade/data/` 然后 `md5 -q` 对 `55926b74…` 验位
- ⚠️ 该族**无 R2 归档、非 git**(上轮已核),故这份 B 是**该 09:46 版本的全网唯一副本**——不得再动

### 1.6 ⚠️ 停下项:C(-1345 版)**未删**,与任务书的「2 份」不符,请拍板

- 事实:C = md5 `e79d3cc8…`,与保留份 B **不同**,是**独立的第 2 个版本**(当日 13:45 快照),**不是**「逐位重复副本」
- 任务书写「留 trade-data 侧 1 份,删掉**那 2 份重复副本**」,但复核后「逐位重复」的只有 **1 份**(A,已删);**C 不满足「确认确实逐位重复」这道任务书自设闸门** ⇒ 依「若复核发现并非逐位重复 → 停下报告,一份都不删」的纪律,**C 未删**
- C 一旦删除即**不可逆**(无 R2 归档、非 git、无其他副本);若用户确认「这台机器不再需要 09-09 13:45 版快照」,可再下一批删除(释放 176.1 MiB)
- 净结果:乙1 本批释放 **176.1 MiB**(528.2 MiB 中的 1/3);剩余 2 份 = B(保留源)+ C(待拍板)

## 二、② 109 个 `trade_sim_*.html` —— git tracked 归属分类表(**只核查,零删除**)

### 2.1 结论(先给结论)

- 实测家族成员 **109 个**(= trade-data 侧 103 + trade 侧 6),**全部 untracked**;
  家族中**唯一 git tracked** 的是 `static-site/trade_sim.html` **本体**(2.5MB,8-21,**禁删**,不在本表 109 内)
- 总量:**204,784,968 B(195.3 MiB,trade-data 侧)+ 5,490,618 B(5.2 MiB,trade 侧)= 200.5 MiB**
- 109 份 **md5 全互不相同**(无内容重复);6 个跨树同名对(trade-data vs trade)内容**各不相同**
- 全部为**真实文件**(非 symlink);同目录 25 个 symlink 均为活跃站点文件(index/about/trade_sim.html 等 → trade 侧),**不在本表**

### 2.2 ⚠️ 数量与上轮报告不符(如实标注)

| 维度 | 上轮报告(10-07) | 本轮实测(10-09) |
|---|---|---|
| 数量 | 107 个 | **109 个**(trade-data 103 + trade 6) |
| mtime 分布 | 103 个 7-29 + 4 个 7-23 | trade-data 103 个**全 = 2026-07-29 00:06**;trade 6 个**全 = 2026-08-02 23:11**;无 7-23 文件 |
| 同名对 | 「1 个与 trade-data 侧实体同名」 | **6 个全部同名**(cac40/g.cn10y/g.oil/g.usdcnh/kospi/nikkei225)且内容各异 |

- 已尽力校核差异来源:在 `trade-data-signal-staticdata` / `-old-20260926` / `code/wt` / `trade-data-dataset` 四个镜像根 `find -maxdepth 3` 搜 `trade_sim_*.html` = **零命中** ⇒ 差额 4 个不在这些常见镜像处;按实测数为准(109)

### 2.3 tracked 判定方法(严格只读)

```
git ls-files static-site          → 44 条(其中 .html 7 条:index/about/guide/privacy/databrief/
                                    admin/feedback/trade_sim.html;均不含 trade_sim_*.html)
109 个 basename × tracked 列表交叉 → 交集 = 0
git -C trade-data rev-parse       → fatal: not a git repository(trade-data 不属任何 repo)
```
⇒ 109 个 `trade_sim_*.html` **全部 untracked** 成立(≠ 上轮「103 个未跟踪」的说法在数量上需修正为 109)。

### 2.4 站内线上可达性/上传链路(引上轮实测,本轮未重跑)

- 上轮 curl 实测:`ss.fx8.store/trade_sim_bj50.html` → **404**、`trade_sim_cgb_idx.html` → **404**;`upload_r2.py` 仅传 `STATIC_DIR/data/trade_sim/*.json`(L1546),**从不涉及 static-site 根 html**
- 停用声明:`scripts/update_lab.sh` L22/L254「旧版 trade_sim.html 已停用,2026-08-21 清理」

### 2.5 全量表(109 行,按目录序:1-103 = trade-data/static-site,104-109 = trade/static-site)

| # | 路径(code/ 相对) | MiB | 侧 | mtime | git | md5(前12) |
|---|---|---|---|---|---|---|
| 1 | `trade-data/static-site/trade_sim_bj50.html` | 1.04 | TD | 2026-07-29 00:06 | **untracked** | 341ce0b08b49 |
| 2 | `trade-data/static-site/trade_sim_cac40.html` | 0.77 | TD | 2026-07-29 00:06 | **untracked** | bb89a0f4426f |
| 3 | `trade-data/static-site/trade_sim_cgb_10y_etf.html` | 6.08 | TD | 2026-07-29 00:06 | **untracked** | b89c9e4a6250 |
| 4 | `trade-data/static-site/trade_sim_cgb_10y_future.html` | 5.87 | TD | 2026-07-29 00:06 | **untracked** | 58ff78323a48 |
| 5 | `trade-data/static-site/trade_sim_cgb_idx.html` | 22.79 | TD | 2026-07-29 00:06 | **untracked** | d59ad74b2519 |
| 6 | `trade-data/static-site/trade_sim_csi1000.html` | 1.77 | TD | 2026-07-29 00:06 | **untracked** | be6a87cf35a3 |
| 7 | `trade-data/static-site/trade_sim_csi500.html` | 3.00 | TD | 2026-07-29 00:06 | **untracked** | fc68e9c31c53 |
| 8 | `trade-data/static-site/trade_sim_csi_div.html` | 1.26 | TD | 2026-07-29 00:06 | **untracked** | 53416feb3455 |
| 9 | `trade-data/static-site/trade_sim_cyb.html` | 2.75 | TD | 2026-07-29 00:06 | **untracked** | 323d7bbf36ac |
| 10 | `trade-data/static-site/trade_sim_dax.html` | 0.98 | TD | 2026-07-29 00:06 | **untracked** | a198354a5b73 |
| 11 | `trade-data/static-site/trade_sim_div_lowvol.html` | 1.43 | TD | 2026-07-29 00:06 | **untracked** | f4fe7c0763c9 |
| 12 | `trade-data/static-site/trade_sim_ftse100.html` | 0.76 | TD | 2026-07-29 00:06 | **untracked** | c213ed5a85e5 |
| 13 | `trade-data/static-site/trade_sim_g.a_qvix_1000.html` | 1.05 | TD | 2026-07-29 00:06 | **untracked** | b27640a125cb |
| 14 | `trade-data/static-site/trade_sim_g.a_qvix_300.html` | 0.63 | TD | 2026-07-29 00:06 | **untracked** | 8091515f752a |
| 15 | `trade-data/static-site/trade_sim_g.brent.html` | 1.30 | TD | 2026-07-29 00:06 | **untracked** | 65224e07eb44 |
| 16 | `trade-data/static-site/trade_sim_g.cn10y.html` | 0.68 | TD | 2026-07-29 00:06 | **untracked** | be2e68dedc8b |
| 17 | `trade-data/static-site/trade_sim_g.comex_silver.html` | 1.20 | TD | 2026-07-29 00:06 | **untracked** | a710b82a7464 |
| 18 | `trade-data/static-site/trade_sim_g.gold.html` | 1.16 | TD | 2026-07-29 00:06 | **untracked** | 4b556e4d6e75 |
| 19 | `trade-data/static-site/trade_sim_g.oil.html` | 1.11 | TD | 2026-07-29 00:06 | **untracked** | f8350a95c13a |
| 20 | `trade-data/static-site/trade_sim_g.us10y.html` | 1.35 | TD | 2026-07-29 00:06 | **untracked** | 8bf8e924035b |
| 21 | `trade-data/static-site/trade_sim_g.usdcnh.html` | 0.30 | TD | 2026-07-29 00:06 | **untracked** | c39173b47f99 |
| 22 | `trade-data/static-site/trade_sim_g.wti_oil.html` | 2.03 | TD | 2026-07-29 00:06 | **untracked** | 8e7619b5e6a8 |
| 23 | `trade-data/static-site/trade_sim_hk_cesg10.html` | 2.16 | TD | 2026-07-29 00:06 | **untracked** | 7832b01f047a |
| 24 | `trade-data/static-site/trade_sim_hk_cshkdiv.html` | 2.22 | TD | 2026-07-29 00:06 | **untracked** | 75a7ddb51074 |
| 25 | `trade-data/static-site/trade_sim_hk_cshklc.html` | 2.55 | TD | 2026-07-29 00:06 | **untracked** | dca9574ce114 |
| 26 | `trade-data/static-site/trade_sim_hk_cshklre.html` | 2.20 | TD | 2026-07-29 00:06 | **untracked** | 3131195841d5 |
| 27 | `trade-data/static-site/trade_sim_hk_hscci.html` | 2.51 | TD | 2026-07-29 00:06 | **untracked** | 395079d39d21 |
| 28 | `trade-data/static-site/trade_sim_hk_hsmbi.html` | 2.50 | TD | 2026-07-29 00:06 | **untracked** | 7399c4e46693 |
| 29 | `trade-data/static-site/trade_sim_hk_hsmogi.html` | 2.46 | TD | 2026-07-29 00:06 | **untracked** | 2000fe6d5ffb |
| 30 | `trade-data/static-site/trade_sim_hk_hsmpi.html` | 1.81 | TD | 2026-07-29 00:06 | **untracked** | b695f01af282 |
| 31 | `trade-data/static-site/trade_sim_hs300.html` | 2.60 | TD | 2026-07-29 00:06 | **untracked** | a2b8137c8986 |
| 32 | `trade-data/static-site/trade_sim_hscei.html` | 2.65 | TD | 2026-07-29 00:06 | **untracked** | e5e3b6393674 |
| 33 | `trade-data/static-site/trade_sim_hsi.html` | 2.22 | TD | 2026-07-29 00:06 | **untracked** | af2b5e96c291 |
| 34 | `trade-data/static-site/trade_sim_hstech.html` | 0.99 | TD | 2026-07-29 00:06 | **untracked** | fc405c7b5af5 |
| 35 | `trade-data/static-site/trade_sim_kc50.html` | 1.45 | TD | 2026-07-29 00:06 | **untracked** | 3c88aea79539 |
| 36 | `trade-data/static-site/trade_sim_kospi.html` | 1.18 | TD | 2026-07-29 00:06 | **untracked** | d7099cf9f122 |
| 37 | `trade-data/static-site/trade_sim_nikkei225.html` | 1.16 | TD | 2026-07-29 00:06 | **untracked** | b352b019a365 |
| 38 | `trade-data/static-site/trade_sim_sh.html` | 2.39 | TD | 2026-07-29 00:06 | **untracked** | ac56345f724f |
| 39 | `trade-data/static-site/trade_sim_sw_801010.html` | 0.93 | TD | 2026-07-29 00:06 | **untracked** | eb6b9806e5d9 |
| 40 | `trade-data/static-site/trade_sim_sw_801030.html` | 1.21 | TD | 2026-07-29 00:06 | **untracked** | ab4085f05561 |
| 41 | `trade-data/static-site/trade_sim_sw_801040.html` | 1.44 | TD | 2026-07-29 00:06 | **untracked** | 0142fc04d37c |
| 42 | `trade-data/static-site/trade_sim_sw_801050.html` | 1.93 | TD | 2026-07-29 00:06 | **untracked** | cf2ed5f08ad3 |
| 43 | `trade-data/static-site/trade_sim_sw_801080.html` | 1.16 | TD | 2026-07-29 00:06 | **untracked** | 94ed6c2f2590 |
| 44 | `trade-data/static-site/trade_sim_sw_801110.html` | 1.49 | TD | 2026-07-29 00:06 | **untracked** | 7741cadcb4fa |
| 45 | `trade-data/static-site/trade_sim_sw_801120.html` | 1.52 | TD | 2026-07-29 00:06 | **untracked** | e08ddd9b5440 |
| 46 | `trade-data/static-site/trade_sim_sw_801130.html` | 4.28 | TD | 2026-07-29 00:06 | **untracked** | 80c83d0b631c |
| 47 | `trade-data/static-site/trade_sim_sw_801140.html` | 4.54 | TD | 2026-07-29 00:06 | **untracked** | d98e61ae6bbc |
| 48 | `trade-data/static-site/trade_sim_sw_801150.html` | 1.29 | TD | 2026-07-29 00:06 | **untracked** | cd36c04b9347 |
| 49 | `trade-data/static-site/trade_sim_sw_801160.html` | 0.65 | TD | 2026-07-29 00:06 | **untracked** | 3795a0e53fc8 |
| 50 | `trade-data/static-site/trade_sim_sw_801170.html` | 0.67 | TD | 2026-07-29 00:06 | **untracked** | 0cbfbe61a50a |
| 51 | `trade-data/static-site/trade_sim_sw_801180.html` | 1.37 | TD | 2026-07-29 00:06 | **untracked** | 6fac0ead350e |
| 52 | `trade-data/static-site/trade_sim_sw_801200.html` | 4.53 | TD | 2026-07-29 00:06 | **untracked** | 2f77d056628d |
| 53 | `trade-data/static-site/trade_sim_sw_801210.html` | 1.04 | TD | 2026-07-29 00:06 | **untracked** | 6afd45547a73 |
| 54 | `trade-data/static-site/trade_sim_sw_801230.html` | 4.76 | TD | 2026-07-29 00:06 | **untracked** | dbc9f9e09f8d |
| 55 | `trade-data/static-site/trade_sim_sw_801710.html` | 1.25 | TD | 2026-07-29 00:06 | **untracked** | f9fc64cac273 |
| 56 | `trade-data/static-site/trade_sim_sw_801720.html` | 1.36 | TD | 2026-07-29 00:06 | **untracked** | 9a4b22680be2 |
| 57 | `trade-data/static-site/trade_sim_sw_801730.html` | 1.07 | TD | 2026-07-29 00:06 | **untracked** | e85b0f175fc5 |
| 58 | `trade-data/static-site/trade_sim_sw_801740.html` | 1.68 | TD | 2026-07-29 00:06 | **untracked** | 2a325660eb92 |
| 59 | `trade-data/static-site/trade_sim_sw_801750.html` | 1.19 | TD | 2026-07-29 00:06 | **untracked** | 607803ef6039 |
| 60 | `trade-data/static-site/trade_sim_sw_801760.html` | 1.18 | TD | 2026-07-29 00:06 | **untracked** | 55f800c44dae |
| 61 | `trade-data/static-site/trade_sim_sw_801770.html` | 1.23 | TD | 2026-07-29 00:06 | **untracked** | fbeeb920507d |
| 62 | `trade-data/static-site/trade_sim_sw_801780.html` | 1.88 | TD | 2026-07-29 00:06 | **untracked** | 7b2d91d485a7 |
| 63 | `trade-data/static-site/trade_sim_sw_801790.html` | 1.77 | TD | 2026-07-29 00:06 | **untracked** | 44daa2670472 |
| 64 | `trade-data/static-site/trade_sim_sw_801880.html` | 1.68 | TD | 2026-07-29 00:06 | **untracked** | 839477f911a3 |
| 65 | `trade-data/static-site/trade_sim_sw_801890.html` | 0.96 | TD | 2026-07-29 00:06 | **untracked** | bca8b8ffcf33 |
| 66 | `trade-data/static-site/trade_sim_sw_801950.html` | 1.08 | TD | 2026-07-29 00:06 | **untracked** | 5ce72e0af19e |
| 67 | `trade-data/static-site/trade_sim_sw_801960.html` | 0.84 | TD | 2026-07-29 00:06 | **untracked** | a629bded56a9 |
| 68 | `trade-data/static-site/trade_sim_sw_801970.html` | 1.08 | TD | 2026-07-29 00:06 | **untracked** | edfe91e80a5d |
| 69 | `trade-data/static-site/trade_sim_sw_801980.html` | 0.98 | TD | 2026-07-29 00:06 | **untracked** | 7cb5a5fd7ee0 |
| 70 | `trade-data/static-site/trade_sim_sz.html` | 3.14 | TD | 2026-07-29 00:06 | **untracked** | 2f94457fa4e7 |
| 71 | `trade-data/static-site/trade_sim_sz50.html` | 3.81 | TD | 2026-07-29 00:06 | **untracked** | 51a21006e6c9 |
| 72 | `trade-data/static-site/trade_sim_sz_div.html` | 2.80 | TD | 2026-07-29 00:06 | **untracked** | ff71c338e550 |
| 73 | `trade-data/static-site/trade_sim_thsc_300008.html` | 0.69 | TD | 2026-07-29 00:06 | **untracked** | 9def3f8cad01 |
| 74 | `trade-data/static-site/trade_sim_thsc_300082.html` | 1.82 | TD | 2026-07-29 00:06 | **untracked** | 4d59441e2c9e |
| 75 | `trade-data/static-site/trade_sim_thsc_300733.html` | 1.39 | TD | 2026-07-29 00:06 | **untracked** | 7104900a2f08 |
| 76 | `trade-data/static-site/trade_sim_thsc_300816.html` | 0.96 | TD | 2026-07-29 00:06 | **untracked** | fb3a7fd3301b |
| 77 | `trade-data/static-site/trade_sim_thsc_300830.html` | 1.87 | TD | 2026-07-29 00:06 | **untracked** | 907c294d4cc6 |
| 78 | `trade-data/static-site/trade_sim_thsc_301079.html` | 1.54 | TD | 2026-07-29 00:06 | **untracked** | bf18da9d33c7 |
| 79 | `trade-data/static-site/trade_sim_thsc_301085.html` | 1.05 | TD | 2026-07-29 00:06 | **untracked** | c437887adafb |
| 80 | `trade-data/static-site/trade_sim_thsc_302035.html` | 0.68 | TD | 2026-07-29 00:06 | **untracked** | d0df44ba17db |
| 81 | `trade-data/static-site/trade_sim_thsc_306380.html` | 0.98 | TD | 2026-07-29 00:06 | **untracked** | f37ccf90ccbf |
| 82 | `trade-data/static-site/trade_sim_thsc_307940.html` | 0.99 | TD | 2026-07-29 00:06 | **untracked** | bf4006972653 |
| 83 | `trade-data/static-site/trade_sim_thsc_308014.html` | 1.03 | TD | 2026-07-29 00:06 | **untracked** | a18c9a4b7076 |
| 84 | `trade-data/static-site/trade_sim_thsc_308294.html` | 1.11 | TD | 2026-07-29 00:06 | **untracked** | 89ff8f2c5f08 |
| 85 | `trade-data/static-site/trade_sim_thsc_308300.html` | 1.54 | TD | 2026-07-29 00:06 | **untracked** | e76443dffe08 |
| 86 | `trade-data/static-site/trade_sim_thsc_308491.html` | 1.82 | TD | 2026-07-29 00:06 | **untracked** | 3493e469d786 |
| 87 | `trade-data/static-site/trade_sim_thsc_308700.html` | 1.47 | TD | 2026-07-29 00:06 | **untracked** | 3cf174bb0fc6 |
| 88 | `trade-data/static-site/trade_sim_thsc_308725.html` | 1.30 | TD | 2026-07-29 00:06 | **untracked** | 30bb9e4e7627 |
| 89 | `trade-data/static-site/trade_sim_thsc_308752.html` | 1.38 | TD | 2026-07-29 00:06 | **untracked** | 32c75e1721d4 |
| 90 | `trade-data/static-site/trade_sim_thsc_308828.html` | 1.53 | TD | 2026-07-29 00:06 | **untracked** | 248366f06f65 |
| 91 | `trade-data/static-site/trade_sim_thsc_308870.html` | 1.33 | TD | 2026-07-29 00:06 | **untracked** | 2b6f8d0c8f30 |
| 92 | `trade-data/static-site/trade_sim_thsc_309020.html` | 0.91 | TD | 2026-07-29 00:06 | **untracked** | 5c455206f85e |
| 93 | `trade-data/static-site/trade_sim_thsc_309049.html` | 0.77 | TD | 2026-07-29 00:06 | **untracked** | bd5b28710531 |
| 94 | `trade-data/static-site/trade_sim_thsc_309060.html` | 0.90 | TD | 2026-07-29 00:06 | **untracked** | e91d1d8d66f6 |
| 95 | `trade-data/static-site/trade_sim_thsc_309068.html` | 0.98 | TD | 2026-07-29 00:06 | **untracked** | b61f6aa27fd6 |
| 96 | `trade-data/static-site/trade_sim_thsc_309113.html` | 0.72 | TD | 2026-07-29 00:06 | **untracked** | 4c48bf7e0055 |
| 97 | `trade-data/static-site/trade_sim_thsc_309115.html` | 0.76 | TD | 2026-07-29 00:06 | **untracked** | c627b0836597 |
| 98 | `trade-data/static-site/trade_sim_thsc_309119.html` | 0.87 | TD | 2026-07-29 00:06 | **untracked** | 09c59730e846 |
| 99 | `trade-data/static-site/trade_sim_thsc_309128.html` | 0.77 | TD | 2026-07-29 00:06 | **untracked** | 9ca554404ac3 |
| 100 | `trade-data/static-site/trade_sim_us_dji.html` | 2.07 | TD | 2026-07-29 00:06 | **untracked** | 509e17c2802e |
| 101 | `trade-data/static-site/trade_sim_us_ixic.html` | 3.27 | TD | 2026-07-29 00:06 | **untracked** | dd8321a32f99 |
| 102 | `trade-data/static-site/trade_sim_us_ndx.html` | 2.28 | TD | 2026-07-29 00:06 | **untracked** | 295b97ff71bc |
| 103 | `trade-data/static-site/trade_sim_us_spx.html` | 2.35 | TD | 2026-07-29 00:06 | **untracked** | d5b2a2d16925 |
| 104 | `trade/static-site/trade_sim_cac40.html` | 0.77 | TR | 2026-08-02 23:11 | **untracked** | c492e0958a1a |
| 105 | `trade/static-site/trade_sim_g.cn10y.html` | 0.68 | TR | 2026-08-02 23:11 | **untracked** | 6e44a0cd4e1e |
| 106 | `trade/static-site/trade_sim_g.oil.html` | 1.11 | TR | 2026-08-02 23:11 | **untracked** | cd17b224eff0 |
| 107 | `trade/static-site/trade_sim_g.usdcnh.html` | 0.31 | TR | 2026-08-02 23:11 | **untracked** | 78bb25119890 |
| 108 | `trade/static-site/trade_sim_kospi.html` | 1.19 | TR | 2026-08-02 23:11 | **untracked** | c5d1c36cf3b5 |
| 109 | `trade/static-site/trade_sim_nikkei225.html` | 1.18 | TR | 2026-08-02 23:11 | **untracked** | f931ba788644 |

- 侧说明:**TD** = `/Users/linhuichen/code/trade-data/static-site/`(103 个,195.3 MiB)、**TR** = `/Users/linhuichen/code/trade/static-site/`(6 个,5.2 MiB)
- 最大 10 个:`trade_sim_cgb_idx.html` 22.79 / `cgb_10y_etf` 6.08 / `cgb_10y_future` 5.87 / `sw_801230` 4.76 / `sw_801140` 4.54 / `sw_801200` 4.53 / `sw_801130` 4.28 / `sz50` 3.81 / `us_ixic` 3.27 / `sz` 3.14(MiB)
- 尺寸区间:min 317,222 B / max 23,902,254 B / 均值 ≈1,929,134 B

### 2.6 待拍板(未删任何文件)

- 是否删这 109 个(200.5 MiB)?判据齐备:线上 404 + 已停用声明 + 上传链路不含 + 全部 untracked;⚠️ 唯一阻断点 = **本体 `trade_sim.html` 本体 2.5MB 是 git tracked(禁删)**,删时必须白名单 `trade_sim_*.html` 模式、**勿按「根 html」通配**(会踩 25 个活跃 symlink)
- 恢复路径:重生成 `python3 scripts/simulate_trade.py --html`(已停用形态,不建议重建)或删前 tar 归档

## 三、③ stash ×3 只读审阅(呈用户拍板,**未 apply/pop/drop/save**)

| stash | base / 日期 | 文件(+/−) | 改了什么 | 现状对账(本轮实测) | 值不值得留 |
|---|---|---|---|---|---|
| `stash@{0}` | 98470715b / 2026-09-19 20:01 | 1: `docs/kelly/position/scripts/accum_nav_map.json`(1+/1−) | JSON 单行整行改写(管线产物,含 20260826-… 净值 map 的一天差异) | 当前工作区文件与 HEAD **一致**(`git status --porcelain` 空);该产物是**每日 deploy 管线再生成品** | **可弃**:内容=过时管线中间态,下一次 deploy 即重算覆盖 |
| `stash@{1}` | b52804d64 / 2026-09-08 08:37 | 7: README(5+/12−)、TASKS(1+/1−)、accum_nav_map(1+/1−)、**plist 删除**(0+/40−)、about/guide/privacy html(各 2+/2−) | ①README **删 5 条描述**(3 条功能条目:#101 北交所宽度独立指标 / #100 lab 凯利区两阶段 / #99 更新新版气泡预览 + 2 条工具说明:check_task_state / 数据缺口告警)+ 改写 FAPI 行、回测买入价口径行、首页模拟回测行、删 verify_sigkelly 段;②**G/H/I 的 H 档数字 230.83%→224.92%**;③TASKS 头部「最后更新」句;④plist 整文件删除;⑤三个 html 版本串 a554→a555 | README:当前 main **仍含** #101/#100/#99 三条(各 grep=1)且仍是 **230.83%**(224.92% 零命中)⇒ 该改动**从未落地**;plist:当前已不存在且未 tracked(后续 commit `536d62202` 已删)⇒ **已被取代**;html 版本串:当前 = **20261004-a642** ⇒ **远新于 a555,过时**;accum_nav_map 同上条(管线产物) | **其中的「删 README 描述」是唯一口味项**(用户原意是否是删那几条?)——但内容已过时:数字回退(224.92 与现行 230.83 冲突)、版本串差 3 个版本、plist/管线件已被取代。**建议:整条弃**(若用户仍想删那几条描述,重开小任务现删,勿 apply 一个月前的 stash) |
| `stash@{2}` | 60185b511 / 2026-09-07 09:08 | 2: `docs/pending-features-index.md`(1+/1−)、`scripts/agent_inbox_watcher.py`(11+/1−) | ①index 第 91 行改写为「凯利回测次日开盘/当日收盘买入口径双档切换(实施中…)」;②watcher `sync_git_refs()`:failed 且 retry 未耗尽 → 重建 `.ready` 让 pump 重试 | ①当前 index 第 91 行 = 「次日开盘口径确认(**✅ 已完成,2026-09-12 核销**)」⇒ **已过时**;②当前 main 的 `sync_git_refs()` 已含**同语义且更完整**的实现(L247-259:failed→retry<MAX 重建 ready + 退避 `retry_backoff_ok` + 耗尽写 `blocked` 终态 + `cleanup_ref` 防泄漏)⇒ **stash 版是它的早期草稿** | **可弃**:两处内容均已由 main 的更完整实现取代 |

> 三个 stash 的 message 原文保留可查(`git stash list`)。**本轮全程只读**:`git stash list` / `git stash show` / `git diff stash@{n}^1 stash@{n}`(注:`git stash show -p <stash> -- <path>` 不支持 pathspec 会报 "Too many revisions",改用 `git diff` 等价读)。

## 四、纪律合规声明(逐条实测)

- ① **零 git 写操作**:未切分支 / 未 `checkout` / 未 `reset` / 未 `commit` / 未 `push`;`git stash` 仅用只读子命令(`list` / `show` / `diff stash@{n}^1`),**未 apply / pop / save / drop**(收尾实测 `git stash list` 仍 3 条,与开始时一致)
- ② 收尾 `git status --porcelain` = **仅 1 行**:`?? docs/ops/disk-cleanup-batch2-20261009.md`(本报告本身);分支仍 `main` ✓
- ③ **未触发任何真实告警/邮件/飞书**;未写 R2(本轮零 R2 调用);未裸跑 pip/npm;未用 Docker;未 `find /`;未无白名单 `grep -r`(仅 `scripts docs .claude` 项目目录)
- ④ 所有命令带 Bash timeout(最长 300s 档);大输出落盘截断,不内联
- ⑤ 删除类动作遵守 §25:先复核(独立 md5)→ 确认存在(ls -la)→ 验过再删;**C 因「非逐位重复」按纪律停下未删**
- ⑥ 未触碰保护对象:根 `data/` 其他文件、sentiment.db、staticdata-old(8.3G,保留至 10-30)、git tracked 内容
- ⑦ df 收尾:`/dev/disk3s5 460Gi 用 288Gi 可用 144Gi (67%)`

## 五、复现命令(核验用)

```bash
# ① p0:复核三对象 + md5(现只剩 2 个)
ls -la /Users/linhuichen/code/trade-data/data/etf_national_team.db.bak-p0-20260909 \
       /Users/linhuichen/code/trade/data/etf_national_team.db.bak-p0-20260909-1345
md5 -q /Users/linhuichen/code/trade-data/data/etf_national_team.db.bak-p0-20260909   # 55926b744cca11d69ed32e90e91d6eb1
md5 -q /Users/linhuichen/code/trade/data/etf_national_team.db.bak-p0-20260909-1345   # e79d3cc8003106f4bea86e78339c2c85
git -C /Users/linhuichen/code/trade ls-files -- data/etf_national_team.db.bak-p0-20260909   # 空 = untracked
# ② 109 html:数量 + tracked 交叉
ls -1 /Users/linhuichen/code/trade-data/static-site/trade_sim_*.html | wc -l   # 103
ls -1 /Users/linhuichen/code/trade/static-site/trade_sim_*.html | wc -l        # 6
cd /Users/linhuichen/code/trade && git ls-files static-site | grep '\.html$'   # 7 条,无 trade_sim_*
# ③ stash 只读审阅
cd /Users/linhuichen/code/trade && git stash list
git stash show --numstat "stash@{1}"
git diff "stash@{1}^1" "stash@{1}" -- README.md | grep -E '^[-+]' | grep -vE '^(--- a/|\+\+\+ b/)'
```

## 六、待主控/用户拍板项(本批新增 + 顺延)

1. **乙1 的 C 份**(`data/etf_national_team.db.bak-p0-20260909-1345`,176.1 MiB):与保留份**不同版本**、无 R2 归档、删即不可逆 → 是否删?(本批按纪律未删)
2. **109 个 `trade_sim_*.html`**(200.5 MiB):全部 untracked + 线上 404 + 已停用 → 是否删?(删时白名单 `trade_sim_*.html`,护住本体 `trade_sim.html` 与 25 个活跃 symlink)
3. **stash ×3**:①`stash@{0}` 管线中间态 ②`stash@{1}` 含 README 口味项(删 #101/#100/#99 三条功能描述 + H 档数字回退 224.92)③`stash@{2}` 已被 main 更完整实现取代 → 是否 drop?(**drop = git 状态写操作,需用户点头后由主控另派执行**)

> 落档:docs/ops/disk-cleanup-batch2-20261009.md(2026-10-09,未 commit,待主控统一收)。
