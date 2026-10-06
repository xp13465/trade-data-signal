# #219 parts 元数据三字段撤出(治本 P1)独立审报告

- 审查角色: 独立 reviewer agent(fresh context,与实施 agent 不同会话;结论全部为独立复算,**未采信实施者报告**)
- 被审对象: `origin/feat/219-parts-metadata`,tip `ef9b000b2`,base/merge-base = `origin/main` `35a89fa2c`
- 实施报告: `docs/ops/219-parts-metadata-fix-20261006.md`(分支内) | 根因报告: `docs/ops/219-verify-r2-backfill-rootcause-20261006.md`(main 内)
- 审查日期: 2026-10-06 | 审查分级: B 级③(跨「数据产物 + 上传链 + 前端解析面」)= 完整 review
- **结论: merge 资格 PASS —— 无 FAIL 级返修点**(merge 由主控走 `scripts/main-merge.sh`,避开 §14 盘后时点)

---

## 一、必审 8 项(全 PASS)

### ① 穷举完整性(§23.3) PASS
- 全仓 grep 三个键(`generated_at`/`period_cutoffs`/`buy_amount`)所有真消费方:**只有 2 处解析器**,且都只取 `fields`/`quadrants`:
  - `static-site/app.js` L3775 `_simParseTrades`(首页模拟回测弹窗)
  - `static-site/lab.js` L8699 `_labKellyParseTrades`(策略实验室凯利区)
- min 产物字符串复核: `app.min.js` 命中 `period_cutoffs=0 / buy_amount=0`,`generated_at` 5 处均为 summary/daily_brief 链路(逐处核对,与 parts 无关);`lab.min.js` 命中仅 `t.buy_amount || (config.buy_amount) || 1e4` 与 `config.period_cutoffs` 回退串,语义与源码一致
- 本 diff 文件清单 6 个,**static-site 改动数 = 0** ⇒ 无前端源码变更、无需 bump / min 重建(§24 四查不触发);§21 公示不适用(未动算法/评分/权重)
- 遗留非消费方 2 类(不影响功能,见「三、低分注记」): `scripts/playwright-accept/p0_verify_fetch_sources.mjs`(诊断打印)、`docs/kelly/scripts/*.js` dead mock 脚本

### ② 键集一致性(§22) PASS
- 登记点清单核对(逐项已读):
  - `scripts/upload_r2.py` `_kelly_parts_md5` L1017-1036: pop 三键 = **保留为 no-op**(新 body 已无三键,pop 为防御性冗余,不冲突)
  - `scripts/sync_dev_from_r2.sh`: `TARGET_LABELS` 不含 kelly-*;`META_KEYS` 三键递归剔除 = no-op
  - `_R2_CHANNELS`(L3306-3310): kelly-parts → `.r2_kelly_parts_state.json`;kelly-parts-sdc → `.r2_kelly_sdc_state.json`,两通道 state 在位
  - 云上 `.r2_standalone_keys.json`(35 项)不含 kelly;`check_data_integrity.py` / `check_r2_consistency.py` 无 parts 键结构断言
- 无遗漏登记点

### ③ 合流成立 + 状态连续性 PASS(云上真实 34 文件实测)
- 判据一: B 档旧文件指纹 == state 记录,NDO 17/17 + SDC 17/17 = **34/34**
- 判据二: 模拟新格式文件(只含 `{fields,quadrants}` + sort_keys)整字节 md5 == B 档指纹,34/34
- 判据三: JSON 往返字节稳定(loads→dumps 同参)34/34
- 云上 state 复核: `.r2_kelly_parts_state.json` / `.r2_kelly_sdc_state.json` 均 count=17、changed=0(2026-10-06 21:32 增量轮)
- **上传风暴判定: 无** —— `_incremental_upload` 只比 md5 不比 size(文件变小不触发重传);新旧格式同 body 的 B 档指纹相等 ⇒ 不触发

