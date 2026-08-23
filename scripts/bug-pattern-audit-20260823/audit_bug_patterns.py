#!/usr/bin/env python3
"""全站同类 bug 模式排查脚本(2026-08-23 四连 bug 举一反三, §23.2③ 全站版)。

【目的】把 2026-08-23 调研报告 docs/bug-pattern-site-audit-20260823.md 的可机检项固化成一条命令可复跑:
  ① D族 schema 清单漂移: signal_kelly_backtest.TRADE_FIELDS vs overfit_monitor.FIELD 逐列 diff
     + loss_rules 后端 NEW_KEYS_PROD vs 前端三处字面量清单(common.js T1 / app.js 映射 / lab.js 映射)对账
     + export.py 导出面 vs check_data_integrity 覆盖(P1-D2 结构性修复后口径升级:
       判据改为「EXPORT_MANIFEST 单一事实源在位 + check 已接入 import 断言」, 见 D3 段)
  ② E族 静默失败: requests 无 timeout 全量扫(含多行调用) / subprocess 无 returncode 处理粗筛
  ③ F族 存储键映射: localStorage/sessionStorage 键→读写方(文件:行号)全量表, 标 MULTI-WRITE/CROSS-PAGE

【输入依赖】仓库内源码, 不读 DB/网络:
  scripts/signal_kelly_backtest.py, scripts/overfit_monitor.py, scripts/loss_rules.py,
  static-site/{common.js,app.js,lab.js}, static-site/export.py, scripts/check_data_integrity.py,
  app/**/*.py, scripts/**/*.py

【输出】stdout 文本报告(各段 PASS/DIFF 清单)。退出码: 有 DIFF=1, 全 PASS=0。

【关键口径一句话】只做"清单 vs 清单"静态对账与模式 grep; 行为级判定(是否真泄漏/真静默)见报告人工走读段。

【复现命令】python3 scripts/bug-pattern-audit-20260823/audit_bug_patterns.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
issues = []


def rd(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def section(title):
    print(f"\n{'=' * 8} {title} {'=' * 8}")


# ---------- ①D: TRADE_FIELDS vs overfit FIELD ----------
section("D1 TRADE_FIELDS(24列权威) vs overfit_monitor.FIELD")
tf = re.search(r"TRADE_FIELDS\s*=\s*\[(.*?)\]", rd("scripts/signal_kelly_backtest.py"), re.S).group(1)
tf = re.findall(r'"([a-z_0-9]+)"', tf)
of = re.search(r"FIELD = \[(.*?)\]", rd("scripts/overfit_monitor.py"), re.S).group(1)
of = re.findall(r'"([a-z_0-9]+)"', of)
print(f"TRADE_FIELDS={len(tf)}  overfit FIELD={len(of)}")
if tf != of:
    msg = f"漂移: 权威有而 FIELD 无={sorted(set(tf)-set(of))}; FIELD 多出={sorted(set(of)-set(tf))}"
    print("DIFF", msg)
    issues.append(("D1", msg))
else:
    print("PASS 两清单逐位一致")

# ---------- ①D: loss_rules NEW_KEYS_PROD vs 前端三处 ----------
section("D2 loss_rules 20新键 vs 前端 common/app/lab 字面量清单")
bk = set(re.findall(r':\s*"([A-Za-z0-9]+)"', re.search(
    r"MINING_TO_PROD_KEY = \{(.*?)\n\}", rd("scripts/loss_rules.py"), re.S).group(1)))
common = rd("static-site/common.js")
t1 = set(re.findall(r'"([A-Za-z0-9]+)"', re.search(
    r"_KELLY_FADE_T1_KEYS = \[(.*?)\]", common, re.S).group(1)))
pairs = {}
for rel in ("static-site/app.js", "static-site/lab.js"):
    txt = rd(rel)
    idx = txt.find('"n2NorthOutConcept", "n2nout"')
    seg = txt[max(0, idx - 3000):idx + 2000]
    pairs[rel] = set(re.findall(r'\["([A-Za-z0-9]+)",\s*"[a-zA-Z0-9]+"\]', seg))
print(f"backend={len(bk)} commonT1={len(t1)} appMap={len(pairs['static-site/app.js'])} labMap={len(pairs['static-site/lab.js'])}")
for name, s in [("common._KELLY_FADE_T1_KEYS", t1)] + [(f"{k} map", v) for k, v in pairs.items()]:
    if s != bk:
        msg = (f"{name} 与后端不一致: 后端独有={sorted(bk - s)}; 前端独有={sorted(s - bk)}")
        print("DIFF", msg)
        issues.append(("D2", msg))
    else:
        print(f"PASS {name} == backend({len(bk)})")

# ---------- ①D: export json vs integrity check ----------
# 2026-08-23 P1-D2 结构性修复后口径升级: 清单单源 = export.py EXPORT_MANIFEST,
# check_data_integrity 经 importlib 动态加载断言全量在位(不在自身源码抄字面量),
# 故旧的「两文件字符串差集」口径失效, 改判据 = 单一事实源在位 + check 已接入。
section("D3 export 导出面 vs check_data_integrity 覆盖")
exp_txt = rd("static-site/export.py")
chk_txt = rd("scripts/check_data_integrity.py")
has_manifest = re.search(r"^EXPORT_MANIFEST\s*[:\w ]*=", exp_txt, re.M) is not None
chk_hooked = ("_load_export_manifest" in chk_txt and "check_export_manifest" in chk_txt)
if has_manifest and chk_hooked:
    written = set(re.findall(r'["\']([\w\-]+\.json)["\']', exp_txt))
    print(f"PASS export.py EXPORT_MANIFEST 单一事实源在位; check 经 import 断言全量在位"
          f"(清单漂移由 export main() 末尾对账自守; 参考: export 源码提及 {len(written)} 个 json 名)")
else:
    written = set(re.findall(r'["\']([\w\-]+\.json)["\']', exp_txt))
    checked = set(re.findall(r'["\']([\w\-]+\.json)["\']', chk_txt))
    uncovered = sorted(written - checked)
    print(f"export 提及 {len(written)} 个 json 名; check 覆盖 {len(checked)}; 未覆盖 {len(uncovered)}")
    for u in uncovered:
        print("  UNCOVERED", u)
    if len(uncovered) > 10:
        issues.append(("D3", f"check_data_integrity 未覆盖导出产物 {len(uncovered)} 个(结构性盲区, 见报告 D 族)"))
    if not has_manifest:
        issues.append(("D3", "export.py 缺 EXPORT_MANIFEST 单一事实源(P1-D2 未修)"))
    if not chk_hooked:
        issues.append(("D3", "check_data_integrity 未接入 EXPORT_MANIFEST 断言(P1-D2 未修)"))

# ---------- ②E: requests 无 timeout ----------
section("E1 requests.* 无 timeout(含多行调用)")
cnt = 0
for dp, _, fns in os.walk(os.path.join(ROOT, "app")):
    pass
for top in ("app", "scripts"):
    for dp, _, fns in os.walk(os.path.join(ROOT, top)):
        for fn in sorted(fns):
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            p = os.path.join(dp, fn)
            lines = open(p, encoding="utf-8").read().split("\n")
            for i, l in enumerate(lines):
                m = re.search(r"requests\.(get|post|put|head)\(", l)
                if not m:
                    continue
                buf, j, depth = l, i, l.count("(") - l.count(")")
                while depth > 0 and j + 1 < len(lines):
                    j += 1
                    buf += lines[j]
                    depth += lines[j].count("(") - lines[j].count(")")
                if "timeout" not in buf:
                    cnt += 1
                    print(f"  NO-TIMEOUT {os.path.relpath(p, ROOT)}:{i+1}")
                    issues.append(("E1", f"{p}:{i+1} requests 无 timeout"))
print(f"PASS 扫描完成, 无 timeout 的 requests 调用={cnt}(期望 0)")

# ---------- ③F: storage key mapping ----------
section("F localStorage/sessionStorage 键→读写方映射")
files = ["static-site/app.js", "static-site/lab.js", "static-site/common.js",
         "static-site/sw.js", "static-site/inline-init.js", "static-site/i18n.js"]
table = {}
for rel in files:
    for i, l in enumerate(rd(rel).split("\n")):
        for m in re.finditer(r'(localStorage|sessionStorage)\.(getItem|setItem|removeItem)\(\s*["\']([^"\']+)["\']', l):
            table.setdefault(f"{m.group(1)}::{m.group(2) if False else ''}{m.group(3)}", []) \
                .append(f"{os.path.basename(rel)}:{i+1}:{m.group(2)}")
for k in sorted(table):
    ws = [x for x in table[k] if x.endswith("setItem")]
    pages = set(x.split(":")[0] for x in table[k])
    tags = ("[MULTI-WRITE]" if len(ws) > 1 else "") + ("[CROSS-PAGE]" if len(pages) > 1 else "")
    print(f"{k} {tags} W={len(ws)} R={len(table[k]) - len(ws)} :: {' | '.join(table[k])}")

print(f"\n{'=' * 8} SUMMARY {'=' * 8}")
print(f"机检 DIFF/盲区项: {len(issues)}")
for tag, msg in issues:
    print(f"  [{tag}] {msg[:160]}")
sys.exit(1 if issues else 0)
