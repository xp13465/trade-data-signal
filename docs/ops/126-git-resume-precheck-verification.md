# #126 收口前独立复核:R2 large-json 固定前缀完整性验证

> 独立复核人:tester agent(role-tester),2026-09-30。全只读:未碰 git 分支、未在云上执行任何写操作。
> 结论:**PASS** —— 「R2 已传满 9 目录、可安全 `git rm --cached` 收口」可复现,未见反证。

## 验证对象与口径

- R2 私有桶:`signal-backup`(BACKUP_BUCKET 默认值,未覆盖)。
- 固定前缀 key:`large-json/<rel>.gz`(rel = 相对 `data/` 的路径,去 `data/` 前缀)。剔除 legacy 日期形态 `large-json/YYYY-MM-DD/`。
- staticdata 仓:云上 `/home/ubuntu/code/trade-data-signal-staticdata`(生产备份仓,非本地;本地仅 31235 落后 4 文件)。
- 9 目录:`data/{signal_kelly_trades_parts, signal_kelly_trades_sdc_parts, nav_bucket, etf, accum_nav, lab, index, trade_sim, fund_nav}`(与 `large_json_excludes.py` `DIR_EXCLUDES` 一致)。

## 1. key 总数

独立脚本 `/tmp/verify_126.py`(独立实现 ListObjectsV2 分页枚举 Key+Size;SigV4 复用 `upload_r2.s3_request` 的 canonical query 排序,避开已知 403 坑),list-type=2 分页取全量:

```
枚举 total=59360
固定前缀(非日期形态)=31663  日期形态 legacy=27697
```

**报告值 31663 属实。** 目录分布:fund_nav 26458 / accum_nav 1713 / etf 1713 / trade_sim 504 / sdc_parts 391 / parts 383 / nav_bucket 256 / index 173 / lab 65 / root 7。

## 2. MISSING=0 复现(独立映射)

云上 `git ls-files` 9 目录 = **31239**(任务口径一致)。独立映射 `data/xxx → xxx` 与 R2 key 集合(set 差)比对:

```
git 9目录 tracked(去data/前缀)=31239  R2固定key=31663
MISSING(在git不在R2)=0
反向多余(在R2不在git)=424
```

- **MISSING=0 复现成立。**
- **反向多余 424 全部有来源,无孤儿**:
  - `trade_sim` 415 个:磁盘 504 文件 vs git tracked 仅 89 → 磁盘真实文件但 git 未跟踪(备份按磁盘全量传,非仅 tracked)。
  - root 级 7 个:`accum_nav_map.json / offshore_fund_{fee_detail,performance,purchase_status,risk_indicator}.json / signal_kelly_trades.json / signal_kelly_trades_sdc.json` = 9 目录外 >20MB 大 JSON 单文件(阈值纳入上传清单)。
  - `accum_nav/158039.json`、`etf/158039-all.json` 各 1 个:磁盘新文件。
- 交叉自洽:31663 = 31656(磁盘 9 目录全量)+ 7(root 级),**一个不多一个不少**。

## 3. 空对象检查(size=0)

分页枚举直接带 `<Size>` 字段统计:

```
size=0 空对象数=0
```

**无 size=0 空对象**,排除「上传成功但内容没上去」的隐蔽失败形态。

## 4. 抽样内容对账(最强证据)

随机抽 5 个 key(覆盖 fund_nav / etf / accum_nav / lab / index),GET 回 → gunzip → md5,与云上 staticdata 磁盘同路径文件 `md5sum` **逐位比对**:

| key | R2 字节 | R2 md5 | 磁盘 md5 | 结果 |
|---|---|---|---|---|
| fund_nav/023684.json | 6456 | c52cd5fd…c45c56 | c52cd5fd…c45c56 | 一致 |
| etf/159123-all.json | 18258 | af7458b8…0afb82b | af7458b8…0afb82b | 一致 |
| accum_nav/516660.json | 24297 | c9b8ee20…c2289c41 | c9b8ee20…c2289c41 | 一致 |
| lab/lab_sim_sz50_fusion_full.json | 6177850 | 7dc434df…a7174 | 7dc434df…a7174 | 一致 |
| index/csi_div-all.json | 569804 | fb5b151c…6198ac | fb5b151c…6198ac | 一致 |

