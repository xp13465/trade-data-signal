#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_223_timeout_gradient_copy.py — #217④ 告警文案订正 + #223 超时梯度自测(static-only)。

覆盖:
  [A] ③ fapi_bj_width_export.py 的 R2 上传超时守卫(_r2_upload_timeout)行为 + 回归守卫
  [B] ③ 调用点确实使用守卫值(静态文本)
  [C] ① / ② / nextday_gap_check 的超时值未被擅改(只加 #223 结构性注释)
  [D] A) 文案:AST 抽 notify.send 正文并真渲染,校验口径/举例/双因结构
  [E] A) 判别逻辑与阈值(D:>50) / dedup key / subject 未动

§18 L50(探针一律 static-only):本脚本**不 import** 任何业务模块(upload_r2 /
fapi_bj_width_export 模块级会读 config/DB),只从源文件文本抽 AST 节点 compile+eval。
§18 L48:全程不 import/调用 notify ⇒ 结构上不可能真实外发;零 R2 调用、零文件写入。

用法: python3 scripts/test_223_timeout_gradient_copy.py   (任一 cwd,任意机器)
"""
import ast
import io
import os
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F_FAPI = os.path.join(ROOT, "scripts", "fapi_bj_width_export.py")
F_UPLOAD = os.path.join(ROOT, "scripts", "upload_r2.py")

P = F = 0


def ck(ok, name, extra=""):
    global P, F
    if ok:
        P += 1
        print(f"  PASS  {name}")
    else:
        F += 1
        print(f"  FAIL  {name} {extra}")


def src(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


# ── 1. 抽 fapi 守卫常量 + 函数(不 import 模块) ──────────────────────────────
tree = ast.parse(src(F_FAPI))
want = {"_R2_UPLOAD_TIMEOUT", "_R2_UPLOAD_TIMEOUT_MARGIN"}
nodes = [n for n in tree.body
         if (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in want for t in n.targets))
         or (isinstance(n, ast.FunctionDef) and n.name == "_r2_upload_timeout")]
ns = {"os": os, "print": print}
exec(compile(ast.Module(body=nodes, type_ignores=[]), F_FAPI, "exec"), ns)
guard = ns["_r2_upload_timeout"]
print(f"[抽取] _R2_UPLOAD_TIMEOUT={ns['_R2_UPLOAD_TIMEOUT']} "
      f"MARGIN={ns['_R2_UPLOAD_TIMEOUT_MARGIN']}")


def run(env):
    old = os.environ.get("R2_UPLOAD_HTTP_TIMEOUT")
    if env is None:
        os.environ.pop("R2_UPLOAD_HTTP_TIMEOUT", None)
    else:
        os.environ["R2_UPLOAD_HTTP_TIMEOUT"] = env
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            v = guard()
    finally:
        if old is None:
            os.environ.pop("R2_UPLOAD_HTTP_TIMEOUT", None)
        else:
            os.environ["R2_UPLOAD_HTTP_TIMEOUT"] = old
    return v, buf.getvalue()


print("\n[A] ③ fapi 守卫行为")
v, o = run(None);   ck(v == 900 and "⚠" not in o, "默认(无 env, 内层30): 900 且静默", f"v={v} o={o!r}")
v, o = run("600");  ck(v == 900 and "⚠" not in o, "云上(内层600): 900 且静默(内层+300)", f"v={v} o={o!r}")
v, o = run("abc");  ck(v == 900 and "⚠" not in o, "非法 env → 回落 30: 900 且静默", f"v={v} o={o!r}")
v, o = run("900");  ck(v == 1200 and "⚠" in o, "内层900 ⇒ 零梯度: 抬到1200+警告", f"v={v} o={o!r}")
for bad in (600, 300, 120):
    ns["_R2_UPLOAD_TIMEOUT"] = bad
    v, o = run("600")
    ck(v == 900 and "⚠" in o, f"回归守卫: 外层被调到 {bad} ⇒ 自动抬到 900+警告", f"v={v} o={o!r}")
ns["_R2_UPLOAD_TIMEOUT"] = 900

print("\n[B] ③ 调用点确实用守卫值(静态)")
s = src(F_FAPI)
ck("_to = _r2_upload_timeout()" in s, "调用点取 _to = _r2_upload_timeout()")
ck("timeout=_to" in s, "subprocess.run 用 timeout=_to")
ck("timeout=600" not in s, "旧硬编码 timeout=600 已消失")
ck('超时({_to}s)' in s, "超时消息带动态值")
ck("✗ upload-data-files 超时(600s)" not in s, "旧硬编码消息已消失")

print("\n[C] ① / ② / gap_check 值未动(只加注释)")
for f, old in ((os.path.join(ROOT, "scripts", "gen_daily_brief.py"), "timeout=120"),
               (os.path.join(ROOT, "scripts", "nextday_plan_generator.py"), "timeout=300"),
               (os.path.join(ROOT, "scripts", "nextday_gap_check.py"), "timeout=300")):
    t = src(f)
    ck(old in t, f"{os.path.basename(f)}: {old} 保留(未改值)")
    ck("#223" in t, f"{os.path.basename(f)}: 已加 #223 结构性注释")

print("\n[D] A) 文案:AST 抽 notify.send 正文 + 真渲染")
ut = ast.parse(src(F_UPLOAD))
found = {}
for n in ast.walk(ut):
    if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "send":
        try:
            subj = ast.literal_eval(n.args[0])
        except Exception:
            continue
        if isinstance(subj, str) and ("异源覆盖" in subj or "独立上传链产物" in subj):
            found["mass" if "异源覆盖" in subj else "stale"] = (subj, n.args[1])
ck(set(found) == {"mass", "stale"}, "两处 notify.send 均定位到", f"{set(found)}")

env = {"total_mismatch_found": 114, "repaired_total": 114,
       "stale_standalone_names": ["data/schedule_stats.json", "data/a-stock-3m.json"],
       "_fmt_name_list": lambda xs: ", ".join(xs)}
for k in ("mass", "stale"):
    subj, body_node = found[k]
    body = eval(compile(ast.Expression(body_node), F_UPLOAD, "eval"), {"__builtins__": {}}, env)
    print(f"\n--- [{k}] subject: {subj}\n--- [{k}] body:\n{body}\n")
    if k == "mass":
        ck("114" in body, "mass: N 动态带出(=114)")
        ck("不可逐字考" in body and ">50 已证" in body and "≈114" in body,
           "mass: 口径「N 不可考 / >50 已证 / ≈114」齐")
        ck("周日全量对账" in body, "mass: 保留周日可忽略判别")
        ck("误跑" in body, "mass: 保留「本机误跑」真故障判别")
    else:
        ck("a-stock-{3m,6m,1y,3y,5y,all}.json" in body and "news_digest" in body
           and "schedule_stats.json" in body and "overview.json" in body,
           "stale: 举例=台账实有池(fapi a-stock/overview/news_digest/schedule_stats)")
        ck("s06" not in body and "nextday_plan" not in body and "daily_brief" not in body,
           "stale: 误导举例 s06/nextday_plan/daily_brief 已清除")
        ck("跑前 gen" in body and "设计内" in body, "stale: 归因改为设计内「生成/上传解耦」")
        ck("连续失败" in body and "被截断" in body and "告警与链路同亡" in body,
           "stale: 真故障分支(b)判别保留")

print("\n[E] A) 判别逻辑/阈值未动(静态)")
u = src(F_UPLOAD)
ck("total_mismatch_found > 50" in u, "mass 阈值 >50 未动")
ck('_dedup_key = "verify_r2_mass_mismatch"' in u, "mass dedup key 未动")
ck('_dedup_key = "verify_r2_standalone_stale"' in u, "stale dedup key 未动")
ck('"[告警] 独立上传链产物与 R2 脱节(verify-r2 兜底补传)"' in u, "stale subject 未动")
ck('"[告警] R2 可能被异源覆盖(verify-r2 大量不一致)"' in u, "mass subject 未动")
ck("notify.update_dedup(_dedup_key)" in u, "dedup 写回未动")

print(f"\n===== 汇总: PASS={P} FAIL={F} =====")
print("ALL_PASS" if not F else "SOME_FAIL")
sys.exit(1 if F else 0)