### ④ 判别力未损 PASS(负控独立复现)
- 负控-A(真实数据改 1 行 profit): `变化片 1 个(两侧尺子都须变),未变片 16 个` —— 判别力真实存在
- 负控-B(verify 判据原型): `{一致: True, 404(etag=None): False, 被破坏(deadbeef): False, 同大小异内容: False}`
- **样本真实性核验(§18 L49)**: 实施者 pytest 6 用例为人造小样本;我在 `/tmp` 快照树独立复跑 6/6 PASS,并用**真实产物 + 真实生成器 + 真实指纹函数**端到端复算(见复现段),L49 风险排除

### ⑤ 解析面零变化 PASS
- node 加载**真实** app.js/lab.js 函数源码(直接 eval 源码切片 `_simParseTrades`/`_labKellyParseTrades`),对真实产物旧格式 vs 新格式解析:
  - `app 等价: true | lab 等价: true | 解析结果键: fIdx,fields,quadrants`(本轮复跑 NDO t2011、SDC t2020;此前同法跑过 NDO recent/t2026,结论同)
- lab.js `td.buy_amount` 恒 undefined(解析产物键只有 fIdx/fields/quadrants)⇒ 恒走 `data.config.buy_amount` 回退;实测 `signal_kelly_backtest.json config.buy_amount = 10000 == trades.buy_amount = 10000`,`config.period_cutoffs` 在位 ⇒ 回退值与撤出值相等,**行为零变**

### ⑥ 覆盖两族 PASS(NDO + SDC + unique)
- NDO 与 SDC 共用同一 `_dump`(`main()` 单点调用),`static-site/export.py` 里 SDC 仅换 `KELLY_BUY_NEXTDAY=0` + `--trades-output signal_kelly_trades_sdc.json`,无第二份代码路径
- 端到端复算 17/17 × 2 族全 PASS
- unique parts: `_dump_unique` 本就不含三键;云 `.env` 无 `KELLY_UNIQUE_EXPORT`(默认 0)、云 parts 目录 0 个 unique 产物、无 pipeline shell 传该变量 ⇒ 生产不启用

### ⑦ 过渡轮「一次性回填」收敛判定 PASS(精度订正: 34 → **≤34**,详见二.①)
- 回填 = 不匹配文件数;该轮上限 34(NDO 17 + SDC 17);其中「body 真变且被上传链先传」的文件不再回填 ⇒ 实际 **≤34**
- **收敛条件**: 合流后新文件字节 = B 档指纹的字节形态 ⇒ 生成端 body 不变 ⇒ 文件字节恒定 ⇒ verify `etag == local_md5` 恒真 ⇒ 0 补传,永久收敛;即便某轮上游数据修订致 body 变,上传链先传新字节、verify 比对一致 ⇒ 同轮内即收敛,不积压
- 跨轮 body 漂移实测: 本地镜像两轮 body 变化 10 个文件(recent + t2023..t2026 × 2 族),源于上游数据修订(两轮间 max_signal 日期推进),**非本改动引入**;24/34 跨轮稳定 ⇒ 序列化确定性成立
- 结论: 不会永不收敛、不会上传风暴

### ⑧ git 纪律 PASS
- 单 commit;parent == merge-base == `35a89fa2c`;`origin/feat == tip` 逐位一致;trailer `Co-Authored-By: Claude <noreply@anthropic.com>` 在位
- `git diff --stat 35a89fa2c ef9b000b2` 恰为 6 文件(382+/7-): `scripts/signal_kelly_backtest.py`、`scripts/upload_r2.py`、`scripts/tests/test_219_parts_metadata.py`、`docs/ops/219-parts-metadata-fix-20261006.md`、`docs/kelly/analysis/r2-incremental-upload-design-20260915.md`、`docs/pending-features-index.md`
- 无 `data/` 夹带(0)、无 static-site 改动(0)、无 force 痕迹

---

## 二、4 条诚实标注判定

