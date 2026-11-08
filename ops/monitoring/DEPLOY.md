# 私有运维控制面部署与回滚

本包在隔离分支实现，由 **Claude 审核、合并、部署**。以下生产命令是交付步骤，本轮作者没有执行 D1 创建/迁移、设置 secrets、部署 Worker、启动 collector 或发送真实通知。

## 1. 拓扑与边界

- CODE：`/home/ubuntu/code/trade-data-signal`；DATA：`/home/ubuntu/code/trade-data`。代码和业务数据独立，collector 不导入业务入口，不改业务 DB/日志/配置。
- 云端 `trade-ops-monitor.timer` 每15分钟启动 `trade-ops-monitor.service`（oneshot），入口为 `scripts/ops_monitor.py --config /etc/trade-ops-monitor/collector.json --once`。不是 `ops/monitoring/collector.py`，没有 `--push`。
- Worker 复用现有域名、session 和 HTTPS 路由，新增 `/api/ops/*` 与 `/admin/ops.html`；不开放云端入站端口，不增反向代理服务。
- **独立新 D1 `OPS_DB`** 保存私有快照/事件/人工修订，不能绑定到 `FUND_SCORE_DB`、订阅KV或公开R2。ingest bearer 只有写入权限，不是 viewer/admin。
- 新通知默认 `OPS_ALERT_SCOPE=watchdog`：仅页 collector失联/恢复；所有业务checks继续保留事件，但通知标为 `owned_by_existing_chain` suppressed，由已有运维链承担，避免同故障service critical/schedule warning多响。`all` 是显式扩展，只有Claude审过旧链去重才可开启，不能靠配置遗漏扩大范围。
- Worker `scheduled` 每15分钟独立判断失联并执行保留期/有界 outbox 重试。有快照时，最新采样超过900秒为 stale。首次尚无快照时，从 watchdog 首次检查记下的 `first_seen_at` 开始给予15分钟宽限，期间保持 unknown；超过宽限仍无首样，后续cron将 `watchdog.status` 置为 stale、`bootstrap_overdue=true`，防止永远unknown而不暴露监测未建立。无head时 `collector_status` 本身仍为unknown，不能当健康。检测在下一cron轮生效，不能承诺恰好第15分钟；宽限从首次独立检查而非部署命令时间起算。这些状态只说明监测建立/新鲜度，不代表业务故障或恢复。告警可能在远端接受后回执未持久化时重复传输，不承诺 exactly once。
- 本控制面已交 C 作为新增第45项登记；canonical 源是 `docs/deploy/systemd-units-20260912.md`，`install/` 单元与其必须逐字一致。不要再维护独立的第44项计数常量。生成器/注册测试由 C 负责。

契约见 [contract.md](contract.md)。当前路径可通过非敏感配置和 systemd drop-in 调整；不得用业务 `.env` 作为 collector EnvironmentFile。

## 1.1 合并前置：先实装但不启动，再追加真实云快照

**原实施交接时（历史记录，非当前快照状态）**，canonical文档/UNIT_REGISTRY已登记45项，但当时 `docs/deploy/systemd-units-cloud-snapshot.txt` 仍是44个service/44个timer。以下是首次追加流程；本次 systemd 249 兼容补修基底 `2514b9a30952b100e835f28f0eda335fbe369cf0` 已包含实际45对快照，改走第5.1节，不重复执行88段断言或追加service/timer。首次追加时的比较命令为：

```bash
python3 -B scripts/systemd_timeout_gradient_audit.py \
  --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc
```

已独立确认该命令真实返回 **1**：已有条目的字段差异0处，仅doc多 `trade-ops-monitor.service`、`trade-ops-monitor.timer`，快照侧没有额外项。该门禁正常阻断尚未完成的生产事实；本轮作者没有修改旧gate或历史snapshot，也没有把45项声明伪造成45项云上已观察。

以下前置由 **Claude在部署窗口执行并回执**，使用已经实现、审核的源文件，不需要主控代写实现。`OPS_REVIEW_CODE` 指目标云端独立暂存的完整已审核分支/交付目录，包含本包、canonical文档、现有审计脚本及原历史snapshot；它不是提前pull或切换现有生产CODE目录。可通过既有私有交付通道暂存，本文不提供连接参数。

1. **安装两项但保持停用**：先核对暂存安装文件的冻结哈希与canonical字节一致，安装后reload；timer disabled/inactive，service不启动。service为无`[Install]`的oneshot，`UnitFileState=static`是预期，不能把它误写成已启用/已运行。

```bash
set -e
# Set this path to the complete approved staging checkout on the target cloud.
OPS_REVIEW_CODE=/tmp/trade-ops-reviewed-code
cd "$OPS_REVIEW_CODE"
sha256sum ops/monitoring/install/trade-ops-monitor.service ops/monitoring/install/trade-ops-monitor.timer
sudo install -m 0644 -o root -g root ops/monitoring/install/trade-ops-monitor.service /etc/systemd/system/trade-ops-monitor.service
sudo install -m 0644 -o root -g root ops/monitoring/install/trade-ops-monitor.timer /etc/systemd/system/trade-ops-monitor.timer
sudo systemd-analyze verify /etc/systemd/system/trade-ops-monitor.service /etc/systemd/system/trade-ops-monitor.timer
sudo systemctl daemon-reload
sudo systemctl disable --now trade-ops-monitor.timer
sudo systemctl stop trade-ops-monitor.service
sudo systemctl show trade-ops-monitor.service trade-ops-monitor.timer --property=LoadState,UnitFileState,ActiveState,SubState
```

