"""Real async wrapper, inert child programs and isolated paths; no real upload/mail."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('enabled,optin,upload_rc,readback_rc,expected_calls', [
    ('0','1',0,0,['upload']), ('1','0',0,0,['upload']),
    ('1','1',0,0,['upload','verify']), ('1','1',0,7,['upload','verify']),
    ('1','1',2,0,['upload','notify'])])
def test_async_readback_does_not_change_upload_result(tmp_path, enabled, optin, upload_rc, readback_rc, expected_calls):
    root = Path(__file__).resolve().parents[2]
    (tmp_path/'scripts/lib').mkdir(parents=True)
    (tmp_path/'.venv/bin').mkdir(parents=True)
    script = tmp_path/'scripts/fund_nav_upload_async.sh'
    shutil.copyfile(root/'scripts/fund_nav_upload_async.sh', script)
    (tmp_path/'scripts/lib/repo_paths.sh').write_text('resolve_repo() { :; }\n')
    py = tmp_path/'.venv/bin/python'
    py.write_text('''#!/usr/bin/env python3
import os,sys,json
name=os.path.basename(sys.argv[1])
kind={'upload_r2.py':'upload','notify.py':'notify','ops_nav_publication.py':'verify'}[name]
with open(os.environ['TEST_CALLS'],'a') as f:f.write(json.dumps([kind,sys.argv[2:]])+'\\n')
raise SystemExit(int(os.environ['TEST_UPLOAD_RC'] if kind=='upload' else os.environ['TEST_READBACK_RC'] if kind=='verify' else '0'))
''')
    py.chmod(0o700)
    calls = tmp_path/'calls'
    env = dict(os.environ, REPO=str(tmp_path), GIT_REPO=str(tmp_path), FUND_NAV_UPLOAD_LOCKED='1',
               OPS_DELIVERY_EVIDENCE_ENABLED=enabled, OPS_NAV_PUBLIC_READBACK_ENABLED=optin,
               TEST_CALLS=str(calls), TEST_UPLOAD_RC=str(upload_rc), TEST_READBACK_RC=str(readback_rc))
    result = subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True, timeout=10)
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    assert result.returncode == upload_rc, result.stdout+result.stderr
    assert [x[0] for x in recorded] == expected_calls
    if 'verify' in expected_calls:
        assert recorded[-1][1] == ['verify','--root',str(tmp_path),'--seconds','60','--max-bytes','67108864']
