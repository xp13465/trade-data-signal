#!/usr/bin/env python3
"""HC16有界只读追溯。hash/mtime/内嵌源时间分开记录；缺失不外推全历史不存在。"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import tarfile

KEYS=['20261104|csi_000102|buy','20261104|csi_000330|buy','20261104|csi_000673|buy',
      '20261104|gz_399395|buy','20261104|thsc_307940|buy','20261104|thsc_309049|buy','20261105|dax|buy_special']
MAX_FILE=16*1024*1024
MAX_ARCHIVE=160*1024*1024
MAX_TOTAL=300*1024*1024


def inspect(raw):
    out={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'mentions':[k for k in KEYS if k.encode() in raw]}
    try:j=json.loads(raw)
    except (ValueError,UnicodeError):return out
    out['source_time']={k:j[k] for k in ['generated_at','frozen_at','created_at','sample_at','timestamp'] if isinstance(j,dict) and k in j}
    container=j.get('entries',j) if isinstance(j,dict) else {}
    if not isinstance(container,dict):container={}
    out['candidate_records']={k:container[k] for k in KEYS if k in container and isinstance(container[k],dict)}
    # 命中只是候选；台账中的缺键描述不能当真实T0。
    return out


def scan(paths):
    out={'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'keys':KEYS,'files':[],
         'archives':[],'skipped':[],'exhaustive':False,'scanned_bytes':0,
         'candidate_limit':200,'candidates_omitted_by_limit':max(0,len(paths)-200)}
    for path in paths[:200]:
        p=Path(path)
        if p.is_symlink() or not p.is_file():continue
        st=p.stat()
        if p.name.endswith(('.tar','.tgz','.tar.gz')):
            if st.st_size>MAX_ARCHIVE:
                out['skipped'].append({'path':str(p),'reason':'archive compressed byte cap'});continue
            item={'path':str(p),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'source_time':None,'members':[],'complete_listing':False}
            # SHA流式读取有总限额；归档成员只读，不extract。
            if out['scanned_bytes']+st.st_size>MAX_TOTAL:
                out['skipped'].append({'path':str(p),'reason':'total byte cap'});continue
            h=hashlib.sha256()
            with p.open('rb') as f:
                for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
            item['sha256']=h.hexdigest();out['scanned_bytes']+=st.st_size
            logical=0
            with tarfile.open(p,'r|*') as tar:
                for i,m in enumerate(tar):
                    if i>=3000 or logical+m.size>64*1024*1024:
                        item['stop_reason']='member/logical byte cap';break
                    logical+=m.size
                    if any(k in m.name.lower() for k in ('freeze','frozen','t0','manifest')):
                        rec={'name':m.name,'bytes':m.size,'source_member_mtime':m.mtime,'type':m.type.decode(errors='replace')}
                        if m.isfile() and m.size<=MAX_FILE and m.name.endswith(('.json','.jsonl','.md')):
                            rec.update(inspect(tar.extractfile(m).read(MAX_FILE+1)))
                        item['members'].append(rec)
                else:item['complete_listing']=True
            out['archives'].append(item)
        elif st.st_size<=MAX_FILE and out['scanned_bytes']+st.st_size<=MAX_TOTAL:
            raw=p.read_bytes();out['scanned_bytes']+=len(raw)
            rec={'path':str(p),'mtime_ns':st.st_mtime_ns,**inspect(raw)}
            if 'manifest' in p.name.lower():
                try:j=json.loads(raw)
                except (ValueError,UnicodeError):j={}
                # 只列归档里可能的原件路径；不把manifest hash误当内容hash。
                text=json.dumps(j,ensure_ascii=False)
                import re
                rec['freeze_path_hints']=sorted(set(re.findall(r'[^"\s]*?(?:freeze|frozen|t0)[^"\s]*',text,re.I)))[:80]
            out['files'].append(rec)
        else:out['skipped'].append({'path':str(p),'reason':'file/total byte cap'})
    return out


def candidates(roots):
    paths=[];visited=0
    for root in roots:
        root=Path(root)
        if root.is_file():paths.append(str(root));continue
        for base,ds,fs in os.walk(root,followlinks=False):
            depth=len(Path(base).relative_to(root).parts)
            ds[:]=[d for d in ds if d not in {'.git','node_modules','.venv','__pycache__','logs','nav_bucket','public_fund','stock_daily','fund_nav'}]
            if depth>=5:ds[:]=[]
            for name in fs:
                visited+=1
                if visited>40000:return paths,visited,False
                p=Path(base)/name
                if (any(k in str(p).lower() for k in ('freeze','frozen','t0','manifest')) and name.endswith(('.json','.jsonl'))) or name.endswith(('.tar','.tar.gz','.tgz')):
                    paths.append(str(p))
    return paths,visited,True


def main():
    ap=argparse.ArgumentParser();ap.add_argument('roots',nargs='+');args=ap.parse_args()
    signal.alarm(35)
    paths,visited,complete=candidates(args.roots)
    result=scan(paths);result.update(roots=args.roots,candidate_count=len(paths),visited_files=visited,enumeration_complete_within_depth=complete)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