2. **只实读新两项，记录观察时间**：确认LoadState已加载且没有启动；检查unit/drop-in不含明文密钥。捕获源必须是实际 `systemctl cat`，不能从canonical/install复制内容假充观察。遇到缺项/秘密值/意外差异先停止，保留私有证据。

```bash
set -e
umask 077
OPS_OBS_STAGE="$(mktemp -d /tmp/trade-ops-unit-observation.XXXXXX)"
chmod 0700 "$OPS_OBS_STAGE"
date -u +'%Y-%m-%dT%H:%M:%SZ' > "$OPS_OBS_STAGE/observed_at.txt"
for unit in trade-ops-monitor.service trade-ops-monitor.timer; do
  systemctl cat --no-pager "$unit" > "$OPS_OBS_STAGE/$unit"
  test -s "$OPS_OBS_STAGE/$unit"
done
```

3. **仅追加新两项到原snapshot**：先确认原44项是此前已观察的基线且新项尚未出现。保留原文件字节前缀，不重建、不整文件覆盖，也不顺手刷新旧44项。下面只把上述实读两项追加，带观察时间；它不安装/启动任何服务。

```bash
cd "$OPS_REVIEW_CODE"
python3 - docs/deploy/systemd-units-cloud-snapshot.txt "$OPS_OBS_STAGE" <<'PY'
import fcntl, hashlib, os, sys
from pathlib import Path
snapshot, observed = Path(sys.argv[1]), Path(sys.argv[2])
units = ('trade-ops-monitor.service', 'trade-ops-monitor.timer')
stamp = (observed/'observed_at.txt').read_text().strip()
assert stamp.endswith('Z') and '\n' not in stamp
addition = b''
for unit in units:
    raw = (observed/unit).read_bytes()
    assert raw.strip() and b'[Unit]' in raw and b'@@@FILE:' not in raw
    addition += ('@@@FILE:' + unit + '\n# observed_at_utc=' + stamp + '\n').encode()
    addition += raw.rstrip(b'\n') + b'\n'
with snapshot.open('r+b') as f:
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    before = f.read()
    for unit in units:
        assert ('@@@FILE:' + unit + '\n').encode() not in before
    assert before.count(b'@@@FILE:') == 88
    with (observed/'snapshot-before.sha256').open('x') as proof:
        proof.write(hashlib.sha256(before).hexdigest() + '\n')
    delta = (b'' if before.endswith(b'\n') else b'\n') + addition
    f.seek(0, os.SEEK_END)
    f.write(delta); f.flush(); os.fsync(f.fileno())
    f.seek(0)
    assert f.read() == before + delta
PY
```

若观察地点与最终合并工作树不同，把**实读的新两项追加片段和观察回执**带回审核分支，仅做同样的追加；不拿暂存整份snapshot覆盖合并工作树里的原44项。若原snapshot已被其他授权操作更新，先对账，不用此88段基线断言绕过并发变化。

4. **四方一致后再main-merge**：在含新registry/canonical及真实追加snapshot的已审核代码上运行以下现有只读检查；云端实值检查在目标云执行。要求无集合/字段差异且真实rc=0；不能仅看shell命令串最后一条命令的退出码。门禁未通过就停止，不使用`--align-doc`、跳过/弱化gate或伪造快照来放行。

```bash
cd "$OPS_REVIEW_CODE"
python3 -B scripts/check_unit_registry_drift.py --quiet
python3 -B scripts/systemd_timeout_gradient_audit.py \
  --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc
python3 -B scripts/systemd_timeout_gradient_audit.py \
  --units-dir /etc/systemd/system \
  --snapshot docs/deploy/systemd-units-cloud-snapshot.txt --check-snapshot
```

Claude将真实追加快照、观察时间、已安装但停用状态及检查rc作为交接证据审核。main-merge前还必须完成第4节的OPS_DB迁移、secrets就绪及根配置持久化；根 `wrangler.jsonc` 的部署配置与真实追加快照一并提交审核，再按现有规范main-merge。不能先合并触发自动部署，再补库或密钥。源实现已在交付中；待完成的是生产资源/安装/观察事实，而不是交给Claude另写脚本。

5. **合并后才拉源码并启用**：上述门槛满足且main-merge成功后，Claude再在真实CODE目录确认main分支并 `git pull --ff-only origin main`。完成第3—6节的密钥/D1/API配置和首样验收后，才允许启用timer。合并前/拉取前不启动collector、不启用timer；不以提前采样制造“已云部署”证据。只安装单元不代表采集、独立cron或业务健康已验证。

## 2. 本地验收（无生产账户/通知）

从 CODE 根目录运行。使用仓库已锁定的 Wrangler v4；始终显式传 `--config`，不在默认 stock `wrangler.jsonc` 上运行 dev，因为其中已有 `SUBSCRIBE_KV remote:true`。

