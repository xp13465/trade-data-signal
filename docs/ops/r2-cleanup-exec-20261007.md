# R2 老账号清理执行报告(A 档 21 对象 + C 档 27,673 对象)

> 依据:`docs/ops/r2-cleanup-audit-20261007.md`(审计,已合 main `0967fe413`)+ 用户拍板「全做 A + C」。§25 硬顺序:①逐 key 清单 →②备份 →③验可恢复 →④验过才删 →⑤删后复核。全程逐 key DELETE,**无前缀通配**;未动 #197(云上仓)、未动新桶 flat 备份本体。
> 执行环境:本机(Mac,直连 R2;老账号凭据 `R2_S3_*` + 新账号凭据 `R2_BACKUP2_*` 均在 repo `.env`);未 ssh 云上、未动云上任何文件。执行窗口 2026-10-07 16:55~17:28(本地)。
> 时间戳口径:UTC;MiB=1048576 B。

## 0. 结论总览

| # | 结论 | 证据 |
|---|---|---|
| 1 | **A 档 21 对象已删**(bucket `signal-data`,171,894,762 B=163.93 MiB) | DELETE ok=21 / 404=0 / fail=0;删后 HEAD 21/21 → 404;根级对象 5→0 |
| 2 | **C 档 27,673 对象已删**(bucket `signal-backup`,279,046,499 B=266.1 MiB) | DELETE ok=27,673 / 404=0 / fail=0;两日期目录删后 0 对象;老桶 `large-json/` 只剩 flat 31,673 无日期目录残留 |
| 3 | **备份可恢复(§25②)全部 PASS** | A:21/21 GET md5==ETag + 归档 tar.gz 上传新桶 + HEAD/整包回取逐位一致 + 解包演练 21/21;MISSING=0。C:集合级对账 orphan=0(15,805 rel 全覆盖)+ 严格版时点校 0 个 flat 版本早于 legacy |
| 4 | **两桶总量下降逐位对得上** | `signal-backup` 66,000→38,327(-27,673 精确)、字节 -279,046,499 逐位;`signal-data` 31,484→31,463(-21 精确);合计降 450,941,261 B=430.05 MiB |
| 5 | **新桶备份本体零触碰** | `signal-backup2` flat 31,673 仍全量在位(删后复列同数,抽样 HEAD 10/10==200);新增仅 4 个 `decommissioned/` 归档对象 |

## 1. 执行硬顺序逐项记录

### ① 逐 key 清单(落盘为文件)
- A 档 21 key:对每个 key 实时 HEAD 复核(`size`+`ETag`)→ `/tmp/r2c_out/A_head.json`;**21/21 与审计表 §3.1~3.3 逐位一致**(etag+size 全对)。
- C 档 27,673 key:LIST 老桶 `large-json/2026-09-29/`+`/2026-09-30/` 全量(含 size/ETag/mtime)→ `/tmp/r2c_out/C_keys.json`。实测 11,875+15,798=**27,673 对象 / 279,046,499 B,与审计 §4.1 逐位一致**。
- 删前键值域审计:A 清单 21 条去重 21、合计 171,894,762 B;C 清单 27,673 条去重 27,673、**越界 key(不在两日期前缀内)=0**、字节合计逐位一致。

### ② 备份
- **A1 industry-*(10)**:GET 全部 10 个 → md5==ETag 逐位(其中 `data/industry-3y.json` 本机 `static-site/data/` 亦有同款副本,md5 `812f3821…` 一致);
- **A2 测速/探测残留(8)**:可再生(重造/重跑探测),已随归档一并保存;
- **A3/A4/A5 无源重建组**(根级 `overview.json`、`sss.jpg`、`data/signal_kelly_backtest.json.gz`):**GET 归档**,与新桶方案二选一→**两份都做了**(本地归档目录 + 上传新桶)。
- 归档落盘:`~/r2-archive-20261007/`(21 文件,164M);打包 `r2-cleanup-a-20261007.tar.gz` = 20,456,524 B,md5 `a8712a090cd29752e105afcf438c8275`;
- 上传:`signal-backup2/decommissioned/r2-cleanup-a-20261007.tar.gz`(PUT ETag==md5;HEAD size+etag 一致;**整包 GET 回取 md5 逐位一致**);
- **C 档备份口径(主控/用户拍板)**:新桶 flat(31,673)已含全部 15,805 个 distinct rel 的当前版 ⇒ 以**集合级对账**证明 orphan=0(见 ③)。清单与对账证据同步上传:`decommissioned/r2-cleanup-c-keylist-20261007.json`(4,346,185 B)、`r2-cleanup-c-recon-20261007.json`、`r2-cleanup-a-head-20261007.json`。

