# #203 · `check_failed_units.py` ②b「脚本存在性」层生产空转修复(2026-10-06)

> 任务:#203(源自 #193/#196 §0 上线验证 P2 发现)。
> base = `origin/main` `33d380090`;分支 `feat/203-check-units-timer-20261006`。
> 结论:**根因已修 + 真实生产样本验证(修复前 0/7 → 修复后 7/7)+ 反向对照(存在/缺失两分支)+ 同类排查(仅此一处受影响)**。
> 自验:`scripts/tests/` 240 passed / 1 failed(预存,与本改动无关)/ 1 skipped;本文件自带复现段。

---

## 1. 根因(逐行核实,非抄派单结论)

`scripts/check_failed_units.py` 的 ②b 层(`main()` L231 起)判「巡检者被执行的脚本本体是否还在盘」:

```python
for r in rows:
    for p in adr.extract_script_paths(r.get("exec_start")):
        if not Path(p).exists():
            script_missing.append(...)
```

而 `rows[].exec_start` 的来源:

- 真实路径:`_run_unit_show(u)` → `systemctl show -p ... -p ExecStart <u>`;
- 注入路径:`show_map[u].ExecStart`。

问题出在 **`WATCHMAN_UNITS` 全部是 `.timer`**(`alert_denoise_rules.py:69-77`,7 个:`trade-cloud-unit-patrol.timer` / `check-monitor-heartbeat` / `schedule-monitor` / `self-heal` / `r2-consistency` / `check-data-gap` / `overfit-monitor`)。

**systemd 语义:`.timer` 单元没有 `ExecStart` 属性**——timer 的职责是调度,真正执行发生在其触发的 `.service` 里。云上逐 unit 只读实测(见 §4)证实:`systemctl show <timer> -p ExecStart` 无输出 ⇒ `exec_start` 恒 `None` ⇒ `extract_script_paths(None)` ≡ `[]` ⇒ **②b 层在生产从不下任何判定(永不报警,假绿)**。

**为何测试全绿(§18 L49「假样本养绿」)**:原测试 `test_cfu_watchman_script_missing_rc1` 往 `.timer` 条目直接喂了一个 `ExecStart`——**现实中不存在的输入形态**。层逻辑被这段假样本「测活」,但生产的真实输入(timer 无 ExecStart)无人对账。

> 逐行核实与派单给定结论一致,无偏差。仅一处补充:原派单/索引提的修法是「改查**配对 `.service`**」,本实现改用 systemd 权威字段 `Triggers`(见 §2 说明),并保留同名 `.service` 作为回退。

---

## 2. 改法(语义正确的根因修,非过测试的 hack)

**核心:把「读 unit 自身 ExecStart」换成「先解析到真正持 ExecStart 的 `.service`,再读它」。**

新增纯函数 `_resolve_exec_entries(unit, kind, show)`(`scripts/check_failed_units.py`):

- `kind != "timer"` → 直接取该 unit 的 `ExecStart`(service 路径,反向对照用);
- `kind == "timer"` → 读 `systemctl show <timer> -p Triggers`(云上实测形态:`Triggers=<名>.service`)→ 对**每个被触发 unit** 取 `ExecStart` 聚合;`Triggers` 为空(unit 未加载/查询失败)时**回退**同名前缀 `.service`(systemd 的 timer 默认 `Unit=<同名>.service` 规则);仍取不到 → `[]`。

**为什么用 `Triggers` 而非纯名称替换**:`Triggers` 是 systemd **自己声明的权威触发对象**,能覆盖 timer 用 `Unit=` 显式指定异名 service 的情形;名称替换(索引建议法)是启发式,只在「timer 与 service 同名」时成立。本实现用权威源,同时把名称替换作回退,两者叠加优于任一单法。

配套改动:

- `_run_unit_show()` 的 `-p` 列表加 `Triggers`(对 `.service` 该字段为空,无害);
- 新增 `_as_list()`(str/list/None → list 归一);
- `main()` ② 段:真实(`_run_unit_show`)与注入(`show_map`)**共用同一个 `_resolve_exec_entries` 解析路径**(防两态逻辑漂移);
- 文档同步:档头 ② 说明 / `--unit-show-json` 桩说明 / ②b 注释 / `alert_denoise_rules.extract_script_paths` docstring 各补一句「timer 无 ExecStart,须先解析到 .service」,防后来者重踩。

**fail-open 保持**:解析不到就不判,绝不把「解析失败」报成「脚本被删」;unit 被删(LoadState=not-found)的形态仍由 `judge_watchman_units` 报,不在本层兜。

---

## 3. 改动文件

| 文件 | 改动 |
|---|---|
| `scripts/check_failed_units.py` | 新增 `_as_list` / `_resolve_exec_entries`;`_run_unit_show` 加 `Triggers`;`main()` ② 段统一走解析函数;文档同步 |
| `scripts/alert_denoise_rules.py` | 仅 `extract_script_paths` docstring 补调用方提示(无逻辑改动) |
| `scripts/tests/test_196_patrol_visibility_20261005.py` | 替换 2 个假样本用例为 7 个真实形态用例;新增云上实测 fixture |

