# 安全实施计划 · 架构评审五大问题治理

> 编写：Codex (o3)
> 日期：2026-08-26
> 前置文档：`docs/architecture/tech-stack-review-20260826.md`、`docs/perf/perf-architecture-review-20260826.md`、`docs/perf/performance-architecture-standards.md`

---

## 〇、全局约束（适用于所有 Phase）

### 硬性规则

1. **任何改动前必须先建分支**，禁止在 main 上直接 commit。
2. **每个 Phase 结束后跑完整 smoke test**（桌面冷/热 + 移动冷/热 + SW enabled/blocked），结果落档。
3. **每个 Phase 必须有回滚方案并实际演练过**，不能只写在纸上。
4. **改动顺序严格按本文档执行**，不能跳步。后一步依赖前一步验证通过。
5. **每次部署后 30 分钟内手动检查线上状态**：R2 产物存在、Worker 响应正常、SW 更新成功、无 console error。

### 分支策略

```bash
# 每个 Phase 独立分支，验证通过后 squash merge 到 main
git switch -c codex/phase-0-security
# 验证通过后：
git checkout main
git merge --squash codex/phase-0-security
git commit -m "phase-0: 安全止血..."
# 不 push，由用户确认后统一 push
```

### 回滚通用流程

```bash
# 任何 Phase 出问题，30 秒内回滚：
git checkout main
git reset --hard <phase开始前的main HEAD>
# 然后执行一次 deploy
```

---

## 一、Phase 0 · P0 安全 + 原子写统一（0-3 天）

### 1.1 P0：轮换 plist 明文 Secret

**问题**：`scripts/deploy.sh` 和 launchd plist 中 `PURGE_SECRET` 以明文存储。

**具体步骤**：

#### 步骤 1：生成新 Secret

```bash
# 在终端执行（非脚本，必须手动）
NEW_SECRET=$(openssl rand -hex 32)
echo "新 secret: $NEW_SECRET"
# 立即保存到安全位置（密码管理器或 Keychain）
```

#### 步骤 2：更新 Cloudflare Worker Secret

```bash
# 登录 Cloudflare Dashboard → Workers & Pages → trade-data-signal → Settings → Variables
# 删除旧 PURGE_SECRET，新增同名 Variable，值设为 $NEW_SECRET
# ⚠️ 必须在本机脚本更新前完成，否则 deploy 失败
```

#### 步骤 3：更新 .env（本地）

```bash
# 编辑 .env 文件（已在 .gitignore 中）
PURGE_SECRET=$NEW_SECRET
# ⚠️ 不要把 .env 加入 git
```

#### 步骤 4：更新 deploy.sh 模板

```bash
# deploy.sh 只从 .env 读取，不硬编码 —— 验证一下：
grep -n 'PURGE_SECRET' scripts/deploy.sh
# 确认只在注释或 source .env 处出现，不在代码中赋值
```

#### 步骤 5：验证

```bash
# 手动跑一次 deploy，确认 purge 正常：
bash scripts/deploy.sh 2>&1 | grep -i purge
# 预期看到 purge 成功日志
```

#### 回滚方案

如果新 secret 不工作：
1. Cloudflare Dashboard 改回旧 secret
2. .env 恢复旧值
3. 重新 deploy

#### ⚠️ 风险提醒

- **必须**在 Cloudflare 更新 secret 后才能跑 deploy，否则 purge 全部失败
- 建议在非交易时段执行（收盘后）
- 执行后把旧 secret 标记为已废弃

---

### 1.2 原子写统一

**问题**：多个脚本用 `json.dump(f)` 直接覆盖写 JSON，断电/crash 会损坏文件。

**已有的原子写实现**（可以直接复用）：

- `scripts/agent_inbox_watcher.py:125` — `atomic_write_signal()`
- `scripts/alert_ack.py:42` — `_save_atomic()`
- `scripts/codex_review_claims.py:40` — `_atomic_write_json()`
- `scripts/export_etf_hist.py:75` — `_atomic_write_json()`

**方案**：抽取一个通用的 `scripts/atomic_json.py` 模块，所有需要写 JSON 的地方导入它。

#### 步骤 1：创建通用模块

```python
# scripts/atomic_json.py
import json, os, tempfile
from pathlib import Path

def atomic_json_dump(data, path, ensure_ascii=False, separators=None):
    """原子写 JSON：先写 .tmp，再 rename，防止半成品损坏。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp', prefix=path.stem + '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=ensure_ascii, separators=separators)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise
```

#### 步骤 2：需要改的文件（共 13 处 json.dump）