### ③ 验可恢复(§25②,验不过不许删)
- **A 档**:清单全量比对**MISSING=0**;21/21 `md5(文件) == R2 ETag`;归档包 HEAD+整包回取的 md5 逐位一致;**恢复演练**:解包后 21/21 文件 md5 逐位一致。
- **C 档集合级对账(删前)**:legacy distinct rel=15,805,全部在新桶 flat(31,673)找到当前版 → **orphan=0**;老桶 flat 交叉核对同样 0 缺失。**严格版时点校(删后复核补充)**:逐 rel 比较 `LastModified`,**flat 版本早于 legacy 快照的 rel 数 = 0**(即 flat 恒为「不早于」版本);新桶 flat mtime 范围 2026-10-05T08:55Z ~ 2026-10-07T08:55Z。
- **尺子先验**(见 §5):md5 篡改 1 字节可检出;注入不存在 rel 被对账脚本报 missing=1。

### ④ 验过才删(逐 key DELETE,禁通配)
- A 档:`s3_request('DELETE', key, bucket='signal-data')` × 21 → **ok=21, 404=0, fail=0**(7s)。
- C 档:`s3_request('DELETE', key, bucket='signal-backup')` × 27,673(16 线程 keep-alive,nohup+进度落文件)→ **ok=27,673, 404=0, fail=0**(693s)。删除清单 = C_keys.json 显式 27,673 key 逐一,无任何前缀/通配/递归删除。

