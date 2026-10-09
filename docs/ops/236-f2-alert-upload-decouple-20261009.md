# #236 F2 实施报告:预警数据独立上传 R2 —— 解开 deploy 校验自锁(2026-10-09)

> 实施 agent 落档,2026-10-09。改动仅 1 个文件(`scripts/update_all.sh`);唯一一次 R2 写 = alert.json(先备份后上传,内容未变);零告警/邮件/飞书外发。
> 前置:`docs/ops/deploy-selflock-recon-20261009.md`(只读核查,§5 F2 方向)。

## 0. 一句话结论

在 deploy 主链之外(update_all.sh 两个 export 之后)加了一步**独立、失败不阻断、留痕不静默**的 `upload_r2.py upload-data-files alert.json alert_analyze_*.json`(**带 `--skip-if-locked`**),使 R2 侧的 alert.json 不再依赖 deploy 自身。**「读 R2 的闸门拦住了它自己输入的唯一运输通道」这一结构死锁被解开**:即使某天 deploy 被 check_alert 拦住,前一天的 update_all 已把新 alert.json 推上 R2,闸门下次自然放行,不再需要人工解锁。

## 1. 改了什么(改动点)

**唯一文件:`scripts/update_all.sh`**(相对 main,+31 / -1)。

| 位置 | 内容 |
|---|---|
| L174-176(C6 注释) | 口径更新:原「alert.json 本地更新,下次 pipeline deploy 推上线」→ 改为「本地更新 + 随下方 #236 F2 独立上传推 R2」 |
| L187-214(新增 F2 块) | 30 行注释(死锁结构/修法/不冲突论证/失败策略/先例)+ 5 行逻辑 |

核心逻辑(逐字,`scripts/update_all.sh` L204-214):

```bash
echo "-> 预警数据独立上传 R2（alert.json + alert_analyze_*.json，#236 F2 解自锁，--skip-if-locked 不阻塞主链）..." | tee -a "$LOG"
ALERT_R2_OUT="$( cd "$REPO/static-site/data" && "$PY" "$REPO/scripts/upload_r2.py" --skip-if-locked upload-data-files alert.json alert_analyze_*.json 2>&1 )"
ALERT_R2_RC=$?
printf '%s\n' "$ALERT_R2_OUT" >> "$LOG"   # 全文入日志（留痕，不静默）
if [ "$ALERT_R2_RC" -ne 0 ]; then
  echo "⚠ 预警数据独立上传 R2 失败(rc=$ALERT_R2_RC, 不阻塞主流程)。..." | tee -a "$LOG"
elif printf '%s' "$ALERT_R2_OUT" | grep -q "SKIPPED_LOCKED"; then
  echo "ℹ 预警数据独立上传 R2 被锁跳过(...)" | tee -a "$LOG"
else
  echo "✓ 预警数据独立上传 R2 完成（alert.json + alert_analyze_*.json，#236 F2）" | tee -a "$LOG"
fi
```

**位置为什么放这**:紧跟在 C6(`export_alert`)与 C7(`export_alert_analyze`)之后 —— 恰好是本地 alert.json / alert_analyze_*.json 刚写完、内容最新的那一刻。

**关键实现细节(踩过的坑,勿回退)**:

1. **必须 `cd "$REPO/static-site/data"` 包一层**。`upload_r2.py cmd_upload_data_files` 把每个参数当**相对 data_dir 的 glob**,但先用 `(data_dir/f).exists()` 预过滤 —— 字面量 `alert_analyze_*.json` 传进去会被 `exists()` 判否而**静默丢弃**。所以必须让 **shell** 先展开 glob,再传基名进去。
2. **必须带 `--skip-if-locked`**。默认锁行为是**排队等锁最多 7300s**(会拖住 update_all)。带此 flag 后:拿不到锁就短重试(R2_UPLOAD_SKIP_RETRY_SECS 默认 60s),仍未拿到则打印 `SKIPPED_LOCKED: ...` 到 stderr 并 **exit 0**。选它是为了「既不阻塞主链、又不与主链既有上传打架」(见 §3)。
3. **必须带 `REPO=`**(由 update_all.sh 上方已 export;`guard_repo_default` 拒裸跑)。
4. **rc 用命令替换后的 `$?` 捕获**(不是管道 `PIPESTATUS`)——因为输出已 `2>&1` 收进变量,再 `printf` 落日志。

## 2. 死锁为何被解开(结构说明)

