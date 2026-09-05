#!/usr/bin/env python3
"""
k3bench 实测脚本:kimi-k3 vs deepseek-v4-flash 经同一 8899 代理双跑
目的:测「做事速度(同任务端到端耗时)」+「API 速度(TTFB/吞吐)」+「实测 429 重试表现」
口径:
  - 端点 http://127.0.0.1:8899/v1/messages,stream=true(与 Claude Code 真实调用形态一致)
  - 两模型均不带 thinking 参数(kimi-k3 在 8899 本就是剥 thinking 形态,公平)
  - 3 个固定任务(A 短答/B 代码修改/C 长文摘要),每任务每模型 REPS 次,交错执行摊平时段漂移
  - 记录:HTTP 状态/TTFB(首个 SSE 事件)/总耗时/usage tokens/错误正文前200字
  - 429 冷却风险:每请求间隔 SLEEP_S 秒;失败也记录不丢弃(429 本身就是评测维度①的现实表现)
依赖:/Users/linhuichen/code/trade-data/.env 的 SENSENOVA_KEY1(仅作占位 Bearer,代理会轮换覆写)
输出:/tmp/k3bench/bench_results.jsonl(每行一次请求)+ 汇总打印
复现:python3 /tmp/k3bench/bench.py
"""
import json, time, urllib.request, urllib.error, ssl, sys, datetime

REPS = 6
SLEEP_S = 3
TIMEOUT = 300
URL = "http://127.0.0.1:8899/v1/messages"
MODELS = ["kimi-k3", "deepseek-v4-flash"]

KEY = ""
for line in open("/Users/linhuichen/code/trade-data/.env"):
    if line.startswith("SENSENOVA_KEY1="):
        KEY = line.strip().split("=", 1)[1]
        break
assert KEY, "SENSENOVA_KEY1 not found"

CODE_SNIPPET = '''def calc_position(score, capital, risk_pct=0.02):
    """根据信号评分计算买入仓位"""
    if score < 60:
        return 0
    base = capital * risk_pct
    return base * (score / 100)
'''
LONG_TEXT = ("2026年9月5日,A股三大指数集体收涨。上证指数涨1.2%报3890点,深成指涨1.8%,创业板指涨2.3%。"
    "两市成交额1.35万亿元,较昨日放大12%。板块方面,人工智能概念领涨,多只个股涨停;"
    "半导体板块午后走强,北方华创涨逾7%;新能源板块分化,宁德时代小幅收跌。"
    "北向资金全天净流入86亿元,其中沪股通净流入42亿元,深股通净流入44亿元。"
    "消息面上,央行今日开展3000亿元MLF操作,利率持平;证监会就程序化交易新规公开征求意见。"
    "市场情绪指标显示,恐贪指数升至72,进入贪婪区间;涨停家数98家,跌停仅3家,赚钱效应明显。"
    "技术面上,上证指数放量突破3880点压力位,MACD金叉延续,短期均线呈多头排列。"
    "机构观点方面,多家券商认为当前市场处于业绩真空期与政策窗口期叠加阶段,主题投资活跃,"
    "建议关注AI算力、半导体设备、人形机器人三条主线,同时警惕高位题材股的波动风险。"
    "港股方面,恒生指数涨0.8%,恒生科技指数涨1.5%,南向资金净流入52亿港元。") * 2

TASKS = {
    "A_short": {
        "prompt": "用一句话回答:HTTPS 和 HTTP 的区别是什么?",
        "max_tokens": 200,
    },
    "B_code": {
        "prompt": f"以下是 Python 函数:\n```python\n{CODE_SNIPPET}```\n请给它增加一个功能:当 score>=90 时仓位乘以 1.5 倍,但单笔仓位不得超过 capital 的 10%。输出修改后的完整函数代码,不要解释。",
        "max_tokens": 1200,
    },
    "C_digest": {
        "prompt": f"请阅读以下市场复盘文本,输出结构化 JSON:{{\"指数表现\":..., \"资金面\":..., \"情绪\":..., \"主线板块\":[...], \"风险提示\":...}}。文本如下:\n{LONG_TEXT}",
        "max_tokens": 800,
    },
}

def one_call(model, task_key, rep):
    t = TASKS[task_key]
    body = json.dumps({
        "model": model,
        "max_tokens": t["max_tokens"],
        "stream": True,
        "messages": [{"role": "user", "content": t["prompt"]}],
    }).encode()
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KEY}",
        "anthropic-version": "2023-06-01",
    })
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "model": model, "task": task_key, "rep": rep,
           "status": None, "ttfb_ms": None, "total_ms": None,
           "input_tokens": None, "output_tokens": None, "err": None,
           "text_chars": 0, "has_thinking": False, "raw_bytes": 0}
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            rec["status"] = r.status
            first = True
            for raw in r:
                rec["raw_bytes"] += len(raw)
                if first:
                    rec["ttfb_ms"] = round((time.monotonic() - t0) * 1000, 1)
                    first = False
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except Exception:
                    continue
                et = ev.get("type")
                if et == "message_start":
                    rec["input_tokens"] = ev.get("message", {}).get("usage", {}).get("input_tokens")
                elif et == "content_block_start":
                    cb = ev.get("content_block") or {}
                    if cb.get("type") == "thinking":
                        rec["has_thinking"] = True
                elif et == "content_block_delta":
                    d = ev.get("delta") or {}
                    if d.get("type") == "text_delta":
                        rec["text_chars"] += len(d.get("text", ""))
                elif et == "message_delta":
                    u = ev.get("usage") or {}
                    if u.get("output_tokens") is not None:
                        rec["output_tokens"] = u["output_tokens"]
            rec["total_ms"] = round((time.monotonic() - t0) * 1000, 1)
            if rec["raw_bytes"] == 0:
                rec["err"] = "empty_body_200"
    except urllib.error.HTTPError as e:
        rec["status"] = e.code
        rec["total_ms"] = round((time.monotonic() - t0) * 1000, 1)
        try:
            rec["err"] = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
    except Exception as e:
        rec["status"] = -1
        rec["total_ms"] = round((time.monotonic() - t0) * 1000, 1)
        rec["err"] = f"{type(e).__name__}: {e}"[:200]
    return rec

def main():
    out = open("/tmp/k3bench/bench_results.jsonl", "a")
    n = 0
    for rep in range(REPS):
        for task_key in TASKS:
            order = MODELS if rep % 2 == 0 else MODELS[::-1]  # 交错抵消时段漂移
            for model in order:
                rec = one_call(model, task_key, rep)
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                n += 1
                print(f"[{n}] {rec['model']:18s} {rec['task']:8s} rep{rec['rep']} "
                      f"status={rec['status']} ttfb={rec['ttfb_ms']}ms total={rec['total_ms']}ms "
                      f"out_tok={rec['output_tokens']} err={(rec['err'] or '')[:60]}", flush=True)
                time.sleep(SLEEP_S)
    out.close()

if __name__ == "__main__":
    main()
