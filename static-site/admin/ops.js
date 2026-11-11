/* Private, dependency-free ops client. Credentials and private responses live in memory only. */
(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const TITLES = { overview: ['概览', '运行概览', '把当前观察与历史证据分开看。'], services: ['服务与定时器', '服务与定时器', '看执行状态，也保留业务健康的未知。'], data: ['数据与发布', '数据与交付', '数据、发布、备份和资源，各自按证据对账。'], architecture: ['架构与知识库', '架构与知识库', '从版本化目录导航到依赖、合同和来源。'], incidents: ['问题与跟进', '问题与跟进', '修复、根因、部署、验收与观察，分轴记录。'], history: ['采集与事件', '采集与事件', '区分检查变化、恢复事件与实际投递。'] };
  const GROUPS = { pending_review: '待复核', investigating: '调查', repair_pending: '修复', awaiting_verification: '待验', observing: '观察', scoped_verified: '已限定验收', not_replayable: '不可回放', mixed_historical_disposition: '混合历史处置' };
  const WORKFLOW = { unknown: '未知', open: '待处理', investigating: '调查中', repairing: '修复中', in_progress: '处理中', blocked: '受阻', verification: '待验', observing: '观察中', closed: '已关闭（有证据）', accepted_risk: '已接受风险', not_replayable: '不可回放' };
  const VERIFICATION = { unknown: '未知', unverified: '未验证', pending: '待验证', failed: '验证失败', scoped_pass: '限定通过', verified: '已验证', passed: '通过' };
  const OBSERVATION = { unknown: '未知', pending: '待观察', not_started: '尚未开始', observing: '观察进行中', observed: '已有观察证据', passed: '观察通过', complete: '观察完成' };
  const KINDS = { host: '主机', repository: '仓库', service: '服务', task: '任务', data: '数据', monitor: '监控', alert_rule: '告警规则', surface: '展示入口', external: '外部服务', edge: '关系', incident: '问题' };
  const FRESHNESS_MINUTES = 30;
  const FRESHNESS_MS = FRESHNESS_MINUTES * 60 * 1000;
  const STATUS = { ok: 'OK', warning: '警告', critical: '严重', unknown: '未知', fresh: '采集新鲜', stale: '采集过期', failed: '失败', baseline: '版本基线' };
  // Exact product messages only (ops_monitor.py and ops state/watchdog). Raw evidence stays unchanged.
  const SUMMARIES = new Map(Object.entries({
    'Natural invocation not verified; execution health remains unknown': '尚未取得完整的自然执行证据；执行健康仍未知。',
    'Recovery invocation not verified; original problem remains open': '尚未证实新的自然执行成功；原问题保持未关闭。',
    'Current invocation business evidence; scope and expiry apply': '本轮业务证据；只对声明的对象和有效期负责。',
    'Local R2 request evidence only; current public content and delivery deadline are not verified': '仅检查本地逐请求队列；待处理数量与等待时间见详情，当前线上内容和交付期限尚未验证。',
    'Registered unit not observed as loaded': '未观察到已登记单元成功加载，状态未知。',
    'Systemd reports failed; business impact not evaluated': '系统报告执行失败；业务影响尚未核实。',
    'Registered timer is not active': '已登记的定时器当前未启用。',
    'Timer scheduling state only; job outcome is separate': '仅反映定时器调度状态；任务执行结果需另查。',
    'Unit is executing; this is not completed business validation': '服务正在执行；尚不代表业务验收完成。',
    'Oneshot last systemd run succeeded; data correctness not checked': '一次性任务最近执行成功；尚未检查数据是否正确。',
    'Oneshot previous run was not successful': '一次性任务上次执行未成功。',
    'Inactive oneshot has no trusted completion record': '一次性任务当前未运行，且没有可信的完成记录。',
    'Unit state has no implemented success criterion': '当前单元状态尚无可用的成功判定规则，结果未知。',
    'Collection unavailable; source not assumed healthy': '采集未完成；不能据此认定数据源正常。',
    'Registered and installed unit sets compared': '已核对登记单元与实际安装单元；差额见证据。',
    'Installed unit enumeration unavailable': '无法获取已安装单元清单，覆盖情况未知。',
    'Systemd property collection unavailable': '无法采集系统服务属性，运行状态未知。',
    'Historical coverage catalogue unavailable; fixed asset groups still reported': '历史覆盖目录不可用；仍列出固定资产组。',
    'Fixed asset metadata observed; content correctness and business freshness unknown': '已看到固定资产的文件信息；内容是否正确、业务数据是否及时仍未知。',
    'Asset content unverified; fixed source absent or outside lightweight scope': '资产内容未验证；固定来源缺失或超出本次轻量检查范围。',
    'Asset observation budget unavailable': '受采集时限限制，未完成资产检查。',
    'Derived schedule input age only; not market or asset freshness': '仅检查调度统计输入的新旧；不代表行情或资产数据及时。',
    'Derived schedule input unavailable': '调度统计输入不可用。',
    'No current trusted derived execution verdict': '暂无可信的当前执行结论。',
    'Derived exit evidence conflicts; not auto-resolved': '执行退出证据存在冲突；未自动消解。',
    'Existing schedule producer reports a missed execution': '现有调度统计报告漏执行，需核对原始证据。',
    'Existing schedule producer reports an anomaly; details withheld': '现有调度统计报告异常；本面板未展示日志详情。',
    'Existing schedule producer reports an unfinished round': '现有调度统计报告一轮执行尚未完成。',
    'Scheduled unit is running; completion not yet observed': '调度任务正在运行；尚未观察到执行完成。',
    'Scheduled round completed after derived snapshot; data correctness not checked': '调度轮次已在统计快照之后完成；尚未检查数据是否正确。',
    'Scheduled round failed according to current systemd evidence': '当前系统执行证据确认本轮失败。',
    'Unfinished scheduled round has no verified completion': '本轮尚缺有效的执行完成证据；保留待确认状态。',
    'Trusted derived execution verdict; no business data validation': '已取得可信来源的执行结论；尚未验证业务数据。',
    'Default local backup metadata only; remote copy and restore validity unknown': '仅检查默认本地备份的文件信息；远端副本和可恢复性仍未知。',
    'Default local backup observation unavailable': '默认本地备份检查未完成。',
    'Backup ledger exists; remote objects and restoration not verified': '备份台账存在；远端对象和恢复能力尚未验证。',
    'Filesystem free capacity only; workload health is separate': '仅反映磁盘剩余容量；业务运行情况需另查。',
    'Point memory availability; no trend inference': '仅反映当前可用内存；未判断变化趋势。',
    'Point system load only': '仅反映当前系统负载。',
    'Actual registry contract loaded without importing its generator': '已读取实际任务注册表；未运行生成器。',
    'External content and deployed event membership are not inferred from local metadata': '仅凭本地文件信息，无法确认线上内容及已发布事件是否齐全。',
    'Coverage exceeded bounded snapshot capacity': '检查数量超出单次快照容量；存在未覆盖项。',
    'HTTPS HEAD transport observation only; content correctness unknown': '仅检查 HTTPS 连通性；内容是否正确仍未知。',
    'Publication transport observation unavailable': '发布连通性检查未完成。',
    'Optional transport probe skipped to preserve upload budget or collect-only mode': '为保留上传时间或处于仅采集模式，未执行可选连通性检查。',
    'Not present in latest snapshot coverage; not a recovery': '最新快照未覆盖此检查；不代表已经恢复。',
    'Missing from latest snapshot; coverage unknown; not a recovery': '最新快照缺少此检查，覆盖情况未知；不代表已经恢复。',
    'Observation expired; not a recovery': '观察证据已过期；不代表已经恢复。',
    'Collector snapshot overdue; data freshness unknown': '采集快照已超时；数据是否及时仍未知。',
    'Collector freshness changed; not incident closure': '采集新旧状态发生变化；不代表故障已经关闭。'
  }));
  const unitNameIndexes = new WeakMap();
  const state = {
    token: '', authorized: false, locked: false, epoch: 0, loadSeq: 0, job: null, controllers: new Set(),
    timer: null, paused: false, interval: 30000, view: 'overview', query: '', status: 'all',
    data: {}, errors: {}, records: [], recordMap: new Map(), incidents: [], revisions: [],
    graphFocus: null, selectedRecord: null, edit: null, saving: false, exporting: false,
    serverOffset: 0, lastUpdated: null, hasStateError: false, toastTimer: null, exportURLs: new Set()
  };

  function node(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function append(parent, ...children) {
    for (const child of children.flat()) if (child != null) parent.append(child);
    return parent;
  }
  const list = value => Array.isArray(value) ? value : [];
  const object = value => value && typeof value === 'object' && !Array.isArray(value);
  const known = value => value !== undefined && value !== null && value !== '' && value !== 'unknown';
  function text(value) {
    if (!known(value)) return 'unknown';
    return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
  }
  function brief(value, length = 100) { const s = text(value); return s.length > length ? s.slice(0, length) + '…' : s; }
  function time(value) {
    if (!known(value)) return '时间未知';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? text(value) : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(d);
  }
  function fullTime(value) {
    const d = new Date(value);
    return !known(value) || Number.isNaN(d.getTime()) ? 'unknown' : d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) + ' +08:00';
  }
  function ago(value) {
    const n = Date.parse(value);
    if (!Number.isFinite(n)) return '时间未知';
    const seconds = Math.max(0, Math.floor((Date.now() + state.serverOffset - n) / 1000));
    return seconds < 60 ? seconds + ' 秒前' : seconds < 3600 ? Math.floor(seconds / 60) + ' 分钟前' : Math.floor(seconds / 3600) + ' 小时前';
  }
  function badge(value, label) {
    const cls = Object.hasOwn(STATUS, value) ? value : 'unknown';
    return node('span', 'badge ' + cls, label || STATUS[value] || text(value));
  }
  function button(label, onClick, className = 'button compact') {
    const b = node('button', className, label); b.type = 'button'; b.addEventListener('click', onClick); return b;
  }
  function empty(title, description = '') { return append(node('div', 'empty'), node('strong', '', title), description ? node('span', '', description) : null); }
  function notice(message, type = '') { return node('div', 'notice ' + type, message); }
  function safeURL(value) {
    try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : null; } catch { return null; }
  }
  function safeEvidenceURL(value) {
    const safe = safeURL(value);
    if (!safe) return null;
    const u = new URL(safe);
    return !u.search && u.hostname !== 'localhost' && !u.hostname.endsWith('.localhost') && !/^[\d.]+$/.test(u.hostname) && !u.hostname.includes(':') && !/\/(tmp|private|Users|home|root)\//.test(u.pathname) ? safe : null;
  }
  function safeStatusText(value, max = 160) {
    return typeof value === 'string' && !!value.trim() && value.length <= max && !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value) && !/(?:\/(?:tmp|private|Users|home|root|etc|var)\/|[A-Za-z]:\\|\.env\b|Bearer\s+\S+|https?:\/\/|-----BEGIN|[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:token|password|secret|webhook)\s*[:=])/i.test(value);
  }
  function sourceValue(record, key) {
    if (known(record[key])) return record[key];
    for (const obs of list(record.observations)) {
      if (object(obs.record) && known(obs.record[key])) return obs.record[key];
      if (known(obs[key])) return obs[key];
    }
    return undefined;
  }
  function summaryOf(value) { return SUMMARIES.get(value) || value; }
  function checkName(check) {
    if (check.id === 'business:public-fund') return '公募日更 · 业务证据';
    if (check.id === 'business:fof-nav') return 'FOF 净值 · 业务证据';
    const record = state.recordMap.get(check.id);
    if (record?.kind === 'data' && known(record.name)) return record.name;
    let names = unitNameIndexes.get(state.records);
    if (!names) {
      names = new Map();
      for (const task of state.records) {
        const unit = sourceValue(task, 'unit'), name = sourceValue(task, 'name');
        if (task.kind !== 'task' || typeof unit !== 'string' || typeof name !== 'string' || !/[\u3400-\u9fff]/.test(name)) continue;
        names.set(unit, names.has(unit) && names.get(unit) !== name ? null : name);
      }
      unitNameIndexes.set(state.records, names);
    }
    const unit = typeof check.id === 'string' && /^(cloud-service|cloud-timer):/.test(check.id) ? check.id.slice(check.id.indexOf(':') + 1) : sourceValue(check, 'unit');
    const timer = typeof unit === 'string' && unit.endsWith('.timer');
    const taskName = names.get(unit) || (timer ? names.get(unit.replace(/\.timer$/, '.service')) : null);
    return taskName ? taskName + (timer ? ' · 定时器' : '') : check.name || record?.name || check.id || '未命名检查';
  }
  function nameOf(record) { return record.kind === 'service' ? checkName(record) : record.name || record.id || '未命名记录'; }
  function matches(value) {
    return !state.query || text(value).toLocaleLowerCase().includes(state.query);
  }
  function sourceTime(record) { return sourceValue(record, 'observed_at') || sourceValue(record, 'source_inventory_time') || sourceValue(record, 'last_verified_at'); }
  function detailsButton(record) {
    const wrap = node('div'); append(wrap, button(nameOf(record), () => showRecord(record), 'link-button'), node('span', 'record-id mono', record.id)); return wrap;
  }
  function table(headers, rows, emptyLabel = '当前范围内没有记录') {
    if (!rows.length) return empty(emptyLabel, state.query || state.status !== 'all' ? '可尝试清除搜索或筛选。' : '没有记录不等于没有故障，请核对覆盖范围。');
    const t = node('table'); const head = node('thead'); const tr = node('tr'); headers.forEach(h => tr.append(node('th', '', h))); head.append(tr); t.append(head);
    const body = node('tbody');
    for (const cells of rows) { const row = node('tr'); cells.forEach((cell, i) => { const td = node('td', i === 0 ? 'title-cell' : ''); td.append(cell instanceof Node ? cell : node('span', '', text(cell))); row.append(td); }); body.append(row); }
    t.append(body); return append(node('div', 'table-wrap'), t);
  }
  function pairs(values) {
    const dl = node('dl', 'key-value');
    values.forEach(([label, value]) => append(dl, node('dt', '', label), append(node('dd'), value instanceof Node ? value : node('span', '', text(value)))));
    return dl;
  }
  function toast(message) {
    clearTimeout(state.toastTimer); $('toast').textContent = message; $('toast').hidden = false;
    state.toastTimer = setTimeout(() => { $('toast').hidden = true; $('toast').textContent = ''; }, 4000);
  }

  class HTTPError extends Error { constructor(status, payload) { super('HTTP ' + status); this.status = status; this.payload = payload; } }
  function clearTimer() { clearTimeout(state.timer); state.timer = null; }
  function abortAll() { for (const c of state.controllers) c.abort(); state.controllers.clear(); }
  function cancelRefresh() { if (state.job) state.job.controller.abort(); state.job = null; state.loadSeq += 1; clearTimer(); }
  function clearPrivate(message, style = '') {
    state.epoch += 1; state.loadSeq += 1; abortAll(); clearTimer(); state.job = null;
    state.authorized = false; state.locked = true; state.token = ''; state.data = {}; state.errors = {}; state.benefitCursor = '';
    state.records = []; state.recordMap.clear(); state.incidents = []; state.revisions = [];
    state.graphFocus = null; state.selectedRecord = null; state.edit = null; state.saving = false;
    state.hasStateError = false; state.lastUpdated = null; state.serverOffset = 0;
    for (const url of state.exportURLs) URL.revokeObjectURL(url); state.exportURLs.clear();
    document.querySelectorAll('.private-content').forEach(n => n.replaceChildren());
    for (const id of ['detail-dialog', 'edit-dialog']) if ($(id).open) $(id).close();
    for (const id of ['freshness', 'knowledge-meta', 'graph-caption', 'refresh-note', 'auth-mode']) $(id).replaceChildren();
    for (const id of ['knowledge-kind', 'incident-group']) $(id).replaceChildren(new Option(id === 'knowledge-kind' ? '全部类型' : '全部分组', 'all'));
    $('global-notice').textContent = ''; $('global-notice').hidden = true;
    $('search-input').value = ''; state.query = ''; $('status-filter').value = 'all'; state.status = 'all';
    $('admin-token').value = ''; $('toast').hidden = true; $('toast').textContent = ''; clearTimeout(state.toastTimer);
    $('private-shell').hidden = true; $('private-shell').inert = true; $('auth-gate').hidden = false;
    $('auth-message').textContent = message; $('auth-message').className = 'notice ' + style;
    document.title = '运维工作台 · 私有';
  }
  async function request(path, options = {}, parentSignal) {
    const requestEpoch = state.epoch;
    const controller = new AbortController(); state.controllers.add(controller);
    const abort = () => controller.abort();
    if (parentSignal?.aborted) controller.abort(); else parentSignal?.addEventListener('abort', abort, { once: true });
    const timeout = setTimeout(abort, 15000);
    const headers = new Headers(options.headers || {});
    if (state.token) headers.set('X-Ops-Admin-Token', state.token);
    try {
      const response = await fetch(path, { ...options, headers, cache: 'no-store', credentials: state.token ? 'omit' : 'same-origin', mode: 'same-origin', redirect: 'error', signal: controller.signal });
      if (response.status === 401 || response.status === 403) {
        if (state.epoch === requestEpoch) clearPrivate(response.status === 403 ? '没有管理员权限，私有数据已清除。请使用管理员会话或管理员令牌。' : '管理员认证已失效，私有数据已清除。', 'error');
        throw new HTTPError(response.status, null);
      }
      if (!response.ok) {
        let payload = null;
        try { payload = await response.json(); } catch { /* An HTML error is not private state. */ }
        throw new HTTPError(response.status, payload);
      }
      if (options.asBlob) return await response.blob();
      return await response.json();
    } finally {
      clearTimeout(timeout); state.controllers.delete(controller); parentSignal?.removeEventListener('abort', abort);
    }
  }
  function errorMessage(error) {
    if (error instanceof HTTPError) {
      if (error.status === 503) return '服务尚未配置就绪或暂不可用（503）';
      if (error.status === 404) return '接口尚未提供（404）';
      if (error.status === 409) return '记录版本冲突（409）';
      return '请求未完成（' + error.status + '）';
    }
    return error?.name === 'AbortError' ? '请求取消或超时' : '连接失败或响应无法解析';
  }
  function schedule() {
    clearTimer();
    if (!state.authorized || state.locked || state.paused || document.hidden || state.saving) return;
    state.timer = setTimeout(() => refresh(), state.interval);
  }
  function setBusy() {
    $('refresh-button').disabled = !!state.job || state.saving;
    $('export-button').disabled = state.exporting || !state.authorized;
    $('pause-button').textContent = state.paused ? '继续' : '暂停';
    $('pause-button').setAttribute('aria-pressed', String(state.paused));
    $('refresh-note').textContent = state.job ? '正在更新…' : state.paused ? '已暂停自动刷新' : document.hidden ? '后台暂停' : state.lastUpdated ? '本页更新 ' + time(state.lastUpdated) : '';
  }
  function normaliseKnowledge(payload) {
    state.records = list(payload?.records).filter(r => object(r) && typeof r.id === 'string');
    state.recordMap = new Map(state.records.map(r => [r.id, r]));
    const old = $('knowledge-kind').value;
    $('knowledge-kind').replaceChildren(new Option('全部类型', 'all'));
    [...new Set(state.records.map(r => r.kind || 'unknown'))].sort().forEach(k => $('knowledge-kind').add(new Option(KINDS[k] || k, k)));
    $('knowledge-kind').value = [...$('knowledge-kind').options].some(o => o.value === old) ? old : 'all';
  }
  function normaliseIncidents(payload) {
    state.incidents = list(payload?.incidents).filter(object).map(r => ({ ...r, ...(object(r.effective) ? r.effective : object(r.override) ? r.override : {}), baseline: r.baseline, override: r.override, revision: r.revision }));
    state.revisions = list(payload?.revisions);
    const old = $('incident-group').value;
    $('incident-group').replaceChildren(new Option('全部分组', 'all'));
    const groups = new Set(state.incidents.map(incidentGroup));
    [...groups].sort().forEach(k => $('incident-group').add(new Option(groupLabel(k), k)));
    $('incident-group').value = [...$('incident-group').options].some(o => o.value === old) ? old : 'all';
  }
  async function refresh(forceKnowledge = false) {
    if (state.job || state.locked || state.saving) return;
    clearTimer();
    const job = { controller: new AbortController(), seq: ++state.loadSeq, epoch: state.epoch };
    state.job = job; setBusy();
    const paths = { benefits: '/api/ops/benefits' + (state.benefitCursor ? '?study_after=' + encodeURIComponent(state.benefitCursor) : ''), state: '/api/ops/state', history: '/api/ops/history?limit=60', events: '/api/ops/events?limit=100', incidents: '/api/ops/incidents' };
    if (!state.data.knowledge || forceKnowledge) paths.knowledge = '/api/ops/knowledge';
    const keys = Object.keys(paths);
    try {
      const results = await Promise.allSettled(keys.map(key => request(paths[key], {}, job.controller.signal)));
      if (state.epoch !== job.epoch || state.loadSeq !== job.seq) return;
      const stateResult = results[keys.indexOf('state')];
      if (!state.authorized && stateResult.status !== 'fulfilled') {
        $('auth-message').textContent = errorMessage(stateResult.reason) + '。未显示任何私有数据；可稍后重新连接。';
        $('auth-message').className = 'notice warning'; return;
      }
      results.forEach((result, i) => {
        const key = keys[i];
        if (result.status === 'fulfilled') { state.data[key] = result.value; delete state.errors[key]; }
        else state.errors[key] = errorMessage(result.reason);
      });
      if (stateResult.status === 'fulfilled') {
        state.hasStateError = false;
        const server = Date.parse(state.data.state?.server_time);
        state.serverOffset = Number.isFinite(server) ? server - Date.now() : 0;
      } else state.hasStateError = true;
      state.authorized = true; state.lastUpdated = new Date().toISOString();
      if (paths.knowledge && !state.errors.knowledge) normaliseKnowledge(state.data.knowledge);
      if (!state.errors.incidents) normaliseIncidents(state.data.incidents);
      $('auth-gate').hidden = true; $('private-shell').hidden = false; $('private-shell').inert = false;
      $('auth-mode').textContent = state.token ? '临时管理员连接' : '管理员会话';
      renderAll();
    } finally {
      if (state.job === job) { state.job = null; setBusy(); schedule(); }
    }
  }
  function connect(token = '') {
    clearPrivate('正在验证管理员权限…');
    state.token = token; state.locked = false; state.paused = false;
    $('admin-token').value = ''; refresh(true);
  }
  function freshness() {
    const s = state.data.state;
    if (state.hasStateError || !s?.latest) return 'unknown';
    const stamp = Date.parse(s.latest.collected_at);
    if (!Number.isFinite(stamp) || !['fresh', 'stale'].includes(s.collector_status)) return 'unknown';
    if (s.collector_status === 'stale' || Date.now() + state.serverOffset - stamp > FRESHNESS_MS) return 'stale';
    return 'fresh';
  }
  function currentChecks() {
    return [...list(state.data.state?.latest?.checks).filter(object), ...list(state.data.state?.missing_checks).filter(object).map(c => ({ ...c, _missing: true }))];
  }
  function liveStatus(check) { return !check._missing && freshness() === 'fresh' && ['ok', 'warning', 'critical', 'unknown'].includes(check.status) ? check.status : 'unknown'; }
  function checkDisplay(check) {
    const running = freshness() === 'fresh' && !check._missing && check.observation_status === 'observed' && check.status === 'unknown' && check.evidence?.execution_state === 'running';
    const display = append(node('div'), badge(liveStatus(check), running ? '运行中（待完成）' : check._missing ? '未覆盖 · 未知' : undefined));
    if (check.problem_open === true) display.append(node('div', 'small muted', '此前问题未证实恢复'));
    if (check.evidence?.source_reason) display.append(node('div', 'small muted', evidenceReason(check.evidence.source_reason)));
    return display;
  }
  function evidenceReason(reason) {
    return ({ metadata_only: '只有文件信息，内容待验证', fixed_source_not_configured: '尚未接入固定证据源',
      receipt_missing: '缺少本轮业务回执', receipt_invalid: '回执无法校验', code_ref_mismatch: '代码版本不匹配',
      invocation_not_verified: '未能对应当前运行', invocation_running: '当前任务尚在运行', invocation_failed: '当前运行失败',
      business_failed: '业务结果失败', expired_or_invalid_time: '证据过期或时间不合法', business_date_mismatch: '业务日期不匹配',
      coverage_or_completion_unverified: '完成或覆盖范围未证实', hash_or_confirmation_missing: '内容哈希或发布确认缺失',
      generation_unverified: '主文件与扩展文件尚未证明属于同一轮生成',
      fund_collection_receipt_missing: '缺少本轮净值采集明细凭证',
      fund_metadata_incomplete: '净值采集凭证不完整',
      fund_collection_failed: '本轮净值采集出现异常',
      fund_publication_unverified: '已有采集阶段记录，尚未验证净值线上发布',
      pending_queue_not_configured: '尚未配置与发布任务一致的队列位置',
      inspection_incomplete: '队列检查不完整，不能按空队列处理',
      invalid_request_evidence: '请求记录或发布凭证损坏，需保留原件核查',
      pending_without_deadline_contract: '仍有请求待处理；尚无已确认的逐请求交付期限',
      no_pending_requests_observed: '未见逐请求待处理记录；不代表线上内容已验证',
      current_invocation_verified: '本轮证据已核对（仅限声明范围）', completion_not_observed: '尚未观察到完成',
      next_trigger_observed: '已观察到下一触发点', active_timer_next_not_observed: '定时器活动中，下一触发点未观察到'
    })[reason] || '证据待核查';
  }
  function visibleChecks(categories) {
    return currentChecks().filter(c => (!categories || categories.includes(c.category)) && (matches(c) || matches(checkName(c)) || matches(summaryOf(c.summary))) && (state.status === 'all' || liveStatus(c) === state.status));
  }
  function updateHeader() {
    const fresh = freshness(); const box = $('freshness'); box.replaceChildren();
    state.displayFreshness = fresh;
    append(box, badge(fresh), node('span', 'muted small', state.data.state?.latest ? '采集于 ' + time(state.data.state.latest.collected_at) + ' · ' + ago(state.data.state.latest.collected_at) : '尚无采集快照'));
    const errors = Object.entries(state.errors);
    $('global-notice').hidden = !errors.length && fresh === 'fresh';
    $('global-notice').className = 'notice warning';
    $('global-notice').textContent = errors.length ? errors.map(([key, value]) => key + '：' + value).join('；') + '。已保留的数据仅供历史参考，未完成的检查不按健康处理。' : fresh === 'stale' ? '采集已过期（新鲜度阈值 ' + FRESHNESS_MINUTES + ' 分钟）。下方保留最近证据，当前结果按未知显示；没有自动宣告恢复。' : fresh === 'unknown' ? '当前采集状态未知。缺少数据或配置不能按正常处理。' : '';
  }
  function renderLive(target, categories) {
    const checks = visibleChecks(categories);
    const rows = checks.map(c => {
      const title = append(node('div'), button(checkName(c), () => showCheck(c), 'link-button'), node('span', 'record-id mono', c.id));
      const statusCell = checkDisplay(c);
      if (freshness() !== 'fresh') statusCell.append(node('div', 'muted', '最近记录：' + (STATUS[c.status] || text(c.status))));
      return [title, statusCell, node('span', 'truncated', summaryOf(c.summary) || '未提供检查摘要'), time(c.observed_at), button('详情', () => showCheck(c))];
    });
    $(target).replaceChildren(table(['检查 / 稳定 ID', '当前状态', '摘要', '证据时间', ''], rows, currentChecks().length ? '当前筛选无匹配检查' : '尚无该范围的采集检查'));
    const missing = currentChecks().filter(c => c._missing && matches(c) && ['all', 'unknown'].includes(state.status));
    if (missing.length) {
      $(target).append(node('div', 'section-heading', '未在最新快照覆盖（全部分类）'), table(['先前检查', '当前状态', '最近记录', '原观察时间'], missing.map(c => [button(checkName(c), () => showCheck(c), 'link-button'), checkDisplay(c), STATUS[c.previous_status] || text(c.previous_status), time(c.observed_at)])));
    }
  }
  function renderBaseline(target, kinds) {
    const rows = state.records.filter(r => kinds.includes(r.kind) && matches(r) && (state.status === 'all' || state.status === 'unknown')).map(r => {
      const runtime = sourceValue(r, 'runtime');
      const raw = runtime ? text(runtime.ActiveState || runtime.active || 'unknown') : text(sourceValue(r, 'declaration_state') || r.evidence_status);
      return [detailsButton(r), node('span', 'small', raw), brief(sourceValue(r, 'schedule') || sourceValue(r, 'expected_frequency'), 90), time(sourceTime(r)), badge('unknown', '业务健康未核'), button('来源', () => showRecord(r))];
    });
    $(target).replaceChildren(node('p', 'count-note', '这里只展示版本化声明／历史观察，不自动映射为实时服务健康。' + (state.errors.knowledge ? ' 知识库更新未完成。' : '')), table(['记录', '声明 / 原始运行态', '调度 / 频次', '原始观察时间', '健康语义', ''], rows));
  }
  function metric(label, value, foot, cls = '') { return append(node('div', 'metric ' + cls), node('div', 'metric-label', label), node('div', 'metric-value', value), node('div', 'metric-foot', foot)); }
  function overviewLink(label, tab, value) { return button(label + '  ·  ' + value + ' →', () => setTab(tab), 'overview-link'); }
  function renderOverview() {
    const host = $('overview-content');
    const attentionOpen = host.querySelector('.attention-more')?.open || false;
    host.replaceChildren();
    const checks = currentChecks(); const f = freshness(); const counts = { ok: 0, warning: 0, critical: 0, unknown: 0 };
    checks.forEach(c => counts[liveStatus(c)]++);
    const metrics = node('div', 'metrics');
    append(metrics, metric('返回的跟踪检查', state.data.state?.latest ? checks.length : '—', f === 'fresh' ? '含未覆盖项 · 不等于全站覆盖' : '当前覆盖与健康尚待确认', 'accent'), metric('严重', counts.critical, f === 'fresh' ? '当前检查' : '过期时不沿用旧结论', 'bad'), metric('警告', counts.warning, '按检查维度计数', 'warn'), metric('未知', checks.length ? counts.unknown : '—', '含本次未覆盖项'), metric('已限定验收', state.errors.incidents ? '—' : state.incidents.filter(r => incidentGroup(r) === 'scoped_verified').length, '基线限定验收 · 不自动根治'));
    host.append(metrics);
    const coverage = state.data.state?.latest?.coverage;
    const coveragePanel = node('details', 'panel coverage-panel');
    const latestCount = state.data.state?.latest ? list(state.data.state.latest.checks).length : '未知';
    append(coveragePanel, node('summary', '', '检查 ' + latestCount + ' 项 · 未覆盖 ' + list(state.data.state?.missing_checks).length + ' 项（覆盖与限制详情）'));
    const labels = { checks: '检查', services: '服务', timers: '定时器', data: '数据', publication: '发布', backup: '备份', resource: '资源', monitor: '监控', service_checks: '服务检查', timer_checks: '定时器检查', data_checks: '数据检查', publication_checks: '发布检查', backup_checks: '备份检查', resource_checks: '资源检查', checks_returned: '返回检查数', checks_total: '检查总数', errors: '采集错误', failed_probes: '探测失败', skipped: '跳过', requested: '请求数量', completed: '完成数量', files: '文件', databases: '数据库', units: '单元', sql_checks: '数据库检查' };
    const countPairs = object(coverage?.counts) ? Object.entries(coverage.counts).map(([key, value]) => [labels[key] || key.replaceAll('_', ' '), value]) : [['本次覆盖计数', 'unknown']];
    coveragePanel.append(pairs([...countPairs, ['跟踪范围', state.data.state?.coverage?.tracked_checks], ['未覆盖列表截断', state.data.state?.coverage?.prior_list_truncated === true ? '是，当前列表不完整' : state.data.state?.coverage?.prior_list_truncated === false ? '否' : 'unknown']]));
    const limitations = list(coverage?.limitations);
    if (limitations.length) { const ul = node('ul', 'small muted'); limitations.forEach(l => ul.append(node('li', '', l))); coveragePanel.append(ul); }
    else coveragePanel.append(node('p', 'small muted', '未提供采集限制说明；不能默认完整覆盖。'));
    if (state.data.state?.coverage?.limitation) coveragePanel.append(node('p', 'small muted', state.data.state.coverage.limitation));
    const rawCoverage = node('details', 'evidence-item'); append(rawCoverage, node('summary', '', '原始覆盖字段'), node('pre', '', text({ snapshot: coverage, tracking: state.data.state?.coverage }))); coveragePanel.append(rawCoverage);
    const grid = node('div', 'overview-grid'); const attention = node('section', 'panel');
    append(attention, node('h2', '', '当前需要关注'), node('p', 'small muted', '先看检查证据，再判断业务影响。'));
    // Keep every urgent check visible; unknown remains in the preview and expandable list.
    const priority = { critical: 0, warning: 1, unknown: 2 };
    const flagged = visibleChecks().filter(c => liveStatus(c) !== 'ok')
      .sort((a, b) => priority[liveStatus(a)] - priority[liveStatus(b)]);
    const urgentCount = flagged.filter(c => ['critical', 'warning'].includes(liveStatus(c))).length;
    const previewCount = Math.max(8, urgentCount + 1);
    if (!flagged.length) attention.append(empty(checks.length && f === 'fresh' ? '当前筛选内没有非 OK 检查' : '当前证据不足', '只限已覆盖检查；仍需独立看业务交付与未知项。'));
    else {
      const activity = node('div', 'activity');
      const more = node('details', 'attention-more'); more.open = attentionOpen;
      more.append(node('summary', '', '查看全部关注项（共 ' + flagged.length + ' 项，另有 ' + Math.max(0, flagged.length - previewCount) + ' 项未知）'));
      const remaining = node('div', 'activity');
      flagged.forEach((c, index) => {
        const n = node('div', 'activity-item');
        append(n, checkDisplay(c), node('span', '', ' '), button(checkName(c), () => showCheck(c), 'link-button'), node('div', 'small muted', brief(summaryOf(c.summary), 160)));
        (index < previewCount ? activity : remaining).append(n);
      });
      attention.append(activity);
      if (flagged.length > previewCount) { more.append(remaining); attention.append(more); }
    }
    const context = node('section', 'panel'); append(context, node('h2', '', '交付与处置入口'), overviewLink('服务与定时器', 'services', currentChecks().filter(c => ['service', 'timer'].includes(c.category)).length + ' 项当前检查'), overviewLink('数据 / 发布 / 备份', 'data', '逐链对账'), overviewLink('知识库', 'architecture', state.records.length + ' 个版本记录'), overviewLink('问题与跟进', 'incidents', state.incidents.length + ' 项'), overviewLink('采集与告警投递', 'history', '历史 / 事件'));
    append(context, node('div', 'subtle-divider'), node('p', 'small muted', '声明、运行态、业务健康、根因状态各自保留；不会从静态基线自动生成绿色健康结论。'));
    append(grid, attention, context); host.append(grid, coveragePanel);
    const activity = node('section', 'panel'); activity.style.marginTop = '18px'; append(activity, node('div', 'section-heading'), node('h2', '', '最近事件'));
    const events = list(state.data.events?.events).slice(0, 5).filter(matches);
    if (!events.length) activity.append(empty('暂无可展示事件', '事件为空不代表采集或投递已正常。'));
    else events.forEach(e => activity.append(append(node('div', 'evidence-item'), button(eventName(e), () => showEvent(e), 'link-button'), node('span', '', ' '), deliveryBadge(e), node('p', 'small muted', time(eventTime(e))))));
    host.append(activity);
  }
  function incidentRevision(r) {
    if (Number.isSafeInteger(r.revision) && r.revision >= 0) return r.revision;
    const revisions = state.revisions.filter(v => (v.incident_id === r.id || v.id === r.id) && Number.isSafeInteger(v.revision));
    if (revisions.length) return Math.max(...revisions.map(v => v.revision));
    return 0;
  }
  function incidentGroup(r) {
    if (r.override && Object.hasOwn(r.override, 'workflow_status')) {
      return ({ unknown: 'unclassified', open: 'pending_review', investigating: 'investigating', repairing: 'repair_pending', in_progress: 'repair_pending', blocked: 'blocked', verification: 'awaiting_verification', observing: 'observing', closed: 'closed', accepted_risk: 'accepted_risk', not_replayable: 'not_replayable' })[r.override.workflow_status] || 'unclassified';
    }
    return sourceValue(r, 'workflow_group') || 'unclassified';
  }
  function groupLabel(group) { return GROUPS[group] || ({ blocked: '受阻', closed: '人工已关闭', accepted_risk: '已接受风险', unclassified: '未知 / 未分组' })[group] || group; }
  function renderIncidents() {
    const group = $('incident-group').value;
    const visible = state.incidents.filter(r => matches(r) && (group === 'all' || incidentGroup(r) === group) && (state.status === 'all' || state.status === 'unknown'));
    const rows = visible.map(r => {
      const groupCell = append(node('div'), badge('baseline', groupLabel(incidentGroup(r))));
      if (r.override) groupCell.append(node('div', 'small muted', '人工更新；基线：' + groupLabel(sourceValue(r.baseline || r, 'workflow_group') || 'unclassified')));
      return [detailsButton(r), groupCell, node('span', 'truncated', text(sourceValue(r, 'remediation_state'))), node('span', 'truncated', text(sourceValue(r, 'root_cause_state'))), node('span', 'truncated', text(sourceValue(r, 'verification_state'))), node('span', 'small', 'r' + incidentRevision(r)), button('详情 / 更新', () => showIncident(r))];
    });
    $('incidents-content').replaceChildren(node('p', 'count-note', visible.length + ' / ' + state.incidents.length + ' 项。此状态筛选按未独立核定业务健康处理，不把工作流分组当健康值。'), table(['问题 / 原 ID', '工作流', '修复', '根因', '验收', '修订', ''], rows, '当前筛选下没有问题记录'));
  }
  function countText(counts) {
    if (!object(counts)) return 'unknown';
    return ['ok', 'warning', 'critical', 'unknown'].filter(k => typeof counts[k] === 'number').map(k => (STATUS[k] || k) + ' ' + counts[k]).join(' / ') || text(counts);
  }
  function eventName(e) { return checkName({ id: e.check_id || e.id, name: e.name || e.check_name }) || '未命名事件'; }
  function eventTime(e) { return e.created_at || e.observed_at; }
  function delivery(e) {
    const value = e.delivery_status ?? (object(e.delivery) ? e.delivery.status : undefined);
    if (['sent', 'delivered'].includes(value)) return 'sent';
    if (['pending', 'retry', 'retrying', 'queued'].includes(value)) return 'pending';
    if (['failed', 'dead', 'exhausted'].includes(value)) return 'failed';
    if (value === 'suppressed' || value === 'disabled') return value;
    return 'unknown';
  }
  function deliveryBadge(e) { const key = delivery(e); return badge(key === 'sent' ? 'ok' : key === 'pending' ? 'warning' : key === 'failed' ? 'critical' : 'unknown', { sent: '已投递', pending: '待投递 / 重试', failed: '投递失败', suppressed: '按策略不投递', disabled: '投递未启用', unknown: '投递未知' }[key]); }
  function renderBenefits() {
    const host = $('benefits-content'); host.replaceChildren();
    const b = state.data.benefits;
    if (state.errors.benefits || !b?.configured) { host.append(empty('收益观察未配置', state.errors.benefits || '启用功能并迁移私有数据库后显示；原采集继续运行。')); return; }
    host.append(node('p', 'notice', '只做描述性比较，真实收益与归因尚未建立。登记、历史导入是人工声明；独立生产证据缺失时保持未就绪。'));
    if (!list(b.studies).length) host.append(node('p', 'muted', '未登记观察窗口，当前不可比较。'));
    for (const s of list(b.studies)) {
      const c = s.comparison || {}, panel = node('section', 'panel');
      panel.append(node('h3', '', s.study_id + ' · ' + ({ real: '真实测量', synthetic: '合成测量', unknown: '类型未知' }[s.measurement_kind] || '类型未知') + ' · ' + (c.status === 'ready' ? '描述性比较就绪' : '未就绪')));
      panel.append(node('p', 'small muted', '登记：' + s.registration_strength + '；证据：' + s.evidence_strength + '；窗口排除上线当日，取最近 10 前 / 10 后实际会话。'));
      const rows = ['before', 'after'].map(k => { const t = c[k]?.raw_totals || c[k]?.raw_totals_partial, r = c[k]?.rates; return [k === 'before' ? '上线前' : '上线后', [list(s[k]?.days)[0]?.date, list(s[k]?.days).at(-1)?.date].filter(Boolean).join(' 至 '), t?.denominator ?? 'unknown', t ? t.success + ' / ' + t.failure + ' / ' + t.unknown : 'unknown', r ? (r.known_outcome_coverage * 100).toFixed(1) + '%' : 'unknown', r ? (r.success_lower * 100).toFixed(1) + '%–' + (r.success_upper * 100).toFixed(1) + '%' : 'unknown']; });
      panel.append(table(['窗口', '会话', '分母', '成功 / 失败 / 未知', '已知覆盖', '成功逻辑区间'], rows, '待采样'));
      const delta = c.descriptive_change?.success_rate_change_percentage_points_bounds;
      panel.append(node('p', '', delta ? '成功率变化区间：' + delta.map(x => x.toFixed(2)).join(' 至 ') + ' 个百分点；不能自动归因。' : '缺项：' + list(c.not_ready_reasons).join('；')));
      panel.append(button('版本、混杂因素与完整比较', () => showGeneric('收益证据', s))); host.append(panel);
    }
    if (state.benefitCursor) host.append(button('返回首批观察窗口', () => { state.benefitCursor = ''; refresh(); }));
    if (b.next_study_after) host.append(button('更多观察窗口', () => { state.benefitCursor = b.next_study_after; refresh(); }));
    const chainNames = { market_signal_freeze_plan: '信号、冻结与计划', backtest_publish_consume: '回测、发布与消费', backup_isolated_restore: '备份与隔离恢复' };
    const strengths = { verified: '已验证', partial: '部分证据', unknown: '未知' };
    host.append(table(['链 / 会话', '成功 / 失败 / 未知', '证据强度', '预期', '截止时间', ''], list(b.records).map(r => [append(node('div'), node('strong', '', chainNames[r.chain_id] || '交付链'), node('div', 'small muted', r.session_date), node('div', 'small muted', { real: '真实测量', synthetic: '合成 · 不计真实收益', unknown: '类型未知 · 不可比较' }[r.measurement_kind] || '类型未知 · 不可比较')), r.evidence_conflict ? '结果冲突（已知失败 ' + (r.conflict_evidence?.failure ?? '未知') + '）' : [r.success, r.failure, r.unknown].map(x => x ?? '未知').join(' / '), r.evidence_conflict ? '证据冲突 · 不可比较' : strengths[r.strength] || '未知', r.expected ?? '未知', time(r.deadline_at), button('证据详情', () => showGeneric('交付证据与逻辑槽', r))]), '暂无可保存的交付证据'));
    const details = node('details', 'panel'); details.append(node('summary', '', '登记窗口 / 导入历史声明'));
    details.append(node('p', 'small muted', '粘贴 benefits-api 约定的 JSON。不可读取 URL 或文件；登记身份不可修改，导入不会自动升级为生产证明。私有导出包含保留证据。'));
    const form = node('form', 'benefits-form'), kind = document.createElement('select'); kind.setAttribute('aria-label', '收益登记类型'); kind.append(new Option('登记窗口', 'studies'), new Option('导入历史声明', 'import'));
    const input = document.createElement('textarea'); input.rows = 6; input.maxLength = 250000; input.setAttribute('aria-label', '收益登记 JSON'); input.autocomplete = 'off'; input.spellcheck = false;
    const submit = node('button', 'button', '保存私有声明'); submit.type = 'submit';
    form.append(kind, input, submit); form.addEventListener('submit', async event => {
      event.preventDefault(); if (state.saving || !state.authorized) return;
      let value; try { value = JSON.parse(input.value); } catch { toast('JSON 无法解析'); return; }
      state.saving = true; clearTimer(); submit.disabled = true;
      try { await request('/api/ops/benefits/' + kind.value, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Ops-Intent': 'update' }, body: JSON.stringify(value) }); input.value = ''; toast('声明已保存，证据强度与就绪状态另行核验。'); }
      catch (e) { if (state.authorized) toast(errorMessage(e)); }
      finally { state.saving = false; submit.disabled = false; if (state.authorized) refresh(); }
    }); details.append(form); host.append(details);
  }
  function renderHistory() {
    renderBenefits();
    const runs = list(state.data.history?.runs).filter(matches);
    const rows = runs.map(r => [append(node('div'), button(r.snapshot_id || '采集记录', () => showGeneric('采集记录', r), 'link-button')), time(r.collected_at), time(r.received_at), countText(r.counts), Number.isFinite(r.duration_ms) ? r.duration_ms + ' ms' : 'unknown']);
    $('history-content').replaceChildren(table(['快照 ID', '采集时间', '接收时间', '结果分布', '耗时'], rows, '尚无采集历史'));
    const filter = $('delivery-filter').value;
    const events = list(state.data.events?.events).filter(e => matches(e) && (filter === 'all' || delivery(e) === filter));
    const eventRows = events.map(e => [button(eventName(e), () => showEvent(e), 'link-button'), node('span', '', [e.previous_status, e.status].filter(known).join(' → ') || '状态字段未知'), deliveryBadge(e), time(eventTime(e)), button('事件证据', () => showEvent(e))]);
    $('events-content').replaceChildren(table(['事件', '状态变化（原始）', '投递', '事件时间', ''], eventRows, '当前范围没有告警事件'));
  }

  function edges() {
    const found = []; const seen = new Set();
    function add(source, target, relation, uncertain, record) {
      if (!source || !target) return;
      const key = source + '\u0000' + target + '\u0000' + relation;
      if (seen.has(key)) return; seen.add(key); found.push({ source, target, relation, uncertain, record });
    }
    for (const r of state.records) {
      if (r.kind === 'edge') add(sourceValue(r, 'source_id'), sourceValue(r, 'target_id'), sourceValue(r, 'relation') || '声明关系', !['runtime_observed', 'code_confirmed'].includes(r.evidence_status), r);
      else for (const dep of list(r.depends_on)) add(dep, r.id, '声明依赖', !['runtime_observed', 'code_confirmed'].includes(r.evidence_status), r);
    }
    return found;
  }
  function renderGraph() {
    const host = $('graph'); host.replaceChildren();
    if (!state.records.length) { host.append(empty('知识库尚未加载', '仅在管理员认证后获取版本化基线。')); $('graph-caption').textContent = ''; return; }
    const allEdges = edges(); const selected = new Set();
    if (state.graphFocus) {
      selected.add(state.graphFocus);
      allEdges.filter(e => e.source === state.graphFocus || e.target === state.graphFocus).forEach(e => { selected.add(e.source); selected.add(e.target); });
    } else {
      // Ontology only in public assets; all actual IDs arrive after admin auth.
      const quotas = { host: 1, repository: 2, task: 1, service: 1, data: 4, external: 2, surface: 1 };
      for (const r of state.records) if (quotas[r.kind] > 0) { selected.add(r.id); quotas[r.kind] -= 1; }
      for (const e of allEdges) if (selected.size < 22 && (selected.has(e.source) || selected.has(e.target))) { selected.add(e.source); selected.add(e.target); }
      if (!selected.size) state.records.filter(r => r.kind !== 'edge').slice(0, 18).forEach(r => selected.add(r.id));
    }
    const ids = [...selected].slice(0, 28); const positions = new Map(); const columns = [[], [], [], []];
    ids.forEach(id => { const kind = state.recordMap.get(id)?.kind; const column = ['host', 'external'].includes(kind) ? 0 : ['repository', 'task', 'service'].includes(kind) ? 1 : kind === 'data' ? 2 : 3; columns[column].push(id); });
    const height = Math.max(330, Math.max(...columns.map(c => c.length)) * 86 + 30); const width = 1000;
    columns.forEach((column, x) => column.forEach((id, y) => positions.set(id, { x: x * 245 + 16, y: y * 86 + 20 })));
    const ns = 'http://www.w3.org/2000/svg'; const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height); svg.setAttribute('aria-label', state.graphFocus ? '选中记录的一跳依赖图' : '架构主要记录与声明依赖');
    const defs = document.createElementNS(ns, 'defs'); const marker = document.createElementNS(ns, 'marker'); marker.setAttribute('id', 'ops-arrow'); marker.setAttribute('viewBox', '0 0 10 10'); marker.setAttribute('refX', '9'); marker.setAttribute('refY', '5'); marker.setAttribute('markerWidth', '5'); marker.setAttribute('markerHeight', '5'); marker.setAttribute('orient', 'auto'); const arrow = document.createElementNS(ns, 'path'); arrow.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z'); arrow.setAttribute('fill', '#8298aa'); marker.append(arrow); defs.append(marker); svg.append(defs);
    const shownEdges = allEdges.filter(e => positions.has(e.source) && positions.has(e.target)).slice(0, 65);
    for (const e of shownEdges) {
      const a = positions.get(e.source), b = positions.get(e.target); const path = document.createElementNS(ns, 'path');
      const ax = a.x + 213, ay = a.y + 28, bx = b.x, by = b.y + 28;
      path.setAttribute('d', 'M' + ax + ',' + ay + ' C' + (ax + 28) + ',' + ay + ' ' + (bx - 28) + ',' + by + ' ' + bx + ',' + by);
      path.setAttribute('class', 'graph-edge' + (e.uncertain ? ' candidate' : '')); path.setAttribute('marker-end', 'url(#ops-arrow)');
      const title = document.createElementNS(ns, 'title'); title.textContent = e.source + ' → ' + e.target + ' · ' + e.relation + (e.uncertain ? '（推断/计划/待证）' : '（版本声明，非运行验收）'); path.append(title); svg.append(path);
    }
    for (const id of ids) {
      const r = state.recordMap.get(id) || { id, name: id, kind: 'unknown', evidence_status: 'unknown', evidence: [] }; const p = positions.get(id);
      const g = document.createElementNS(ns, 'g'); g.setAttribute('class', 'graph-node' + (id === state.graphFocus ? ' selected' : '')); g.setAttribute('transform', 'translate(' + p.x + ',' + p.y + ')'); g.setAttribute('role', 'button'); g.setAttribute('tabindex', '0'); g.setAttribute('aria-label', '查看 ' + nameOf(r));
      const rect = document.createElementNS(ns, 'rect'); rect.setAttribute('width', '213'); rect.setAttribute('height', '57'); rect.setAttribute('rx', '7'); g.append(rect);
      const label = document.createElementNS(ns, 'text'); label.setAttribute('x', '11'); label.setAttribute('y', '23'); label.textContent = brief(nameOf(r), 19); g.append(label);
      const type = document.createElementNS(ns, 'text'); type.setAttribute('x', '11'); type.setAttribute('y', '43'); type.setAttribute('class', 'node-type'); type.textContent = (KINDS[r.kind] || r.kind) + ' · ' + brief(id, 26); g.append(type);
      const title = document.createElementNS(ns, 'title'); title.textContent = id; g.append(title);
      const open = () => { state.graphFocus = id; showRecord(r); };
      g.addEventListener('click', open); g.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } }); svg.append(g);
    }
    host.append(svg);
    $('graph-caption').textContent = (state.graphFocus ? '一跳视图：' + state.graphFocus + '。' : '主要记录总览。') + '显示 ' + ids.length + ' 个节点 / ' + shownEdges.length + ' 条关系；目录可搜索全部 ' + state.records.length + ' 条记录。图上的声明不等于运行成功。';
  }
  function renderKnowledge() {
    const k = state.data.knowledge;
    $('knowledge-meta').replaceChildren(append(node('div', 'baseline-meta'), badge('baseline'), node('span', 'small', '代码 ' + (k?.baseline_code_ref || 'unknown')), node('span', 'small muted', '版本观察：' + fullTime(k?.observed_at)), button('刷新版本基线', () => refresh(true))));
    const kind = $('knowledge-kind').value;
    const rows = state.records.filter(r => matches(r) && (kind === 'all' || r.kind === kind));
    const host = $('knowledge-list'); host.replaceChildren();
    if (!rows.length) host.append(empty('没有匹配的版本记录'));
    rows.forEach(r => { const b = button(nameOf(r), () => showRecord(r), r.id === state.graphFocus ? 'selected' : ''); b.append(node('span', 'mono', (KINDS[r.kind] || r.kind) + ' · ' + r.id)); host.append(b); });
    renderGraph();
  }

  function renderAll() {
    if (!state.authorized) return;
    updateHeader();
    switch (state.view) {
      case 'overview': renderOverview(); break;
      case 'services':
        renderLive('services-live', ['service', 'timer']);
        renderBaseline('services-baseline', ['service', 'task']);
        break;
      case 'data': {
        const category = $('data-category').value;
        renderLive('data-live', category === 'all' ? ['data', 'publication', 'backup', 'resource', 'monitor'] : [category]);
        renderBaseline('data-baseline', ['data', 'repository', 'external', 'surface']);
        break;
      }
      case 'architecture': renderKnowledge(); break;
      case 'incidents': renderIncidents(); break;
      case 'history': renderHistory(); break;
    }
    setBusy();
  }
  function setTab(tab) {
    if (!Object.hasOwn(TITLES, tab)) return;
    state.view = tab;
    document.querySelectorAll('[data-tab]').forEach(n => { if (n.dataset.tab === tab) n.setAttribute('aria-current', 'page'); else n.removeAttribute('aria-current'); });
    Object.keys(TITLES).forEach(key => { $('view-' + key).hidden = key !== tab; });
    const [label, title, desc] = TITLES[tab]; $('page-title').textContent = label; $('view-heading').textContent = title; $('view-description').textContent = desc;
    if (state.authorized) renderAll();
  }
  function openDetail(title, kicker) {
    $('detail-title').textContent = title; $('detail-kicker').textContent = kicker || ''; $('detail-body').replaceChildren();
    if (!$('detail-dialog').open) $('detail-dialog').showModal();
    return $('detail-body');
  }
  function evidenceBlock(evidence, fallbackTime) {
    const wrap = node('div');
    if (!list(evidence).length) return empty('未提供证据', '未知不会自动当作已验收。');
    list(evidence).forEach(e => {
      const div = node('div', 'evidence-item'); append(div, node('div', 'small muted', text(e.kind || '证据') + ' · ' + fullTime(e.observed_at || fallbackTime)));
      const location = text(e.location || e.evidence_url || '来源未知'); const url = safeURL(location); const ref = location.includes('#') ? location.slice(location.indexOf('#') + 1) : '';
      if (state.recordMap.has(ref)) div.append(button(location, () => showRecord(state.recordMap.get(ref)), 'link-button mono'));
      else if (url) { const a = node('a', 'mono', location); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; div.append(a); }
      else div.append(node('div', 'mono', location));
      if (e.note) div.append(node('p', 'muted small', e.note)); wrap.append(div);
    }); return wrap;
  }
  function showGeneric(title, value) {
    const host = openDetail(title, '原始结构化证据'); host.append(notice('保留原始字段与缺失项，不从结果标签推断业务健康。'), node('pre', '', text(value)));
  }
  function showCheck(check) {
    const host = openDetail(checkName(check), '实时采集 / ' + text(check.category));
    append(host, pairs([['稳定 ID', check.id], ['当前状态', checkDisplay(check)], ['最近记录值', STATUS[check.previous_status || check.reported_status || check.status] || check.previous_status || check.status], ['观察标记', check.observation_status], ['检查时间', fullTime(check.observed_at)], ['最新快照时间', fullTime(state.data.state?.latest?.collected_at)], ['摘要', summaryOf(check.summary)]]));
    append(host, pairs([['执行状态', ({running:'运行中', completed:'已完成', failed:'失败', scheduled:'等待触发', not_observed:'未观察到'})[check.evidence?.execution_state] || '未知'],
      ['证据说明', evidenceReason(check.evidence?.source_reason)], ['下一份所需证据',
        check.evidence?.next_evidence === 'configure_same_pending_flag_as_producer' ? '核对发布任务使用的队列位置，再配置本采集器。' :
        check.evidence?.next_evidence === 'request_consumption_and_current_public_hash_verification' ? '逐请求消费结果、当前线上文件哈希，以及有来源的交付期限。' :
        check.evidence?.next_evidence ? '对应业务的本轮回执：运行编号、业务日、输入输出哈希、覆盖数、规则和有效期。' : '未知'],
      ['业务发生时间', check.evidence?.event_at ? fullTime(check.evidence.event_at) : '未知'], ['接收时间', state.data.state?.latest?.received_at ? fullTime(state.data.state.latest.received_at) : '未知'],
      ['确认送达时间', state.data.state?.latest?.delivered_at ? fullTime(state.data.state.latest.delivered_at) : '未知'], ['证据有效期', check.evidence?.valid_until ? fullTime(check.evidence.valid_until) : '未知']]));
    if (check.id === 'publication:r2-pending-requests') {
      const e = check.evidence || {}, count = k => Number.isFinite(e[k]) ? String(Math.floor(e[k])) : '未知';
      append(host, pairs([['已观察待处理', count('pending_count')], ['尚未被取入批次', count('unoffered_count')],
        ['凭证缺失或损坏', count('proof_invalid_count')], ['最久等待（秒）', count('oldest_wait_seconds')],
        ['检查范围', e.inspection_status === 'complete' && e.truncated === false ? '本次有界扫描完整' : '不完整或未知；数量不能当作队列总数']]));
    }
    if (['business:public-fund', 'business:fof-nav'].includes(check.id)) {
      const e = check.evidence || {}, count = k => Number.isFinite(e[k]) ? String(e[k]) : '未知';
      append(host, pairs([['采集阶段', ({scoped_committed:'所选批次事务已提交', legal_empty:'查询结果为空，不代表全量齐全', failure:'存在采集异常'})[e.collection_state] || '未知'],
        ['净值线上发布', '未取得本轮净值与公开文件的完整对应凭证'], ['池内尚未尝试', count('pool_not_attempted')],
        ['所选批次尚未尝试', count('selected_not_attempted')], ['源端非空净值行', count('published_rows')],
        ['已提交非空输入行', count('committed_rows')]]));
    }
    if (check._missing) host.append(notice('该检查未在最新覆盖范围。保留旧状态仅供追溯，当前为 unknown，不作恢复。', 'warning'));
    if (freshness() !== 'fresh') host.append(notice('采集过期或不可判定：此记录仅是最近证据，当前状态未知。', 'warning'));
    append(host, node('h3', '', '安全证据字段'), node('pre', '', text(check.evidence)));
    const raw = node('details', 'evidence-item'); append(raw, node('summary', '', '检查原始字段'), node('pre', '', text(check))); host.append(raw);
    const match = state.recordMap.get(check.id); if (match) host.append(button('查看同 ID 版本记录', () => showRecord(match)));
  }
  function showEvent(event) {
    const host = openDetail(eventName(event), '事件与投递');
    append(host, pairs([['事件 ID', event.event_id || event.id], ['检查 ID', event.check_id], ['摘要', summaryOf(event.summary)], ['事件时间', fullTime(eventTime(event))], ['投递状态', deliveryBadge(event)], ['尝试次数', event.attempts], ['下次尝试', fullTime(event.next_attempt_at)], ['投递时间', fullTime(event.delivered_at)], ['最近错误', event.last_error]]), notice('重复投递可能发生；投递成功不等于业务故障已恢复。'), node('h3', '', '事件原始字段'), node('pre', '', text(event)));
  }
  function showRecord(record) {
    const incident = state.incidents.find(r => r.id === record.id);
    if (incident) return showIncident(incident);
    state.selectedRecord = record.id;
    const host = openDetail(nameOf(record), (KINDS[record.kind] || record.kind || '记录') + ' / ' + record.id);
    append(host, pairs([['证据状态', record.evidence_status], ['业务健康', record.health || 'unknown'], ['原始观察时间', fullTime(sourceTime(record))], ['来源层', sourceValue(record, 'source_layer') || sourceValue(record, 'configuration_layer')]]));
    const actions = node('div', 'detail-actions');
    if (record.kind !== 'edge') actions.append(button('在架构图中聚焦', () => { state.graphFocus = record.id; $('detail-dialog').close(); setTab('architecture'); }));
    host.append(actions);
    const dep = list(record.depends_on);
    if (dep.length) { const links = node('div', 'relation-links'); dep.forEach(id => links.append(button(state.recordMap.get(id) ? nameOf(state.recordMap.get(id)) : id, () => showRecord(state.recordMap.get(id) || { id, name: id, evidence: [], health: 'unknown' })))); append(host, node('h3', '', '已声明依赖'), links); }
    const dependents = state.records.filter(r => list(r.depends_on).includes(record.id));
    if (dependents.length) { const links = node('div', 'relation-links'); dependents.slice(0, 40).forEach(r => links.append(button(nameOf(r), () => showRecord(r)))); append(host, node('h3', '', '引用此记录'), links); }
    append(host, node('h3', '', '来源证据'), evidenceBlock(record.evidence, sourceTime(record)));
    list(record.observations).forEach((obs, index) => {
      const d = node('details', 'evidence-item'); d.append(node('summary', '', '来源观察 ' + (index + 1) + ' · ' + (obs.source_file || 'unknown') + ' · ' + time(obs.observed_at || obs.source_inventory_time)));
      append(d, evidenceBlock(obs.record?.evidence || obs.evidence, obs.record?.observed_at || obs.observed_at || obs.source_inventory_time), node('pre', '', text(obs))); host.append(d);
    });
    const d = node('details', 'evidence-item'); append(d, node('summary', '', '全部版本字段 / 未知与合同'), node('pre', '', text(record))); host.append(d);
  }
  function revisionsFor(id) { return state.revisions.filter(r => r.incident_id === id || r.id === id); }
  function showIncident(r) {
    const host = openDetail(nameOf(r), (sourceValue(r, 'original_issue_id') || r.id) + ' · revision ' + incidentRevision(r));
    append(host, notice('各轴独立：交接完成、已修复、部署与根治不能互相代替。历史不可回放不等于恢复。'), pairs([
      ['当前工作流组', groupLabel(incidentGroup(r))], ['基线原分组', groupLabel(sourceValue(r.baseline || r, 'workflow_group') || 'unclassified')],
      ['分组范围', sourceValue(r, 'workflow_group_scope')], ['工作流状态', sourceValue(r, 'workflow_status')], ['修复状态', sourceValue(r, 'remediation_state')], ['根因状态', sourceValue(r, 'root_cause_state')], ['部署状态', sourceValue(r, 'deployment_state')], ['验收状态', sourceValue(r, 'verification_state')], ['观察状态', r.observation_status || sourceValue(r, 'observation_window')], ['负责人', sourceValue(r, 'owner')], ['上次核验', sourceValue(r, 'last_verified_at')], ['关闭条件', sourceValue(r, 'close_conditions')]
    ]), button('人工更新 / 追加证据', () => openEditor(r), 'button primary'));
    if (r.override?.note) append(host, node('h3', '', '最近人工说明'), node('p', 'small', r.override.note));
    if (r.override?.evidence_url) append(host, node('h3', '', '人工证据链接'), evidenceBlock([{ kind: '人工修订', location: r.override.evidence_url }], r.override.updated_at));
    append(host, node('h3', '', '原始基线证据'), evidenceBlock((r.baseline || r).evidence || sourceValue(r, 'evidence'), sourceValue(r, 'last_verified_at')));
    const runtime = sourceValue(r, 'related_runtime_observations');
    if (runtime) append(host, node('h3', '', '关联运行观察（不等于业务故障）'), node('pre', '', text(runtime)));
    const revisions = revisionsFor(r.id);
    append(host, node('h3', '', '人工修订审计（最近 12 条）'), revisions.length ? node('pre', '', text(revisions.slice(0, 12))) : node('p', 'small muted', '暂无人工修订记录；保留版本基线。'));
    const detail = node('details', 'evidence-item'); append(detail, node('summary', '', '完整记录与所有来源'), node('pre', '', text(r))); host.append(detail);
  }

  function openEditor(record) {
    if (state.saving) { toast('上一项修订仍在提交，请先等待结果。'); return; }
    if (!state.authorized || state.errors.incidents) { toast('问题台账尚未成功刷新，暂不能更新。'); return; }
    if ($('detail-dialog').open) $('detail-dialog').close();
    const host = $('edit-body'); host.replaceChildren();
    const revision = incidentRevision(record); state.edit = { id: record.id, revision, record, conflict: false };
    append(host, node('p', 'small muted', nameOf(record) + ' · ' + record.id), notice('基于 revision ' + revision + ' 更新。下拉表示本次人工声明，不自动把基线中文推断为机器状态。未核实请保留未知；所有基线原文独立保留。'));
    const form = node('form'); form.id = 'incident-edit-form'; const grid = node('div', 'edit-grid');
    const fields = [['workflow_status', '工作流状态'], ['remediation_state', '修复状态'], ['root_cause_state', '根因状态'], ['deployment_state', '部署状态'], ['verification_state', '验收状态'], ['observation_status', '观察状态']];
    fields.forEach(([key, label]) => {
      const wrap = node('label', 'edit-field', label);
      const dict = key === 'workflow_status' ? WORKFLOW : key === 'verification_state' ? VERIFICATION : key === 'observation_status' ? OBSERVATION : null;
      const input = dict ? node('select') : node('textarea'); input.name = key;
      const value = record.override?.[key];
      if (dict) { Object.entries(dict).forEach(([id, display]) => input.add(new Option(display, id))); input.value = Object.hasOwn(dict, value) ? value : 'unknown'; }
      else { input.maxLength = 160; input.rows = 3; const original = value ?? sourceValue(record, key); input.value = safeStatusText(original) ? original : 'unknown'; input.placeholder = 'unknown / 状态简述，不填写链接或私密路径'; }
      const baseline = key === 'observation_status' ? sourceValue(record.baseline || record, 'observation_window')?.status : sourceValue(record.baseline || record, key);
      append(wrap, input, node('span', 'muted small', '基线：' + text(baseline))); grid.append(wrap);
    });
    const noteWrap = node('label', 'edit-field wide', '变更说明（必填）'); const note = node('textarea'); note.name = 'note'; note.maxLength = 2000; note.required = true; note.placeholder = '依据、核验范围、尚未解决事项。无链接、私密绝对路径、账号或凭证；链接填在下方。'; noteWrap.append(note); grid.append(noteWrap);
    const evidenceWrap = node('label', 'edit-field wide', '证据链接（HTTPS，无 query，建议固定版本）'); const evidence = node('input'); evidence.name = 'evidence_url'; evidence.type = 'url'; evidence.maxLength = 500; evidence.placeholder = 'https://…'; evidenceWrap.append(evidence); grid.append(evidenceWrap);
    grid.append(notice('选择“已关闭”时，须有证据链接和说明；验收须为已验证／通过／限定通过，观察须为已有证据／通过／完成。只声明“待观察”不能关闭。', 'warning'));
    const message = node('div', 'form-status'); message.id = 'edit-status'; message.setAttribute('role', 'status');
    const actions = node('div', 'form-actions'); const cancel = button('取消', () => $('edit-dialog').close()); const save = button('保存人工修订', () => {} , 'button primary'); save.id = 'edit-save'; save.type = 'submit'; append(actions, cancel, save);
    append(form, grid, message, actions); form.addEventListener('submit', event => { event.preventDefault(); saveIncident(form); }); host.append(form);
    if (!$('edit-dialog').open) $('edit-dialog').showModal();
  }
  async function saveIncident(form) {
    if (state.saving || !state.authorized || !state.edit || state.edit.conflict || !form.reportValidity()) return;
    const values = new FormData(form); const payload = { expected_revision: state.edit.revision };
    ['workflow_status', 'root_cause_state', 'remediation_state', 'deployment_state', 'verification_state', 'observation_status', 'note', 'evidence_url'].forEach(k => { payload[k] = String(values.get(k) || '').trim(); });
    const box = $('edit-status'); box.replaceChildren();
    if (!payload.note) { box.append(notice('请填写变更说明。', 'warning')); return; }
    if (!Object.hasOwn(WORKFLOW, payload.workflow_status)) { box.append(notice('请选择有效工作流状态。', 'warning')); return; }
    if (payload.evidence_url && !safeEvidenceURL(payload.evidence_url)) { box.append(notice('证据须为无账号密码、无 query、非本机/私密路径的 HTTPS 链接。', 'warning')); return; }
    const unsafe = Object.entries(payload).some(([key, value]) => !['expected_revision', 'evidence_url'].includes(key) && !safeStatusText(value, key === 'note' ? 2000 : 160));
    if (unsafe) { box.append(notice('状态/说明请勿包含链接、私密绝对路径、账号或凭证；证据链接单独填写。', 'warning')); return; }
    const closing = payload.workflow_status === 'closed' || /已根治|根治完成|已解决/.test(payload.root_cause_state);
    if (closing && (!payload.evidence_url || !['verified', 'passed', 'scoped_pass'].includes(payload.verification_state) || !['observed', 'passed', 'complete'].includes(payload.observation_status))) { box.append(notice('关闭或根治声明需附证据，验收为已验证／通过／限定通过，观察为已有证据／通过／完成。', 'warning')); return; }
    const epoch = state.epoch, edit = state.edit;
    cancelRefresh(); state.saving = true; $('edit-save').disabled = true; setBusy();
    try {
      await request('/api/ops/incidents/' + encodeURIComponent(edit.id), { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Ops-Intent': 'update' }, body: JSON.stringify(payload) });
      if (state.epoch !== epoch || !state.authorized) return;
      const fresh = await request('/api/ops/incidents');
      if (state.epoch !== epoch || !state.authorized) return;
      state.data.incidents = fresh; delete state.errors.incidents; normaliseIncidents(fresh);
      $('edit-dialog').close(); state.edit = null; renderAll();
      const record = state.incidents.find(r => r.id === edit.id);
      if (record) showIncident(record); toast('人工修订已保存，原始基线证据保留。');
    } catch (error) {
      if (state.epoch !== epoch || !state.authorized) return;
      if (error.status === 409) {
        edit.conflict = true; box.replaceChildren(notice('记录已被其他管理员更新（409）。当前草稿保留，未自动重试或覆盖。请先核对最新版本。', 'warning'));
        box.append(button('重新载入最新记录（替换本草稿）', async () => {
          try {
            const latest = await request('/api/ops/incidents');
            if (state.epoch !== epoch || !state.authorized) return;
            state.data.incidents = latest; normaliseIncidents(latest); renderAll();
            const found = state.incidents.find(r => r.id === edit.id);
            if (found) openEditor(found); else box.append(notice('最新台账中未找到此记录，草稿仍保留。', 'warning'));
          } catch (e) { if (state.epoch === epoch) box.append(notice(errorMessage(e), 'error')); }
        }));
      } else box.append(notice(errorMessage(error) + '。未确认保存完成；草稿保留，请核对记录后再操作。', 'error'));
    } finally {
      if (state.epoch === epoch) {
        state.saving = false; const save = $('edit-save'); if (save) save.disabled = !!state.edit?.conflict;
        setBusy(); schedule();
      }
    }
  }
  async function exportPrivate() {
    if (!state.authorized || state.exporting) return;
    const epoch = state.epoch; state.exporting = true; setBusy();
    try {
      const blob = await request('/api/ops/export', { asBlob: true });
      if (state.epoch !== epoch || !state.authorized) return;
      const url = URL.createObjectURL(blob); state.exportURLs.add(url);
      const a = node('a'); a.href = url; a.download = 'private-ops-' + new Date().toISOString().slice(0, 10) + '.json'; a.hidden = true; document.body.append(a); a.click(); a.remove();
      setTimeout(() => { URL.revokeObjectURL(url); state.exportURLs.delete(url); }, 1000);
      toast('运维记录已导出；非事务一致性备份。完整恢复需 D1 原生导出与演练。');
    } catch (e) { if (state.epoch === epoch && state.authorized) toast(errorMessage(e) + '，未生成导出文件。'); }
    finally { state.exporting = false; setBusy(); }
  }

  document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));
  $('session-connect').addEventListener('click', () => connect());
  $('token-form').addEventListener('submit', event => { event.preventDefault(); const token = $('admin-token').value.trim(); $('admin-token').value = ''; if (token) connect(token); else $('auth-message').textContent = '请输入管理员令牌。'; });
  $('refresh-button').addEventListener('click', () => refresh());
  $('pause-button').addEventListener('click', () => { state.paused = !state.paused; if (state.paused) clearTimer(); else refresh(); setBusy(); });
  $('poll-interval').addEventListener('change', () => { state.interval = Number($('poll-interval').value) * 1000; schedule(); });
  $('export-button').addEventListener('click', exportPrivate);
  $('logout-button').addEventListener('click', async () => {
    clearPrivate('本页私有数据与临时令牌已清除。');
    try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin', cache: 'no-store', mode: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: '{}' }); }
    catch { $('auth-message').textContent = '本页私有数据已清除；账号退出尚未确认。'; }
  });
  let searchTimer;
  $('search-input').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.query = $('search-input').value.trim().toLocaleLowerCase(); renderAll(); }, 130); });
  ['status-filter', 'data-category', 'knowledge-kind', 'incident-group', 'delivery-filter'].forEach(id => $(id).addEventListener('change', () => { state.status = $('status-filter').value; renderAll(); }));
  $('graph-reset').addEventListener('click', () => { state.graphFocus = null; renderGraph(); });
  $('detail-close').addEventListener('click', () => $('detail-dialog').close());
  $('edit-close').addEventListener('click', () => $('edit-dialog').close());
  $('edit-dialog').addEventListener('close', () => { if (!state.saving) { state.edit = null; $('edit-body').replaceChildren(); } });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { clearTimer(); cancelRefresh(); } else if (state.authorized && !state.paused) refresh(); setBusy(); });
  window.addEventListener('pagehide', () => clearPrivate('页面已锁定，请重新验证管理员会话。'));
  window.addEventListener('pageshow', event => { if (event.persisted) connect(); });
  // This clock updates local age labels only. Network polling is separately serialized.
  setInterval(() => {
    if (!state.authorized || document.hidden) return;
    const changed = state.displayFreshness !== freshness();
    updateHeader();
    if (changed) renderAll();
  }, 15000);
  setTab('overview'); refresh(true);
})();