```bash
python3 -m pytest -q ops/monitoring/tests/test_deploy.py
python3 scripts/ops_monitor.py --help
python3 ops/monitoring/configure.py --help
node node_modules/wrangler/bin/wrangler.js d1 migrations apply OPS_DB --local --config ops/monitoring/wrangler.local.jsonc
```

本地 dev、session/ingest/历史/事件/人工关闭/cron/outbox 的实际集成验收使用 F 的 `ops/monitoring/tests/smoke_local.py` 与父任务流程：全部 binding 显式 `remote:false`，一次性模拟密钥，仅 loopback，`OPS_ALERT_ENABLED=false`。不要对生产调用 `/__scheduled`，该端点会运行有副作用的 scheduled handler。生产验证器从不调用它。

部署包测试实际运行 collector `--help`，并在子进程外发/业务写入陷阱下验证缺配置非零退出；不会通过 `--help` 测试代替数据正确性验收。macOS 无 systemd 时不能宣称现场 unit 已校验；Claude 必须在目标 Linux 上运行下一节的 `systemd-analyze verify`。

## 3. 私有文件与保密输入

在 Claude 授权的管理机上准备私有目录；不将目录放在 CODE、静态资源或被同步的文档目录。下面命令只传**文件路径**，没有 token 字面值或 secret 命令行参数；禁止 `set -x`、`echo token` 和把 token 放 URL。

```bash
umask 077
OPS_PRIVATE="$HOME/.local/state/trade-ops-deploy"
install -d -m 0700 "$OPS_PRIVATE"
python3 - "$OPS_PRIVATE" <<'PY'
import json, os, secrets, sys
from pathlib import Path
root = Path(sys.argv[1])
# Exclusive create prevents accidental token rotation on rerun.
for name in ('ingest.token', 'admin.token'):
    fd = os.open(root/name, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(secrets.token_urlsafe(48)+'\n')
        f.flush(); os.fsync(f.fileno())
payload = {'OPS_INGEST_TOKEN': (root/'ingest.token').read_text().strip(),
           'OPS_ADMIN_TOKEN': (root/'admin.token').read_text().strip()}
fd = os.open(root/'worker-secrets.json', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    json.dump(payload, f); f.flush(); os.fsync(f.fileno())
PY
```

`OPS_ADMIN_TOKEN` 是可选 bootstrap：若只允许 session admin，不创建/上传该字段，验证器改由 UI/session 人工验收。不要以 `OPS_INGEST_TOKEN` 代替它。此示例生成独立 token，不读取既有业务凭据。

已有 session secret 与 `ADMIN_USERS` 原样保留。`ADMIN_USERS` 使用既有 `provider:providerUid` 完整 allowlist；普通登录用户禁止访问。若需新增管理员，Claude 先核对原 allowlist，在私有输入流程中提供完整合并值（不能覆盖丢旧成员），加入私有 secrets 文件；不要提交身份列表或把 session secret 放入候选 config。前端 bootstrap token 只驻留内存，不持久化到 localStorage/URL。

本次main-merge会触发自动部署，必须按第4节先把OPS密钥配置到实际目标Worker，再放行合并；仅生成本地secrets文件或上传未发布版本不算就绪。`wrangler secret put/bulk` 会影响已部署Worker，不是无副作用准备步骤，由Claude在部署窗口执行并记录版本；不要在目标不存在时接受创建空Worker的兜底。若采用versions secret流程，必须明确发布并验证密钥已对目标部署生效。手动发布也可使用 `wrangler deploy --secrets-file` 随代码上传，未列出的已有secrets保留，但不能用“稍后手动上传”代替自动部署前的就绪门槛。初期不配置 `OPS_ALERT_WEBHOOK`，且 `OPS_ALERT_ENABLED=false`、`OPS_ALERT_SCOPE=watchdog`。

## 4. 新建 D1、配置合成与迁移顺序（Claude 生产步骤）

1. 记录当前生产 Worker 版本、现有绑定和 cron；对已有公开/业务路由做只读基线。确认目标账户和 Worker。认证沿用授权管理机的 Cloudflare 登录，不输出认证配置。
2. **新建独立库**，只记录返回的 database UUID（不是 secret）；禁止选择既有业务库。

```bash
node node_modules/wrangler/bin/wrangler.js d1 create trade-ops-monitor --config wrangler.jsonc
```

3. 使用 F 的 `ops/monitoring/configure.py` 从当前生产基础配置合成**私有候选文件**，保留现有 KV/R2/FUND_SCORE_DB/assets/routes/session 设置；增加 `OPS_DB` 和 `ops/monitoring/migrations`，合并 cron 而非清空旧 cron，初始 alerts disabled。CLI 以脚本 `--help` 为准；交付验收时以该脚本的真实参数调用，不手写第二套合成器。