| 文件 | 行号 | 当前写法 | 改法 |
|---|---|---|---|
| `scripts/fetch_news.py` | 616, 619 | `json.dump(digest, f, ...)` | 改为 `atomic_json_dump(digest, path)` |
| `scripts/simulate_trade.py` | 1970, 1972, 2152, 2263 | `json.dump(..., f, ...)` | 改为 `atomic_json_dump(..., path)` |
| `scripts/lab/lab_retest.py` | 485 | `json.dump(output, f, ...)` | 改为 `atomic_json_dump(output, path)` |
| `scripts/export_notifications.py` | 397 | `json.dump(out, f, ...)` | 改为 `atomic_json_dump(out, path)` |
| `scripts/schedule_monitor.sh` | 183 | `json.dumps(state)` 写 shell | 改为调用 `python3 -c "from atomic_json import ..."` 或改 Python 调用 |

#### 步骤 3：schedule_monitor.sh 特殊处理

`schedule_monitor.sh` 是 bash 脚本，不能直接 import Python。两种方案选一：

- **方案 A（推荐）**：在 shell 里调用 Python：
  ```bash
  python3 -c "
  import sys; sys.path.insert(0, 'scripts')
  from atomic_json import atomic_json_dump
  import json
  atomic_json_dump(json.loads('''$(cat state_json)'''), '$STATE_FILE')
  "
  ```
- **方案 B**：把 `save_alert_state()` 改成写 `.tmp` 再 `mv`，纯 bash 实现：
  ```bash
  save_alert_state() {
      local tmp="${ALERT_STATE_FILE}.tmp.$$"
      python3 -c "import json; json.dump($1, open('$tmp','w'), ensure_ascii=False, indent=2)"
      mv -f "$tmp" "$ALERT_STATE_FILE"
  }
  ```

#### 步骤 4：验证

```bash
# 单元测试：断电模拟（kill -9 中断写入）
python3 -c "
from scripts.atomic_json import atomic_json_dump
import json, os, signal, subprocess, tempfile
# 先写一个正常文件
atomic_json_dump({'test': 1}, '/tmp/test_atomic.json')
assert json.load(open('/tmp/test_atomic.json')) == {'test': 1}
# 模拟中断：fork 子进程写入，然后 kill
# 如果文件被损坏，原子写方案需要调整
print('atomic write basic test PASS')
"
```

#### 回滚方案

改回原来的 `json.dump` 即可。每个文件都是独立的，可以逐个回滚。

#### ⚠️ 风险提醒

- `os.replace()` 在 macOS/Linux 上是原子的，Windows 上不一定——但本项目只部署在 macOS，没问题
- `tempfile.mkstemp` 会创建临时文件，如果磁盘满了会失败——但这是极端场景
- `schedule_monitor.sh` 的改造需要特别小心，它是调度核心

---

### 1.3 Pin 依赖版本

**问题**：Wrangler 用 `@latest`，Node 只约束 LTS，Python 依赖只有下限。

#### 步骤 1：Pin Wrangler

```bash
# 在 package.json 中加入
npm install wrangler@3.114.5 --save-exact
# 验证
npx wrangler --version  # 应输出 3.114.5
```

#### 步骤 2：Python 依赖 lock file

```bash
# 生成精确版本 lock file
pip freeze > requirements-lock.txt
# 在 requirements.txt 顶部加注释说明要配合 lock file 使用
```

#### 步骤 3：Node 版本锁定

```bash
# 如果还没有 .nvmrc，创建一个
node -v > .nvmrc
# 验证
cat .nvmrc  # 例如 v22.8.0
```

#### 步骤 4：验证

```bash
# 确认 wrangler 版本固定
grep wrangler package.json  # 应该看到具体版本号而非 ^latest

# 确认 Python lock file 存在
wc -l requirements-lock.txt
```

#### 回滚方案

删除 `requirements-lock.txt` 和 `.nvmrc`，package.json 中 wrangler 版本改回 `*`。

---

### 1.4 Phase 0 完整验收清单

```bash
# 1. Secret 已轮换
grep -c 'YOUR_OLD_SECRET' scripts/deploy.sh  # 应为 0

# 2. 原子写已部署
python3 -c "from scripts.atomic_json import atomic_json_dump; print('OK')"

# 3. 依赖已 pin
cat .nvmrc
grep wrangler package.json
test -f requirements-lock.txt && echo "lock exists"

# 4. 功能 smoke test
# 手动跑一次完整采集+部署流程
bash scripts/deploy.sh

# 5. 回滚演练
git stash  # 暂存改动
# 手动在 R2 删一个文件，确认旧代码能恢复
git stash pop
```

