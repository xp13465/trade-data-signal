#!/usr/bin/env python3
"""父任务手动执行的真实R2探针。默认只生成计划；不使用业务关键键/通知/缓存接口。

plan --bucket NAME --state /tmp/r2-probe.json
execute --state /tmp/r2-probe.json
cleanup --state /tmp/r2-probe.json  # 无服务端条件删除合同：核验后保留对象，列明原因。
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qs
import uuid

from r2_safe_write import durable

PART = 5 * 1024 * 1024


def digest(body):
    return hashlib.sha256(body).hexdigest()


def make_plan(bucket):
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
        raise ValueError('explicit S3 bucket name required')
    prefix = '__codex_validation__/ops-backlog-' + uuid.uuid4().hex + '/'
    return {'version': 1, 'bucket': bucket, 'prefix': prefix, 'status': 'planned',
            'objects': {prefix + n: {'max_bytes': size, 'attempts': []} for n, size in (
                ('cas.bin', 16), ('backup.bin', 16), ('multipart.bin', PART + 31),
                ('lost-response.bin', 16))},
            'multipart_uploads': [], 'results': {},
            'planned_data_upload_bytes_max': 2 * (PART + 31) + 128,
            'data_upload_bytes_max_with_five_part_attempts': 10 * (PART + 31) + 128,
            'cleanup_policy': 'retain: R2 does not document conditional DeleteObject; no unconditional DELETE'}


def validate(plan):
    prefix = plan['prefix']
    if not re.fullmatch(r'__codex_validation__/ops-backlog-[a-f0-9]{32}/', prefix):
        raise ValueError('invalid isolated prefix')
    if set(plan['objects']) != {prefix + n for n in ('cas.bin', 'backup.bin', 'multipart.bin', 'lost-response.bin')}:
        raise ValueError('unexpected object key; production keys forbidden')
    if plan['version'] != 1 or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', plan['bucket']):
        raise ValueError('invalid plan')


class Probe:
    def __init__(self, api, state, plan):
        validate(plan)
        self.api, self.state, self.plan = api, Path(state), plan
        self.lock = threading.Lock()
        self.local = threading.local()
        self.original = api.s3_request
        self.deadline = time.monotonic() + 180
        api._WORK_DEADLINE = self.deadline
        api._WORK_BUDGET_S = 180
        api._WORK_LABEL = 'isolated-probe'
        api.R2_UPLOAD_HTTP_TIMEOUT = 25
        # 每次逻辑请求(含底层重试)最多25s，全部流程180s，分片线程独立计时。
        api._remaining_work = lambda: min(self.deadline,
            getattr(self.local, 'deadline', self.deadline)) - time.monotonic()
        api.s3_request = self.request
        api._MULTIPART_PART_SIZE = PART  # 仅探针进程；不改变生产保护集合。

    def save(self):
        durable(self.state, json.dumps(self.plan, indent=2, sort_keys=True).encode())

    def request(self, method, key, **kwargs):
        if key not in self.plan['objects'] or kwargs.get('bucket', self.plan['bucket']) != self.plan['bucket']:
            raise ValueError('request escaped exact probe allowlist')
        if method not in ('GET', 'PUT', 'POST', 'DELETE'):
            raise ValueError('unsupported probe operation')
        query = kwargs.get('query', '')
        if method == 'DELETE':
            uid = parse_qs(query).get('uploadId', [''])[0]
            if not uid or {'key': key, 'upload_id': uid} not in self.plan['multipart_uploads']:
                raise ValueError('object DELETE forbidden; only own known multipart abort allowed')
        kwargs['bucket'] = self.plan['bucket']
        self.local.deadline = time.monotonic() + 25
        try:
            result = self.original(method, key, **kwargs)
            if method == 'POST' and query == 'uploads=' and result[0] == 200:
                uid = self.api._parse_upload_id(result[1])
                if uid:
                    with self.lock:
                        self.plan['multipart_uploads'].append({'key': key, 'upload_id': uid})
                        self.save()
            if method == 'POST' and 'uploadId=' in query:
                with self.lock:
                    self.plan.setdefault('complete_requests', []).append({
                        'key': key, 'query': query, 'conditions': kwargs.get('extra_headers'),
                        'status': result[0]})
                    self.save()
            return result
        finally:
            self.local.deadline = self.deadline

    def get(self, key):
        st, body, headers = self.request('GET', key, with_headers=True, progress_label=key)
        if st == 404 and b'NoSuchKey' in body:
            return None
        if st != 200 or str(len(body)) != self.api._header_lookup(headers, 'content-length'):
            raise RuntimeError(f'GET not confirmed: {st}')
        return body, headers

    def confirmed(self, key, body, write_id):
        for _ in range(2):
            obj = self.get(key)
            if (obj and digest(obj[0]) == digest(body) and
                    self.api._header_lookup(obj[1], 'x-amz-meta-write-id') == write_id):
                with self.lock:
                    self.plan['objects'][key]['confirmed'] = {
                        'sha256': digest(body), 'size': len(body), 'write_id': write_id,
                        'etag': self.api._header_lookup(obj[1], 'etag')}
                    self.save()
                return obj
        raise RuntimeError('original write-id/hash not confirmed; retain object and journal')

    def write(self, key, body, condition, multipart=False, before_complete=None, lose_response=False):
        write_id = uuid.uuid4().hex
        headers = {**condition, 'x-amz-meta-write-id': write_id}
        with self.lock:
            self.plan['objects'][key]['attempts'].append({
                'sha256': digest(body), 'size': len(body), 'write_id': write_id,
                'conditions': condition})
            self.save()  # 发送前记归属；响应丢失也能按原id核验，不新建许可。
        try:
            if multipart:
                st, _ = self.api._multipart_upload(key, len(body), lambda off, n: body[off:off+n],
                    'application/octet-stream', bucket=self.plan['bucket'], extra_headers=headers,
                    before_complete=before_complete)
            else:
                st, _ = self.request('PUT', key, payload=body, extra_headers=headers)
            if lose_response and st == 200:
                raise OSError('probe intentionally discarded successful response')
        except OSError:
            self.confirmed(key, body, write_id)
            return 200
        if st == 200:
            self.confirmed(key, body, write_id)
        return st

    def run(self):
        if self.plan['status'] != 'planned':
            raise ValueError('plan already attempted; do not blindly replay, use a new unique plan')
        self.plan['status'] = 'running'; self.save()
        p = self.plan['prefix']
        # 所有新键先GET，写入仍必须If-None-Match，避免检查与写之间竞态。
        for key in self.plan['objects']:
            if self.get(key) is not None:
                raise RuntimeError('prefix collision; no existing object may be overwritten')
        cas = p + 'cas.bin'; old = b'old-probe-bytes'
        assert self.write(cas, old, {'if-none-match': '*'}) == 200
        obj = self.get(cas)
        condition = {'if-match': self.api._header_lookup(obj[1], 'etag')}
        # 同一GET读得的旧bytes备份+逐字节hash回读。
        assert self.write(p + 'backup.bin', obj[0], {'if-none-match': '*'}) == 200
        assert digest(self.get(p + 'backup.bin')[0]) == digest(old)
        self.plan['results']['backup_readback'] = True
        barrier = threading.Barrier(2, timeout=10)
        def contender(body):
            barrier.wait()
            return self.write(cas, body, condition)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(contender, b'writer-A'), pool.submit(contender, b'writer-B')]
            statuses = sorted(f.result() for f in futures)
        assert statuses == [200, 412], statuses
        self.plan['results']['same_condition_two_writers'] = statuses
        multi = p + 'multipart.bin'
        assert self.write(multi, b'seed', {'if-none-match': '*'}) == 200
        etag = self.api._header_lookup(self.get(multi)[1], 'etag')
        def race_at_complete(query, xml):
            assert xml.count(b'<Part>') == 2
            assert self.write(multi, b'rival', {'if-match': etag}) == 200
        payload = b'm' * PART + b'n' * 31
        status = self.write(multi, payload, {'if-match': etag}, multipart=True,
                            before_complete=race_at_complete)
        assert status == 412, status
        assert self.get(multi)[0] == b'rival'
        fresh = self.api._header_lookup(self.get(multi)[1], 'etag')
        assert self.write(multi, payload, {'if-match': fresh}, multipart=True) == 200
        self.plan['results']['multipart_final_complete'] = [412, 200]
        assert self.write(p + 'lost-response.bin', b'original-id', {'if-none-match': '*'},
                          lose_response=True) == 200
        self.plan['results']['discarded_response_original_write_id'] = True
        self.plan['status'] = 'passed'; self.save()

    def cleanup(self):
        # R2未给DeleteObject原子条件合同。即使GET匹配也不能消除TOCTOU；宁留不误删。
        # 不递归LIST/不删除未知版本；完整归属状态供父任务与服务端生命周期决策。
        report = {}
        for key, entry in self.plan['objects'].items():
            obj = self.get(key)
            if obj is None:
                report[key] = 'absent'
                continue
            write_id = self.api._header_lookup(obj[1], 'x-amz-meta-write-id')
            owned = any(a['write_id'] == write_id and a['sha256'] == digest(obj[0])
                        for a in entry['attempts'])
            report[key] = 'owned-but-retained-no-atomic-delete-contract' if owned else 'UNKNOWN-retained'
        self.plan['cleanup'] = report; self.save()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'execute', 'cleanup'))
    parser.add_argument('--bucket')
    parser.add_argument('--state', required=True, type=Path)
    args = parser.parse_args()
    if not args.state.is_absolute():
        parser.error('--state must be an absolute isolated /tmp path')
    if not args.state.resolve().is_relative_to(Path('/tmp').resolve()):
        parser.error('--state must be under /tmp')
    if args.action == 'plan':
        if args.state.exists():
            parser.error('state already exists; never replace a previous probe ledger')
        plan = make_plan(args.bucket or '')
        durable(args.state, json.dumps(plan, indent=2).encode())
        print(json.dumps(plan, indent=2)); return
    plan = json.loads(args.state.read_text()); validate(plan)
    print('EXACT_PLAN: ' + json.dumps(plan), flush=True)
    # 只在显式execute/cleanup时加载现有标准库SigV4客户端及其凭据；默认plan零网络。
    os.environ['REPO'] = str(args.state.parent / (args.state.stem + '-runtime'))
    api = importlib.import_module('upload_r2')
    probe = Probe(api, args.state, plan)
    try:
        if args.action == 'execute':
            probe.run()
        else:
            print(json.dumps(probe.cleanup(), indent=2))
    except BaseException as exc:
        plan['error_type'] = type(exc).__name__
        probe.save()
        raise
    print('R2_ISOLATED_PROBE: ' + plan['status'])


if __name__ == '__main__':
    main()