```bash
OPS_CANDIDATE_DIR="$(mktemp -d /tmp/trade-ops-candidate.XXXXXX)"
chmod 0700 "$OPS_CANDIDATE_DIR"
OPS_CANDIDATE="$OPS_CANDIDATE_DIR/wrangler.ops.production.jsonc"
# Read the NEW database UUID returned by d1 create; it is not a secret.
read -r -p 'New dedicated OPS database UUID: ' OPS_DATABASE_ID
python3 ops/monitoring/configure.py --source "$PWD/wrangler.jsonc" \
  --database-id "$OPS_DATABASE_ID" --database-name trade-ops-monitor \
  --output "$OPS_CANDIDATE" > "$OPS_PRIVATE/configure-report.json"
OPS_SOURCE_SHA256="$(python3 - "$OPS_PRIVATE/configure-report.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))['source_sha256'])
PY
)"
python3 ops/monitoring/configure.py --source "$PWD/wrangler.jsonc" --check-current "$OPS_SOURCE_SHA256"
```

`configure.py` 输出限制为私有 `/tmp` 候选；它保留旧绑定/路由设置，并将支持的文件路径按源配置目录重定位，不代建D1或设置secrets。本次候选迁移到 `/tmp` 后路径解析错误已修复闭环：父任务已用真实候选完成 D preflight（`config.paths` 全部OK）与真正 Wrangler `--dry-run`（PASS，只构建、未部署）。证据为私有 `/tmp/codex-reports/ops-monitoring-complete-20261107/dryrun-candidate.jsonc` 和 `production-candidate-build/`，版本/候选/构建哈希记录在作者私有闭环回执。原小组49项测试验证部署包边界，**不作为该路径bug修复通过的替代证据**。每次正式发布前仍须对本次候选运行路径预检；若未来路径漂移为critical，应停止发布。

初始告警值必须显式false；生成器保留旧vars而非擅改。因此在私有候选上仅做这项已审阅覆盖（不替代F合成逻辑）：

```bash
python3 - "$OPS_CANDIDATE" <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path('ops/monitoring').resolve()))
from configure import loads_jsonc
p = Path(sys.argv[1]); cfg = loads_jsonc(p.read_text())
cfg.setdefault('vars', {})['OPS_ALERT_ENABLED'] = 'false'
cfg['vars']['OPS_ALERT_SCOPE'] = 'watchdog'
tmp = p.with_name(p.name + '.alerts-off.tmp')
fd = os.open(tmp, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    json.dump(cfg, f, indent=2); f.flush(); os.fsync(f.fileno())
os.replace(tmp, p)
PY
```

4. 人工复核候选 diff：`OPS_DB` ID与所有现有 D1 不同、迁移目录正确、Worker名与主入口不变、旧绑定不丢、只新增同域路径、没有 secret 字面值、没有将本地 fake namespace带到生产。`/tmp`候选用于预检和资源准备，不能成为唯一生产配置来源，不能整份复制覆盖根配置。
5. **main-merge前**迁移 **OPS_DB 这一 binding**，先列表再执行。必须显式 `--remote --config`；不要对 FUND_SCORE_DB 执行本包 SQL。记录真实UUID及迁移成功回执，失败时不得合并触发自动部署。

```bash
node node_modules/wrangler/bin/wrangler.js d1 migrations list OPS_DB --remote --config "$OPS_CANDIDATE"
node node_modules/wrangler/bin/wrangler.js d1 migrations apply OPS_DB --remote --config "$OPS_CANDIDATE"
```

6. **main-merge前配置secrets**：确认目标是既有生产Worker，并核对当前版本/旧业务路由基线，再由Claude执行下列有副作用的密钥更新。私有JSON只含本次需要的字符串值，不含null（null会删除密钥）；既有session/ADMIN_USERS等未列出的secret保留。`OPS_INGEST_TOKEN`必须就绪，`OPS_ADMIN_TOKEN`仅在使用bootstrap时设置。密钥值不进配置/提交/日志；仅记录目标、密钥名称及更新后的版本。更新后复核旧业务路由，失败时停止合并。

```bash
python3 ops/monitoring/configure.py --source "$PWD/wrangler.jsonc" --check-current "$OPS_SOURCE_SHA256"
node node_modules/wrangler/bin/wrangler.js secret bulk "$OPS_PRIVATE/worker-secrets.json" --config "$OPS_CANDIDATE"
```

7. **把真实部署增量持久化到根 `wrangler.jsonc`**：Claude在部署整合分支手工合入下列逻辑片段。真实UUID只能来自第2步实际新建D1，示例占位符不能提交/部署。将OPS_DB对象追加到现有 `d1_databases`，将cron按集合并入原 `triggers.crons`，将两个非密钥vars并入现有 `vars`；保留所有旧字段、对象、表达式及注释。根配置的迁移目录必须使用仓库相对路径。候选为解决跨目录解析含有绝对本机路径，**禁止把整个 `/tmp`候选复制回根配置**，也不提交本地fake binding或secret文件。

```jsonc
{
  "d1_databases": [
    // 保留原有数据库对象；在该数组末尾追加此对象。
    {
      "binding": "OPS_DB",
      "database_name": "trade-ops-monitor",
      "database_id": "<替换为本次真实新建OPS_DB的UUID>",
      "migrations_dir": "ops/monitoring/migrations"
    }
  ],
  "triggers": {
    // 保留其他triggers字段及所有原有cron；此处只展示新增表达式，已有则不重复。
    "crons": ["*/15 * * * *"]
  },
  "vars": {
    // 保留所有原有非密钥vars；密钥不放在这里。
    "OPS_ALERT_ENABLED": "false",
    "OPS_ALERT_SCOPE": "watchdog"
  }
}
```