---

## 二、Phase 1 · 性能止血（1-2 周）

### 2.1 Boot 摘要化（最高 ROI）

**问题**：`boot.json` 的 `overview.signals_today` 有 463 条信号，每条内嵌 ETF 明细，序列化约 1.075MB。

#### 步骤 1：定义 boot-v2 协议

```json
{
  "schemaVersion": 2,
  "generatedAt": "2026-08-26T20:00:00",
  "overview": {
    "signals_today": [
      {
        "id": "20260826_sh_1",
        "index": "sh",
        "type": "buy",
        "score": 85.3,
        "etf_count": 12,
        "etf_top1": {
          "code": "510300",
          "name": "沪深300ETF",
          "track_score": 92.1
        },
        "detail_url": "/r2/data/signals/20260826_sh_1.json"
      }
    ]
  }
}
```

关键改动：
- 每条信号只保留 `id`、`type`、`score`、`etf_count`、`etf_top1`
- 明细通过 `detail_url` 懒加载
- `schemaVersion` 字段区分新旧协议

#### 步骤 2：后端改造

```python
# 在生成 boot.json 的脚本中（通常是 scripts/gen_boot.py 或类似）
def make_signal_summary(signal, detail_path):
    """从完整信号提取摘要字段。"""
    etfs = signal.get('etfs', [])
    top1 = max(etfs, key=lambda e: e.get('track_score', 0)) if etfs else None
    return {
        'id': signal['id'],
        'index': signal['index'],
        'type': signal['type'],
        'score': signal['score'],
        'etf_count': len(etfs),
        'etf_top1': {'code': top1['code'], 'name': top1['name'], 'track_score': top1['track_score']} if top1 else None,
        'detail_url': f'/r2/data/signals/{signal["id"]}.json'
    }
```

#### 步骤 3：前端兼容方案（关键！）

```javascript
// static-site/app.js 中处理 boot 数据
function parseSignals(ov) {
  if (!ov || !ov.signals_today) return [];
  return ov.signals_today.map(sig => {
    // v2: 只有摘要，ETF 明细需要懒加载
    if (sig.detail_url && !sig.etfs) {
      return { ...sig, etfs: [], _needsDetail: true };
    }
    // v1: 完整数据（兼容旧 boot.json）
    return sig;
  });
}

// 用户展开信号卡时才加载明细
async function loadSignalDetail(sig) {
  if (!sig._needsDetail) return sig;
  const detail = await fetchJSON(sig.detail_url);
  return { ...sig, etfs: detail.etfs, _needsDetail: false };
}
```

#### 步骤 4：过渡期策略（2 周）

```
第 1 周：boot-v2 生成脚本上线，同时生成 boot.json（旧）和 boot-v2.json（新）
         前端代码同时支持 v1 和 v2（检测 schemaVersion）
第 2 周：前端默认请求 boot-v2.json，boot.json 作为 fallback
第 3 周：确认无问题后，停止生成 boot.json
```

#### 步骤 5：验证

```bash
# 生成新旧两版 boot，对比大小
python3 scripts/gen_boot.py --output data/boot.json
python3 scripts/gen_boot.py --output data/boot-v2.json --schema-version 2
ls -la data/boot.json data/boot-v2.json
# boot-v2 应该比 boot.json 小 30-40%

# 前端加载测试
# 1. 用旧 boot.json → 前端正常（v1 路径）
# 2. 用新 boot-v2.json → 前端正常（v2 路径）
# 3. 展示的信号数量一致
# 4. 展开 ETF 明细能正常加载
```

#### 回滚方案

1. 前端删除 v2 检测代码，回退到只消费 v1
2. 后端停止生成 boot-v2.json
3. `git revert` 对应 commit

#### ⚠️ 风险提醒

- **这是 breaking change**，必须有过渡期
- 旧 shell（Service Worker 缓存的 HTML）拉新 boot 时，前端必须能处理
- 详细 URL 的 R2 路径必须在部署前创建好，否则 404
- **PARITY 测试必须通过**：新旧 boot 展示的信号列表、ETF top1、计数必须完全一致

---

### 2.2 移动 Skeleton 固定高度（CLS 治理）

**问题**：移动 CLS 实测 1.11-1.34，根因是 skeleton 高度不匹配实际内容。

#### 步骤 1：测量真实高度

```bash
# 在线上环境用 Playwright 测量各区块真实高度
# 已有探针：scripts/playwright-accept/perf_arch_probe.mjs
node scripts/playwright-accept/perf_arch_probe.mjs --device iPhone13 --output /tmp/cls-baseline.json
```

