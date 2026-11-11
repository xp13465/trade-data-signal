#!/usr/bin/env python3
"""HC19/20 精确隔离和清理。默认dry-run，apply必须有固定head/hash及完成证据。

不通知、不改源码、不删分支。所有外部命令有timeout；备份/恢复/复核任一失败即停。
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tarfile
import tempfile

REPO = Path('/Users/linhuichen/code/trade')
TREES = REPO / '.claude/worktrees'
ARCHIVE = Path('/Users/linhuichen/.local/share/trade-audit/20261111/ops-backlog-cleanup')
ALERT_TREE = 'agent-ae637b217439bb921'
ALERT_HEAD = '61a56ce7fc037e0a9f8ce8aad018ee1c173edd95'
PACKETS = Path('/tmp/codex-reports/handoffs')
ALERT_HASH = 'c18fc064357244910150efb080304fb08f32117d48b00d7a4c0356403f6b3683'
ALLOWED = {
 'codex-fof-nav-completeness-20261109': 'b1f20bca27d96db15a07230f7bed0d9e0f7d6f9e',
 'codex-fund-index-reconnect-20261109': 'e30d1c90a9482e754b802be202e9cd7d59b9875a',
 'codex-ops-fund-budget-20261110': '01aa15a9bdfa54d95cccedffe2b9525ba99e02d3',
}


def command(args, timeout=20, allowed=(0,), input_bytes=None):
    proc = subprocess.Popen(args, stdin=subprocess.PIPE if input_bytes is not None else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env=dict(os.environ,GIT_OPTIONAL_LOCKS='0'))
    try:
        out, err = proc.communicate(input=input_bytes, timeout=timeout)
    except BaseException:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    if proc.returncode not in allowed:
        raise RuntimeError(f'{args[:3]} exit {proc.returncode}: {err.decode(errors="replace")[-500:]}')
    return out


def git(tree, *args):
    return command(['git', '-C', str(tree), *args])


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def relative(name):
    p = Path(name)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError('非安全相对路径')
    return p


def manifest(root, names):
    out = {}
    for name in sorted(set(names)):
        rel = relative(name)
        # 禁止通过父目录symlink读取/删除树外内容。
        for parent in rel.parents:
            if parent != Path('.') and (root/parent).is_symlink():
                raise ValueError('路径父级是symlink')
        p = root/rel
        st = p.lstat()
        rec = {'mode': stat.S_IMODE(st.st_mode), 'mtime_ns': st.st_mtime_ns}
        if stat.S_ISLNK(st.st_mode):
            rec.update(kind='symlink', target=os.readlink(p), bytes=st.st_size)
        elif stat.S_ISREG(st.st_mode):
            rec.update(kind='file', bytes=st.st_size, sha256=digest_file(p))
        elif stat.S_ISDIR(st.st_mode):
            rec.update(kind='dir', bytes=0)
        else:
            raise ValueError('拒绝特殊文件')
        out[str(rel)] = rec
    return out


def same_content(a, b):
    # 恢复后权限、内容、symlink逐项一致；tar不用于保纳秒时间。
    clean=lambda m:{n:{k:v for k,v in r.items() if k!='mtime_ns'} for n,r in m.items()}
    return clean(a)==clean(b)


def backup_restore(root, names, dest):
    dest.mkdir(parents=True, exist_ok=False, mode=0o700)
    original=manifest(root,names)
    (dest/'manifest.json').write_text(json.dumps(original,ensure_ascii=False,indent=2))
    archive=dest/'payload.tar'
    with tarfile.open(archive,'w') as tar:
        for name, rec in original.items():
            info=tarfile.TarInfo(name);info.mode=rec['mode'];info.mtime=rec['mtime_ns']//10**9
            if rec['kind']=='file':
                info.size=rec['bytes']
                with (root/name).open('rb') as f:tar.addfile(info,f)
            elif rec['kind']=='symlink':
                info.type=tarfile.SYMTYPE;info.linkname=rec['target'];tar.addfile(info)
            else:info.type=tarfile.DIRTYPE;tar.addfile(info)
    archive.chmod(0o600)
    restore=dest/'restore-check';restore.mkdir(mode=0o700)
    restore_archive(archive, restore, original)
    if original!=manifest(restore,names):
        raise RuntimeError('恢复manifest不一致')
    if manifest(root,names)!=original:
        raise RuntimeError('备份期间源变化')
    receipt={'archive_sha256':digest_file(archive),'entries':len(original),'restore_verified':True}
    (dest/'verified.json').write_text(json.dumps(receipt,indent=2))
    return original, receipt


def restore_archive(archive, root, expected):
    if any(root.iterdir()):raise ValueError('恢复目录必须为空')
    seen=set()
    with tarfile.open(archive,'r:') as tar:
        for member in tar:
            rel=relative(member.name);name=str(rel)
            if name not in expected or name in seen:raise ValueError('归档成员不匹配')
            seen.add(name)
            for parent in rel.parents:
                if parent!=Path('.') and (root/parent).is_symlink():raise ValueError('恢复穿过symlink')
            target=root/rel;target.parent.mkdir(parents=True,exist_ok=True)
            rec=expected[name]
            if member.isfile() and rec['kind']=='file':
                with tar.extractfile(member) as src,target.open('xb') as dst:
                    for chunk in iter(lambda:src.read(1024*1024),b''):dst.write(chunk)
                target.chmod(rec['mode'])
            elif member.issym() and rec['kind']=='symlink' and member.linkname==rec['target']:
                target.symlink_to(member.linkname)
            elif member.isdir() and rec['kind']=='dir':
                target.mkdir(exist_ok=True);target.chmod(rec['mode'])
            else:raise ValueError('归档类型不匹配')
    if seen!=set(expected):raise RuntimeError('恢复成员不完整')
    # tar头仅秒精度；独立manifest保留纳秒。先子后父，避免建子项改变父目录时间。
    for name in sorted(seen,key=lambda n:len(Path(n).parts),reverse=True):
        ns=expected[name]['mtime_ns']
        os.utime(root/name,ns=(ns,ns),follow_symlinks=False)
    if expected!=manifest(root,seen):
        raise RuntimeError('恢复内容验证失败')


def inactive(tree):
    # 拒绝所有打开句柄（比只拦writer更严格）；+D包含cwd，独立检查退出码。
    raw=command(['lsof','-nP','+D',str(tree),'-F','pcfatn'],allowed=(0,1))
    if raw.strip():raise RuntimeError('树存在cwd/打开句柄，保留')
    # 不运行git自身会占用待删树的cwd；调用方始终在本独立工作树。


def guard(tree, head, *, merged=False):
    raw=git(REPO,'worktree','list','--porcelain').decode()
    blocks=[b for b in raw.split('\n\n') if b.startswith('worktree '+str(tree)+'\n')]
    if len(blocks)!=1 or '\nlocked' in blocks[0] or '\nprunable' in blocks[0]:
        raise RuntimeError('工作树登记/锁状态不符')
    if git(tree,'rev-parse','HEAD').decode().strip()!=head:raise RuntimeError('head变化')
    if git(tree,'status','--porcelain').strip():raise RuntimeError('dirty/untracked树禁止改动')
    if merged:git(tree,'merge-base','--is-ancestor',head,'main')
    inactive(tree)
    return {'registry':blocks[0],'head':head,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat()}


def alert_plan(path):
    raw=path.read_bytes()
    if sha(raw)!=ALERT_HASH:raise ValueError('latest不是批准的固定hash')
    import re
    starts=[m.start() for m in re.finditer(rb'(?m)^---\n(?=## \[)',raw)]
    blocks=[raw[a:b] for a,b in zip(starts,starts[1:]+[len(raw)])]
    if len(blocks)!=3:raise ValueError('不是精确三个测试块')
    for block in blocks:
        if not block.startswith(b'---\n## [digest] 2026-11-10 09:18:09 ') or b'test:h_existing' not in block:
            raise ValueError('块身份不符')
        if b'## [severe]' in block:raise ValueError('拒绝真实严重块')
    return raw[:starts[0]], blocks


def quarantine(tree, dest, *, apply=False):
    if tree != TREES/ALERT_TREE:raise ValueError('非批准告警树')
    head=ALERT_HEAD
    initial_guard=guard(tree,head)
    latest=tree/'data/alerts/latest.md'
    keep,blocks=alert_plan(latest)
    names=['data/alerts/'+p.name for p in (tree/'data/alerts').iterdir() if p.is_file() and not p.is_symlink()]
    plan={'action':'quarantine','before_sha256':ALERT_HASH,'after_sha256':sha(keep),
          'blocks':[sha(b) for b in blocks],'retain_prefix_bytes':len(keep),'files':names,
          'alert_ledger_present':(tree/'data/alerts/alert_ledger.jsonl').exists(),'guard':initial_guard}
    if not apply:return plan
    original,receipt=backup_restore(tree,names,dest)
    (dest/'removed-blocks.md').write_bytes(b''.join(blocks))
    (dest/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    guard(tree,head)
    if manifest(tree,names)!=original or digest_file(latest)!=ALERT_HASH:raise RuntimeError('CAS前源变化')
    # 与现有notify镜像写者共用锁，绝不运行notify/发送路径。
    import fcntl
    lock=tree/'data/alerts/.latest.lock'
    lock_created = not lock.exists()
    if lock.is_symlink():raise ValueError('lock不能为symlink')
    with lock.open('a') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if manifest(tree,names)!=original:raise RuntimeError('锁内CAS失败')
        fd,tmp=tempfile.mkstemp(prefix='.hc19-',dir=latest.parent)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write(keep);out.flush();os.fsync(out.fileno())
                os.fchmod(out.fileno(),original['data/alerts/latest.md']['mode'])
            if digest_file(latest)!=ALERT_HASH:raise RuntimeError('rename前CAS失败')
            os.replace(tmp,latest)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)  # 仅本次自产临时文件
    after=manifest(tree,names)
    if digest_file(latest)!=sha(keep):raise RuntimeError('隔离后hash不符')
    for name in names:
        if name!='data/alerts/latest.md' and after[name]!=original[name]:raise RuntimeError('原ledger变化')
    result=dict(plan,applied=True,backup=receipt,after=after,coordination_lock_created=lock_created)
    (dest/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def completion_evidence(tree, head):
    source = ('docs/codex-reviews/ops-alert-recovery-20261110/verification.json'
              if tree.name == 'codex-ops-fund-budget-20261110' else
              'docs/codex-reviews/alert-rootfix-20261109/continued-implementation-20261109.md')
    evidence=Path(__file__).resolve().parents[3]/source
    if head not in evidence.read_text():raise ValueError('缺本轮完成记录，不能仅凭祖先关系删除')
    return {'completion_evidence':str(evidence),'completion_evidence_sha256':digest_file(evidence)}


def worktree_plan(tree):
    if tree.parent!=TREES or tree.name not in ALLOWED:raise ValueError('非批准Codex已完成树')
    head=ALLOWED[tree.name]
    check=guard(tree,head,merged=True)
    branch=git(tree,'branch','--show-current').decode().strip()
    if not branch.startswith('codex/'):raise ValueError('非Codex分支')
    # 正式packet直接引用的最终head/branch不删除；只读，不ACK。
    for p in PACKETS.glob('*.json'):
        if p.stat().st_size>1024*1024:raise ValueError('packet过大，无法确认最终树')
        packet=json.loads(p.read_text())
        serialized=json.dumps(packet)
        if head in serialized or branch in serialized:
            raise ValueError('正式交接树须保留')
    names=[n.decode() for n in git(tree,'ls-files','--others','--ignored','--exclude-standard','-z').split(b'\0') if n]
    dirs=[]
    for base,children,_ in os.walk(tree,followlinks=False):
        dirs.extend(str((Path(base)/n).relative_to(tree)) for n in children)
    if dirs:
        ignored_dirs=command(['git','-C',str(tree),'check-ignore','-z','--stdin'],
                             input_bytes=b'\0'.join(n.encode() for n in dirs)+b'\0',allowed=(0,1))
        names.extend(n.decode() for n in ignored_dirs.split(b'\0') if n)
    info=manifest(tree,names)
    total=0;allocated=0;count=0
    for base,ds,fs in os.walk(tree,followlinks=False):
        for n in fs+list(ds):
            p=Path(base)/n;st=p.lstat();total+=st.st_size;allocated+=st.st_blocks*512;count+=1
    return {**completion_evidence(tree,head),
            'action':'remove-worktree' ,'tree':str(tree),'head':head,'branch':branch,'guard':check,
            'ignored':info,'ignored_bytes':sum(r['bytes'] for r in info.values()),
            'logical_bytes':total,'allocated_bytes':allocated,'entries':count}


def remove_worktree(tree,dest,*,apply=False):
    plan=worktree_plan(tree)
    if not apply:return plan
    original,receipt=backup_restore(tree,plan['ignored'],dest)
    (dest/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    again=worktree_plan(tree)
    for key in ['head','branch','ignored','logical_bytes','allocated_bytes','entries']:
        if again[key]!=plan[key]:raise RuntimeError('二次核验状态变化，保留树')
    if original!=plan['ignored']:raise RuntimeError('备份对象与计划不一致')
    # git正常删除已合并clean树；不--force，不预先批量rm ignored。
    git(REPO,'worktree','remove',str(tree))
    if tree.exists():raise RuntimeError('git返回后树仍存在')
    if git(REPO,'rev-parse',plan['branch']).decode().strip()!=plan['head']:raise RuntimeError('分支ref变化')
    result=dict(plan,applied=True,backup=receipt,branch_retained=True,
                released_logical_bytes=plan['logical_bytes'],released_allocated_bytes=plan['allocated_bytes'])
    (dest/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['quarantine','remove'])
    ap.add_argument('--tree',required=True)
    ap.add_argument('--archive-name',required=True)
    ap.add_argument('--apply',action='store_true')
    args=ap.parse_args()
    signal.alarm(120)
    relative(args.archive_name)
    if '/' in args.archive_name:raise ValueError('archive-name必须为单个名字')
    action=quarantine if args.action=='quarantine' else remove_worktree
    result=action(Path(args.tree),ARCHIVE/args.archive_name,apply=args.apply)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