此片段是增量示意，不是替换整份配置的模板。修改后人工逐字段对比根配置与已核验候选：OPS_DB真实ID、名称、迁移目录解析结果、合并后的cron和vars一致，旧binding/routes/assets/session设置不丢。对**根配置**再做静态预检和真实Wrangler构建干跑，不仅验/tmp候选；预检中的运行态unknown仍按第6节处理，不能改判绿。下面命令由Claude执行，不部署、不迁移数据库：

```bash
python3 ops/monitoring/verify_deployment.py --worker-config "$PWD/wrangler.jsonc"
node node_modules/wrangler/bin/wrangler.js deploy --dry-run --config "$PWD/wrangler.jsonc" --outdir "$OPS_PRIVATE/root-config-build"
```

8. **提交根部署配置与真实unit快照，再main-merge**：只有第5步迁移、第6步已生效secrets、第1.1节disabled安装/真实快照及所有门禁均有回执，Claude才提交根配置和真实新unit快照并按规范main-merge。根配置变更会触发 `.github/workflows/deploy-cf.yml`（实际执行 `npx wrangler deploy`）；Cloudflare Git integration也必须使用同一仓库根目录的版本化 `wrangler.jsonc`，不读/tmp候选或另一个旧配置。合并前由Claude核对两条部署通道的目标Worker、工作目录和构建来源，避免任一通道先上未就绪库。

main自动部署成功后，记录实际commit、Worker版本、OPS_DB绑定/迁移与独立cron实值；若需手动重发，也显式使用 `--config "$PWD/wrangler.jsonc"`，而不是旧候选。即使曾用候选过渡发布，也必须完成根配置入main及从该source部署的验收；仅候选部署成功不算交付完成。

9. 首次尚无采样时，GET `/api/ops/state` 在watchdog首次检查起15分钟宽限内应保持unknown（不是setup green）；逾宽限仍无首样后，后续独立cron须暴露 `watchdog.status=stale` 和 `bootstrap_overdue=true`，不能永久以空库unknown掩盖监测未建立。未登录/普通用户拒绝；允许的session admin或bootstrap才能读；ingest token不能读；所有API错误与成功都 `no-store`、无CORS。缺binding/迁移明确503。先验收这些，再启用collector。

D1历史full快照保留24h、摘要历史30d、事件/修订90d，由独立scheduled执行清理；**当前最后head记录及其full快照是例外，不受24h payload清理或30d历史删除门限限制，直到新head取代它**。这样长期失联后仍有最后一次采样可供排查，但旧head必须继续显示陈旧/未知观察，保留内容不等于fresh或业务健康。配置声明不是清理已执行证明。Cron变更传播可能需数分钟，官方上限说明为15分钟；必须以实际Worker scheduled记录和界面时间核验，不能仅看config。

## 5. 拉取main后的collector配置与首次启动（Claude执行）

必须先完成第1.1节的停用安装、真实快照追加和一致性验收，并在main-merge成功后让真实CODE拉取新main，才进入本节。两项unit已在合并前安装，本节不重复覆盖已观察的单元；若现场内容发生变化，重新实读并按原门禁核对，不沿用旧观察冒充一致。