#### 步骤 2：修改 CSS skeleton

```css
/* static-site/style.css 中 */
/* 移动端 skeleton 高度必须匹配真实内容 */
@media (max-width: 768px) {
  .overview-skeleton {
    /* AI 预测卡 */
    height: 280px;  /* 实测值，不是猜测 */
  }
  .overview-signals-skeleton {
    /* 信号网格，3 行 × N 列 */
    min-height: 450px;
  }
  .overview-kpi-skeleton {
    /* KPI 行 */
    height: 120px;
  }
}

/* 关键：禁止内容到达后在视口上方插入新块 */
#content {
  contain: layout paint;
}
```

#### 步骤 3：TradingView 固定高度

```css
.tradingview-widget-container {
  aspect-ratio: 16/9;  /* 或具体比例 */
  /* 不要让 widget 自己动态调整高度 */
}
```

#### 步骤 4：验证

```bash
# 再跑一次 CLS 测量
node scripts/playwright-accept/perf_arch_probe.mjs --device iPhone13 --output /tmp/cls-after.json
# CLS 应该从 1.11 降到 < 0.10
```

#### 回滚方案

删除新增的 skeleton 高度规则，CLS 会回到旧状态但不会崩溃。

---

### 2.3 Phase 1 完整验收清单

```bash
# 1. Boot 摘要化
ls -la data/boot.json data/boot-v2.json  # 两版都存在
# 前端 v1/v2 兼容测试

# 2. CLS 改善
node scripts/playwright-accept/perf_arch_probe.mjs --device iPhone13
# CLS < 0.10

# 3. 数据 Parity
# 新旧 boot 展示的信号数量、ETF top1、计数完全一致

# 4. 回滚演练
git stash  # 回退改动
# 确认旧 boot 仍然正常工作
git stash pop
```

---

## 三、Phase 2 · 缓存策略统一 + 可靠性（2-4 周）

### 3.1 Cache Policy Manifest

**问题**：Worker/SW/R2 三层缓存策略各自为政。

#### 步骤 1：创建 cache-policy.json

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-08-26T20:00:00",
  "policies": {
    "boot-v2.json": {
      "type": "daily-derived",
      "worker": "stale-while-revalidate=600",
      "sw": "network-first",
      "r2": "ttl=3600"
    },
    "signals/*.json": {
      "type": "critical-realtime",
      "worker": "no-cache",
      "sw": "network-first",
      "r2": "ttl=0"
    },
    "kelly/*.json": {
      "type": "daily-derived",
      "worker": "stale-while-revalidate=3600",
      "sw": "network-first",
      "r2": "ttl=86400"
    },
    "*.min.js": {
      "type": "versioned-asset",
      "worker": "immutable",
      "sw": "cache-first",
      "r2": "immutable"
    }
  }
}
```

#### 步骤 2：生成 Worker headers

```python
# scripts/gen_cache_headers.py
import json

policy = json.load(open('cache-policy.json'))
for path_pattern, config in policy['policies'].items():
    # 根据 config.worker 生成对应的 HTTP header
    # 写入 worker/headers.js 的对应规则
    pass
```

#### 步骤 3：生成 SW 策略

```javascript
// 从 cache-policy.json 生成 sw.js 的策略分支
// ⚠️ 不要手动改 sw.js，从 manifest 生成
```

#### ⚠️ SW 改动的特殊风险控制

**这是全场最高危操作**，必须分三步走：

```
第 1 步：只改 Worker headers（服务端，可控）
第 2 步：SW 加一个 debug 模式（?sw_debug=1 走新策略，否则走旧策略）
第 3 步：观察 1 周后，SW 默认走新策略
```

**回滚方案**：
1. Worker headers：立即回滚（服务端）
2. SW：发一个空的 sw.js 更新，强制所有客户端清缓存

---

### 3.2 通知 Outbox（可靠性）

**问题**：通知发送失败可能被提前去重。

#### 步骤 1：定义 outbox 状态机

```
pending → sending → sent / failed
                                    ↓ retry (3次)
                                  dead-letter
```

#### 步骤 2：修改 schedule_monitor.sh

```bash
# 在 send_severe_email 函数中：
# 1. 先写 outbox 状态为 pending
# 2. 发送邮件
# 3. 成功 → 标记 sent
# 4. 失败 → 标记 failed，3 次后 dead-letter
```

#### 步骤 3：去重逻辑修改

```bash
# 旧逻辑：发送前就进入去重状态
# 新逻辑：只有 sent 才进入去重状态，failed/pending 不去重
```

---

### 3.3 Phase 2 完整验收清单

```bash
# 1. Cache policy manifest 存在且有效
python3 -m json.tool cache-policy.json

