# B3 fund_nav 清理 审计产物归档 — #111(2026-10-11)

> 归档目的(§23.5 新产物当场落档):B3 清理 run 的**原始审计清单**原仅存 `/tmp/b3/`(易失),审查修正项 4 建议归档入报告链。本目录 = 该 run 的一手证据落档副本。
> 生成:implementer(role-implementer),2026-10-11 二轮返修;源 `/tmp/b3/`(2026-10-11 09:56~10:01 实跑输出)。
> 关联报告:`docs/ops/next-steps-b3-verify-20261011.md`(清理前验证)/ `next-steps-b3-exec-20261011.md`(执行)/ `next-steps-b3-review-20261011.md`(独立审查)。

## 文件清单 + 校验

| 文件 | 内容 | 计数 | 体积 | sha256(源件,未压缩) |
|---|---|---|---|---|
| `r2_fund_nav_pre.json.gz` | R2 `signal-data` 桶 `fund_nav/` 前缀**删前** LIST(key/size/mtime) | 26,458 | 254,884 B(gz) | `dee44986519b946acda5674b6c08ce2724f06f43de2cc9aa0d64bae6956fc040` |
| `r2_backup_post.json.gz` | R2 `signal-backup2` 桶 `large-json/fund_nav/` **删后** LIST(证明备份未动) | 26,458 | 253,786 B(gz) | `fb31cdcf472cd5b0f0e5b7a0ae15413e75e4c8da585239ce6c4f90414ce1ee2f` |
| `r2_fundnav_post.json` | R2 `signal-data` 桶 `fund_nav/` **删后** LIST(证明归零) | 0(`[]`) | 2 B | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `r2_navbucket_post.json.gz` | R2 `signal-data` 桶 `nav_bucket/`(现役)**删后** LIST(证明未动) | 256 | 3,349 B(gz) | `6e36d17f72c4e42d18caca1dfe0b1bbdb27c9fbd31443f8aa983922834184d7e` |
| `restore_test_fund_nav_000001.json` | 从备份实测取回样本(000001,恢复路径可用性证据) | — | 30,497 B | `953ac5a3b43352bcd14ebca0e5715c1b62a0ce011483a1dfb38aeb29294af27c` |
| `mac_staticdata_names.txt.gz` | mac staticdata `data/fund_nav` 残树文件名清单(二轮返修清单比对源) | 26,370 | 64,376 B(gz) | (源文本见下) |

**同源校验(为什么只留这些)**:
- 源 `/tmp/b3/r2_backup_fundnav.json`(09:56)与 `r2_backup_post.json`(10:00)**sha256 逐位相同**(`fb31cdcf…`)⇒ 备份删前删后零变化,只留 post 一份。
- 源 `/tmp/b3/r2_nav_bucket.json`(09:56)与 `r2_navbucket_post.json`(10:00)**sha256 逐位相同**(`6e36d17f…`)⇒ nav_bucket 零变化,只留 post 一份。

**mac_staticdata_names.txt 源件 sha256**(gzip 前文本,26,370 行):`f9dff777f0245231cc16b88aa91250125c7423084b8a49232a907b07d443bc55`(文本可 `gzip -dc` 还原)。

## 恢复/复现

- **审计件还原**:`gzip -dc <file>.json.gz > <file>.json`。
- **R2 前缀现状复 LIST(复现,只读)**:`python scripts/r2_list_prefix.py signal-data "fund_nav/" /tmp/x.json` → 应 `[]`(前缀已删)。
- **备份现状复 LIST(只读)**:`python scripts/r2_list_prefix.py signal-backup2 "large-json/fund_nav/" /tmp/x.json` → 应 26,458。
- **数据恢复**(若要还原 fund_nav 数据本体):`bash scripts/restore-large-json.sh --all --target <目标树>/static-site/data`(从 `signal-backup2/large-json/fund_nav/` 取回;详见 exec 报告 §4)。

> 注:本目录为 `docs/ops/` 下的**只读证据归档**,非上线产物,不进 `static-site/`、不碰 R2。