需要支持 `LoadCredential` 的 systemd；安装包的 `ExecStart` 使用 systemd 249 官方支持的 `${CREDENTIALS_DIRECTORY}/ops_ingest_token` 路径形式（见 [systemd 249 凭据说明](https://www.freedesktop.org/software/systemd/man/249/systemd.exec.html#Credentials)），不使用该版本不支持的 `%d`。目标机实际版本仍需现场核对。默认 `User=ubuntu`，CODE/DATA 上只需只读权限；systemd对业务目录只读，唯一持久运行输出为 `/run/trade-ops-monitor`。不授予 sudo、不允许对业务DB目录加 ReadWritePaths。

### 5.1 systemd 249 兼容补修：复验既有45对快照

本修复只更正安装包和canonical的凭据路径。基底 `2514b9a30952b100e835f28f0eda335fbe369cf0` 已包含Claude实读追加的45对快照；其中监控service仍是旧 `%d/ops_ingest_token`。父侧已观察该service的 `LoadState=bad-setting`，systemd 249 parser报 `Invalid slot`，且没有启动记录；这些是修复前事实，不得用新安装包内容覆盖快照来伪装已观测。

Claude在授权部署窗口按下列顺序复验，期间不启动collector、不启用timer：

1. 留存修复前版本、已安装unit字节/哈希、`systemd-analyze verify` 原始输出/rc、`LoadState=bad-setting` 和 `ExecMainStartTimestamp/ExecMainExitTimestamp` 无启动记录的实读回执；先核实现场仍与该基线一致。
2. 对修复包执行真实249隔离parser正负控；应用修复后的service并 `daemon-reload`，保持timer disabled/inactive、service不启动。重新实读已安装unit及service的 `LoadState/ActiveState/SubState/Result/ExecMainStatus/ExecMainStartTimestamp/ExecMainExitTimestamp`；必须确认 `LoadState=loaded`、`ActiveState=inactive`，无启动记录，并留存timer仍停用的证据。parser通过或loaded本身均不证明collector运行成功。
3. 将实际unit字节/哈希、systemd版本、parser输出/rc和上述状态连同 `observed_at` 留为观察回执。只有这些事实齐备后，才以实读内容更新仓库快照中**既有监控service段**的实际观测；保留其余44对和既有timer段，不重复执行第1.1节的88段断言，不再次追加service/timer，不重建整份快照。本次作者不修改实际snapshot。
4. 在实读更新前，新canonical/install与实际snapshot暂有监控service的 `ExecStart` 字段差异，现有 `--dump ... --check-doc` 门禁应如实报差异并返回非零，阻断放行。不得 `--align-doc` 退回旧路径、跳过/弱化门禁或先伪造snapshot。实读回执与单段更新完成后，再跑第1.1节现有四方一致检查并逐条记录rc；全部差异解决后才进入后续流程。

### 5.2 collector配置与首次启动

在目标云端用安全文件传输把**同一 ingest token**交给 Claude；传输方式沿用已有私有通道，本文不粘贴 SSH/连接参数。`worker-secrets.json` 和 admin token不应复制给 collector。

```bash
cd /home/ubuntu/code/trade-data-signal
INGEST_TOKEN_SOURCE="$HOME/.local/state/trade-ops-deploy/ingest.token"
sudo install -d -m 0700 -o root -g root /etc/trade-ops-monitor
sudo install -m 0600 -o root -g root "$INGEST_TOKEN_SOURCE" /etc/trade-ops-monitor/ingest.token
```

配置目录示例权限需允许 `ubuntu` 读取非敏感 JSON（目录0700 root会阻断，因此在写入完成后使用下列组读目录策略）；token仍root0600，systemd管理器通过 LoadCredential 复制到只读私有credential目录。collector接受owner-only0400/0600且owner是当前uid或root的普通非symlink文件。`${CREDENTIALS_DIRECTORY}/ops_ingest_token` 由 systemd 在 `ExecStart` 中展开，只作路径参数，不暴露值。

```bash
sudo chgrp ubuntu /etc/trade-ops-monitor
sudo chmod 0750 /etc/trade-ops-monitor
sudo install -m 0640 -o root -g ubuntu ops/monitoring/collector.example.json /etc/trade-ops-monitor/collector.json
sudo install -m 0600 -o root -g root /dev/null /etc/trade-ops-monitor/collector.env
```

Claude 编辑私有 `collector.json`，实际 schema示例：

```json
{
  "collector_id": "cloud-main",
  "code_root": "/home/ubuntu/code/trade-data-signal",
  "data_root": "/home/ubuntu/code/trade-data",
  "output_dir": "/run/trade-ops-monitor",
  "ingest_url": "https://ss.fx8.store/api/ops/ingest",
  "secret_file": "/etc/trade-ops-monitor/ingest.token",
  "total_timeout_seconds": 20,
  "command_timeout_seconds": 3,
  "schedule_max_age_seconds": 1800,
  "publication_head_url": null
}
```

`--token-file ${CREDENTIALS_DIRECTORY}/ops_ingest_token` 覆盖 JSON secret_file，故ubuntu不直接读取root的源token。JSON和 EnvironmentFile 不含秘密值。`collector.env` 可仅保存下列非敏感覆盖；缺文件或缺JSON必须启动失败，禁止自动回退生产默认配置。

```ini
OPS_CODE_ROOT=/home/ubuntu/code/trade-data-signal
OPS_CONFIG=/etc/trade-ops-monitor/collector.json
```

需要其他用户名/目录时，Claude通过systemd drop-in覆盖 `User/Group`、`EnvironmentFile`、`LoadCredential` 源路径、`OPS_CODE_ROOT/OPS_CONFIG` 并同步实际 JSON。注意 `EnvironmentFile`/`LoadCredential` 覆盖用原生unit规则，不依赖环境变量在这些指令里展开；清空旧 LoadCredential后再设新值。`ReadWritePaths` 保持只允许自己的运行目录；若改输出目录必须同步 RuntimeDirectory/相应安全策略并重新验收。不要编辑 canonical安装包来塞现场路径。

```bash
sudo systemd-analyze verify /etc/systemd/system/trade-ops-monitor.service /etc/systemd/system/trade-ops-monitor.timer
sudo systemctl daemon-reload
sudo systemctl start trade-ops-monitor.service
sudo systemctl show trade-ops-monitor.service --property=LoadState,ActiveState,SubState,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp
```

首轮手动启动会采集并向 OPS ingest POST（会产生正常控制面记录），只在 Claude 审批后的生产执行；它不跑业务采集或真实发信。核验本地私有 `snapshot.json/report.json` 和已认证state中 snapshot_id/时间对应、checks覆盖与unknown原因、无路径/argv/env/日志体泄漏。完成首轮验收后再启用 timer：

```bash
sudo systemctl enable --now trade-ops-monitor.timer
sudo systemctl show trade-ops-monitor.timer --property=LoadState,ActiveState,LastTriggerUSec,NextElapseUSecRealtime
```

service不设自动 Restart；systemd oneshot不并发，collector总预算默认20s/最大25s，unit超时240s，避免5分钟轮堆积。CPU25%、MemoryHigh192M/Max256M、TasksMax32；实际资源结果仍须观察。磁盘/配置/权限/网络失败不得被吞成ok。PrivateTmp/ProtectSystem不应阻断只读systemctl/DB/元数据；若遇不可读先显示unknown并核对权限，不能放开业务写权限“修绿”。

## 6. 默认只读验证与启用验收

```bash
python3 ops/monitoring/verify_deployment.py
python3 ops/monitoring/verify_deployment.py --worker-config "$OPS_CANDIDATE"
python3 ops/monitoring/verify_deployment.py --origin https://ss.fx8.store --admin-token-file "$OPS_PRIVATE/admin.token"
```

默认无网络、无凭据读取、不启进程/collector。`--origin` 明确启用有限固定 GET，仅访问state/history/events/knowledge/incidents；不访问ingest、incident写端点或scheduled触发器。不会跟随redirect转发token，不使用环境代理，不打印响应体/secret/URL/异常细节。HTTP只读探针不发送真实告警、不改业务。

返回码：1=已证实契约/配置失败或fresh快照中的warning/critical；2=unknown/证据不全；0=证据全部充分。独立cron与实际timer只靠GET无法证明，因此本版正常只读验证仍可返回2，不能把2改为0或略过未证项。即使全API200，缺采样/过期/时钟漂移/空checks/缺观察时间/未知check都不判绿；已知critical优先保留。该工具不替代Claude在目标环境的人工部署验收。

完整验收至少包含：

- canonical↔install字节一致、实际collector --help参数匹配、缺配置非零退出。
- 默认watchdog scope下，service/schedule/data等业务checks即便告警也只有事件、通知为 `owned_by_existing_chain` suppressed；collector stale/fresh事件才可进入通知outbox。配置all的本地反例要证明是显式开关，不能默认扩大。
- 授权/普通用户/未登录/ingest与admin隔离；private no-store/no-CORS；公开HTML不含私有快照。
- 两次5min采样与独立Worker cron均实际发生；D1新库可读写、历史/事件幂等去重、人工修订乐观冲突保护。
- 停collector的失联演练应先在本地smoke中完成；生产演练如需做，由Claude单独安排并保持真实通知关闭。unknown、stale、critical不能以“已发信”关闭。
- 真实通知仍为可选：只有用户/Claude显式启用 `OPS_ALERT_ENABLED=true` 并私下配置批准host的HTTPS `OPS_ALERT_WEBHOOK` 后才允许；默认 `OPS_ALERT_SCOPE=watchdog`，只通知collector失联/恢复。后续启用或调整scope时，先配置所需secret，再把实际开关同步到根 `wrangler.jsonc` 的版本化vars，审核合并后从该source部署并验证。不能只在CF控制台临时改vars，否则下次main部署可能覆盖；不用`--keep-vars`代替配置对账。业务事件必须保留且以 `owned_by_existing_chain` suppressed 可见，不新增业务通知。显式 `all` 必须由Claude先审核与旧链的故障域/实例/恢复去重。启用前审查已有outbox积压/重试记录，防旧事件集中投递；本轮测试不发送真实消息。

## 7. 不丢数据库的回滚

1. **暂停写入**：`sudo systemctl disable --now trade-ops-monitor.timer`，随后 `sudo systemctl stop trade-ops-monitor.service`。不要删输出文件来制造“已恢复”，不要移除业务任务。
2. **关闭真实通知与独立cron**：在私有回滚候选配置中令 `OPS_ALERT_ENABLED=false`、`OPS_ALERT_SCOPE=watchdog`，只移除本次新增 `*/15 * * * *` watchdog cron，保留所有原有cron/绑定。若部署前本来就有相同表达式，不能机械移除共享cron，交Claude按原配置恢复。由Claude显式deploy回滚候选，并将同样的非密钥vars/cron回滚同步到版本化根配置、审核合并，防下次自动deploy重新启用；保留OPS_DB绑定和资源。Cron删除同样有传播延时，不能仅停collector后假定不会触发失联告警。
3. 必要时回滚 Worker 到已记录的先前版本，保留回滚前候选、版本与私有证据；既有业务API/session/assets要按原基线验收。Worker代码回滚不等于数据库迁移逆转，也不保证cron配置一同撤回，单独核对。
4. **保留 OPS_DB 资源、迁移表、事件和人工修订**。不执行 d1 delete、不删迁移、不TRUNCATE、不将其改绑业务库。停止scheduled后保留期清理也暂停，历史暂时超过原保留窗属于暂停状态，交Claude评估容量，不自动删除。
5. 原生数据库备份与隔离恢复演练按下一节执行；保持umask077，不放静态资源/R2/public仓。不能以面板数据导出替代数据库备份，也不能以导出成功代替恢复成功。
6. 重新启用时先核对兼容迁移/secret一致、告警关闭、fresh首次采样、独立cron，再启timer；旧事件不会自动关闭人工incident，旧D1证据不被baseline覆盖。

## 8. D1原生数据库备份与隔离恢复演练（Claude执行）

面板 `/api/ops/export` 是**分页流式运维记录数据导出**，不是SQLite/D1一致性数据库备份，不承诺直接还原数据库。数据库备份使用原生 `wrangler d1 export`，恢复须实测到独立新D1。

Claude记录源数据库ID、schema/迁移版本、导出时间和恢复点要求。需要可比一致恢复点时，先按回滚步骤停collector、关闭告警并只移除本次watchdog cron，等待传播并核对写入静止；不能在并发写入时拿两个时点的计数误判损坏。原生逻辑导出仍须恢复演练，不因命令exit0直接关闭备份风险。

```bash
umask 077
node node_modules/wrangler/bin/wrangler.js d1 export OPS_DB --remote \
  --config "$OPS_CANDIDATE" --output "$OPS_PRIVATE/ops-db-backup.sql"
python3 - "$OPS_PRIVATE/ops-db-backup.sql" <<'PY'
import hashlib, sys
from pathlib import Path
p = Path(sys.argv[1]); p.chmod(0o600)
print(hashlib.sha256(p.read_bytes()).hexdigest())
PY
node node_modules/wrangler/bin/wrangler.js d1 create trade-ops-restore-drill --config "$OPS_CANDIDATE"
```

只把新的演练UUID加到**私有演练配置**，binding为 `OPS_RESTORE_DRILL_DB`，与OPS_DB/FUND_SCORE_DB ID均不同。此配置只用于D1命令，**禁止deploy该演练配置到生产Worker**：

```bash
read -r -p 'NEW isolated restore-drill database UUID: ' OPS_DRILL_DATABASE_ID
OPS_DRILL_CONFIG="$OPS_CANDIDATE_DIR/wrangler.ops.restore-drill.json"
python3 - "$OPS_CANDIDATE" "$OPS_DRILL_CONFIG" "$OPS_DRILL_DATABASE_ID" <<'PY'
import json, os, re, sys
from pathlib import Path
sys.path.insert(0, str(Path('ops/monitoring').resolve()))
from configure import loads_jsonc
cfg = loads_jsonc(Path(sys.argv[1]).read_text()); identifier = sys.argv[3].lower()
assert re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', identifier)
assert all(str(d.get('database_id', '')).lower() != identifier for d in cfg['d1_databases'])
assert not any(d.get('binding') == 'OPS_RESTORE_DRILL_DB' for d in cfg['d1_databases'])
cfg['d1_databases'].append({'binding': 'OPS_RESTORE_DRILL_DB',
  'database_name': 'trade-ops-restore-drill', 'database_id': identifier})
fd = os.open(sys.argv[2], os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    json.dump(cfg, f, indent=2); f.flush(); os.fsync(f.fileno())
PY
node node_modules/wrangler/bin/wrangler.js d1 execute OPS_RESTORE_DRILL_DB --remote \
  --config "$OPS_DRILL_CONFIG" --file "$OPS_PRIVATE/ops-db-backup.sql"
node node_modules/wrangler/bin/wrangler.js d1 execute OPS_RESTORE_DRILL_DB --remote \
  --config "$OPS_DRILL_CONFIG" --command "SELECT name,type FROM sqlite_master WHERE type IN ('table','index','trigger') ORDER BY type,name"
node node_modules/wrangler/bin/wrangler.js d1 execute OPS_RESTORE_DRILL_DB --remote \
  --config "$OPS_DRILL_CONFIG" --command "SELECT COUNT(*) AS runs FROM ops_runs; SELECT COUNT(*) AS revisions FROM ops_incident_revisions; SELECT COUNT(*) AS events FROM ops_events"
```

验收隔离库的表/索引/触发器/迁移记录、各表计数、最新snapshot主键/时间、人工修订revision链及JSON可解析性，与冻结恢复点源库/备份元数据对比。不得为演练执行真实webhook；不将演练库接生产路由，也不向旧OPS_DB反向导入试错。演练结果和SQL哈希保存在私有证据，检验实际恢复而非只有导出大小。

真正灾难恢复时，Claude在另一个全新恢复D1导入并验收，保持collector/cron暂停，审核只变更OPS_DB的新UUID、保留旧库和回退配置，再按首次采样→cron→timer顺序恢复。恢复、重绑和演练库清理由Claude另案执行；任何回滚都不删除OPS_DB。

## 官方依据

- [D1 migrations及migrations_dir](https://developers.cloudflare.com/d1/reference/migrations/)
- [Cron Triggers配置、UTC与传播](https://developers.cloudflare.com/workers/configuration/cron-triggers/)
- [Worker secrets、部署副作用及secrets-file](https://developers.cloudflare.com/workers/configuration/secrets/)
- [版本化非密钥环境变量](https://developers.cloudflare.com/workers/configuration/environment-variables/)
- [Wrangler命令](https://developers.cloudflare.com/workers/wrangler/commands/)

本包只实现安装材料和读验证，不替Claude执行生产操作，也不把面板/API可用直接等同业务健康。
