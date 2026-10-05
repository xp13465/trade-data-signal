# large-json/ 前缀 lifecycle 可配性核实报告(pending #179 前置核实,2026-10-05,全程只读)

> 任务:核实老桶 `signal-backup` 的 `large-json/` 前缀**能否安全配 R2 lifecycle**(为 pending-features-index #179「R2 备份桶 lifecycle 补齐」提供依据)。
> 前置文档:docs/ops/r2-backup-prefix-lifecycle-audit-20261005.md(普查报告)。
> **结论一句话:`large-json/` 整段不能配(规则命中 prefix 下全部对象,会删掉 31,673 个唯一副本);「一条能自动覆盖任意 legacy 日期目录、又不碰 flat 的泛化前缀」**不存在**(R2 prefix 为字面字符串匹配,不支持通配符);legacy 存量 27,673 个正被代码「7 天宽限」机制按日自动清(预计 10-06~10-08 清零),无需 R2 规则——只要在「代码切走」前做一次遗留清零复核即可。**

## 0. 四问直答

| 问 | 答 | 一句话证据 |
|---|---|---|
| ① flat 的 key 实际形态?会不会与 legacy 日期目录同形? | `large-json/<rel>.gz`,rel=staticdata 仓库 `data/` 下相对路径(9 个固定目录 + 7 个根层文件);**31,673 个 flat key 中 0 个含 `YYYY-MM-DD` 形态的路径段** | 云上全量 ListObjectsV2 逐 key 正则穷举(§1) |
| ② legacy 27,673 现在还在不在?prune 跑过吗? | **还在**(09-29: 11,875 + 09-30: 15,798);**prune 一直在跑**(10-02/10-04/10-05 各有真实删除记录);没清的**真原因=7 天宽限期未到**(非「从未执行」、非「上传失败 exit」) | async 日志 + dry-run 实测(§2) |
| ③ 有没有一个前缀只命中 legacy、不命中 flat? | **泛化前缀:不可配**(无通配符;任何短前缀的安全性只靠当前命名约定,未来不可控);**具体前缀:当前可配**(`large-json/2026-09-` 或两个具体日期目录,实测 0 flat 命中)但无泛化价值 | 前缀命中穷举 + CF 官方文档(§3) |
| ④ 该不该配?滞留风险如何规避? | **`large-json/` 不配**(必删唯一副本);legacy 靠代码清+切走前清零复核;**无需配任何大型规则**;可选临时规则方案见 §4 | §4 |

## 1. ① flat key 实际形态(云上实测,2026-10-05 12:09)

**机制**(代码):默认固定前缀模式下 key = `large-json/<rel>.gz`,`rel` = staticdata 仓库 `data/` 下相对路径(清单来源 `scripts/large_json_excludes.py --print`,L291-305;key 生成 `scripts/upload_r2.py:2651-2652 _mk_key`)。legacy 形态 = `large-json/<YYYY-MM-DD>/<rel>.gz`(逃生门 `R2_LARGE_JSON_DATE_PREFIX=1`,同 L2652)。

**实测总量**:`large-json/` 全量 59,346 key / 733,529,084 B(与普查报告一致)。其中:
- **flat 31,673** / 454,482,585 B / 首段构成:`fund_nav` 26,458、`accum_nav` 1,718、`etf` 1,718、`trade_sim` 504、`signal_kelly_trades_sdc_parts` 391、`signal_kelly_trades_parts` 383、`nav_bucket` 256、`index` 173、`lab` 65,加 7 个 data/ 根层文件(`accum_nav_map.json.gz`、`offshore_fund_fee_detail/performance/purchase_status/risk_indicator.json.gz`、`signal_kelly_trades.json.gz`、`signal_kelly_trades_sdc.json.gz`)。
- **legacy 27,673** / 279,046,499 B / 2 个日期目录:2026-09-29(11,875)、2026-09-30(15,798)。

**关键穷举(flat 是否与 legacy 同形)**:
- flat 中首段为 `^\d{4}-\d{2}-\d{2}$` 形态的 key:**0 个**;
- flat 中路径**任意中间段**为日期形态的 key:**0 个**;
- flat 首段以数字开头的:**0 个**;flat 任意段以 `2026` 开头的:**0 个**。
- ⇒ flat 与 legacy 唯一共享的是 `large-json/` 这个大前缀;**不存在 flat key 落入 `large-json/<date>/` 形态**。

## 2. ② legacy 现状 + prune 执行史(云上实测)

**现状**:27,673 个 legacy 对象仍在(09-29: 11,875 / 09-30: 15,798),检查时刻 2026-10-05 12:09。

**来源佐证(两目录=当时按日上传的完整合法快照,非残渣)**:09-29 目录 ≈ 当日三轮上传并集(00:09 首轮 8 个根层文件 + 05:22 轮 11,868 + 19:41 轮 2,437 → 11,875);09-30 目录 = 当日三轮并集(00:50 轮 102 + 02:36 轮 9,466 + 05:49 轮 15,799 → 15,798);09-30 19:23 起即切固定前缀(flat)。

**prune 执行史**(云上 `/home/ubuntu/code/trade-data/data/logs/staticdata_backup_async_2026*.log`):
- 10-01 起每一轮 async 都执行 `_prune_large_json`,输出「无待清理旧日期目录(固定前缀 31673 个唯一副本保留)」;
- **真实删除发生过 3 次**:10-02 23:44、10-04 04:07、10-05 00:32 各「清理旧日期目录(legacy) **8 个 key**」(推断=早期每日首轮仅 8 个根层文件时代的小目录尾巴到期后被清;09-29 日志首轮『8/8 上传』佐证当时首轮清单确为 8 个根层文件;单次删除的日志打印不含目录名,归属为推断);
- **历史零「删除失败」记录**(grep 全日志无 `删除失败`);
- 20261001~05 共 **22 次 step3.5b 全 ✓**、无「large-json 上传 x/y 失败」记录。

**「没清」的原因 = 7 天宽限期未到(代码设计),不是没跑**:
- `_prune_large_json` L2466:`if (today - dd).days < 7: continue`——键龄 <7 天的日期目录保留(过渡期快照仍可能被恢复侧读)。10-05 时 09-29 age=6、09-30 age=5,均在宽限内。
- **dry-run 双路径实测**(2026-10-05 12:1x):默认路径 `_prune_large_json(dry_run=True)` 与逃生门路径 `_prune_large_json_legacy(dry_run=True)` 均输出「无待清理」、可删数=0,与代码判定一致。
- **对任务假设的否定**:「因 cmd_upload_large_json 上传失败即 exit(:2869)导致 prune 从不执行」**不成立**——(a) prune 实际执行过且清过 3 次;(b) 近 5 天无任何上传失败;(c) 即便某轮失败 exit,下轮成功仍会执行 prune,不存在「从不」路径。

**预测清零时点**(前提:async 继续跑,常态每日 4~7 轮,统计:10-01 6 轮 / 10-02 1 / 10-03 7 / 10-04 4 / 10-05 截至中午 4):
- 09-29 目录 10-06 起(age=7)进入可删;09-30 目录 10-07 起;
- 单轮删除上限 `R2_LARGE_JSON_PRUNE_LIMIT=3000`(L2443),09-29 需 4 轮、09-30 需 6 轮 → **预计 10-06~10-08 内清空**(按日期升序分批);若个别天 async 触发轮次不足(如 10-02 全天仅 1 轮),清零顺延 1~2 天。
- **复核动作(建议)**:10-08 后跑一次只读枚举,确认 `large-json/` 下无 `^\d{4}-\d{2}-\d{2}/` 形态 key(命令见 §5)。

## 3. ③ 前缀可行性穷举(R2 lifecycle 前缀语义 + 全量命中实测)

**R2 lifecycle 前缀语义(外部查证,2026-10-05)**:
- CF 官方文档源文 `cloudflare-docs@production: src/content/docs/r2/buckets/object-lifecycles.mdx` L28:「When you create an object lifecycle rule, you can specify which prefix you would like it to apply to」;示例 Filter 全为**字面串**(`Prefix: "2019/"` L90、`"logs/"` L114、`"useruploads/"` L133);**全文无 wildcard/glob 表述**;上限 1000 条规则(L30)。
- R2 S3 兼容页:`PutBucketLifecycleConfiguration / GetBucketLifecycleConfiguration` 均 ✅ 支持(developers.cloudflare.com/r2/api/s3/api/)——`Filter.Prefix` 即 S3 语义「对象键以该字符串开头」的**字面前缀**匹配。
- 本环境先例:老桶已配的唯一规则即字面 prefix 配法(`backup/` 14 天,用户 dashboard 实测)。
- 诚实标注:未检索到「显式声明不支持通配符」的官方原文(文档只是从未提及;community.cloudflare.com 被反爬 403、WebFetch 域名被网络策略阻断,社区检索未果)。「字面前缀」结论由「文档不声明通配 + S3 标准语义 + 示例全字面」三项组合支撑,用于本判断足够。

**候选前缀全量命中实测(31,673 flat + 27,673 legacy 全 key 穷举)**:

| 候选前缀 | flat 命中 | legacy 命中 | 判定 |
|---|---|---|---|
| `large-json/` | **31,673** | 27,673 | **不可用**(删唯一副本) |
| `large-json/2` | 0 | 27,673 | 当前安全,但语义靠命名约定(未来 flat 出现数字开头即误命中) |
| `large-json/20` / `large-json/2026` / `large-json/2026-` / `large-json/2026-09` | 0 | 27,673 | 同上 |
| `large-json/2026-09-`(legacy 全集的 LCP) | **0** | **27,673** | 当前可单条全覆盖两目录;**仅覆盖 2026-09,对未来新 legacy(逃生门)不生效** |
| `large-json/2026-09-29/` | 0 | 11,875 | 具体目录级,可用但静态 |
| `large-json/2026-09-30/` | 0 | 15,798 | 同上 |

**回答③**:「一条能自动覆盖『任意 legacy 日期目录』的泛化前缀」**不存在/不可配**——理由:(a) R2 只支持字面字符串前缀,写不出「任意日期形态」的通配匹配;(b) 任何比具体日期更短的前缀(如 `large-json/2`)之所以『现在』零 flat 命中,靠的是当前数据命名恰好无数字开头,属于**命名约定而非设计保证**(flat 清单含「data/ 下新增 >20MB 未跟踪文件」自动纳入路径,命名未来可变);(c) `large-json/` 整段必然同时命中 flat(实测 31,673)。而「针对当前两个已知日期目录」的具体前缀**行为上可配**(实测零 flat 命中),但只覆盖这批存量、不泛化。

## 4. ④ 结论与建议

1. **`large-json/` 前缀不配删除类 lifecycle(明确不可)**。flat 31,673 是 git 已 `rm --cached` 后的**唯一完整异地副本**(上传脚本与 manifest 均如此声明:L2428-2429、L2534);R2 prefix 无法区分 legacy/flat,凡落 `large-json/` 的删除规则必误删唯一副本 = 灾备丢数据。**此项可作 #179 对 large-json/ 的定案:不配。**
2. **legacy 存量(27,673)无需 R2 规则**:代码 7 天宽限机制正在按日清(§2),预计 10-06~10-08 清零;唯一要补的是**复核 + 切走前检查**(见下)。
3. **可选(不推荐作常态;仅当想与代码解耦时)**:临时配 `large-json/2026-09-`(或并列 2 条具体日期前缀)+ 「7 天过期」,清空后**移除规则**。注意两点尾部风险:①只覆盖 2026-09 存量,对未来逃生门新 legacy 不生效;②未来若出现以该串开头的 flat 新对象会被误删(概率极低但非零)。
4. **legacy 滞留风险与规避**:
   - 量级=**一次性存量 ≈0.28 GiB,不会增长**——默认固定前缀机制下不再产生日期目录;仅当有人显式设 `R2_LARGE_JSON_DATE_PREFIX=1`(逃生门)才会新增,云上实测 scripts/systemd 均无该 env,当前未启用。
   - **推荐规避 = 「代码切走前先清零复核」**:切走(迁新桶/停 async)前,只读枚举 `large-json/` 确认无 `YYYY-MM-DD/` 形态 key;若届时未清(async 停跑等),手动跑一次 `upload-large-json`(其 prune 按既定宽限清)或按日期目录直接删。此检查把滞留风险压为 0,且不需要任何 R2 规则。
   - 新桶 `signal-backup2` 同理:不要为 large-json 配 `large-json/` 整段规则;若承接 large-json 写入,同样只需「legacy 清零后再切」。

## 5. 取证方式清单(每条可复核)

- 【云上实测-全量分类】探针 `/tmp/lj_probe.py`(ssh `ubuntu@122.51.111.173` -i tdsignal.pem;`/home/ubuntu/code/trade-data/.venv/bin/python`),复用 `upload_r2._list_keys/s3_request` 全量分页列 `large-json/` → 59,346 key,legacy/flat 分类、首段分布、日期形态穷举(脚本全文见附录 A)。
- 【云上实测-dry-run】`/tmp/lj_dry.py`:`_prune_large_json(dry_run=True)` + `_prune_large_json_legacy(dry_run=True)` → 均 0 可删(宽限内)。
- 【云上实测-prune 史】`grep "清理旧日期目录\|无待清理旧日期\|删除失败" /home/ubuntu/code/trade-data/data/logs/staticdata_backup_async_2026*.log` → 24 行记录(3 次清理各 8 key + 其余无待清理 + 0 失败)。
- 【云上实测-上传成功史】`grep "step3.5b" ...2026100*.log` → 22 次全 ✓;`grep "上传 [0-9]*/[0-9]* 失败"` → 0。
- 【云上实测-逃生门 env】`grep -rn "R2_LARGE_JSON_DATE_PREFIX" scripts/*.sh /etc/systemd/system/*` → 无。
- 【代码】`scripts/upload_r2.py`:L2419 `_prune_large_json` / L2435-2440 逃生门分派 / L2446 `_list_keys("large-json/")` / L2450 legacy 正则 / L2455-2456 空判 / L2466 7 天宽限 / L2443 删除上限 3000 / L2473-2480 逐 key DELETE / L2651-2652 `_mk_key` / L2869 上传失败 exit / L2893 prune 调用点(全成功才跑);`scripts/large_json_excludes.py`:L69-79 DIR_EXCLUDES / L291-305 --print。
- 【官方文档】cloudflare-docs `production` 分支 `src/content/docs/r2/buckets/object-lifecycles.mdx`(prefix 字面示例 L90/114/133、无 wildcard、1000 条上限 L30);R2 S3 API 兼容页(PutBucketLifecycleConfiguration ✅)。
- 【前报告】docs/ops/r2-backup-prefix-lifecycle-audit-20261005.md(§1 前缀全量表/§4.1 建议/§7 取证)。

### 5.1 探针脚本全文(可重建,重建后直接跑)

见附录 A(探针)与附录 B(dry-run)。云上 /tmp 脚本为临时件,过期即失;本报告内嵌为可复现版本。

## 6. 遗留 / 待复核

1. **10-06~10-08 复核 legacy 是否按预测清空**(只读枚举 `large-json/` 无日期形态目录);若未清,按 §4 第 3/4 条处置。
2. 本报告未改动任何桶对象/代码;所有云上操作均为只读 List/HEAD 类(prune 用 dry_run)。
3. `large-json/` 的 lifecycle 定案(不配)建议在 #179 落地时同步写进待办与后续「老桶冷冻/切走检查清单」。

---

## 附录 A:探针脚本(lj_probe.py,可复跑)

```python
# 用法: scp 到云上, /home/ubuntu/code/trade-data/.venv/bin/python /tmp/lj_probe.py
import sys, os, re
sys.path.insert(0, "/home/ubuntu/code/trade-data/scripts")
os.environ.setdefault("GIT_REPO", "/home/ubuntu/code/trade-data")
os.environ.setdefault("REPO", "/home/ubuntu/code/trade-data")
import upload_r2 as u
from collections import Counter

def list_all(prefix, delimiter=None, maxkeys=1000, bucket=None):
    bkt = bucket or u.BACKUP_BUCKET
    out = []; prefixes = []; token = ""
    for page in range(500):
        q = "list-type=2&max-keys=" + str(maxkeys) + "&prefix=" + u.quote(prefix, safe="")
        if delimiter: q += "&delimiter=" + u.quote(delimiter, safe="")
        if token: q += "&continuation-token=" + u.quote(token, safe="")
        status, data = u.s3_request("GET", "", query=q, bucket=bkt)
        if status != 200:
            print("ERR prefix=%s status=%s" % (prefix, status)); return out, prefixes
        text = data.decode("utf-8", errors="replace")
        prefixes += re.findall(r"<CommonPrefixes>.*?<Prefix>([^<]+)</Prefix>", text, re.S)
        keys = re.findall(r"<Key>([^<]+)</Key>", text)
        sizes = re.findall(r"<Size>(\d+)</Size>", text)
        for k, s in zip(keys, sizes): out.append((k, int(s)))
        if "<IsTruncated>true</IsTruncated>" not in text: break
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if not m: break
        token = m.group(1)
    return out, prefixes

ks, _ = list_all("large-json/")
print("TOTAL:", len(ks), sum(s for _, s in ks))
legacy = []; flat = []
for k, s in ks:
    (legacy if re.match(r"^large-json/\d{4}-\d{2}-\d{2}/", k) else flat).append((k, s))
print("legacy:", len(legacy), "flat:", len(flat))
bad = [k for k, _ in flat if re.match(r"^\d{4}-\d{2}-\d{2}$", k[len("large-json/"):].split("/", 1)[0])]
print("flat key first-seg date-shaped:", len(bad))
```

## 附录 B:dry-run 脚本(lj_dry.py)

```python
import sys, os
sys.path.insert(0, "/home/ubuntu/code/trade-data/scripts")
os.environ.setdefault("GIT_REPO", "/home/ubuntu/code/trade-data")
import upload_r2 as u
print(u._prune_large_json(dry_run=True))
print(u._prune_large_json_legacy(dry_run=True))
```
