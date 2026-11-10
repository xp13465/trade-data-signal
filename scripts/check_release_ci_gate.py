#!/usr/bin/env python3
"""Read-only release guard. Run from the checkout pinned to GITHUB_SHA.

Only push/workflow_dispatch on this repository's current main may release.
PyYAML is already a CI dependency. No dispatch, rerun, or deployment API writes.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

REPOSITORY = 'xp13465/trade-data-signal'
OPS = 'ops-monitoring-checks.yml'
QUALITY = 'ci.yml'
SHA = re.compile(r'[0-9a-f]{40}')
PENDING = {'queued', 'in_progress', 'waiting', 'pending', 'requested'}
RECOVERY = ('在 Actions 重跑该 SHA 的 CI Quality Gate；Ops 缺运行时，'
            '在 main 手动运行 Operations monitoring checks，成功后重跑部署。'
            'main 已前进则只发布新 main，不能用旧 SHA 补跑发布。')


class GateError(Exception):
    pass


class GitHub:
    def __init__(self, token):
        self.token = token

    def get(self, path):
        request = Request('https://api.github.com/repos/' + REPOSITORY + path,
                          headers={'Authorization': 'Bearer ' + self.token,
                                   'Accept': 'application/vnd.github+json',
                                   'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as exc:
            raise GateError(f'GitHub API HTTP {exc.code}，拒绝发布') from None
        except (URLError, TimeoutError, ValueError, OSError):
            # Never print response bodies, request headers, environment, or token.
            raise GateError('GitHub API 不可读，拒绝发布') from None


def require(condition, message):
    if not condition:
        raise GateError(message)


def validate_context(event, event_name, repository, ref, sha, checkout_sha):
    require(repository == REPOSITORY and event.get('repository', {}).get('full_name') == REPOSITORY
            and event.get('repository', {}).get('fork') is False,
            '仅可信源仓库可发布')
    require(ref == 'refs/heads/main' and event_name in {'push', 'workflow_dispatch'},
            '仅 main push/manual 可发布')
    require(SHA.fullmatch(sha) and sha == checkout_sha, 'checkout 必须固定为事件 SHA')
    if event_name == 'push':
        require(event.get('ref') == ref, '事件 ref 不匹配')
        require(event.get('after') == sha and not event.get('deleted'), 'push head 不匹配')


def path_regex(pattern):
    """Deliberately support only the current Ops pattern subset; unknown => require Ops."""
    require(isinstance(pattern, str) and pattern and
            re.fullmatch(r'[A-Za-z0-9_./*\-]+', pattern), 'Ops 路径模式不支持')
    result = []
    parts = pattern.split('/')
    for index, part in enumerate(parts):
        if part == '**':
            result.append('.*' if index == len(parts) - 1 else '(?:[^/]+/)*')
        else:
            require('**' not in part and part not in {'', '.', '..'}, 'Ops 路径模式不支持')
            result.append(''.join('[^/]*' if c == '*' else re.escape(c) for c in part))
            if index < len(parts) - 1:
                result.append('/')
    return re.compile(''.join(result) + r'\Z')


def ops_input_patterns(workflow_text):
    """Workflow paths 是唯一输入分类；push/PR 必须逐项一致，避免第二份路径表漂移。"""
    config = yaml.load(workflow_text, Loader=yaml.BaseLoader)['on']
    push = config['push']
    require(set(push) == {'branches', 'paths'} and 'main' in push['branches'],
            'Ops push 规则无法判定')
    require(isinstance(push['paths'], list) and push['paths'], 'Ops paths 缺失')
    require(config['pull_request']['paths'] == push['paths'], 'Ops push/PR 输入分类不一致')
    return [path_regex(pattern) for pattern in push['paths']]


def ops_expected(api, event, event_name, sha, workflow_text):
    # YAML BaseLoader keeps the Actions key "on" as a string (YAML 1.1 bool otherwise).
    try:
        patterns = ops_input_patterns(workflow_text)
    except (yaml.YAMLError, KeyError, TypeError, GateError):
        return True, 'Ops 规则未知，必须补跑 Ops'
    before = event.get('before', '')
    if event_name != 'push' or not isinstance(before, str) or not SHA.fullmatch(before) or before == '0' * 40:
        return True, '无有效 push before，必须补跑 Ops'
    # The exact entire push, not HEAD^; only an ancestor comparison proves a two-dot diff.
    diff = api.get(f'/compare/{before}...{sha}?per_page=100&page=1')
    files = diff.get('files')
    require(isinstance(files, list), 'compare files 缺失')
    if (diff.get('status') != 'ahead' or diff.get('merge_base_commit', {}).get('sha') != before
            or diff.get('base_commit', {}).get('sha') != before
            or not isinstance(diff.get('total_commits'), int)
            or diff['total_commits'] <= 0 or diff['total_commits'] >= 1000
            or len(files) >= 300):
        return True, 'compare 范围不完整或无法确定，必须补跑 Ops'
    for file in files:
        require(isinstance(file, dict) and isinstance(file.get('filename'), str) and file['filename']
                and file.get('status') in {'added', 'removed', 'modified', 'renamed',
                                           'copied', 'changed', 'unchanged'}, 'compare 文件记录缺失')
        if file.get('status') == 'renamed':
            require(isinstance(file.get('previous_filename'), str), 'rename 原路径缺失')
        for name in (file['filename'], file.get('previous_filename', '')):
            if any(pattern.fullmatch(name) for pattern in patterns):
                return True, 'push 命中 Ops paths'
    return False, '完整 push compare 未命中 Ops paths'


def trusted(run, sha, workflow):
    return (run.get('head_sha') == sha and run.get('head_branch') == 'main'
            and run.get('event') in {'push', 'workflow_dispatch'}
            and run.get('repository', {}).get('full_name') == REPOSITORY
            and run.get('head_repository', {}).get('full_name') == REPOSITORY
            and run.get('head_repository', {}).get('fork') is False
            and run.get('path', '').split('@')[0] == '.github/workflows/' + workflow)


def latest_run(api, workflow, sha):
    runs = []
    page = 1
    while True:
        query = urlencode({'head_sha': sha, 'per_page': 100, 'page': page})
        response = api.get(f'/actions/workflows/{workflow}/runs?{query}')
        batch, total = response.get('workflow_runs'), response.get('total_count')
        require(isinstance(batch, list) and isinstance(total, int) and 0 <= total < 1000,
                'workflow runs 列表不完整')
        require(all(isinstance(run, dict) and
                    all(key in run for key in ('id', 'run_attempt', 'workflow_id', 'head_sha',
                                              'head_branch', 'event', 'repository',
                                              'head_repository', 'path', 'status', 'conclusion', 'updated_at'))
                    for run in batch), 'workflow run 记录无效或字段缺失')
        runs.extend(batch)
        if len(runs) >= total:
            require(len(runs) == total, 'workflow runs 分页不一致')
            break
        require(len(batch) == 100 and page < 10, 'workflow runs 分页缺失')
        page += 1
    candidates = [run for run in runs if trusted(run, sha, workflow)]
    if not candidates:
        return None
    require(all(type(run.get('id')) is int and type(run.get('run_attempt')) is int
                and run['id'] > 0 and run['run_attempt'] > 0
                and type(run.get('workflow_id')) is int and run['workflow_id'] > 0
                and isinstance(run.get('updated_at'), str)
                and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', run['updated_at'])
                for run in candidates), 'run id/attempt 缺失')
    # An older run ID can be rerun after a newer green run: activity time must win.
    selected = max(candidates, key=lambda run: (run['updated_at'], run['id'], run['run_attempt']))
    # This endpoint returns the current attempt; never request /attempts/<old green>.
    current = api.get(f"/actions/runs/{selected['id']}")
    require(trusted(current, sha, workflow) and current.get('id') == selected['id']
            and current.get('workflow_id') == selected.get('workflow_id')
            and type(current.get('run_attempt')) is int
            and current['run_attempt'] >= selected['run_attempt'], 'run 当前 attempt/身份不匹配')
    return current


def current_main(api, sha):
    require(api.get('/git/ref/heads/main').get('object', {}).get('sha') == sha,
            'main 已前进或无法读取，拒绝旧 head 发布')


def wait_for_ci(api, sha, expect_ops, timeout, *, now=time.monotonic, sleep=time.sleep, discovery_timeout=120):
    started = now()
    deadline = started + timeout
    discovery_deadline = started + min(timeout, discovery_timeout)
    while True:
        current_main(api, sha)
        quality = latest_run(api, QUALITY, sha)
        ops = latest_run(api, OPS, sha)
        required = [(QUALITY, quality)]
        if expect_ops or ops is not None:
            required.append((OPS, ops))
        complete = True
        for workflow, run in required:
            if run is None:
                complete = False
                continue
            status, conclusion = run.get('status'), run.get('conclusion')
            if status == 'completed':
                require(conclusion == 'success', f'{workflow} 最新 attempt 未成功，拒绝发布')
            else:
                require(status in PENDING and conclusion is None, f'{workflow} 状态未知，拒绝发布')
                complete = False
        if complete:
            current_main(api, sha)
            return 'quality=success ops=' + ('success' if len(required) == 2 else 'not-triggered')
        if any(run is None for _, run in required):
            require(now() < discovery_deadline, '同 SHA CI 运行缺失，发现等待超时，需补跑后重试')
        remaining = deadline - now()
        require(remaining > 0, '等待同 SHA CI 超时或运行缺失，拒绝发布')
        sleep(min(15, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=int, default=2100,
                        help='等待秒数；临发布复核用 0，仅检查当前结论')
    args = parser.parse_args()
    try:
        require(0 <= args.timeout <= 2100, 'timeout 超出范围')
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        sha = os.environ['GITHUB_SHA']
        checkout = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=5).strip()
        validate_context(event, os.environ['GITHUB_EVENT_NAME'], os.environ['GITHUB_REPOSITORY'],
                         os.environ['GITHUB_REF'], sha, checkout)
        require(bool(os.environ.get('GITHUB_TOKEN')), '缺 GITHUB_TOKEN')
        api = GitHub(os.environ['GITHUB_TOKEN'])
        current_main(api, sha)
        expected, reason = ops_expected(api, event, os.environ['GITHUB_EVENT_NAME'], sha,
                                       Path('.github/workflows/' + OPS).read_text())
        summary = wait_for_ci(api, sha, expected, args.timeout,
                              discovery_timeout=0 if os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch' else 120)
        print(f'RELEASE_CI_GATE_OK head={sha} {summary}; {reason}')
        return 0
    except (GateError, AttributeError, KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        # Only our controlled messages are safe; other exceptions may contain process/env details.
        message = str(exc) if isinstance(exc, GateError) else '门禁输入/运行失败，拒绝发布'
        print('RELEASE_CI_GATE_BLOCKED: ' + message + '。' + RECOVERY, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