**死锁结构(已取证,`deploy-selflock-recon-20261009.md` §2)**:

```
deploy.sh  L323-324  check_data_integrity  ← 读【线上 R2】的 alert.json 判新鲜度
deploy.sh  L326-331  rc≠0 → notify(severe) + exit 1(硬终止)
deploy.sh  L582      触发 r2_upload_async(此时才 upload-all-data,alert.json 的唯一 R2 通道)
```

拦截点(L324)**早于**写入触发点(L582),且 `static-site/data/*` 已全量 gitignore(**无 git 旁路**,`git check-ignore` 已证)→ 一旦 R2 侧 alert.json 滞后 >7 自然日,deploy 永久锁死,且 **deploy 内无 check 跳过开关**(grep 已复核)。

**为什么现在解开**:新步骤把 alert.json 的上传**移出 deploy 主链**。deploy 被拦 ⇒ 本地 alert.json 已是新版 ⇒ 下一次(或当天稍后)update_all 跑完,新 alert.json 已上 R2 ⇒ 明/后日 deploy 的 check_alert 读到的是新鲜副本 ⇒ 放行。闸门不再拦自己输入的唯一通道。

**注意(诚实标注,非本任务范围)**:F2 **单修**只能把「永久锁」降级为「自解锁(等下一个 update_all 跑完)」;长假中「本地也旧」的场景(如 10-08 02:06 六项全 20260930)**仍会被拦**,那是 #235 交易历口径的事(F1,另一任务)。**两件叠加 = 事件不发生 + 结构死锁消除**(recon §4)。

## 3. 反例核对(不冲突 / 不违反 §22 / 不静默)

- **不双重上传、不竞态**:靠 `--skip-if-locked` 天然互斥。主链 R2 上传(`r2_upload_async`)在跑 ⇒ 锁被占 ⇒ 本步**跳过**(且该 async 的 `upload-all-data` 会把同 key 覆盖,内容一致);主链被 deploy 拦(= async 根本没跑)⇒ 锁空闲 ⇒ 本步**正好补上**。二者互斥,不存在同一时刻两路写同一 key。
- **§22 多展示位一致**:`alert.json` 与 `alert_analyze_*.json` **同批同源**上传(同一命令),不会出现「alert 新 / analyze 旧」的展示位不一致;deploy 侧 check_alert 与前端读的是同一 R2 副本。
- **§23.11 不静默**:三态分支各自 `tee -a "$LOG"` 留痕(成功✓/被锁ℹ/失败⚠),且失败分支的 upload 全文也 `printf >> "$LOG"`。失败**不阻断** update_all 主链,但**有痕迹**。
- **持续失败的可见性兜底**:不新增告警通道 —— 由 deploy 侧 `check_alert` 对 R2 新鲜度的判定(超阈值 → severe 邮件/飞书)独立兜底。本步只是「供应方」,「质检方」仍是原有闸门。
- **§21 算法公示**:本改动是**上传管道**,不动任何算法/数值/口径/字段,无公示文案需同步。
- **§23.4 同模块冲突**:`docs/pending-features-index.md` #236 行(待拍板)+ 同模块 update_all.sh 的 #212/#207/#201 均不落在我插入的 L187-214 行区间,无覆盖。

## 4. R2 实测证据(唯一一次写:只写 alert.json 一个 key)

写侧环境 = 云上(`/home/ubuntu/code/trade-data`,唯一合法 public R2 写侧;mac dev 树被 export-guard L2 拦,exit 2)。

