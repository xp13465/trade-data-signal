"""R2 关键键覆盖协议。仅由 upload_r2 在既有锁域内调用，不是多对象事务。"""
import hashlib
import json
import os
import random
import re
import time
import uuid
import fcntl
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

PAIR = ('data/overfit_monitor.json', 'data/overfit_monitor_ext.json')
CRITICAL = frozenset((*PAIR, 'data/nextday_plan.json', 'data/auto_trade_steps.json',
                      'data/signal_kelly_day_snapshot.json'))


def protected(key):
    return key in CRITICAL or bool(re.fullmatch(r'nav_bucket/[^/]+\.json', key))


# ---- 传输层有界重试(2026-11-17;依据 /tmp/rca-backup-nav-20261116.md 实测) ----
# 病灶: 条件 PUT 设计上只发一次(upload_r2.s3_request 对 if-match/if-none-match 请求 attempts=1),
# 跨境链拥塞时一次 TLS 断连/响应丢失即判死。2026-11-16 晚 upload p50 49.4s / max 600.1s(基线
# ~16s), 两种报错同源: 15 份主对象 `write unconfirmed HTTP 0` + 15 份备份桶
# `backup readback SHA256 mismatch`(备份键内容寻址, 该报错真实语义 = 备份 PUT 未落地、读回 404 空)。
#
# 边界(测试逐条锁定, 见 scripts/tests/test_upload_retry_capture_fix_20261117.py):
#   - 只重放**传输层**失败: st==0(连接断/响应丢失) / st>=500(服务端偶发) / 条件 PUT 返回 200
#     但 write-id+sha 读回确认不到(GET 侧同属传输故障); 备份桶侧 = 读回为空(404)或 GET 报错。
#   - 412 Precondition Failed: **绝不重试、绝不覆盖**。唯一例外: 前序尝试本身是传输层失败, 本次
#     412 可能由「自己那次写入已落地」造成 —— 先按 write_id+sha 确认, 确认到自己的字节才算成功
#     (不覆盖任何他人写入), 确认不到如实失败。
#   - 永久性 4xx(412 除外)、备份读回内容确不相同(内容寻址路径上出现别的字节=真异常): 不重试。
#   - 重试耗尽: 与改动前同口径判失败(UnsafeWrite ⇒ 上游 rc=1), **不吞错**。
#   - 每对象最多 TRANSPORT_RETRIES 次重试(共 3 次尝试), 退避 2s → 8s + 抖动; 退避一律走
#     `_work_sleep`(受 #364 工作预算约束), 每次重试前过 `_work_budget_check`。
TRANSPORT_RETRIES = 2
TRANSPORT_BACKOFF_SECONDS = (2.0, 8.0)

# 关键存储文件数预算(2026-11-25 块3 抽为模块常量, 生产值不变 = 原硬编码 8192; 单测可临时
# monkeypatch 小值以构造「超预算」场景, 不靠造 8000+ 文件拖慢门禁)。
PROTECTED_FILE_BUDGET = 8192


def retry_wait(attempt):
    """第 attempt 次重试前的退避秒数(2s → 8s, ±20% 抖动, 越界取最后一段)。"""
    base = TRANSPORT_BACKOFF_SECONDS[min(attempt - 1, len(TRANSPORT_BACKOFF_SECONDS) - 1)]
    return base * (1 + random.uniform(-0.2, 0.2))