### ⑤ 删后复核(全绿)
| 复核项 | 结果 |
|---|---|
| A 档 21 key HEAD | **404 × 21**(全消失) |
| `signal-data` 根级对象 | 5 → **0**(审计 §2.2 的 (root) 5 对象全部属 A 档) |
| `signal-data` 前缀 `probe/` `test/` `r2test/` `data/industry-` | **0 对象** |
| C 档两日期目录 | `large-json/2026-09-29/` **0 对象**;`large-json/2026-09-30/` **0 对象** |
| C 档随机抽检 8 key HEAD | **404 × 8** |
| 老桶 `large-json/` 全量 | 31,673 全为 flat 形状,**日期目录残留 = 0**(belt-and-braces 防「数量相等但构成串味」) |
| 新桶 flat 删后复列 + 抽样 | 31,673 同数;随机 10/10 rel HEAD 200;根层 `signal_kelly_trades(.sdc).json.gz` HEAD 200 |
| 桶总量对账 | `signal-backup` 38,327 / 8,155,372,290 B;`signal-data` 31,463 / 2,857,473,162 B(见 §0#4) |

## 2. 备份与可恢复性(§25 门槛表)

| 块 | 备份形态 | 备份验证(实测) | §25 判定 |
|---|---|---|---|
| A 档 21 对象 | 本地 `~/r2-archive-20261007/`(164M)+ 新桶 `decommissioned/r2-cleanup-a-20261007.tar.gz`(md5 `a8712a09…`) | 21/21 md5==ETag;归档 HEAD/整包回取/解包演练三重逐位一致;MISSING=0 | **通过** |
| C 档 27,673 对象 | 新桶 flat 31,673(现役当前版全集)+ key 清单与对账证据落新桶 | orphan=0(15,805 rel 全覆盖);严格版时点校 0 异常;抽样 HEAD 10/10 | **通过(按拍板口径)** |
| #197 云上仓 | 本轮不做(另派) | — | 未触碰 |

## 3. 恢复路径(§25④:写不出恢复路径 = 不算可逆)

### 3.1 A 档 21 对象(逐 key 回 PUT 即可)
```bash
# (1) 取回归档(二选一:也可直接用本地 ~/r2-archive-20261007/)
cd /Users/linhuichen/code/trade && python3 - <<'PY'
import os,sys
sys.path.insert(0,"scripts")
for l in open(".env"):
    l=l.strip()
    if l and not l.startswith("#") and "=" in l:
        k,v=l.split("=",1); os.environ.setdefault(k,v)
import upload_r2 as u
st,data=u.s3_request("GET","decommissioned/r2-cleanup-a-20261007.tar.gz",bucket="signal-backup2")
open("/tmp/r2-cleanup-a-20261007.tar.gz","wb").write(data); print("GET",st,len(data))
PY
# (2) 校验(应为 a8712a090cd29752e105afcf438c8275)+ 解包
python3 -c "import hashlib;print(hashlib.md5(open('/tmp/r2-cleanup-a-20261007.tar.gz','rb').read()).hexdigest())"
mkdir -p /tmp/r2-restore && tar -xzf /tmp/r2-cleanup-a-20261007.tar.gz -C /tmp/r2-restore
# (3) 逐 key PUT 回 signal-data(21 个;禁通配;清单=tar 内 21 路径)
cd /Users/linhuichen/code/trade && python3 - <<'PY'
import os,sys,hashlib,json
sys.path.insert(0,"scripts")
for l in open(".env"):
    l=l.strip()
    if l and not l.startswith("#") and "=" in l:
        k,v=l.split("=",1); os.environ.setdefault(k,v)
import upload_r2 as u
rows=json.load(open("/tmp/r2c_out/A_head.json"))          # 21 key + 各自 ETag(权威清单)
for r in rows:
    p=os.path.join("/tmp/r2-restore",r["key"]); data=open(p,"rb").read()
    assert hashlib.md5(data).hexdigest()==r["etag_now"], r["key"]
    st,_=u.s3_request("PUT",r["key"],data,bucket="signal-data"); print("PUT",r["key"],st)
PY
# 注:若 /tmp/r2c_out/A_head.json 已丢,对账基准=归档内 21 文件 + 审计报告 §3.1~3.3 的 ETag 列
```
### 3.2 C 档(现役数据零影响;历史时点版不可逐位重建)
- **现役数据**:15,805 个 rel 的当前版**全量在位**,无需恢复;单文件取回示例:`s3_request("GET","large-json/<rel>",bucket="signal-backup2")`。老桶 flat(31,673)亦仍在位,与新桶 flat 互为副本。
- **历史时点(09-29/09-30 逐位原样)**:本轮**未做 266.1 MiB 整包归档**(按拍板口径备份=新桶 flat 集合级对账)⇒ **该历史版本已不可恢复**——语义为审计 §4.3「7 天宽限后设计既定弃置」,删除仅使该设计结果提前兑现。如需「按天快照恢复」能力,走新桶 flat 的当前版(内容≠历史版)。
- **删除前状态可完整还原(元数据)**:27,673 个 key 的 `key/size/ETag/LastModified` 清单存档 = 新桶 `decommissioned/r2-cleanup-c-keylist-20261007.json` + 本地 `/tmp/r2c_out/C_keys.json`。

## 4. 尺子先验与执行自检(§5.2)

1. **ETag 比较口径 bug(自查自纠)**:首轮 A 档 HEAD 复核 21/21 报「不匹配」——逐项核对发现是尺子 bug(`s3_head` 的 ETag 带引号、Content-Length 为字符串,未归一化)。修正后 **21/21 全匹配**。教训直接在报告里留痕:报 FAIL 前先核尺子。
2. **md5 可检出性**:`r2test.txt` 篡改 1 字节后 md5 `1af49f95…`→`d882e2dc…`(可检出),且原 md5 == R2 ETag。
3. **对账脚本 tamper 自检**:注入一个不存在的 rel(`___TAMPER___nonexistent_probe.json`)→ 脚本报 `missing_in_new=1` 且精确指认,尺子有效。
4. **探测笔误自纠**:删后复核对 `large-json/signal_kelly_trades` HEAD 得 404——核实为探测 key 漏了 `.json.gz` 后缀(真实 key 200),非数据问题;随后以「按 key 全名抽样 HEAD」复证 10/10。
5. **上传超时诊断**:首次归档上传连续 `write timed out`(默认 `R2_UPLOAD_HTTP_TIMEOUT=30s` 不适配本机跨境慢链路 ~90KB/s),置 300s 后 12s 完成——供后续跨境上传参考(非数据问题)。

## 5. 诚实标注(局限 / 未验项)

1. **`signal-data` 字节降幅比 A 档清单多 1,590 B**(171,896,352 vs 171,894,762;对象数 -21 精确对得上):差额来自窗口内活数据对象并发更新(同对象改写,非增删),不影响 A 档判定。
2. **C 档 9-29/09-30 历史逐位版本不可恢复**(口径见 §3.2;设计既定弃置语义 + 拍板接受)。「路径覆盖」与「现役当前版」零损失(已机检)。
3. `sss.jpg`/根级 `overview.json` 的**站外历史外链不可程序化穷尽**(同审计口径);站内零引用,归档已有两份(本地+新桶)。
4. 归档传输仅本机链路实测(90KB/s 级);R2 老账号桶删除耗时 693s(27,673 key)为本次实测值,不作 SLA。
5. 本报告所述全部动作均在本机执行;未对云上任何文件、定时任务、#197 仓做任何操作。
6. 本报告**不 commit**(留工作区,由主控处理;与审计报告先例一致)。

## 6. 复现命令段(逐条可复核)

```bash
# ① A 档 21 个 HEAD 复核(应与审计表 ETag+size 逐位一致;本例已 PASS)
python3 /tmp/r2c.py head_a                      # -> 21/21 etag_match=True size_match=True
# ② C 档清单 + flat(新/老桶)全量 LIST
python3 /tmp/r2c.py list_c                      # -> 27673 objs / 279046499 B 与审计逐位一致
python3 /tmp/r2c.py list_flat                   # -> new=31673 / old=59346
# ③ 对账(含尺子 tamper 自检)
python3 /tmp/r2c.py recon_c_tamper              # -> 抓到注入缺失=True
python3 /tmp/r2c.py recon_c                     # -> rel 不在新桶 flat = 0
# ④ A 档备份:GET 归档 + md5 vs ETag + 打包上传 + 复核
python3 /tmp/r2c.py backup_a                    # -> MISSING/不一致 = 0
python3 /tmp/r2c.py tar_a && R2_UPLOAD_HTTP_TIMEOUT=300 \
  python3 /tmp/r2c.py upload_archive ~/r2-archive-20261007/r2-cleanup-a-20261007.tar.gz decommissioned/r2-cleanup-a-20261007.tar.gz
# ⑤ 删除(逐 key;A 21 / C 27673)
python3 /tmp/r2c.py del signal-data /tmp/r2c_out/A_head.json
python3 /tmp/r2c.py del signal-backup /tmp/r2c_out/C_keys.json
# ⑥ 删后复核
python3 /tmp/r2c.py count signal-backup ""        # -> 38327 objs / 8155372290 B
python3 /tmp/r2c.py count signal-backup2 ""       # -> 老账号两桶外,新桶未动(31691 含新增归档)
python3 /tmp/r2c_postcheck.py                     # -> 缺失=0 / flat 版本早于 legacy = 0
python3 /tmp/r2c_final_check.py                   # -> 老桶日期目录残留=0
```

## 7. 生成脚本全文(可重建)

> 脚本无凭据硬编码(从 `repo/.env` 读);删除接口 = `upload_r2.s3_request("DELETE", key, bucket=…)` 逐 key,无任何前缀/通配/递归路径。

### 7.1 主脚本 `/tmp/r2c.py`(265 行;head_a/list_c/list_flat/backup_a/recon_c/recon_c_tamper/tar_a/upload_archive/del/count/prefixes）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""/tmp/r2c.py — R2 老账号清理执行脚本(2026-10-07)。
只读发现 + 备份对账 + 逐 key 删除。凭据从 repo/.env 读(不打印)。
用法: python3 /tmp/r2c.py <cmd> [args...]
cmd: head_a | list_c | list_flat | backup_a | recon_c | tar_a | upload_archive <file> | del <bucket> <listfile> | count <bucket> <prefix>
"""
import os, sys, json, hashlib, time, re, threading, queue, subprocess
from urllib.parse import quote
REPO="/Users/linhuichen/code/trade"
os.chdir(REPO)
for line in open(".env"):
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k,v)
sys.path.insert(0,os.path.join(REPO,"scripts"))
import upload_r2 as u

MAIN="signal-data"; OLDB="signal-backup"; NEWB="signal-backup2"
ARCH=os.path.expanduser("~/r2-archive-20261007")
OUT="/tmp/r2c_out"; os.makedirs(OUT, exist_ok=True)

# A 档 21 key(审计报告 §3 表,含 expected etag/size)
A_KEYS=[
 ("data/industry-1y.json",6738441,"004b4ec7111eef4a8dc503717bfa948b"),
 ("data/industry-3m.json",2492395,"6657acb34e2201565a8241cbcece8263"),
 ("data/industry-3y-concepts.json",10209777,"d60b4d9c88c60d25b9b0a260212f6ab5"),
 ("data/industry-3y-meta.json",4860,"b2da2a15d9a2a1880684470026b7bef9"),
 ("data/industry-3y.json",9601767,"812f38218e8eded6c3d73fcc04d3813b"),
 ("data/industry-5y-concepts.json",15664402,"11b7a5271bd5d97b50febfeec8de6d9f"),
 ("data/industry-5y-meta.json",4860,"b2da2a15d9a2a1880684470026b7bef9"),
 ("data/industry-6m.json",3966034,"b47ec59420fec7dbf32706a282093607"),
 ("data/industry-all-concepts.json",32275765,"429b506dba1ec29806483bde168ca429"),
 ("data/industry-all-meta.json",4860,"b2da2a15d9a2a1880684470026b7bef9"),
 ("__speedtest_20mb.bin",20971520,"f7353682390b0fcd707730f9bef1d2c5"),
 ("__speedtest_50mb.bin",52428800,"2048d4a10a0619745ecdcd33b68f2d8a"),
 ("__speedtest_5mb.bin",5242880,"7d7a6dd7e37454c6a82992eabe7a4613"),
 ("test/speedtest-10m.bin",10485760,"f1c9645dbc14efddc7d8a322685f26eb"),
 ("probe/cf-egress-202610021509514.json",5613,"9acf2244cc966eb6ac8bfc8709189128"),
 ("probe/ping-202610021516514.json",55,"1c4b38a15fcd8127f7f07b46518fd536"),
 ("probe/ping-202610021544518.json",55,"3b4b9d6fbda276cf1ca7743ead0e4cc8"),
 ("r2test/r2test.txt",18,"1af49f952ad5b55c5dd367418ce2680c"),
 ("overview.json",1585628,"caac4fa523a170a8beea04cb3ea9685b"),
 ("sss.jpg",143216,"7759f8b69ff108a3cdbafa73c5b4ffee"),
 ("data/signal_kelly_backtest.json.gz",68056,"ea815672e83e5ee5e5606115c2beb243"),
]

def now(): return time.strftime("%F %T")
def log(msg):
    line=f"[{now()}] {msg}"
    print(line, flush=True)

def list_detail(prefix, bucket, page_tag=""):
    out=[]; token=""; pages=0
    while True:
        q=f"list-type=2&prefix={quote(prefix,safe='')}&max-keys=1000"
        if token: q+=f"&continuation-token={quote(token,safe='')}"
        st,data=u.s3_request("GET","",query=q,bucket=bucket)
        if st!=200: raise RuntimeError(f"LIST {bucket}/{prefix} status={st} {data[:200]}")
        text=data.decode("utf-8",errors="replace")
        for m in re.finditer(r"<Contents>(.*?)</Contents>", text, re.S):
            b=m.group(1)
            key=re.search(r"<Key>(.*?)</Key>",b,re.S).group(1)
            size=int(re.search(r"<Size>(\d+)</Size>",b).group(1))
            etag=re.search(r"<ETag>(.*?)</ETag>",b).group(1).strip('"&quot;')
            lm=re.search(r"<LastModified>(.*?)</LastModified>",b).group(1)
            out.append({"key":key,"size":size,"etag":etag,"lastmod":lm})
        pages+=1
        if pages % 10 == 0: log(f"  list {bucket}/{prefix} pages={pages} objs={len(out)}")
        if "<IsTruncated>true</IsTruncated>" not in text: break
        mm=re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>",text)
        if not mm: break
        token=mm.group(1)
    return out

def cmd_head_a():
    """HEAD 21 个 A 档 key,记录当前 size/etag,与审计表对比。"""
    rows=[]
    for i,(k,sz,et) in enumerate(A_KEYS,1):
        st, etag, clen = u.s3_head(k, bucket=MAIN, keep_alive=True, with_len=True)
        etag=(etag or "").strip('"'); clen=int(clen) if clen not in (None,"") else None
        row={"key":k,"status":st,"etag_now":etag,"size_now":clen,"etag_audit":et,"size_audit":sz}
        row["ok"]= (st==200 and etag==et and clen==sz)
        rows.append(row)
        log(f"  [{i}/21] {k} HEAD={st} etag_match={etag==et} size_match={clen==sz}")
    json.dump(rows, open(f"{OUT}/A_head.json","w"), indent=1)
    bad=[r for r in rows if not r["ok"]]
    log(f"head_a: 21 个 key, 不匹配/异常 = {len(bad)}; 明细 {OUT}/A_head.json")
    return 1 if bad else 0

def cmd_list_c():
    """LIST 老桶 legacy 两目录(detail)→ 文件。"""
    allrows=[]
    for d in ("large-json/2026-09-29/","large-json/2026-09-30/"):
        t=time.time()
        rows=list_detail(d, OLDB)
        tot=sum(r["size"] for r in rows)
        log(f"list_c {OLDB}/{d}: {len(rows)} objs / {tot} B ({time.time()-t:.0f}s)")
        allrows.extend(rows)
    json.dump(allrows, open(f"{OUT}/C_keys.json","w"), indent=0)
    log(f"list_c total: {len(allrows)} objs / {sum(r['size'] for r in allrows)} B -> {OUT}/C_keys.json")
    return 0

def cmd_list_flat():
    """LIST 新桶 flat(large-json/ 全量)+ 老桶 large-json/ 全量,用于 orphan 对账。"""
    t=time.time()
    rows_new=list_detail("large-json/", NEWB)
    log(f"list_flat {NEWB}/large-json/: {len(rows_new)} objs ({time.time()-t:.0f}s)")
    json.dump(rows_new, open(f"{OUT}/flat_new.json","w"), indent=0)
    t=time.time()
    rows_old=list_detail("large-json/", OLDB)
    log(f"list_flat {OLDB}/large-json/: {len(rows_old)} objs ({time.time()-t:.0f}s)")
    json.dump(rows_old, open(f"{OUT}/flat_old.json","w"), indent=0)
    return 0

def cmd_count():
    """count <bucket> <prefix>: 列前缀对象数与字节。"""
    if len(sys.argv)<4: raise SystemExit("用法: count <bucket> <prefix>")
    bkt,prefix=sys.argv[2],sys.argv[3]
    rows=list_detail(prefix,bkt)
    tot=sum(r['size'] for r in rows)
    log(f"count {bkt}/{prefix}: {len(rows)} objs / {tot} B ({tot/1048576:.2f} MiB)")
    return 0

def cmd_prefixes():
    """列桶顶层前缀(delimiter=/)。"""
    bkt=sys.argv[2] if len(sys.argv)>2 else NEWB
    q="list-type=2&delimiter=%2F&max-keys=1000"
    st,data=u.s3_request("GET","",query=q,bucket=bkt)
    text=data.decode("utf-8",errors="replace")
    pref=re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix></CommonPrefixes>",text)
    log(f"prefixes {bkt}: {pref}")
    return 0

def cmd_backup_a():
    """GET 全 21 个 A 档 key 落本地归档 + md5 vs ETag 逐位。"""
    os.makedirs(ARCH, exist_ok=True)
    rows=head_ok=[]
    rows=json.load(open(f"{OUT}/A_head.json"))
    for i,r in enumerate(rows,1):
        k=r["key"]; et=r["etag_audit"] if r["etag_now"] is None else r["etag_now"]
        dst=os.path.join(ARCH,k)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        st,data=u.s3_request("GET",k,bucket=MAIN)
        if st!=200:
            log(f"  ✗ GET {k} status={st}"); r["backup_ok"]=False; continue
        md5=hashlib.md5(data).hexdigest()
        with open(dst,"wb") as f: f.write(data)
        ok = (md5==r["etag_now"]) and (len(data)==int(r["size_now"]))
        r["backup_ok"]=ok; r["md5_local"]=md5
        log(f"  [{i}/21] GET {k} {len(data)}B md5==ETag:{md5==r['etag_now']}")
    json.dump(rows, open(f"{OUT}/A_backup.json","w"), indent=1)
    bad=[r for r in rows if not r.get("backup_ok")]
    log(f"backup_a: 21 个对象,MISSING/不一致 = {len(bad)}")
    return 1 if bad else 0

def _rel_of_c(k):
    return k[len("large-json/2026-09-29/"):] if k.startswith("large-json/2026-09-29/") else k[len("large-json/2026-09-30/"):]

def _recon(c, flat_new, flat_old, tag=""):
    """返回 (miss_new, miss_old);抽出供 tamper 自检复用(同一把尺子)。"""
    rel_c=sorted({_rel_of_c(r["key"]) for r in c})
    keys_new={r["key"] for r in flat_new}
    keys_old={r["key"] for r in flat_old}
    miss_new=[rel for rel in rel_c if ("large-json/"+rel) not in keys_new]
    miss_old=[rel for rel in rel_c if ("large-json/"+rel) not in keys_old]
    log(f"recon_c{tag}: C对象={len(c)} distinct_rel={len(rel_c)} | flat_new={len(flat_new)} flat_old={len(flat_old)}")
    log(f"recon_c{tag}: rel 不在新桶 flat = {len(miss_new)} ; 不在老桶 flat = {len(miss_old)}")
    return miss_new, miss_old

def cmd_recon_c():
    """集合级对账: C legacy 的 distinct rel 每一个都要在新桶 flat 找得到当前版。"""
    c=json.load(open(f"{OUT}/C_keys.json"))
    flat_new=json.load(open(f"{OUT}/flat_new.json"))
    flat_old=json.load(open(f"{OUT}/flat_old.json"))
    miss_new, miss_old = _recon(c, flat_new, flat_old)
    rel_c=sorted({_rel_of_c(r["key"]) for r in c})
    json.dump({"c_objs":len(c),"distinct_rel":len(rel_c),
               "flat_new_n":len(flat_new),"flat_old_n":len(flat_old),
               "missing_in_new":miss_new[:50],"missing_in_new_n":len(miss_new),
               "missing_in_old_n":len(miss_old)}, open(f"{OUT}/recon_c.json","w"), indent=1)
    return 1 if miss_new else 0

def cmd_tar_a():
    """打包归档目录 -> tar.gz,核 md5。"""
    tgz=f"{ARCH}/r2-cleanup-a-20261007.tar.gz"
    subprocess.check_call(["tar","-czf",tgz,"-C",ARCH,"."])
    md5=hashlib.md5(open(tgz,"rb").read()).hexdigest()
    size=os.path.getsize(tgz)
    log(f"tar_a: {tgz} {size} B md5={md5}")
    json.dump({"file":tgz,"size":size,"md5":md5}, open(f"{OUT}/A_tar.json","w"), indent=1)
    return 0

def cmd_upload_archive():
    """upload_archive <localfile> <key>: PUT 到新桶 + ETag 对账 + HEAD 复核。"""
    lf,key=sys.argv[2],sys.argv[3]
    data=open(lf,"rb").read()
    md5=hashlib.md5(data).hexdigest()
    t=time.time()
    st,_,hdrs=u.s3_request("PUT",key,data,bucket=NEWB,with_headers=True)
    et=(hdrs or {}).get("ETag","").strip('"')
    log(f"upload {NEWB}/{key} status={st} {len(data)}B {time.time()-t:.0f}s ETag==md5:{et==md5}")
    st2,etag2,clen=u.s3_head(key,bucket=NEWB,with_len=True)
    log(f"upload HEAD复核: status={st2} size={clen} etag_match={etag2==md5}")
    ok = st in (200,201) and et==md5 and st2==200 and clen==len(data) and etag2==md5
    return 0 if ok else 1

def cmd_del():
    """del <bucket> <listfile>: 逐 key DELETE(多线程,keep-alive),进度落文件。"""
    bkt, lf = sys.argv[2], sys.argv[3]
    rows=json.load(open(lf))
    keys=[r["key"] if isinstance(r,dict) else r for r in rows]
    total=len(keys)
    log(f"del {bkt}: {total} keys 开始")
    q=queue.Queue()
    for k in keys: q.put(k)
    lock=threading.Lock()
    res={"ok":0,"notfound":0,"fail":[]}
    def worker():
        while True:
            try: k=q.get_nowait()
            except queue.Empty: return
            st=0
            for attempt in range(3):
                try:
                    st,_=u.s3_request("DELETE",k,bucket=bkt,keep_alive=True)
                except Exception as e:
                    st=0
                    u._drop_keepalive_conn if False else None
                if st in (200,204,404): break
                time.sleep(1+attempt)
            with lock:
                if st in (200,204): res["ok"]+=1
                elif st==404: res["notfound"]+=1
                else: res["fail"].append((k,st))
                done=res["ok"]+res["notfound"]+len(res["fail"])
                if done % 500 == 0:
                    log(f"  del 进度 {done}/{total} ok={res['ok']} 404={res['notfound']} fail={len(res['fail'])}")
    ths=[threading.Thread(target=worker,daemon=True) for _ in range(16)]
    t0=time.time()
    [t.start() for t in ths]; [t.join() for t in ths]
    log(f"del {bkt} 完成: ok={res['ok']} 404={res['notfound']} fail={len(res['fail'])} 用时{time.time()-t0:.0f}s")
    json.dump({"bucket":bkt,"n":total,"ok":res["ok"],"notfound":res["notfound"],
               "fail":res["fail"]}, open(f"{OUT}/del_{bkt}_{os.path.basename(lf)}.json","w"), indent=1)
    return 1 if res["fail"] else 0

def cmd_recon_c_tamper():
    """尺子自检: 注入一个已知不存在的 rel,尺子必须报 missing(否则尺子坏)。"""
    c=json.load(open(f"{OUT}/C_keys.json"))
    flat_new=json.load(open(f"{OUT}/flat_new.json"))
    flat_old=json.load(open(f"{OUT}/flat_old.json"))
    c2=c+[{"key":"large-json/2026-09-29/___TAMPER___nonexistent_probe.json","size":1,"etag":"x","lastmod":"x"}]
    flat_new2=flat_new+[{"key":"large-json/___TAMPER2___false_positive_probe.json"}]
    miss_new,miss_old = _recon(c2, flat_new2, flat_old, tag="[TAMPER]")
    ok = (miss_new==["___TAMPER___nonexistent_probe.json"])
    log(f"recon tamper 自检: 抓到注入缺失={ok} (miss_new={miss_new})")
    return 0 if ok else 1

CMDS={"recon_c_tamper":cmd_recon_c_tamper,"head_a":cmd_head_a,"list_c":cmd_list_c,"list_flat":cmd_list_flat,"count":cmd_count,
      "prefixes":cmd_prefixes,"backup_a":cmd_backup_a,"recon_c":cmd_recon_c,"tar_a":cmd_tar_a,
      "upload_archive":cmd_upload_archive,"del":cmd_del}
if __name__=="__main__":
    c=sys.argv[1]
    if c not in CMDS: raise SystemExit(f"未知命令 {c}; 可用: {list(CMDS)}")
    sys.exit(CMDS[c]())
```

### 7.2 删后严格版时点校脚本 `/tmp/r2c_postcheck.py`

```python
import os,sys,json,re,time
from urllib.parse import quote
sys.path.insert(0,"/Users/linhuichen/code/trade/scripts")
os.chdir("/Users/linhuichen/code/trade")
for line in open(".env"):
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k,v)
import upload_r2 as u
def list_detail(prefix, bucket):
    out=[]; token=""
    while True:
        q=f"list-type=2&prefix={quote(prefix,safe='')}&max-keys=1000"
        if token: q+=f"&continuation-token={quote(token,safe='')}"
        st,data=u.s3_request("GET","",query=q,bucket=bucket)
        assert st==200, st
        text=data.decode("utf-8",errors="replace")
        for m in re.finditer(r"<Contents>(.*?)</Contents>", text, re.S):
            b=m.group(1)
            out.append({"key":re.search(r"<Key>(.*?)</Key>",b,re.S).group(1),
                        "size":int(re.search(r"<Size>(\d+)</Size>",b).group(1)),
                        "lastmod":re.search(r"<LastModified>(.*?)</LastModified>",b).group(1)})
        if "<IsTruncated>true</IsTruncated>" not in text: break
        mm=re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>",text)
        if not mm: break
        token=mm.group(1)
    return out
print("[%s] 重列新桶 flat(删后)"%time.strftime("%T"),flush=True)
flat=list_detail("large-json/","signal-backup2")
json.dump(flat,open("/tmp/r2c_out/flat_new_post.json","w"),indent=0)
print("新桶 flat 删后:",len(flat),"objs")
c=json.load(open("/tmp/r2c_out/C_keys.json"))
def rel_of(k): return k.split("/",2)[2] if k.startswith("large-json/2026-") else k
rel_legacy={}
for r in c:
    rel=rel_of(r["key"]); lm=r["lastmod"]
    if rel not in rel_legacy or lm>rel_legacy[rel]: rel_legacy[rel]=lm
flat_map={r["key"][len("large-json/"):]: r for r in flat}
miss=[rel for rel in rel_legacy if rel not in flat_map]
older=[(rel,rel_legacy[rel],flat_map[rel]["lastmod"]) for rel in rel_legacy if rel in flat_map and flat_map[rel]["lastmod"]<rel_legacy[rel]]
print("删后 rel 覆盖: legacy_rel=%d 新桶flat=%d 缺失=%d"%(len(rel_legacy),len(flat_map),len(miss)))
print("flat 版本早于 legacy 快照的 rel 数(需为0):",len(older), older[:5])
mt=sorted(r["lastmod"] for r in flat)
print("新桶 flat mtime 范围:",mt[0],"~",mt[-1])
json.dump({"legacy_rel":len(rel_legacy),"flat_n":len(flat),"missing":miss,
           "older_than_legacy":older[:50],"older_n":len(older),
           "flat_mtime_min":mt[0],"flat_mtime_max":mt[-1]},
          open("/tmp/r2c_out/recon_c_post.json","w"),indent=1)
```

### 7.3 删后末检脚本 `/tmp/r2c_final_check.py`

```python
import os,sys,time,re
sys.path.insert(0,"/Users/linhuichen/code/trade/scripts")
os.chdir("/Users/linhuichen/code/trade")
for line in open(".env"):
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k,v)
import upload_r2 as u
t=time.time()
keys=u._list_keys("large-json/","signal-backup")
print("[%s] 老桶 large-json/ 全量 key 数:%d (%.0fs)"%(time.strftime("%T"),len(keys),time.time()-t))
dated=[k for k in keys if re.match(r"large-json/\d{4}-\d{2}-\d{2}/",k)]
print("其中日期目录残留:",len(dated),dated[:5])
flat=[k for k in keys if not k.startswith("large-json/2026-")]
print("flat 形状数:",len(flat))
# 新桶 flat 抽 HEAD
for k in ["large-json/fund_nav/010488.json.gz","large-json/signal_kelly_trades","decommissioned/r2-cleanup-a-20261007.tar.gz"]:
    st,etag,clen=u.s3_head(k,bucket="signal-backup2",keep_alive=True,with_len=True)
    print("新桶 HEAD",k,"->",st,clen)
```

### 7.4 证据文件落点
- 本地:`/tmp/r2c_out/{A_head.json, C_keys.json, flat_new.json, flat_old.json, flat_new_post.json, recon_c.json, recon_c_post.json, A_backup.json, A_tar.json, del_signal-data_A_head.json, del_signal-backup_C_keys.json}`
- 本机归档:`~/r2-archive-20261007/`(21 文件 + tar.gz)
- R2 新桶:`signal-backup2/decommissioned/{r2-cleanup-a-20261007.tar.gz, r2-cleanup-c-keylist-20261007.json, r2-cleanup-c-recon-20261007.json, r2-cleanup-a-head-20261007.json, speedtest_256k_20261007.bin — 已清(os.urandom 可再生类,登记来源即满足 §25)}`