---

## 4. 真实生产样本证据(§18 L49:禁人工构造样本)

云上**只读**取样(2026-10-06,`ssh -i ~/tdsignal.pem ubuntu@122.51.111.173`,`systemctl show`,零写):

```
trade-cloud-unit-patrol.timer: LoadState=loaded ActiveState=active UnitFileState=enabled
                               Triggers=trade-cloud-unit-patrol.service      ← timer 无 ExecStart 行
trade-cloud-unit-patrol.service: ActiveState=inactive UnitFileState=static
    ExecStart={ path=/bin/bash ; argv[]=/bin/bash /home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh ; ... }
```

7 个 timer → 7 个配对 service → 7 个真实脚本路径:

| timer | 触发 service | ExecStart 脚本 |
|---|---|---|
| trade-cloud-unit-patrol | .service | `/home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh` |
| trade-check-monitor-heartbeat | .service | `.../scripts/check_monitor_heartbeat.py`(经 `.venv/bin/python`) |
| trade-schedule-monitor | .service | `.../scripts/schedule_monitor.sh` |
| trade-self-heal | .service | `.../scripts/self_heal.sh` |
| trade-r2-consistency | .service | `.../scripts/check_r2_consistency.sh` |
| trade-check-data-gap | .service | `.../scripts/check_data_gap_alerts.sh` |
| trade-overfit-monitor | .service | `.../scripts/overfit_monitor.sh` |

**修复前后对照(同一份云上实测 show_map,纯函数层)**:

```
旧路径(直读 timer ExecStart)非空数 = 0 / 7
新路径(Triggers→service)非空数   = 7 / 7
样例: ['/home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh']
```

> 该对照即「修复前生产空转(0/7)、修复后非空(7/7)」的直接证据。

---

## 5. 反向对照(§18 L49 精神:不只证「解析器能解析」)

用**云上实测输出**构造 `systemctl show` 桩(非注入 JSON),走**真实代码路径**(`_run_unit_show` 的 Key=Value 文本解析),逐项验证:

| 用例 | 输入 | 期望 | 结果 |
|---|---|---|---|
| 真实形态·脚本全在盘 | 7 脚本铺于受控 root | rc=0 零假阳性 | PASS |
| 真实形态·删 1 个 | 删 `overfit_monitor.sh` | rc=1 且**只报该 1 个** | PASS |
| 真实代码路径·全在盘 | 同上(经 `_run_unit_show` 文本解析) | rc=0 | PASS |
| 真实代码路径·删 1 个 | 删 `check_r2_consistency.sh` | rc=1 且报出该脚本 | PASS |
| 真·缺失侧(云上真值路径) | `/home/ubuntu/...` 全不存在 | 全部判缺失 | PASS(7 条) |

**关键**:「删 1 个 → rc=1」这条同时证明**解析确实非空**——若路径恒空(修复前),删了任何脚本都报不出来(恒 rc=0 假绿)。

另设**反假样本护栏** `test_resolve_exec_entries_timer_ignores_own_execstart_fake_sample`:给 `.timer` **自己**喂 `ExecStart`(云上现实不存在的形态)必须被忽略、仍只认 `Triggers→.service` ⇒ 防「注入假样本养绿」再次复发(§18 L49 直击)。

---

## 6. 同类错误面清单(§23.2 修 bug 三铁律 ③)

全仓 grep `ExecStart` / `systemctl show` 的所有消费点,逐项结论:

| 消费点 | 是否同类(在无该属性的对象上取属性) | 结论 |
|---|---|---|
| `check_failed_units.py` ②b(**本任务**) | ✅ 是 | 已修 |
| `alert_denoise_rules.extract_script_paths` | — 纯解析函数,无 I/O 无属性假设 | 消费方**仅** `check_failed_units.py` 一处(grep 证实);docstring 已补提示 |
| `gen_schedule_stats._systemd_last_exit` | ❌ 否 | 查询对象经 `_label_to_systemd_unit` 解析为 `*.service`,读 `LoadState/ExecMainCode/ExecMainStatus`——**这些属性在 .service 上真实存在**(非 timer) |
| `systemd_timeout_gradient_audit.exec_script` | ❌ 否 | `load_services()` 已过滤为 `*.service`(L74-75 注释明确「timer 无 TimeoutStartSec 语义」),`exec_script(text)` 只作用于 service 文本 |
| `check_r2_consistency.sh` / `schedule_monitor.sh` / `self_heal.sh` 的 `systemctl show -p ActiveState` | ❌ 否 | 读的是 `.service` 的 ActiveState,该属性 service 上存在 |
| `cloud_unit_patrol.sh`(unit 文件漂移巡检) | ❌ 否 | 只比 unit **文件内容**,不读 `ExecStart`(全仓 `.sh` 内 grep 无 `ExecStart`) |

**结论:②b 是 `check_failed_units.py` 内唯一在「无该属性的对象」上取属性的层**;①② 两层的字段(`ActiveState`/`LoadState`/`UnitFileState`)在 `.timer` 上云上实测均存在,无同类问题。其余消费点均作用于 `.service`,无同类风险。

