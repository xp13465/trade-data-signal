#!/usr/bin/env python3
"""check_fade_keys_alignment.py - AI降亏默认档键集跨端一致性机检(§22 代码内常量登记点)

规范: CLAUDE.md §22(2026-08-24 教训补: 代码内常量登记点也是一致性对象) + §5.4⑥(发版联动清单
须含「全部键集登记点+机检 PASS」) + 审计报告 docs/kelly/analysis/v115-new14-baseline-alignment-audit.md
§五机检建议(v1.1.5 切 NEW14 漏 check_signals.py 邮件白名单 R1/R2 即本脚本拦的病灶)。

【目的】AI降亏过滤的「当前默认档键集」在多端各有一份常量副本(前端 common.js 预设表 / 后端邮件链路
check_signals.py 白名单+中文名两张表 / 后端 overfit_monitor 打标集合 / app.js 兜底键集), 切基座时
任何一份漏同步都会造成跨端不一致(邮件不标「AI降亏·建议回避」而首页灰显删除线)。本脚本把六项比对
固化成一条命令, 任一 FAIL 阻断上线。

六项断言(审计报告 §五):
  ① 权威比对: mine24_compare.json new_keys × loss_rules.MINING_TO_PROD_KEY 映射 == common.js
     _KELLY_FADE_MODE_PRESETS 中 id==_KELLY_FADE_DEFAULT_MODE 所指预设的 keys, 逐位相等(含顺序)。
  ② 邮件白名单: check_signals.py AI_MACRO_KEYS(set 字面量, ast 抽取) ⊇ 默认档生产键集;
     缺失键 → FAIL; 多余键 → 提示不阻断(允许超集容对照期, 目标=相等)。
  ③ 徽标中文名覆盖: AI_MACRO_KEY_CN ∪ AI_MACRO_BACKUP_KEY_CN ⊇ 默认档生产键全集,
     缺失即邮件/飞书徽标英文裸键名直出 → FAIL。
  ④ 默认档单源: common.js _KELLY_FADE_DEFAULT_MODE 声明唯一且值非空; app/lab 无「兜底/默认值位置」
     的 "p8" 字面量(?? "p8" / || 'p8' / = "p8" / return "p8" 形态; preset 定义块与 === 比较为合法语境,
     已剔除后再扫)。
  ⑤ 打标集合: overfit_monitor.py RECENT_KEYS ⊇ 默认档键集(新模式组集缺键=组集恒 false 人口偏松)。
  ⑥ app.js 兜底键集: _AI_MACRO_FALLBACK_KEYS == 默认档生产键集(逐位; 兜底语义=按当前默认基座判定)。

【输入依赖】仓库内源码+产物, 不读 DB/网络:
  docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/data/mine24_compare.json (权威键集)
  scripts/loss_rules.py (MINING_TO_PROD_KEY 映射单源, importlib 按路径加载不执行 main)
  static-site/common.js (_KELLY_FADE_MODE_PRESETS + _KELLY_FADE_DEFAULT_MODE)
  scripts/check_signals.py (AI_MACRO_KEYS / AI_MACRO_KEY_CN / AI_MACRO_BACKUP_KEY_CN)
  scripts/overfit_monitor.py (RECENT_KEYS)
  static-site/app.js, static-site/lab.js (兜底键集 + "p8" 字面量扫描)

【输出】stdout 各断言 PASS/FAIL 明细。退出码: 全 PASS=0, 任一 FAIL=1(deploy-mode 同)。

【关键口径一句话】默认档键集以 mine24 权威 new_keys 经 MINING_TO_PROD_KEY 映射为准, 与前端
new14 preset 逐位全等后作为基准, 再验其余四处登记点不落后于该基准。

【复现命令】python3 scripts/check_fade_keys_alignment.py            # 独立跑
           python3 scripts/check_fade_keys_alignment.py --repo /path/to/trade --deploy-mode

deploy.sh 接入(step 1.2 check_universe_alignment 之后同链, FAIL 阻断上线):
  "$PY" "$REPO/scripts/check_fade_keys_alignment.py" --repo "$REPO" --deploy-mode
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent          # .../scripts
DEFAULT_REPO = SCRIPT_DIR.parent                       # .../trade
MINE24_REL = "docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/data/mine24_compare.json"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))


def rd(repo: Path, rel: str) -> str:
    return (repo / rel).read_text(encoding="utf-8")


def load_mining_to_prod(repo: Path) -> dict[str, str]:
    """importlib 按路径加载 loss_rules.py 取 MINING_TO_PROD_KEY(映射单源, 不手抄)。"""
    path = repo / "scripts" / "loss_rules.py"
    spec = importlib.util.spec_from_file_location("loss_rules_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod.MINING_TO_PROD_KEY)


def default_mode_prod_keys(repo: Path) -> tuple[list[str], str]:
    """断言①权威侧: mine24 new_keys × 映射 → 生产键序(挖掘代号经映射, 其余直为生产键)。"""
    mapping = load_mining_to_prod(repo)
    new_keys = json.loads((repo / MINE24_REL).read_text(encoding="utf-8"))["new_keys"]
    prod = [mapping.get(k, k) for k in new_keys]
    unknown = [k for k in new_keys if k not in mapping and not re.fullmatch(r"[a-z][A-Za-z0-9]*", k)]
    return prod, ",".join(unknown)


def extract_new_preset_keys(common_txt: str) -> tuple[list[str], int]:
    """common.js 预设表中 id=="new14" 条目的 keys(正则抽块)。返回 (keys, 匹配到的预设数)。"""
    presets = re.findall(r"\{ id:\s*\"([A-Za-z0-9]+)\".*?keys:\s*\[(.*?)\]\s*\}", common_txt, re.S)
    for pid, body in presets:
        if pid == "new14":
            return re.findall(r"\"([A-Za-z0-9]+)\"", body), len(presets)
    return [], len(presets)


def strip_preset_block(txt: str) -> str:
    """剔除 common.js _KELLY_FADE_MODE_PRESETS 定义块(preset 内 id:"p8" 为合法对照档定义, 不算兜底)。"""
    return re.sub(r"_KELLY_FADE_MODE_PRESETS\s*=\s*\[.*?\n\];", "", txt, flags=re.S)


# 兜底/默认值位置 "p8" 字面量形态。⚠赋值形态用负向后顾排除比较运算符:
#   `x !== "p8"` / `!= "p8"` / `== "p8"` / `>= "p8"` 等比较为合法对照档业务特判(p8 走 bank 不走组集),
#   不算兜底回退; 仅裸赋值 `x = "p8"` 视为硬编码默认档(审计 §五④ 口径)。
P8_FALLBACK_PATTERNS = [
    (r"\?\?\s*[\"']p8[\"']", "nullish 回退 ?? \"p8\""),
    (r"\|\|\s*[\"']p8[\"']", "falsy 回退 || \"p8\""),
    (r"(?<![=!<>+\-*/%&|^])=(?!=)\s*[\"']p8[\"']", "赋默认值 = \"p8\""),
    (r"return\s+[\"']p8[\"']", "return \"p8\""),
]


def scan_p8_fallback(repo: Path, rel: str, txt: str | None = None) -> list[str]:
    hits = []
    if txt is None:
        txt = rd(repo, rel)
    for pat, label in P8_FALLBACK_PATTERNS:
        for m in re.finditer(pat, txt):
            line_no = txt.count("\n", 0, m.start()) + 1
            hits.append(f"{rel}:{line_no} {label}")
    return hits


def assertion1(prod_keys: list[str], preset_keys: list[str]) -> None:
    ok = bool(prod_keys) and prod_keys == preset_keys
    if ok:
        detail = f"NEW14 权威推导 {len(prod_keys)} 键 == common.js new14 preset keys, 逐位相等"
    elif not preset_keys:
        detail = "common.js 预设表中未找到 id=\"new14\" 条目(preset 单源被破坏)"
    else:
        detail = (f"逐位不一致: 权威={prod_keys}; preset={preset_keys}; "
                  f"差集 权威有preset无={sorted(set(prod_keys)-set(preset_keys))} "
                  f"preset有权威无={sorted(set(preset_keys)-set(prod_keys))}")
    record("A1 权威键集↔common.js new14 preset", ok, detail)


def assertion2(default_set: set[str]) -> None:
    cs = SCRIPT_DIR / "check_signals.py"
    tree = ast.parse(cs.read_text(encoding="utf-8"))
    macro_keys = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "AI_MACRO_KEYS" for t in node.targets):
            macro_keys = {ast.literal_eval(e) for e in node.value.elts}
    if macro_keys is None:
        record("A2 check_signals AI_MACRO_KEYS", False, "check_signals.py 未找到 AI_MACRO_KEYS set 字面量")
        return
    missing = sorted(default_set - macro_keys)
    extra = sorted(macro_keys - default_set)
    if missing:
        detail = f"邮件白名单缺默认档键 {missing}(NEW14 命中被静默过滤=R1 病灶复发)"
    else:
        detail = (f"AI_MACRO_KEYS({len(macro_keys)}) ⊇ 默认档 {len(default_set)} 键"
                  + (f"; 多出(允许超集, 目标相等): {extra}" if extra else "; 恰好相等"))
    record("A2 check_signals AI_MACRO_KEYS", not missing, detail)


def assertion3(default_set: set[str]) -> None:
    tree = ast.parse((SCRIPT_DIR / "check_signals.py").read_text(encoding="utf-8"))
    cn_union: set[str] = set()
    found = {"AI_MACRO_KEY_CN": False, "AI_MACRO_BACKUP_KEY_CN": False}
    for node in tree.body:
        for target in ("AI_MACRO_KEY_CN", "AI_MACRO_BACKUP_KEY_CN"):
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == target for t in node.targets):
                found[target] = True
                cn_union |= {k.value for k in node.value.keys}
    if not all(found.values()):
        record("A3 徽标中文名覆盖", False, f"缺少登记表: {[k for k, v in found.items() if not v]}")
        return
    missing = sorted(default_set - cn_union)
    detail = (f"徽标英文裸键名风险: 默认档缺中文名 {missing}"
              if missing else f"KEY_CN ∪ BACKUP_CN 覆盖默认档全部 {len(default_set)} 键(R2 修复到位)")
    record("A3 徽标中文名覆盖", not missing, detail)


def assertion4(app_txt: str, lab_txt: str, common_txt: str) -> None:
    decls = re.findall(r"_KELLY_FADE_DEFAULT_MODE\s*=\s*\"([A-Za-z0-9]*)\"", common_txt)
    problems: list[str] = []
    if len(decls) != 1 or not decls[0]:
        problems.append(f"_KELLY_FADE_DEFAULT_MODE 声明数={len(decls)} 值={decls}(要求恰好 1 个且非空)")
    else:
        stripped = strip_preset_block(common_txt)
        problems.extend(scan_p8_fallback(Path("."), "static-site/common.js", stripped))
        problems.extend(scan_p8_fallback(Path("."), "static-site/app.js", app_txt))
        problems.extend(scan_p8_fallback(Path("."), "static-site/lab.js", lab_txt))
    ok = not problems
    if ok:
        detail = (f"默认档单源唯一且={decls[0]}(当前); app/lab/common 无兜底位 \"p8\" 字面量"
                  "(preset 定义块与 === 比较为合法对照档语境, 已区分)")
    else:
        detail = "; ".join(problems[:10])
    record("A4 默认档单源+无 p8 兜底字面量", ok, detail)


def assertion5(default_list: list[str]) -> None:
    txt = rd(SCRIPT_DIR.parent, "scripts/overfit_monitor.py")
    m = re.search(r"RECENT_KEYS\s*=\s*\[(.*?)\n\]", txt, re.S)
    if not m:
        record("A5 overfit RECENT_KEYS", False, "overfit_monitor.py 未找到 RECENT_KEYS 数组")
        return
    recent = set(re.findall(r"\"([A-Za-z0-9]+)\"", m.group(1)))
    missing = sorted(set(default_list) - recent)
    detail = (f"recent 打标集合缺默认档键 {missing}(新模式组集该键恒 false=人口偏松)"
              if missing else f"RECENT_KEYS({len(recent)}) ⊇ 默认档 {len(default_list)} 键")
    record("A5 overfit RECENT_KEYS", not missing, detail)


def assertion6(app_txt: str, default_list: list[str]) -> None:
    m = re.search(r"_AI_MACRO_FALLBACK_KEYS\s*=\s*\[(.*?)\]", app_txt, re.S)
    if not m:
        record("A6 app.js 兜底键集", False,
               "app.js 未找到 _AI_MACRO_FALLBACK_KEYS(兜底路径回退旧八键口径=R5b 病灶)")
        return
    fallback = re.findall(r"\"([A-Za-z0-9]+)\"", m.group(1))
    ok = fallback == default_list
    detail = (f"兜底键集与默认档逐位相等({len(fallback)} 键)" if ok else
              f"不一致: 兜底={fallback}; 默认档={default_list}")
    record("A6 app.js 兜底键集", ok, detail)


def main() -> int:
    ap = argparse.ArgumentParser(description="AI降亏默认档键集跨端一致性机检(§22 登记点)")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="仓库根(相对解析所有输入)")
    ap.add_argument("--deploy-mode", action="store_true",
                    help="deploy 接入模式(任一 FAIL 以非0退出阻断上线; 本脚本 FAIL 恒非0退出, 参数保持同链签名)")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    need = [
        repo / MINE24_REL,
        repo / "scripts" / "loss_rules.py",
        repo / "scripts" / "check_signals.py",
        repo / "scripts" / "overfit_monitor.py",
        repo / "static-site" / "common.js",
        repo / "static-site" / "app.js",
        repo / "static-site" / "lab.js",
    ]
    for p in need:
        if not p.exists():
            print(f"✗ 缺少输入源 {p}", file=sys.stderr)
            return 1

    try:
        prod_keys, unknown_codes = default_mode_prod_keys(repo)
    except Exception as e:  # noqa: BLE001
        print(f"✗ 权威键集/映射加载失败: {e}", file=sys.stderr)
        return 1
    common_txt = rd(repo, "static-site/common.js")
    app_txt = rd(repo, "static-site/app.js")
    lab_txt = rd(repo, "static-site/lab.js")
    preset_keys, n_presets = extract_new_preset_keys(common_txt)

    print("=== check_fade_keys_alignment.py(AI降亏默认档键集跨端一致性机检) ===")
    print(f"  mine24 权威     : {repo / MINE24_REL}  new_keys={len(prod_keys)}")
    print(f"  common.js       : presets={n_presets} 个, new14 preset keys={len(preset_keys)}")
    print(f"  默认档生产键集   : {len(prod_keys)} 键(挖掘代号未映射残留: [{unknown_codes}] 空=全部经映射)")
    print()

    assertion1(prod_keys, preset_keys)
    assertion2(set(prod_keys))
    assertion3(set(prod_keys))
    assertion4(app_txt, lab_txt, common_txt)
    assertion5(prod_keys)
    assertion6(app_txt, prod_keys)

    ok_all = True
    for name, ok, detail in RESULTS:
        ok_all = ok_all and ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n    {detail}")
        print()

    if not ok_all:
        print("✗ 键集跨端不一致(§22 登记点机检 FAIL, 阻断上线)")
        return 1
    print("✓ AI降亏默认档键集全端对齐(§22 机检 PASS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
