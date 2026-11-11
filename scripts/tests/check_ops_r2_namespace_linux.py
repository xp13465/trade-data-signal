"""Disposable CI namespace check; never starts a Trade production unit."""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import r2_pending_context as q


def probe(flag, root, sibling):
    assert not Path(sibling).exists(), 'PrivateTmp must still hide unrelated host files'
    report = q.inspect_contexts(flag, root, budget_seconds=2)
    assert report['inspection_status'] == 'complete', report['issues']
    assert report['counts']['pending'] == 1
    assert report['status'] == 'unknown'  # pending is not successful delivery
    directory = Path(str(flag) + '.contexts')
    proof = next(directory.glob('*.proof'))
    try:
        with proof.open('ab') as stream:
            stream.write(b'forbidden')
    except OSError as exc:
        assert exc.errno == errno.EROFS, exc
    else:
        raise AssertionError('queue bind is writable')
    print('PROBE_PASS: host queue visible read-only; unrelated host tmp hidden; pending remains unknown')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--flag')
    parser.add_argument('--root')
    parser.add_argument('--sibling')
    args = parser.parse_args()
    if args.probe:
        probe(args.flag, args.root, args.sibling)
        return
    if sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Run only on the disposable Linux CI runner')
    name = 'codex-ops-r2-namespace-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='codex-ops-r2-ci-', dir='/tmp') as value:
        base = Path(value).resolve()
        flag, root, sibling = base / 'pending', base / 'static-site', base / 'host-only'
        sibling.write_text('isolated-fixture')
        source = base / 'source.json'
        source.write_text(json.dumps({'version': 1, 'run_id': 'namespace-fixture',
            'static_dir': str(root), 'outputs': {'data/test.json': {
                'size': 2, 'sha256': hashlib.sha256(b'{}').hexdigest()}}}))
        q.enqueue(flag, root, source, 'namespace-fixture')
        directory = Path(str(flag) + '.contexts')
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}
        command = ['sudo', '-n', 'systemd-run', '--unit=' + name, '--collect', '--wait', '--pipe',
                   '--property=User=' + pwd.getpwuid(os.getuid()).pw_name,
                   '--property=PrivateTmp=yes', '--property=ProtectSystem=strict',
                   '--property=NoNewPrivileges=yes', '--property=RuntimeMaxSec=20',
                   '--property=TimeoutStartSec=20', '--property=BindReadOnlyPaths=-' + str(directory),
                   sys.executable, '-B', str(Path(__file__).resolve()), '--probe',
                   '--flag', str(flag), '--root', str(root), '--sibling', str(sibling)]
        try:
            result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=45)
            print(result.stdout, end='')
            assert result.returncode == 0, 'namespace probe failed'
            assert 'PROBE_PASS:' in result.stdout
        finally:
            # Only this uniquely named temporary test unit may be stopped.
            subprocess.run(['sudo', '-n', 'systemctl', 'stop', name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}
        assert before == after, 'read-only inspection changed the host queue'
        assert sibling.read_text() == 'isolated-fixture'
    print('SYSTEMD_R2_NAMESPACE_OK: temporary fixture removed; no production unit or queue used')


if __name__ == '__main__':
    main()
