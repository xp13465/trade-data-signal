#!/usr/bin/env python3
"""HC16日期索引/归档manifest定向追溯；只读，限20秒/3万路径/32MiB。"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess

KEYS=['20261104|csi_000102|buy','20261104|csi_000330|buy','20261104|csi_000673|buy',
      '20261104|gz_399395|buy','20261104|thsc_307940|buy','20261104|thsc_309049|buy','20261105|dax|buy_special']
DATES=('20261104','20261105','2026-11-04','2026-11-05')


def inspect(path):
    raw=path.read_bytes();st=path.stat()
    rec={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'mtime_ns':st.st_mtime_ns,
         'mentions':[k for k in KEYS if k.encode() in raw],'source_time':None}
    try:j=json.loads(raw)
    except (ValueError,UnicodeError):return rec
    if isinstance(j,dict):
        rec['source_time']={k:j[k] for k in ('created_at','generated_at','frozen_at','sample_at','timestamp') if k in j}
        entries=j.get('entries',j)
        if isinstance(entries,dict):
            rec['exact_candidates']={k:entries[k] for k in KEYS if k in entries}
            rec['date_index_keys']={k:[n for n in entries if n.startswith('|'.join(k.split('|')[:2])+'|')] for k in KEYS}
        if isinstance(j.get('files'),list):
            rec['manifest_file_count']=len(j['files'])
            rec['manifest_relevant_members']=[f for f in j['files'] if isinstance(f,dict) and any(t in str(f.get('path','')).lower() for t in ('freeze','frozen',*DATES))]
    return rec


def run(roots,repos):
    out={'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'scope':roots,'keys':KEYS,
         'exhaustive':False,'visited_files':0,'candidates':[],'files':[],'skipped':[],'git_history':[]}
    for root in map(Path,roots):
        if root.is_file():out['candidates'].append(str(root));continue
        for base,ds,fs in os.walk(root,followlinks=False):
            ds[:]=[d for d in ds if d not in {'.git','node_modules','.venv','logs','nav_bucket','public_fund','stock_daily','fund_nav','__pycache__'}]
            if len(Path(base).relative_to(root).parts)>=4:ds[:]=[]
            for name in fs:
                out['visited_files']+=1
                if out['visited_files']>30000:break
                p=Path(base)/name
                if name.endswith(('.json','.jsonl')) and any(d in str(p) for d in DATES):out['candidates'].append(str(p))
            if out['visited_files']>30000:break
        if out['visited_files']>30000:break
    total=0
    for path in sorted(set(out['candidates']),key=lambda p:('freeze' not in p and 'manifest' not in p,p))[:80]:
        p=Path(path)
        if p.is_symlink() or p.stat().st_size>8*1024*1024 or total+p.stat().st_size>32*1024*1024:
            out['skipped'].append(path);continue
        rec=inspect(p);out['files'].append(rec);total+=rec['bytes']
    out['scanned_bytes']=total
    out['candidate_limit']=80
    for repo in repos:
        args=['git','-C',repo,'log','--all','--since=2026-11-03T00:00:00+08:00','--until=2026-11-07T23:59:59+08:00',
              '-n','40','--format=%H %cI','--name-only','--','*freeze*.json','*frozen*.json']
        try:
            p=subprocess.run(args,capture_output=True,timeout=4,env=dict(os.environ,GIT_OPTIONAL_LOCKS='0'))
            out['git_history'].append({'repo':repo,'exit':p.returncode,'output':p.stdout.decode(errors='replace')[:20000],
                                       'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr':p.stderr.decode(errors='replace')[:1000]})
        except subprocess.TimeoutExpired:out['git_history'].append({'repo':repo,'timeout_seconds':4})
    return out


if __name__=='__main__':
    signal.alarm(20)
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('roots',nargs='+');ap.add_argument('--repo',action='append',default=[])
    args=ap.parse_args();print(json.dumps(run(args.roots,args.repo),ensure_ascii=False,indent=2))
