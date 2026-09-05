#!/usr/bin/env python3
"""
k3bench 日志解析器
目的:从 sensenova-rotate.log(8899 代理)挖掘 kimi-k3 vs deepseek-v4-flash 的重试/稳定性指标
口径:
  - 请求归属 = DETECT 行的 model= 字段(每个请求必有 DETECT;REQBODY 兜底)
  - 一次请求内部的重试(429 detected / COOL KEY / SKIP COOLED)归属当前请求模型
  - 时间戳 = 请求完成时紧跟的 REQDUMP 行内 epoch(req-<epoch>-...),日/小时粒度
  - 字节量 = RESP 行 bytes= 字段;错误 = RESPERR 行
输入:/Users/linhuichen/code/trade-data/data/logs/sensenova-rotate.log
输出:/tmp/k3bench/log_stats.json
复现:python3 /tmp/k3bench/parse_log.py
"""
import re, json, datetime, collections

LOG = "/Users/linhuichen/code/trade-data/data/logs/sensenova-rotate.log"

re_detect  = re.compile(r'DETECT POST .* model=([a-z0-9.\-]+)')
re_reqbody = re.compile(r'REQBODY .* b\'{"model":"([^"]+)"')
re_resp    = re.compile(r'RESP POST .* -> (\d+) bytes=(\d+)')
re_resperr = re.compile(r'RESPERR .* -> (\d+) body=')  # 只计 body= 行(reqheaders= 是同一事件的孪生行)
re_429     = re.compile(r'^429 detected, rotate to next key')
re_cool    = re.compile(r'^COOL (KEY\d+) until (\S+) msg=(.*?) level=(\d+)')
re_skip    = re.compile(r'^SKIP COOLED')
re_reqdump = re.compile(r'REQDUMP req-(\d+)-')

models = collections.defaultdict(lambda: dict(
    requests=0, resp200=0, resp_other=0, bytes_out=0, bytes0_200=0,
    retry429=0, cool_events=0, skip_events=0, resperr=0,
    err_status=collections.Counter(), cool_msg=collections.Counter(),
    first_epoch=None, last_epoch=None,
    # hour -> [requests, retry429, resperr, resp200, bytes, cool]
    hourly=collections.defaultdict(lambda: [0,0,0,0,0,0]),
))

cur_model = None
last_epoch = None
def _hour_bucket(d, epoch):
    return datetime.datetime.fromtimestamp(epoch).strftime("%m-%d %H")

with open(LOG, encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.rstrip("\n")
        m = re_detect.search(line)
        if m:
            cur_model = m.group(1)
            d = models[cur_model]
            d["requests"] += 1
            if last_epoch:
                if d["first_epoch"] is None: d["first_epoch"] = last_epoch
                d["last_epoch"] = last_epoch
                d["hourly"][_hour_bucket(d, last_epoch)][0] += 1
            continue
        m = re_reqbody.search(line)
        if m:
            cur_model = m.group(1)  # REQBODY 先于 DETECT,先记
            continue
        if re_429.search(line):
            if cur_model:
                models[cur_model]["retry429"] += 1
                if last_epoch:
                    models[cur_model]["hourly"][_hour_bucket(d, last_epoch)][1] += 1
            continue
        m = re_cool.search(line)
        if m:
            if cur_model:
                models[cur_model]["cool_events"] += 1
                models[cur_model]["cool_msg"][m.group(3)] += 1
                if last_epoch:
                    models[cur_model]["hourly"][_hour_bucket(d, last_epoch)][5] += 1
            continue
        if re_skip.search(line):
            if cur_model: models[cur_model]["skip_events"] += 1
            continue
        m = re_resperr.search(line)
        if m:
            if cur_model:
                models[cur_model]["resperr"] += 1
                models[cur_model]["err_status"][m.group(1)] += 1
                if last_epoch:
                    models[cur_model]["hourly"][_hour_bucket(d, last_epoch)][2] += 1
            continue
        m = re_resp.search(line)
        if m:
            if cur_model:
                if m.group(1) == "200":
                    models[cur_model]["resp200"] += 1
                    if m.group(2) == "0":
                        models[cur_model]["bytes0_200"] += 1
                else:
                    models[cur_model]["resp_other"] += 1
                models[cur_model]["bytes_out"] += int(m.group(2))
                if last_epoch:
                    h = models[cur_model]["hourly"][_hour_bucket(d, last_epoch)]
                    if m.group(1) == "200": h[3] += 1
                    h[4] += int(m.group(2))
            continue
        m = re_reqdump.search(line)
        if m:
            last_epoch = int(m.group(1))

out = {}
for name, d in models.items():
    req = d["requests"] or 1
    out[name] = {
        "requests": d["requests"],
        "resp200": d["resp200"],
        "resp200_bytes0": d["bytes0_200"],
        "resp_other_non200": d["resp_other"],
        "resperr_final": d["resperr"],
        "retry429_events": d["retry429"],
        "cool_events": d["cool_events"],
        "skip_cooled_events": d["skip_events"],
        "bytes_out_total": d["bytes_out"],
        "avg_resp_bytes": round(d["bytes_out"]/max(d["resp200"],1),1),
        "retry429_per_100req": round(d["retry429"]*100/req, 3),
        "cool_per_100req": round(d["cool_events"]*100/req, 3),
        "resperr_per_100req": round(d["resperr"]*100/req, 3),
        "success_rate_pct": round(d["resp200"]*100/req, 2),
        "first": str(datetime.datetime.fromtimestamp(d["first_epoch"])) if d["first_epoch"] else None,
        "last": str(datetime.datetime.fromtimestamp(d["last_epoch"])) if d["last_epoch"] else None,
        "err_status": dict(d["err_status"]),
        "cool_msg_top": d["cool_msg"].most_common(5),
        "hourly": {k: v for k, v in sorted(d["hourly"].items())},
    }

with open("/tmp/k3bench/log_stats.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

for name, s in out.items():
    print(f"== {name}: req={s['requests']} ok%={s['success_rate_pct']} 429/100req={s['retry429_per_100req']} cool/100req={s['cool_per_100req']} err/100req={s['resperr_per_100req']} avg_bytes={s['avg_resp_bytes']} 窗口={s['first']}~{s['last']}")
print("written /tmp/k3bench/log_stats.json")
