from pathlib import Path
from urllib.parse import unquote,urlparse
from collections import Counter,defaultdict
import json,re,hashlib,os
import argparse,sys,tempfile
base=Path(__file__).resolve().parents[1];root=base.parents[2];schema=json.loads((base/'inventory/schema.json').read_text());errors=[];warnings=[];files=[];byid=defaultdict(list)
def v(x,s,path):
 typ=s.get('type'); ts=typ if isinstance(typ,list) else [typ] if typ else []
 def ok(t):return {'object':isinstance(x,dict),'array':isinstance(x,list),'string':isinstance(x,str),'integer':isinstance(x,int) and not isinstance(x,bool),'number':isinstance(x,(int,float)) and not isinstance(x,bool),'boolean':isinstance(x,bool),'null':x is None}.get(t,True)
 if ts and not any(ok(t) for t in ts):errors.append(path+': type '+str(typ));return
 if 'const' in s and x!=s['const']:errors.append(path+': const')
 if 'enum' in s and x not in s['enum']:errors.append(path+': enum '+str(x))
 if isinstance(x,str) and 'pattern' in s and not re.search(s['pattern'],x):errors.append(path+': pattern')
 if isinstance(x,list):
  if len(x)<s.get('minItems',0):errors.append(path+': minItems')
  for i,a in enumerate(x):v(a,s.get('items',{}),f'{path}[{i}]')
 if isinstance(x,dict):
  for k in s.get('required',[]):
   if k not in x:errors.append(path+': missing '+k)
  for k,a in x.items():
   if k in s.get('properties',{}):v(a,s['properties'][k],path+'.'+k)
for p in sorted((base/'inventory').glob('*.json')):
 if p.name in ['schema.json','catalog.json','reconciliation.json']:continue
 try:j=json.loads(p.read_text())
 except Exception as e:errors.append(str(p)+': json '+type(e).__name__);continue
 v(j,schema,p.name);rs=j.get('records',[]);cnt=Counter(r.get('id') for r in rs)
 for k,n in cnt.items():
  if n>1:errors.append(f'{p.name}: duplicate id {k}')
 for r in rs:byid[r.get('id')].append((p.name,r))
 files.append({'file':str(p.relative_to(root)),'count':len(rs),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
unresolved=[];kindcollisions=[]
for id,entries in byid.items():
 kinds={r.get('kind') for _,r in entries}
 if len(kinds)>1:kindcollisions.append({'id':id,'kinds':sorted(kinds)})
 for name,r in entries:
  for dep in r.get('depends_on',[]):
   if dep not in byid:unresolved.append({'source':id,'target':dep,'file':name})
links=[]
for p in base.rglob('*.md'):
 txt=p.read_text(); stripped=re.sub(r'```.*?```','',txt,flags=re.S)
 for m in re.finditer(r'(?<!!)\[[^\]]+\]\(([^\s()]+)\)',stripped):
  link=m.group(1).strip('<>')
  if link.startswith(('http:','https:','mailto:','#','/tmp/','/private/tmp/')):continue
  if link.startswith('/Users/'):
   warnings.append({'file':p.name,'kind':'absolute-worktree-link','target':link});continue
  path=unquote(link.split('#')[0]);path=re.sub(r':\d+$','',path)
  if path and not (p.parent/path).exists():links.append({'file':p.name,'target':link})
secret_patterns=[r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'\bsk-[A-Za-z0-9_-]{24,}',r'https://(?:open\.)?feishu\.cn/(?:open-apis/bot/v2/hook|services)/[A-Za-z0-9_-]+',r'Authorization\s*[:=]\s*[\"\x27]?Bearer\s+[A-Za-z0-9_.-]{16,}']
secret_hits=[]
for p in base.rglob('*'):
 if p.is_file() and p.suffix in ['.md','.json','.html']:
  txt=p.read_text()
  for pat in secret_patterns:
   for m in re.finditer(pat,txt,re.I):secret_hits.append({'file':str(p.relative_to(base)),'line':txt[:m.start()].count('\n')+1,'rule':secret_patterns.index(pat)})
report={'inventory_files':files,'inventory_record_total':sum(z['count'] for z in files),'unique_ids':len(byid),'schema_errors':errors,'unresolved_depends_on':unresolved,'cross_kind_collisions':kindcollisions,'broken_links':links,'warnings':warnings,'secret_hits':secret_hits,'note':'No secrets values printed. Parent generic checker covers keywords actually used by local schema. Unresolved refs/coverage are reconciliation inputs, not assumed faults.'}
# The catalogue uses the same envelope but is not counted twice as a source inventory.
cp=base/'inventory/catalog.json'
if cp.exists():v(json.loads(cp.read_text()),schema,'catalog.json')
# Bind exported diagrams to their exact Mermaid block sources and SVG bytes.
dm=base/'diagrams/manifest.json'
if dm.exists():
 for d in json.loads(dm.read_text())['diagrams']:
  blocks=list(re.finditer(r'```mermaid\s*\n(.*?)```',(base/d['source_file']).read_text(),re.S))
  i=d['block_index']-1
  if i>=len(blocks) or hashlib.sha256(blocks[i].group(1).encode()).hexdigest()!=d['source_sha256']:errors.append('diagram source drift: '+d['source_file'])
  if not (base/d['svg']).exists() or hashlib.sha256((base/d['svg']).read_bytes()).hexdigest()!=d['svg_sha256']:errors.append('diagram export drift: '+d['svg'])
parser=argparse.ArgumentParser(description='Validate only this architecture knowledge base; no business modules/network/DB.')
parser.add_argument('--report',type=Path,help='Optional validation JSON output; otherwise no writes');args=parser.parse_args()
report['schema_errors']=errors
if args.report:
 resolved=args.report.resolve();allowed=resolved.is_relative_to(Path('/tmp').resolve()) or resolved.is_relative_to(base/'reports')
 if not allowed or resolved.suffix!='.json':parser.error('--report accepts only JSON under /tmp or this knowledge-base reports directory')
 with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=resolved.parent,prefix='.kb-report-',suffix='.tmp',delete=False) as f:
  tmp=Path(f.name);f.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n');f.flush();os.fsync(f.fileno())
 os.chmod(tmp,0o600);os.replace(tmp,resolved)
print(json.dumps({'files':len(files),'source_records':report['inventory_record_total'],'unique_ids':len(byid),'schema_errors':errors[:20],'unresolved_count':len(unresolved),'kind_collisions':kindcollisions,'broken_links':links,'warnings':warnings,'secret_hits':secret_hits},ensure_ascii=False,indent=2))
if errors or unresolved or kindcollisions or links or secret_hits:sys.exit(1)