### ① 过渡轮回填「34」→ 精度订正为「≤34」(成立,已订正)
- 精确表述: **回填数 ≤ 34**,上限 = 该轮全部 parts 文件数(NDO 17 + SDC 17);实际 = 34 − 该轮「body 真变且被上传链先传」的文件数
- **收敛条件(核心)**: 本改动落地(合流)后新文件字节 ≡ B 档指纹的字节形态 ⇒ 生成端 body 不变 ⇒ 文件字节恒定 ⇒ verify `etag == local_md5` 恒真 ⇒ **0 回填,永久收敛**;合流后若某轮上游数据修订致 body 变,上传链先传新字节 ⇒ 该轮内已一致 ⇒ 不积压
- 补充: 稳态 0 补传的前提 = body 不变 + 上传链与 verify 的相对顺序良性;现云上两者分属不同调度时点,即便某轮顺序颠倒,最坏单轮 ≤34 回填后即自动收敛(非风暴、非事故)

### ② recent2.json 旧残留是否本任务清: **不清,判定正确**
- 实际分布(本次复核): 云上 NDO parts = 17(无 recent2.json)+ SDC 17 = **34**;本地镜像 NDO = 18(多一个 `recent2.json` 历史残留)
- recent2.json 不在新生成集(recent 窗口自适应 120/90/60 天后的旧命名),不被新代码再生;其 R2/镜像残留属清理类工作,按 §25(删除前必备份)另立任务 **正确**;本任务 diff 内无其清理动作,不夹带

### ③ 全量 trades(≈173MB/轮)走 data-large 通道 + `generated_at` 被告警链消费: **判定正确**
- parts 与全量 trades 是两条独立通道(`kelly-parts` vs `data-large`),本改动只动 parts 侧
- 告警链消费的是全量 trades / summary 的顶层 `generated_at`(仍在,未撤出);parts 撤出后**无任何在线告警/监控消费方**(见①穷举)⇒ 判定正确

### ④ §23.7 冻结契约(parts 少 3 键,前端零消费): **判定成立(免用户确认;建议知会)**
- 前端解析只读 `fields`/`quadrants`(node 实测);3 键无任何在线消费方;用户可见行为零变(回退路径实测等值)
- 属「数据产物内部形态变更、行为零变」⇒ 不需用户拍板即可合;**建议** merge 时主控口头知会用户一句「parts 文件瘦身,页面行为不变」

---

## 三、低分注记(主控点名维度,保留列出)

1. **`scripts/playwright-accept/p0_verify_fetch_sources.mjs`**: 对 parts 记录 `gen: j.generated_at`,改后将打印 `undefined`(纯诊断脚本、无断言、零功能影响)。是否顺手改由主控定
2. **`docs/smoke-checklist.md` 无 sigkelly/parts 条目**: 本次改动无 P0 smoke 可跑(仅生成端 + 上传端);建议后续补「parts 分片可解析 / 弹窗可加载」清单项,非本次阻塞
3. **实施报告内「34」精度**: 建议与二.① 同口径补「≤34」,防后读的人误以为恒定 34