def _permanent_http(status):
    """永久性 HTTP 状态(4xx; 408/429 属可重试的传输层限流/超时)判定。"""
    return 400 <= status < 500 and status not in (408, 429)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def durable(path, body):
    """数据和父目录均 fsync；ENOSPC/rename 失败向上传播，发送前必须成功。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp.' + uuid.uuid4().hex)
    try:
        with open(tmp, 'xb') as f:
            os.chmod(tmp, 0o600)
            f.write(body); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)


class UnsafeWrite(RuntimeError):
    pass


class SafeWriter:
    def __init__(self, api):
        self.a = api
        self.root = api['STATIC_DIR'].parent / 'data' / '.r2-protected'
        self.bucket = api['BUCKET']
        self.backup = api['BACKUP_BUCKET']

    @contextmanager
    def storage_lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / '.gc.lock', 'a+b') as lock:
            deadline = time.monotonic() + 10
            while True:
                self.a['_work_budget_check']('protected-storage-lock')
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise UnsafeWrite('protected storage lock timeout')
                    self.a['_work_sleep'](.05)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def gc(self):
        """在 storage_lock 下按持久引用清理；坏 manifest 一律拒绝删除。

        2026-11-25 块2/块3: 保留集 = GC 引用闭包 + **全部 nonconfirmed 历史**(保守 hold);
        回收路径不再受新增写入配额(cap/8192/reserve)预检阻挡, 只要引用已证明、同锁域、
        清单 durable 落盘成功即可删本地无引用文件; 新写入配额由 store_many 在回收后按
        保留集 + 新 writes 原样拦截。

        容错模式(实例属性 `gc_tolerate_unreadable=True`, 仅自动自愈轮设置, 见
        upload_r2.cmd_recover_protected): 存在无法解析的 journal 时**零删除**并继续 ——
        引用集不完整时删除任何文件都可能删掉坏文件引用的恢复锚点, 故整轮跳过清理、
        保留全部文件与旧 gc 清单, 坏文件留给人工核验。默认(属性未设)保持严格失败,
        既有「坏 manifest 一律拒绝删除」契约不变。
        """
        tolerate = bool(getattr(self, 'gc_tolerate_unreadable', False))
        if any(p.is_symlink() for p in self.root.rglob('*')):
            raise UnsafeWrite('protected storage contains symlink; GC refused')
        keep = {self.root / '.gc.lock', self.root / 'gc-manifest.json'}
        rows = []
        unreadable = []
        for path in self.root.glob('*.json'):
            if path.name == 'gc-manifest.json':
                continue
            try:
                rows.append(json.loads(path.read_text()))
            except (OSError, ValueError):
                if not tolerate:
                    raise
                unreadable.append(path)
            keep.add(path)
        history = {}
        for path in (self.root / 'history').glob('*.json'):
            try:
                row = json.loads(path.read_text())
            except (OSError, ValueError):
                if not tolerate:
                    raise
                unreadable.append(path)
                keep.add(path)
                continue
            history.setdefault(row['key'], []).append((path, row))
            # 2026-11-25 块2(方案 §3.2): 保守保留**所有 nonconfirmed 历史**, 不再只保
            # unknown/pending_purge/非 confirmed pair。preparing/prepared/failed/plain 等
            # 未结状态的行都可能是恢复锚点: 11-25 复核实测 55 条 plain preparing 历史在旧
            # 语义下可被删, 而它们的 old_sha256 payload(103 个/0.29GiB)只有这些行还挂着引用。
            # 保留后其 new/old payload 与 pair 由下方引用闭包递归保住(sha256/old_sha256 +
            # pair manifest.objects)。禁 HISTORY_KEEP=0、禁把未知状态改写成 confirmed 来省空间。
            if row.get('state') != 'confirmed' or row.get('pending_purge'):
                keep.add(path); rows.append(row)
        count = int(os.environ.get('R2_PROTECTED_HISTORY_KEEP', '1'))
        if not 0 <= count <= 16:
            raise UnsafeWrite('R2_PROTECTED_HISTORY_KEEP must be 0..16')
        for entries in history.values():
            completed = [(p, r) for p, r in entries if r['state'] == 'confirmed' and not r.get('pending_purge')]
            for path, row in sorted(completed, key=lambda x: x[0].stat().st_mtime_ns, reverse=True)[:count]:
                keep.add(path); rows.append(row)
        # 当前/未决 pair 的 manifest 引用两件，即使其中一件已经更新也不能拆掉恢复锚点。
        seen_pairs = set()
        for row in rows:
            if not all(k in row for k in ('key', 'sha256', 'write_id', 'state')):
                raise UnsafeWrite('invalid protected reference journal')
            if not re.fullmatch('[a-f0-9]{32}', row['write_id']) or not protected(row['key']):
                raise UnsafeWrite('invalid protected journal identity')
            keep.add(self.root / 'history' / (row['write_id'] + '.json'))
            for digest in (row['sha256'], row.get('old_sha256')):
                if digest:
                    if not re.fullmatch('[a-f0-9]{64}', digest):
                        raise UnsafeWrite('invalid payload reference')
                    keep.add(self.root / 'payloads' / digest)
            pair_id = row.get('pair_id')
            if pair_id and pair_id not in seen_pairs:
                if not re.fullmatch('[a-f0-9]{32}', pair_id):
                    raise UnsafeWrite('invalid pair reference')
                path = self.root / 'pairs' / (pair_id + '.json')
                manifest = json.loads(path.read_text())
                if manifest['pair_id'] != pair_id or set(manifest['objects']) != set(PAIR):
                    raise UnsafeWrite('invalid pair manifest')
                keep.add(path); seen_pairs.add(pair_id)
                rows.extend(manifest['objects'].values())
        files = [p for p in self.root.rglob('*') if p.is_file()]
        if unreadable:
            # 容错模式: 引用集不完整 ⇒ 本轮零删除 + 不覆写 gc 清单(旧清单保留供人工核验),
            # 只如实把全部现存文件返回给容量核算; 坏文件保留原地。
            print('R2_PROTECTED_GC: ' + json.dumps({
                'tolerated_unreadable': [str(p.relative_to(self.root)) for p in unreadable],
                'action': 'cleanup-skipped-no-deletion'}, ensure_ascii=False), file=sys.stderr)
            return files
        garbage = [p for p in files if p not in keep]
        # 2026-11-25 块3(方案 §3.3): 回收预算与新增写入配额拆开。
        # 旧行为用 check_capacity(全部旧文件) 在 unlink 前预检, C 根 9286 文件 > 8192 且
        # 10.68GB > 2GiB cap 时必抛 UnsafeWrite ⇒ GC 永远清不动(11-25 复核 §6)。
        # 回收路径的准入改由三条自证: ①引用已证明(上文 journal/payload/pair 全量校验, 坏
        # JSON/缺引用/非法身份提前 raise, 零删除); ②同锁域(生产唯一调用方 store_many 在
        # storage_lock 内); ③清单安全落盘(durable 先于任何 unlink, 落盘失败抛错、零删除)。
        # 新增写入配额仍由 store_many 在回收后按「保留文件 + 新 writes」跑原 check_capacity
        # 的 cap/8192/reserve 拦截 —— 仅保留集合本身超预算时照旧拒绝新写, 不调大 cap/降 reserve。
        cap = int(os.environ.get('R2_PROTECTED_MAX_BYTES', str(2 * 1024**3)))
        planned_used = sum(p.stat().st_size + 4096 for p in files)
        if cap > 0 and (planned_used > cap or len(files) + 1 > PROTECTED_FILE_BUDGET):
            print('R2_PROTECTED_GC: ' + json.dumps({
                'action': 'reclaim-over-write-budget', 'planned_used': planned_used,
                'planned_files': len(files), 'cap': cap, 'file_budget': PROTECTED_FILE_BUDGET,
                'retired_count': len(garbage)}, ensure_ascii=False), file=sys.stderr)
        # 删除前复核计划: 文件集或待删文件身份在「计划 → 清单落盘」之间变化(计划后新引用文件 /
        # 文件被替换/消失)⇒ 整批零删除。同锁域下正常恒等, 此步是最后一道身份闸门。
        manifest_path = self.root / 'gc-manifest.json'
        planned_paths = {p for p in files if p != manifest_path}
        identities = {p: self._file_identity(p) for p in garbage}
        # 先持久记录引用集合，再删除无引用的本地缓存；不存在先删后补清单窗口。
        manifest = json.dumps({
            'version': 1, 'keep': sorted(str(p.relative_to(self.root)) for p in keep),
            'retired_count': len(garbage)}).encode()
        durable(manifest_path, manifest)
        self._revalidate_gc_plan(planned_paths, identities, manifest_path)
        for path in garbage:
            self.a['_work_budget_check']('protected-gc')
            path.unlink()
        return [p for p in keep if p.is_file()]

    @staticmethod
    def _file_identity(path):
        st = path.stat()
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

    def _revalidate_gc_plan(self, planned_paths, identities, manifest_path):
        """清单落盘后、unlink 前复核: 文件集或待删文件身份变化 ⇒ 整批零删除(UnsafeWrite)。"""
        current = {p for p in self.root.rglob('*') if p.is_file() and p != manifest_path}
        if current != set(planned_paths):
            raise UnsafeWrite('protected GC plan stale: file set changed before unlink; zero deletion')
        for path, identity in identities.items():
            try:
                now = self._file_identity(path)
            except FileNotFoundError:
                raise UnsafeWrite('protected GC plan stale: planned file vanished; zero deletion') from None
            if now != identity:
                raise UnsafeWrite('protected GC plan stale: planned file identity changed; zero deletion')

    def store_many(self, writes):
        with self.storage_lock():
            files = self.gc()
            self.check_capacity(files, writes)
            for path, body in writes.items():
                durable(path, body)

    def check_capacity(self, files, writes):
        cap = int(os.environ.get('R2_PROTECTED_MAX_BYTES', str(2 * 1024**3)))
        if cap <= 0:
            raise UnsafeWrite('R2_PROTECTED_MAX_BYTES must be positive')
        used = sum(p.stat().st_size + 4096 for p in files)
        extra = sum(len(body) + 4096 for body in writes.values())
        # 包括GC manifest与替换时新临时文件的峰值；容量不足不删未决锚点。
        if used + extra > cap or len(files) + len(writes) > PROTECTED_FILE_BUDGET:
            raise UnsafeWrite(f'protected capacity budget exhausted: used={used} extra={extra} cap={cap}; '
                              'unresolved anchors retained')
        reserve = int(os.environ.get('R2_PROTECTED_MIN_FREE_BYTES', str(128 * 1024**2)))
        if reserve < 0:
            raise UnsafeWrite('R2_PROTECTED_MIN_FREE_BYTES must be nonnegative')
        free = shutil.disk_usage(self.root).free
        if free < extra + reserve:
            raise UnsafeWrite(f'protected disk free insufficient: free={free} extra={extra} reserve={reserve}; '
                              'unresolved anchors retained')

    def store(self, path, body):
        self.store_many({path: body})

    @contextmanager
    def phase(self, key, name):
        self.a['_work_budget_check'](name)
        started = time.monotonic()
        try:
            yield
        finally:
            print('R2_PHASE: ' + json.dumps({'key': key, 'phase': name,
                'seconds': round(time.monotonic() - started, 6)}), flush=True)

    @staticmethod
    def _log_retry(key, attempt, error_kind, elapsed_ms, exhausted):
        """每次重试决策一行可观测日志(key/attempt/error_kind/elapsed_ms), 走 stderr 不污染 stdout。"""
        print('R2_WRITE_RETRY: ' + json.dumps({
            'key': key, 'attempt': attempt, 'error_kind': error_kind,
            'elapsed_ms': elapsed_ms, 'exhausted': exhausted}), file=sys.stderr)

    def path(self, key):
        return self.root / (sha((self.bucket + '/' + key).encode()) + '.json')

    def save(self, row):
        with self.phase(row['key'], 'state'):
            self.store(self.path(row['key']), json.dumps(row, sort_keys=True).encode())
            # 历史回执按 write-id 保留，后续写入不抹掉部分发布/恢复配对。
            self.store(self.root / 'history' / (row['write_id'] + '.json'), json.dumps(row, sort_keys=True).encode())

    def load(self, key):
        try:
            row = json.loads(self.path(key).read_text())
        except FileNotFoundError:
            return None
        if row.get('bucket') != self.bucket or row.get('key') != key:
            raise UnsafeWrite('journal identity mismatch')
        return row

    def get(self, key, bucket=None):
        with self.phase(key, 'old_read' if bucket is None else 'backup_readback'):
            st, body, headers = self.a['s3_request']('GET', key, bucket=bucket or self.bucket,
                with_headers=True, keep_alive=True, progress_label=key)
        if st == 404 and b'NoSuchKey' in body:
            return None
        if st != 200:
            raise UnsafeWrite(f'GET {key}: HTTP {st}')
        etag = self.a['_header_lookup'](headers, 'etag')
        length = self.a['_header_lookup'](headers, 'content-length')
        if not etag or etag.startswith('W/') or not re.fullmatch(r'"[^"\r\n]+"', etag):
            raise UnsafeWrite('missing/invalid strong ETag on GET')
        if length is None or int(length) != len(body):
            raise UnsafeWrite('GET length mismatch')
        return body, etag, headers

    def immutable(self, key, body):
        """备份桶不可变写入(内容寻址键)。传输层失败有界重放: 键含内容 sha, 重放同一 bytes 幂等;
        if-none-match:'*' 下 412 = 同内容已存在(读回 sha 校验通过即成功), 不是覆盖冲突。"""
        attempts = 1 + TRANSPORT_RETRIES
        digest = sha(body)
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            with self.phase(key, 'backup_write' if attempt == 1 else 'backup_write_retry'):
                try:
                    st, _ = self.a['_put_bytes'](key, body, bucket=self.backup,
                        extra_headers={'if-none-match': '*', 'x-amz-meta-write-id': uuid.uuid4().hex})
                except (OSError, self.a['http'].client.HTTPException):
                    st = 0
            if st not in (0, 200, 412) and st < 500:
                # 永久性 4xx(412 除外): 不重试(412 = 同内容已存在, 走读回校验)。
                raise UnsafeWrite(f'backup HTTP {st}')
            error_kind = None
            actual = None
            try:
                actual = self.get(key, self.backup)
            except UnsafeWrite as exc:
                # 读回 GET 失败: 404(含「404 + 空 body」这种响应形态)一律视为「读回为空」可重试
                # —— 真实故障 `backup readback SHA256 mismatch` 的语义就是读回空; 其余 GET 失败属
                # 传输层可重试; 永久 4xx(GET 的 403 等)不重试。
                error_kind = 'readback_error'
                m = re.search(r'HTTP (\d{3})', str(exc))
                if m:
                    code = int(m.group(1))
                    if code == 404:
                        error_kind = 'readback_empty'
                    elif _permanent_http(code):
                        raise
            if actual is not None:
                if sha(actual[0]) == digest:
                    return
                # 内容寻址路径上读到别的字节 = 真异常(不是传输抖动), 不重试、不覆盖。
                raise UnsafeWrite('backup readback SHA256 mismatch')
            error_kind = error_kind or 'readback_empty'
            elapsed_ms = int((time.monotonic() - started) * 1000)
            exhausted = attempt >= attempts
            self._log_retry(key, attempt, error_kind, elapsed_ms, exhausted)
            if exhausted:
                raise UnsafeWrite('backup readback SHA256 mismatch')
            self.a['_work_budget_check']('backup-write-retry')
            self.a['_work_sleep'](retry_wait(attempt))

    def confirm(self, row):
        # 有界确认，不把负读/其他写者的相同 bytes 当成本次成功。
        for _ in range(2):
            try:
                obj = self.get(row['key'])
            except Exception:
                continue
            if (obj and sha(obj[0]) == row['sha256'] and
                self.a['_header_lookup'](obj[2], 'x-amz-meta-write-id') == row['write_id']):
                row.update(state='confirmed', confirmed=True)
                # 未决锚点清零(2026-11-14 B批 D1): confirmed 即已解决; 单点清, 正常/恢复路径同口径。
                row['first_unresolved_at'] = None
                self.save(row)
                return True
        return False

    def purge(self, row):
        if row.get('pending_purge'):
            with self.phase(row['key'], 'purge'):
                # nav_bucket 使用 /r2/ 代理，data 也可能经两条路由访问。
                # 任一失败都保留整键任务；重复清已成功的路径是幂等的。
                for prefix in ('/', '/r2/'):
                    if not self.a['purge_cache']([row['key']], cache_prefix=prefix):
                        raise UnsafeWrite('confirmed object; purge pending')
            row['pending_purge'] = False
            self.save(row)

    def recover(self, row, retry_put=False):
        if row['state'] == 'unknown':
            complete = row.get('complete')
            if complete:
                # 同一 upload-id/part-list/条件重试；绝不启动新的无条件上传。
                try:
                    self.a['s3_request']('POST', row['key'], payload=complete['body'].encode(),
                        query=complete['query'], content_type='application/xml',
                        extra_headers=row['headers'])
                except Exception:
                    pass
            elif retry_put:
                payload = (self.root / 'payloads' / row['sha256']).read_bytes()
                if sha(payload) != row['sha256']:
                    raise UnsafeWrite('recovery payload SHA256 mismatch')
                # 显式恢复命令只重放原 write-id/bytes/条件，不创建新的覆盖许可。
                try:
                    self.a['_put_bytes'](row['key'], payload, extra_headers=row['headers'])
                except Exception:
                    pass
            if not self.confirm(row):
                raise UnsafeWrite('unknown write remains unresolved; journal retained')
        if row['state'] == 'confirmed':
            self.purge(row)
            self.save(row)  # 修复主日志落盘、history 写入失败的崩溃窗口。

    def prepare(self, key, payload):
        with self.phase(key, 'prepare_hash'):
            digest = sha(payload)
        prev = self.load(key)
        if prev:
            self.recover(prev)
            if prev['sha256'] == digest and prev['state'] == 'failed' and prev.get('pair_id'):
                current = self.get(key)
                if (current and sha(current[0]) == prev['old_sha256'] and
                        current[1] == prev['headers'].get('if-match')) or (
                        current is None and prev['headers'].get('if-none-match') == '*'):
                    prev.update(state='prepared', status=None)
                    self.save(prev)
                else:
                    raise UnsafeWrite('partial pair conflicts with another writer; recovery pair retained')
            if prev['sha256'] == digest and prev['state'] == 'prepared':
                if prev.get('backup_key'):
                    old_bytes = (self.root / 'payloads' / prev['old_sha256']).read_bytes()
                    if sha(old_bytes) != prev['old_sha256']:
                        raise UnsafeWrite('saved old bytes SHA256 mismatch')
                    self.immutable(prev['backup_key'], old_bytes)
                return prev
            if prev['sha256'] == digest and prev['state'] == 'confirmed':
                obj = self.get(key)
                if obj and sha(obj[0]) == digest:
                    return prev
        old = self.get(key)
        # 可见性字段(2026-11-14 B批 D1, NAV 发布自动恢复): 全部可选, 读侧 .get 兼容旧 row,
        # 不动 version=1、不进产物字节。来源=调用方 env 注入(fund_nav_upload_async.sh 侧),
        # env 未设 ⇒ None/0, 既有通道行为逐字不变。
        business_date = os.environ.get('R2_BUSINESS_DATE') or None
        run_id = os.environ.get('R2_EXPORT_RUN_ID') or os.environ.get('INVOCATION_ID') or uuid.uuid4().hex
        row = {'version': 1, 'bucket': self.bucket, 'key': key, 'sha256': digest,
               'size': len(payload), 'write_id': uuid.uuid4().hex, 'state': 'preparing',
               'confirmed': False, 'pending_purge': False,
               'run_id': run_id,
               'old_sha256': sha(old[0]) if old else None, 'backup_key': None,
               # 业务交易日(YYYY-MM-DD); 来源轮次(如 fund_nav_upload_async);
               # 代次=run_id@business_date 组合(nav_bucket 产物无 generated_at, 零产物改动);
               # 首次进入非 confirmed 的时刻(UTC, prepare 生成即初始化, confirm 清);
               # 自动恢复已尝试次数(仅 upload_r2 自动恢复路径递增, 人工 recover-protected 不限)。
               'business_date': business_date,
               'source_channel': os.environ.get('R2_SOURCE_CHANNEL') or None,
               'generation': f"{run_id}@{business_date}" if business_date else run_id,
               'first_unresolved_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'retry_count': 0}
        if old:
            row['backup_key'] = f'protected-versions/v1/{self.bucket}/{key}/{sha(old[0])}'
            row['old_generation'] = self.generation(old[0]) if key in PAIR else None
            row['old_publication_run_id'] = self.publication_token(old[0]) if key in PAIR else None
        row['headers'] = {'if-match': old[1]} if old else {'if-none-match': '*'}
        row['headers']['x-amz-meta-write-id'] = row['write_id']
        # preparing 未发主对象请求；先持久引用，再存固定 bytes，GC 才能安全并发。
        self.save(row)
        self.store(self.root / 'payloads' / digest, payload)
        if old:
            self.store(self.root / 'payloads' / sha(old[0]), old[0])
            self.immutable(row['backup_key'], old[0])
        row['state'] = 'prepared'
        self.save(row)  # 逐键许可，旧 bytes 与 ETag 来自同一 GET。
        return row

    @staticmethod
    def generation(body):
        try:
            return json.loads(body).get('generated_at')
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def publication_token(body):
        try:
            token = json.loads(body).get('publication_run_id')
            return token if isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', token) else None
        except (ValueError, AttributeError):
            return None

    def prepare_pair(self, payloads):
        tokens = [self.publication_token(payloads[k]) for k in PAIR]
        if not tokens[0] or tokens[0] != tokens[1]:
            raise UnsafeWrite('overfit main/ext publication_run_id missing or mismatched')
        generation = [self.generation(payloads[k]) for k in PAIR]
        if not generation[0] or generation[0] != generation[1]:
            raise UnsafeWrite('overfit main/ext generation mismatch')
        rows = {k: self.prepare(k, payloads[k]) for k in PAIR}
        pair_ids = {r.get('pair_id') for r in rows.values()}
        if len(pair_ids) == 1 and None not in pair_ids:
            pair_id = next(iter(pair_ids))
            body = (self.root / 'pairs' / (pair_id + '.json')).read_bytes()
            self.immutable(f'protected-pairs/v1/{self.bucket}/{pair_id}.json', body)
            return rows  # 崩溃/部分发布后仍沿原配对恢复。
        olds = [r.get('old_generation') for r in rows.values()]
        old_tokens = [r.get('old_publication_run_id') for r in rows.values()]
        had_old = any(r['old_sha256'] for r in rows.values())
        assurance = 'absent'
        if had_old:
            if old_tokens[0] and old_tokens[0] == old_tokens[1]:
                assurance = 'publication_token_matched'
            elif not any(old_tokens) and olds[0] and olds[0] == olds[1]:
                assurance = 'legacy_timestamp_matched_only'
            else:
                assurance = 'old_bytes_preserved_generation_unverified'
        pair_id = uuid.uuid4().hex
        manifest = {'version': 1, 'pair_id': pair_id, 'generation': generation[0],
                    'publication_run_id': tokens[0], 'old_pair_assurance': assurance,
                    'generation_verified': True,
                    'old_generation_verified': assurance == 'publication_token_matched',
                    'old_pair': {'assurance': assurance,
                                 'generation_verified': assurance == 'publication_token_matched'},
                    'atomic': False, 'objects': rows}
        body = json.dumps(manifest, sort_keys=True).encode()
        writes = {self.root / 'pairs' / (pair_id + '.json'): body}
        for row in rows.values():
            row['pair_id'] = pair_id
            row['publication_run_id'] = tokens[0]
            row['old_pair_assurance'] = assurance
            row['old_generation_verified'] = assurance == 'publication_token_matched'
            encoded = json.dumps(row, sort_keys=True).encode()
            writes[self.path(row['key'])] = encoded
            writes[self.root / 'history' / (row['write_id'] + '.json')] = encoded
        # 一把本地GC锁内先写配对文件、再接两份引用；崩溃只会留下可恢复引用。
        self.store_many(writes)
        self.immutable(f'protected-pairs/v1/{self.bucket}/{pair_id}.json', body)
        return rows

    def commit(self, row, payload):
        if sha(payload) != row['sha256']:
            raise UnsafeWrite('permit does not match frozen bytes')
        if row['state'] == 'confirmed':
            self.purge(row)
            return
        if row['state'] != 'prepared':
            raise UnsafeWrite('permit already consumed')
        row.update(state='unknown', pending_purge=True)
        self.save(row)  # 先存 unknown+purge，进程在 HTTP 后崩溃仍可恢复。

        def before_complete(query, body):
            row['complete'] = {'query': query, 'body': body.decode()}
            self.save(row)

        attempts = 1 + TRANSPORT_RETRIES
        transport_failures = 0
        st = None
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            with self.phase(row['key'], 'upload' if attempt == 1 else 'upload_retry'):
                try:
                    st, _ = self.a['_put_bytes'](row['key'], payload, extra_headers=row['headers'],
                                                before_complete=before_complete)
                except (OSError, self.a['http'].client.HTTPException):
                    st = 0
            if len(payload) >= self.a['_MULTIPART_THRESHOLD'] and not row.get('complete') and st != 200:
                # multipart 中途未 complete = 无对象落地; 沿用既有语义直接判失败, 不新开 upload-id 重放。
                row.update(state='failed', pending_purge=False, status=st)
                self.save(row)
                raise UnsafeWrite('multipart stopped before completion; no committed object')
            if st in (412, 409, 403, 400):
                # 412 = 条件不成立(对象已被更新的写入覆盖) ⇒ 绝不重试、绝不覆盖。
                # 例外仅一种: 前序尝试是传输层失败, 本次 412 由「自己那次写入已落地」造成 ——
                # 先按 write_id+sha 确认, 确认到自己的字节才算成功, 否则如实失败。
                if st == 412 and transport_failures and self.confirm(row):
                    self.purge(row)
                    return
                row.update(state='failed', pending_purge=False, status=st)
                self.save(row)
                raise UnsafeWrite(f'conditional write rejected HTTP {st}')
            if _permanent_http(st):
                # 408/429 之外的全部 4xx 都是永久错误(404/405/422 等): 一律不重试、不重放,
                # 与文件头边界「永久性 4xx(412 除外)不重试」一致。400/403/409/412 已由上面分支处理。
                row.update(state='failed', pending_purge=False, status=st)
                self.save(row)
                raise UnsafeWrite(f'write rejected HTTP {st}')
            if self.confirm(row):
                self.purge(row)
                return
            # 未取得确认(HTTP 0 连接断 / 5xx / 200 但 write-id+sha 读不到): 传输层可重放。
            error_kind = ('connection' if st == 0 else
                          ('server_' + str(st) if st >= 500 else 'unconfirmed_http_' + str(st)))
            elapsed_ms = int((time.monotonic() - started) * 1000)
            exhausted = attempt >= attempts
            self._log_retry(row['key'], attempt, error_kind, elapsed_ms, exhausted)
            if exhausted:
                raise UnsafeWrite(f'write unconfirmed HTTP {st}; no fallback')
            transport_failures += 1
            self.a['_work_budget_check']('conditional-write-retry')
            self.a['_work_sleep'](retry_wait(attempt))
