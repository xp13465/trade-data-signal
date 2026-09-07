#!/usr/bin/env python3
# 目的:OUT_OF_RANGE(code=11 400)定位复现 — 高峰连发压测(模拟会话内高频 agent 流量)
# 方法口径:7 key 轮流循环 30 轮,0.5s 间隔,验证"连发 + effort=high + enabled + mt=384000"是否触发 400
#        结果(2026-09-07 16:10-16:11):21×200 + 9×429,零 400 → 组合/连发不触发 400,是时段性
# 输入依赖:/Users/linhuichen/code/trade-data/.env(SENSENOVA_KEY1-7)
# 输出:stdout 逐行 status;res 汇总
# 关键参数:30 轮,间隔 0.5s,max_tokens=384000(与窗口内 REQBODY 同款)
# 复现命令:python3 replay_out_of_range_burst.py

import json, os, time, ssl, http.client, pathlib
for _l in pathlib.Path("/Users/linhuichen/code/trade-data/.env").read_text().splitlines():
    if "=" in _l and not _l.strip().startswith("#"):
        _k,_v=_l.split("=",1); os.environ.setdefault(_k.strip(), _v.strip().strip('"'))
KEYS=[os.environ[f"SENSENOVA_KEY{i}"] for i in range(1,8) if os.environ.get(f"SENSENOVA_KEY{i}")]
BODY=json.dumps({"model":"deepseek-v4-flash","max_tokens":384000,
  "thinking":{"type":"enabled","budget_tokens":1024},"output_config":{"effort":"high"},
  "messages":[{"role":"user","content":"hi"}]}).encode()
ctx=ssl._create_unverified_context()
def send(key):
    c=http.client.HTTPSConnection("token.sensenova.cn",443,timeout=60,context=ctx)
    c.request("POST","/v1/messages",body=BODY,headers={"Content-Type":"application/json","Authorization":"Bearer "+key,"anthropic-version":"2023-06-01","Accept-Encoding":"identity"})
    r=c.getresponse(); b=r.read(); c.close(); return r.status,b[:80]
res={}; t0=time.time()
for i in range(30):
    k=KEYS[i%len(KEYS)]
    try: st,rb=send(k)
    except Exception as e: st,rb="EXC",str(e)[:60]
    res[st]=res.get(st,0)+1
    print(f"{time.strftime('%H:%M:%S')} #{i} key{i%len(KEYS)+1} -> {st} {rb.decode(errors='replace')[:70] if isinstance(rb,bytes) else rb}", flush=True)
    time.sleep(0.5)
print(f"\ndone {time.time()-t0:.0f}s res={res}")
