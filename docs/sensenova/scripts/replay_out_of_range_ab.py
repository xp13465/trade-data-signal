#!/usr/bin/env python3
# 目的:OUT_OF_RANGE(code=11 400)定位复现 — 单斜杠 /v1/messages vs 双斜杠 //v1/messages 直连 A/B
# 方法口径:同 key 同 body(effort=high+thinking.enabled+mt=384000)交替打 7 key 各 3 轮,
#        验证 400 是否由 path/组合稳定触发(2026-09-07 窗口内全 400、窗口外 200 → 时段性,path 无关)
# 输入依赖:/Users/linhuichen/code/trade-data/.env(SENSENOVA_KEY1-7)
# 输出:stdout 逐行 status;stats 汇总
# 关键参数:max_tokens=384000, thinking.type=enabled budget_tokens=1024, output_config.effort=high
# 复现命令:python3 replay_out_of_range_ab.py

#!/usr/bin/env python3
# 直连 A/B:单斜杠 /v1/messages vs 双斜杠 //v1/messages 同 key 同 body 交替打
# 验证双斜杠是否间歇性触发 OUT_OF_RANGE(code=11 400)
import json, os, time, ssl, http.client

UPSTREAM_HOST = "token.sensenova.cn"
import pathlib
for _line in pathlib.Path("/Users/linhuichen/code/trade-data/.env").read_text().splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _kk, _vv = _line.split("=", 1)
        os.environ.setdefault(_kk.strip(), _vv.strip().strip("\""))
KEYS = []
for i in range(1, 8):
    k = os.environ.get(f"SENSENOVA_KEY{i}")
    if k:
        KEYS.append((i, k))

BODY = json.dumps({
    "model": "deepseek-v4-flash",
    "max_tokens": 128000,
    "thinking": {"type": "enabled", "budget_tokens": 1024},
    "output_config": {"effort": "high"},
    "messages": [{"role": "user", "content": "hi"}],
}).encode()

def send(key, path):
    conn = http.client.HTTPSConnection(UPSTREAM_HOST, context=ssl._create_unverified_context())
    conn.request("POST", path, body=BODY, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
        "anthropic-version": "2023-06-01",
        "Accept-Encoding": "identity",
    })
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, body[:120]

t0 = time.time()
stats = {}
# 交替打:单斜杠 vs 双斜杠,每 key 各 3 轮 = 7*3*2 = 42 请求
for round_i in range(3):
    for (ki, k) in KEYS:
        for path in ("/v1/messages", "//v1/messages"):
            try:
                st, rb = send(k, path)
            except Exception as e:
                st, rb = "EXC", str(e)[:80]
            tag = "S" if path == "/v1/messages" else "D"
            key = (tag, st)
            stats[key] = stats.get(key, 0) + 1
            ts = time.strftime("%H:%M:%S")
            print(f"{ts} KEY{ki} {tag} path={path} -> {st} {rb.decode(errors='replace')[:90] if isinstance(rb, bytes) else rb}", flush=True)
print(f"\n=== done in {time.time()-t0:.1f}s stats={stats}")