---

## 7. 零业务脚本执行证据(§18 L50)

- **云上全程只读**:仅 `systemctl show` / `list-units` 查询,**零写**(未 restart/reset-failed/enable/disable,未跑任何脚本)。
- **本地自测仅两处执行**:①纯函数调用(import 模块 + 调 `_resolve_exec_entries`/`extract_script_paths`,无 subprocess);②`systemctl` **桩**(回放已采样输出,`cat` 预写文本,不 exec 任何业务脚本)。
- **§18 L50 探针 static-only 合规**:未 source/exec 任何仓内业务脚本主体。
- **残留进程证据**:`pgrep -fl "cloud_unit_patrol|schedule_monitor|self_heal|check_r2_consistency|overfit_monitor|check_monitor_heartbeat|check_data_gap"` → **空**。
- **改动面证据**:`git status --porcelain` 仅 3 个源文件(§3 表),无根 `data/` 文件。

> ⚠️ 如实登记一个**非本改动引入**的事实:全量 `pytest scripts/tests/` 会执行预存用例 `test_160_...::test_preflight_real_judge_branch_runs_on_non_systemd`,它真跑 `check_r2_consistency.sh`(沙箱 `tmp_path` + 只读判定);这是仓库既有 CI 用例、非本次新增,且该用例本身在本机失败(见 §8),不产生外发。

---

## 8. 自测结果

```
pytest scripts/tests/test_196_patrol_visibility_20261005.py  →  45 passed
pytest scripts/tests/  (连续 3 次)                            →  241 passed, 1 skipped, 0 failed
```

- **基线对账**:`main`(`33d380090`,无本改动)= **236** 用例(235 passed / 1 skipped);本分支 = **242** 用例(净 +6 = 新增 8 − 移除 2 假样本,其中 196 文件 39→45)。新增用例全 PASS。
- **1 skipped**:`test_monitor_resource_inprogress_20261005.py:183`(macOS APFS `df` 为容器级口径,与 statvfs 卷级不同)——环境性 skip,两分支一致。
- **如实登记一处偶发(非本改动引入)**:首轮全量跑曾出现 1 次 `test_160_r2_consistency_followup_20261005.py::test_preflight_real_judge_branch_runs_on_non_systemd` 失败(该用例真跑 `check_r2_consistency.sh` 的 preflight,把某进程判成「trade-update-all 仍在运行」→ 跳过一致性检查,与断言期望相反)。随后 worktree 连跑 3 次、`main` 连跑 2 次**均全绿**,判为该用例的环境时序偶发(该文件与 `check_r2_consistency.sh` 本次**均未改动**),不属 #203 范畴;如实留痕不隐。

---

## 8.1 交付物自检(§23.3 举一反三)

- **同模式/同数据源/同组件消费点**:`extract_script_paths` 全仓**仅** `check_failed_units.py` 一处调用(grep 证实);其余取 `ExecStart`/`systemctl show` 的消费点均作用于 `.service`(见 §6 清单),不受影响。
- **相关展示位**:本层只产告警文本(邮件/飞书经既有 `notify.py` 通道),无前端展示位、无数据产物 ⇒ **不涉** §21 算法公示 / §22 数据一致性 / §24 版本串 / README。
- **§23.4 团队协作**:已 scan `docs/pending-features-index.md` #203 行(修法描述一致);同模块(巡检可见性族 #196/#193)无其他在改任务;本改动为既有脚本的根因修,无新增对外接口/数据结构 ⇒ 无预留位置需求、无同模块覆盖冲突。

---

## 9. 复现段

```bash
# ① 云上只读取样(零写)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'for t in trade-cloud-unit-patrol trade-check-monitor-heartbeat trade-schedule-monitor \
             trade-self-heal trade-r2-consistency trade-check-data-gap trade-overfit-monitor; do \
     systemctl show $t.timer -p Id -p LoadState -p ActiveState -p UnitFileState -p Triggers; \
     svc=$(systemctl show $t.timer -p Triggers --value); \
     systemctl show "$svc" -p ExecStart; done'

# ② 修复前后对照(纯函数,无 subprocess)
#    见 §4 的 0/7 vs 7/7 输出

# ③ 单测(含云上实测 fixture + 真实代码路径桩)
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q \
  scripts/tests/test_196_patrol_visibility_20261005.py

# ④ 全量对账
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
```

---

## 10. 参考

- 上游发现:`docs/ops/193-196-live-verify-20261006.md` §P2(现象/为何测试全绿/建议修法)
- 病灶同族:CLAUDE.md §18 **L49**(假样本养绿)/ **L50**(探针 static-only)/ §23.2(修 bug 三铁律)/ §23.3(举一反三)
- memory:`mechanism-scope-verify-in-code`(机制作用范围必须读代码确认)/ `alert-denoise-keep-fault-discriminator`(降噪必须保留真故障判别维度)
- 索引:`docs/pending-features-index.md` #203
- 关联:#196(本体,/ `docs/ops/196-patrol-visibility-20261005.md`)/ #193(§0 上线验证发现来源)