另 5 个低分项(<80)已滤未列: dead mock 脚本残留(docs/kelly/scripts/*.js,pre-existing)/`scripts/large_json_excludes.py` 注释内文件数与现状疑似不符(pre-existing)/kelly_mobile_smoke 计数脚本(域外)/实施报告措辞 nitpick/报告排版 nitpick(如需明细可向 reviewer 追问)。

---

## 四、复现段(照抄可重跑)

> 环境: 本机 mac(开发树);Python = `/Users/linhuichen/code/trade-data/.venv/bin/python3`;node 任意版。
> 全程**零业务脚本执行、零 R2 读写、零外发**(§18 L48/L50):下述 python 均为 import 模块后调用纯函数,产物只写 `/tmp`。

### 1) 重建被审代码快照(与 reviewer 当时快照同构)
```bash
rm -rf /tmp/219snap && mkdir -p /tmp/219snap
git -C /Users/linhuichen/code/trade archive origin/feat/219-parts-metadata \
  scripts app config static-site/app.js static-site/lab.js | tar -x -C /tmp/219snap
# 验证: diff -rq 重建树 /tmp/219snap 只见 __pycache__/.pytest_cache 差异(425 文件)
```

### 2) 实施者 6 用例独立复跑(快照树内;L49 样本真实性补充)
```bash
cd /tmp/219snap && /Users/linhuichen/code/trade-data/.venv/bin/python3 \
  -m pytest scripts/tests/test_219_parts_metadata.py -q
# => 6 passed(2026-10-06 复跑)
```

### 3) 真实数据端到端 + 负控(NDO + SDC)
```bash
/Users/linhuichen/code/trade-data/.venv/bin/python3 /tmp/219verify/verify_real.py
```
实测输出(2026-10-06):
```
signal_kelly_trades_parts: 生成 17 片 | 合流 17/17 | 顶层键==[fields,quadrants] 17/17 | 与旧产物同名的 state 连续 17 | 与旧产物本体逐字段相同 17 | 旧目录文件名 18
signal_kelly_trades_sdc_parts: 生成 17 片 | 合流 17/17 | 顶层键==[fields,quadrants] 17/17 | 与旧产物同名的 state 连续 17 | 与旧产物本体逐字段相同 17 | 旧目录文件名 17
负控-A 内容真变(改 1 行 profit): 变化片 1 个(两侧尺子都须变), 未变片 16 个; 行改的是 rating_high/A
负控-B verify 判据: {'一致': True, '404(etag=None)': False, '被破坏': False, '同大小异内容': False}
```
(NDO 本地镜像 18 = 17 + recent2.json 历史残留;「与旧产物逐字段相同」按两侧同名交集比较)

### 4) 前端解析等价(node 跑真实函数源码)
```bash
node /tmp/219verify/parse_eq.js /tmp/219snap/static-site/app.js /tmp/219snap/static-site/lab.js \
  /Users/linhuichen/code/trade-data/static-site/data/signal_kelly_trades_parts/t2011.json \
  /tmp/219verify/signal_kelly_trades_parts/t2011.json
node /tmp/219verify/parse_eq.js /tmp/219snap/static-site/app.js /tmp/219snap/static-site/lab.js \
  /Users/linhuichen/code/trade-data/static-site/data/signal_kelly_trades_sdc_parts/t2020.json \
  /tmp/219verify/signal_kelly_trades_sdc_parts/t2020.json
# => app 等价: true | lab 等价: true | 解析结果键: fIdx,fields,quadrants(两次同)
```

### 5) 云上 34 文件复算(ssh 只读)
```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173
# ① 文件数: ls /home/ubuntu/code/trade-data/static-site/data/signal_kelly_trades_parts | wc -l      => 17(recent2 计数 0)
#           ls /home/ubuntu/code/trade-data/static-site/data/signal_kelly_trades_sdc_parts | wc -l  => 17
# ② state: /home/ubuntu/code/trade-data/data/.r2_kelly_parts_state.json
#           /home/ubuntu/code/trade-data/data/.r2_kelly_sdc_state.json   (count=17, changed=0)
```
状态连续/合流/往返三判定的复核脚本(当时为内联 heredoc 未留档;下述重建版与当时判定式同构,云上跑):
```python
import json, hashlib, sys
from pathlib import Path as P
sys.path.insert(0, "/home/ubuntu/code/trade-data/scripts")
import upload_r2 as ur
D = P("/home/ubuntu/code/trade-data/static-site/data")
for parts, st_name in (("signal_kelly_trades_parts", ".r2_kelly_parts_state.json"),
                       ("signal_kelly_trades_sdc_parts", ".r2_kelly_sdc_state.json")):
    st = json.load(open(f"/home/ubuntu/code/trade-data/data/{st_name}"))
    n_cont = n_confl = n_stable = 0; tot = 0
    for name, rec in st["files"].items():
        f = D / parts / name; tot += 1
        if ur._kelly_parts_md5(f) == rec["md5"]: n_cont += 1          # state 连续
        d = json.load(open(f, encoding="utf-8"))
        nb = json.dumps({"fields": d["fields"], "quadrants": d["quadrants"]},
                        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.md5(nb).hexdigest() == ur._kelly_parts_md5(f): n_confl += 1  # 合流
        if json.dumps(json.loads(nb), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode() == nb: n_stable += 1     # 往返稳定
    print(parts, f"{n_cont}/{tot} 连续 | {n_confl}/{tot} 合流 | {n_stable}/{tot} 往返稳定")
# 期望: 每族 17/17 三项全满(reviewer 2026-10-06 实测 34/34)
```

### 6) git 纪律四查
```bash
git -C /Users/linhuichen/code/trade merge-base origin/feat/219-parts-metadata origin/main   # 35a89fa2c...
git -C /Users/linhuichen/code/trade rev-parse origin/feat/219-parts-metadata               # ef9b000b2...
git -C /Users/linhuichen/code/trade diff --stat 35a89fa2c ef9b000b2                        # 6 files
git -C /Users/linhuichen/code/trade diff --name-only 35a89fa2c ef9b000b2 | grep -c "^data/"        # 0
git -C /Users/linhuichen/code/trade diff --name-only 35a89fa2c ef9b000b2 | grep -c "^static-site/" # 0
```

---

## 五、诚实标注(哪些实跑 / 哪些没跑)

**实跑(全部只读,产物只落 /tmp)**:
1. git 四查、全仓 grep(worktree 树内)
2. pytest 6/6(快照树 `/tmp/219snap` 复跑)
3. `/tmp/219verify/verify_real.py` 端到端(真实镜像数据 + 真实生成器函数 + 真实指纹函数;NDO+SDC 17+17;负控 A/B)
4. node 真实函数源码解析等价(本轮复跑 NDO t2011、SDC t2020;此前同法跑过 NDO recent/t2026)
5. 云上(ssh 只读): 34 文件 state 连续/B 档指纹/往返稳定三项复算;`.env` 无 `KELLY_UNIQUE_EXPORT`;parts 目录 0 个 unique 产物;state 文件 count/changed;NDO/SDC 各 17、无 recent2
6. 本地镜像 `signal_kelly_backtest.json config.buy_amount=10000`/`config.period_cutoffs` 在位、trades 顶层三键在位

**没跑(及原因)**:
1. 未执行 `export.py` / `deploy.sh` / `signal_kelly_backtest.py` main / `upload_r2.py` 任何 CLI(§18 L50: 探针禁执行业务脚本主体);所有 python 均为 import 模块后调纯函数
2. 未做任何 R2 读写/上传/真跑 verify-r2;未发任何通知/邮件/告警(§18 L48)
3. 未跑 `p0_verify_fetch_sources.mjs`(诊断脚本,仅静态阅读)
4. 「过渡轮 ≤34 回填 / 稳态 0 补传」为静态推理 + 云上状态连续性/确定性实测,**未等真实一轮 verify-r2 收敛**(那是生产动作)——建议 merge 后首轮由主控 §0 观察(见六)
5. 云上复核当时为内联 heredoc,**脚本未留档**(复现段给了同构重建版)
6. min 产物仅做字符串命中核验,未做完整 min↔源码语义 diff(本次无前端源码变更,依赖既有 build 机制即可;§24 四查因无前端改动不触发)

---

## 六、merge 后建议验证点(§0 补充,给主控)

1. merge 后首个生成轮: 线上捏 1 片 parts JSON,顶层键应只剩 `fields`/`quadrants`
2. 下一轮 verify-r2 结果: mismatch 数应 ≤34 且随后归零(一次性收敛)
3. §22 三处一致: 线上(CF)curl parts 与 R2 同值;首页模拟回测弹窗 + 实验室凯利区可正常加载(解析等价已由 node 实测,上线后抽 1 片复核即可)

---

(落档说明: 本报告由 reviewer agent 写档;commit 由主控统一记账。独立验证材料: `/tmp/219snap/`(快照树)、`/tmp/219verify/verify_real.py`、`/tmp/219verify/parse_eq.js`、`/tmp/219verify/{signal_kelly_trades_parts,signal_kelly_trades_sdc_parts,mut_signal_kelly_trades_parts}/`;进度文件 `/tmp/agent-progress-219-p1-review.md`)