# 2. Worker headers 与 manifest 一致
# 对比 worker/headers.js 和 cache-policy.json 的 TTL 值

# 3. SW 策略验证
# ?sw_debug=1 走新策略，否则走旧策略

# 4. 通知 outbox 状态机测试
# 模拟发送失败 → 状态为 failed → 重试 → sent

# 5. 回滚演练
```

---

## 四、Phase 3 · 运行时重构（1-2 月，推迟到 Phase 1-2 跑稳后）

### ⚠️ 前置条件

- Phase 1 的 boot 摘要化已上线 2 周且无问题
- Phase 2 的 CI 门禁已跑稳 1 个月
- 当前 CLS < 0.10，LCP 有改善

### 4.1 路由模块化（渐进）

**不要一次性拆 app.js**，按以下顺序：

```
第 1-2 周：拆说明文本和报告正文（低频，不影响核心路由）
第 3-4 周：拆低频弹窗（导出对话框、帮助页面）
第 5-8 周：拆 route module（overview/market/sentiment/fund/lab）
```

### 4.2 Chart Registry

```javascript
// 引入 LRU 缓存，控制图表实例数量
const chartRegistry = new Map();
const MAX_CHARTS = 20;

function getChart(id, option) {
  if (chartRegistry.has(id)) {
    chartRegistry.get(id).setOption(option);
    return chartRegistry.get(id);
  }
  if (chartRegistry.size >= MAX_CHARTS) {
    const oldest = chartRegistry.keys().next().value;
    chartRegistry.get(oldest).dispose();
    chartRegistry.delete(oldest);
  }
  const chart = echarts.init(document.getElementById(id));
  chart.setOption(option);
  chartRegistry.set(id, chart);
  return chart;
}
```

---

## 五、全局风险管理矩阵

| 风险 | 概率 | 影响 | 缓解措施 | 触发回滚条件 |
|---|---|---|---|---|
| SW 策略变更导致数据过期 | 中 | 高 | 分步灰度 + debug 模式 | 用户报告数据不更新 |
| Boot breaking change | 高 | 高 | 2 周过渡期 + schemaVersion | 前端白屏或数据缺失 |
| Kelly shard manifest 上传失败 | 低 | 高 | 自动降级到最近分片 + 告警 | Lab 弹窗白屏 |
| 原子写 rename 失败（磁盘满） | 极低 | 中 | 写入前检查磁盘空间 | 写入失败日志 |
| CI 门禁误报阻塞部署 | 中 | 低 | 例外清单 + owner 签字 | 无正当理由连续 3 次失败 |
| Phase 3 迁移引入新 bug | 高 | 中 | 先拆低频模块 + parity 测试 | 功能回归或性能下降 |

---

## 六、执行顺序总结

```
第 1 天  secret 轮换（P0，必须手动）
         + pin 依赖（wrangler + requirements-lock + .nvmrc）

第 2-3 天 创建 scripts/atomic_json.py
         + 改造 4 个脚本的 json.dump
         + schedule_monitor.sh alert_state 改原子写
         + 功能 smoke test

第 4-5 天 boot-v2 摘要化方案设计文档（不改代码，先出方案）
         + 移动 skeleton 固定高度 + CLS 测试
         + CI 门禁脚本 artifact_budget_check.mjs（boot.json < 250KB）

第 1-2 周 boot-v2 实施 + parity 测试
          + 过渡期：v1/v2 兼容

第 2-3 周 cache-policy.json 建立 + Worker headers 对齐
          （SW 延后到观察期后）

第 3-4 周 SW 策略灰度（?sw_debug=1）
          + 通知 outbox 状态机

Phase 3（Vite/TS）推迟到 CI 门禁跑稳 1 个月后
DuckDB/Parquet 暂不启动
```

---

## 七、给 Claude Code 的执行指令（直接复制）

```
请按 docs/architecture/safe-implementation-plan.md 执行 Phase 0：

1. 轮换 P0 secret（步骤 1.1）
2. 创建 scripts/atomic_json.py（步骤 1.2）
3. 改造 json.dump 为原子写（步骤 1.2 的文件清单）
4. Pin 依赖（步骤 1.3）
5. 每个改动独立 commit，禁止在 main 上操作
6. 所有改动完成后跑完整验收清单（步骤 1.4）
7. 回滚演练通过后，报告给用户确认
```
