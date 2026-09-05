import bench, json, time
bench.REPS=10; bench.SLEEP_S=4
out=open('/tmp/k3bench/bench_results.jsonl','a')
n=0
for rep in range(10):
    for task in ('A_short','B_code'):
        for model in (['kimi-k3','deepseek-v4-flash'] if rep%2==0 else ['deepseek-v4-flash','kimi-k3']):
            r=bench.one_call(model,task,100+rep)
            out.write(json.dumps(r,ensure_ascii=False)+'\n'); out.flush()
            n+=1; print(n, r['model'], r['task'], r['status'], r['total_ms'], r['output_tokens'], r['err'] or '', flush=True)
            time.sleep(4)
out.close()