**5/5 逐位一致,无不一致。** 另 HEAD 抽查 `fund_nav/023684.json.gz` Last-Modified=2026-09-30 12:35 GMT(当天),非陈旧快照。

## 5. 收口后阈值复核

云上 `git ls-files` 剔除 9 目录后 324 个文件逐个 `stat -c %s` 求和:

```
9目录外 tracked 文件总字节 = 187404369
换算 MB: 178.72
```

**178.72MB < 500MB ✓**。

## 6. #130 生效确认

- 云上 `/home/ubuntu/code/trade-data-signal/scripts/upload_r2.py` 含固定前缀逻辑,关键行:
  - `L18`: `upload-large-json  # 大 JSON 私有桶备份(signal-backup/large-json/, #126 固定前缀)`
  - `L1815`: `def _list_keys`(分页实现)
  - `L2214`: `if os.environ.get("R2_LARGE_JSON_DATE_PREFIX", "") == "1"`(逃生门分支,默认走固定前缀)
  - `L2139/2199/2306`: #126 改造注释
- 本地 main 链确认:

```
git merge-base --is-ancestor e01f2a045 origin/main; echo EXIT=$?   → EXIT=0
e01f2a045 fix(r2-large-json): 灾备上传通道根治——固定前缀增量复用 + 并行化 + SigV4/分页修复(#130)
```

**#130 commit 已在 main 链,云上脚本同版生效。**

## 附加发现(非 FAIL,但记录口径)

1. **云上 staticdata git 索引(HEAD@2026-09-28)落后磁盘**:`git status` 4070 变更,抽查 `etf/159123-all.json`、`lab/lab_sim_sz50_fusion_full.json` 的 git blob md5 ≠ 磁盘 md5(磁盘是新版)。**R2 备份的是磁盘生产数据(5/5 与磁盘一致),不是 git 索引版本**。对收口无碍且更安全:收口后完整副本 = R2 + 磁盘双份,均为最新;git 索引里的 09-28 旧数据本就要被 `rm --cached` 移除。
2. legacy 日期形态 key 27697 个仍在(逃生门/清理宽限期内),与固定前缀并存,不构成收口阻碍(固定前缀才是唯一完整副本)。

## 复现段

```bash
# 1. 独立枚举(本机)
cat > /tmp/verify_126.py << 'PYEOF'
import re, sys, urllib.parse as up
sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
from upload_r2 import s3_request
out=[]; token=""
while True:
    q=f"list-type=2&prefix={up.quote('large-json/', safe='')}"+(f"&continuation-token={up.quote(token, safe='')}" if token else "")
    st,data=s3_request("GET","",query=q,bucket="signal-backup")
    text=data.decode("utf-8","replace")
    out += list(zip(re.findall(r"<Key>([^<]+)</Key>",text), re.findall(r"<Size>(\d+)</Size>",text)))
    if "<IsTruncated>true</IsTruncated>" not in text: break
    token=re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>",text).group(1)
PYEOF
python3 /tmp/verify_126.py
# → 固定前缀 31663,size=0 空对象 0

# 2. MISSING 比对(云上只读)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'cd /home/ubuntu/code/trade-data-signal-staticdata && git ls-files data/signal_kelly_trades_parts data/signal_kelly_trades_sdc_parts data/nav_bucket data/etf data/accum_nav data/lab data/index data/trade_sim data/fund_nav' \
  > /tmp/git_9dirs.txt
# 脚本内: git 路径去 data/ 前缀后 与 R2 key set 差 → MISSING=0

# 3. 抽样对账(5 key,覆盖 fund_nav/etf/accum_nav/lab/index)
# 本机 GET+gunzip+md5,云上 md5sum 同路径 → 5/5 逐位一致
```

## 责任边界

- 本验证全只读:未 checkout/commit/push,未在云上写任何对象。
- 收口(`git rm --cached`)是实施动作,由主控/implementer 在用户拍板后执行,本验证不替代 §23.7 冻结契约确认。