| 步骤 | 命令/结果 | 证据 |
|---|---|---|
| ① 先备份(§25) | 上传前把现网 alert.json 落 `/home/ubuntu/backup/f2-236-20261009/alert.json.before` | `md5 = 65c60ad5378e4179a40bfacb69c08352` |
| ② 上传前基线 | `ssd HEAD /data/alert.json` | `etag="65c60ad5378e4179a40bfacb69c08352"`,`LM=Thu 08 Oct 2026 17:08:04 GMT` |
| ③ md5 核对(本地==现网==待传) | 备份 md5 == 上传前 R2 etag == 65c60ad5 ⇒ **内容一致** | 三者同值 |
| ④ 真上传 | `cd .../static-site/data && REPO=... upload_r2.py upload-data-files alert.json` | `[1/1] ✓ alert.json (3205B)` + `Cache purge 完成: 全部 1 批成功, 共 purged 1/1 keys` + `EXIT=0` |
| ⑤ 上传后 R2 直连 | `ssd HEAD /data/alert.json` | `LM=Fri 09 Oct 2026 08:26:23 GMT`(**已推进**),`etag=65c60ad5…`(**未变**) ⇒ 真发生过 PUT 且内容逐位未变 |
| ⑥ CF 侧读取 | `ss.fx8.store/data/alert.json` GET | `md5 = 65c60ad5…`(与源一致,缓存已清) |
| ⑦ 可重复跑 | 同一命令再跑 + 换 `--skip-if-locked` 语义 | 幂等可重复(见 ⑧) |
| ⑧ 锁跳过路径(对真锁实测) | 云上后台 `flock -x /tmp/trade_r2_upload.lock sleep 90` 占锁,再跑本步命令 | 输出 `SKIPPED_LOCKED: R2 上传锁被占用, 跳过本轮上传(--skip-if-locked, 已等锁重试 60s 仍未拿到, 下轮重试)`,`EXIT=0`;**R2 LM 不变(仍 08:26:23)⇒ 零写** |

**时点纪律**:上传发生于 **2026-10-09 16:26(北京)**,距当日禁区时点(15:35/16:00/17:50/20:35/22:00)均 >10 min,且所写内容 = 当前权威最新版(内容未变)。

**本地三态 harness 自测**(`/tmp/f2harness`,stub 化 upload_r2.py,非生产):ok/skip/fail 三态分别 → ✓ / ℹ / ⚠ 分支且父脚本**不中止**(fail 分支后继续执行);glob 展开(5 个 alert_analyze 文件)正确传入;字面量未展开时被 `exists()` 丢弃的坑已在 §1-2 用 `cd` 修掉。

## 5. 未做 / 范围外(诚实标注)

- **未改 deploy.sh / check_data_integrity.py**(F2 无需动,recon §4 已论证)。
- **未修 #235 交易历口径(F1,另一任务)**;未碰 #241 同族(`check_data_gap_alerts.py` / `sensenova-proxy-healthcheck.py` / `overfit_monitor.py`)。
- **未改 `docs/pending-features-index.md` 状态列**(#236 仍「待拍板」)——状态登记归主控收口。
- 未在 mac 上做 R2 写(被 export-guard L2 拦,属预期)。

## 6. 回滚说明

**代码回滚**(改动仅在 feat 分支的 `scripts/update_all.sh` 一处):

```bash
# 方式 A(推荐,保留历史)
git revert <本 commit hash>
# 方式 B(若尚未 merge main,直接丢弃)
git checkout main -- scripts/update_all.sh
```

回滚后 alert.json 的上传通道回到「仅 deploy 内 upload-all-data」= 死锁结构恢复(即回到修复前状态,不会更坏)。

**数据回滚**:本次 PUT 的 alert.json **内容与上传前逐位相同**(md5 一致,仅 Last-Modified 推进),**无需恢复内容**。若将来确需回到本次备份点:

```bash
# 云上
cp /home/ubuntu/backup/f2-236-20261009/alert.json.before \
   /home/ubuntu/code/trade-data/static-site/data/alert.json
cd /home/ubuntu/code/trade-data/static-site/data && \
  REPO=/home/ubuntu/code/trade-data \
  /home/ubuntu/code/trade-data/.venv/bin/python \
  /home/ubuntu/code/trade-data/scripts/upload_r2.py upload-data-files alert.json
```

## 7. 证据索引(可复核)

- 代码:`scripts/update_all.sh` L174-176(注释)/ L187-214(新增 F2 块);`scripts/upload_r2.py`(cmd_upload_data_files / `_acquire_r2_upload_lock` / `--skip-if-locked` / `_record_standalone_keys`);先例 `scripts/s06_snapshot.sh` L133。
- 云上:备份 `/home/ubuntu/backup/f2-236-20261009/alert.json.before`(md5 65c60ad5…);上传后 `ssd HEAD /data/alert.json` LM=09 Oct 08:26:23 GMT。
- 线上:`ss.fx8.store/data/alert.json` GET md5=65c60ad5…。
- 结构:`docs/ops/deploy-selflock-recon-20261009.md` §2(死锁行号)/§4(F1+F2 互补)/§5(F2 方向)。

---
*实施 agent 落档;只 commit + push feat 分支,不 push main;merge 由主控走 `scripts/main-merge.sh`。*