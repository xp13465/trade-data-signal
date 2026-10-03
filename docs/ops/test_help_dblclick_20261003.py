#!/usr/bin/env python3
# 全站帮助图标「❓」移动端双弹修复自测(F1 返工入库版, 2026-10-03)
#
# 方法: 真实提取页面代码(非复刻第二份实现)注入 Playwright DOM 断言。
#   - _initTermPop 完整 IIFE(anchor 定位首尾, 含 `})();` 闭合)   ← 被修的公共委托层
#   - 5 个 modal 委托 IIFE(overfit / ice-note / signal / strategy(app.js) + glossary 双委托(lab.js))
#   - F1 #pfIndHelpBtn span + 其真实 click 绑定形态(`_helpBtn.addEventListener("click", _showIndHelpModal)`)
#   普通 modal 打开函数 stub 计数(仅验证"term-pop 被正确排除 + modal 仍弹";modal 本体非本次改动)。
#
# 修前/修后对比在【同一次运行内】完成, 不依赖"当时 HEAD 是什么":
#   - before = `git show 11073b291:static-site/{app,lab}.js`  (base commit, 修复前)
#   - after  = 当前工作区 static-site/{app,lab}.js
# BEFORE_COMMIT 是显式常量, 脚本自检: git 对象存在; 若将来被 gc 可改此常量指向任意修复前 commit。
#
# 用法: python3 docs/ops/test_help_dblclick_20261003.py
# 依赖: 项目 .venv 已有 playwright + 本地 ms-playwright chromium(见运行说明)。

import subprocess
import sys
import os

from playwright.sync_api import sync_playwright

BEFORE_COMMIT = "11073b291"   # 修复前 base(原始修复开工时 origin/main HEAD;修复前 #pfIndHelpBtn 无双弹排除)


def _git(*args):
    r = subprocess.run(["git"] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("git " + " ".join(args) + " FAILED: " + r.stderr)
    return r.stdout


def repo_root():
    return _git("rev-parse", "--show-toplevel").strip()


ROOT = repo_root()


def git_show_text(ref, path):
    return _git("show", f"{ref}:{path}")


def _index_of(lines, marker, start=0):
    for i in range(start, len(lines)):
        if marker in lines[i]:
            return i
    raise RuntimeError("anchor not found: " + marker)


def extract_anchor_iiife(src, start_marker):
    """anchor 定位完整 IIFE: (function _xxx() ... })(); —— 首尾各锚一次, 不依赖行号漂移。"""
    lines = src.split("\n")
    s = _index_of(lines, start_marker)
    # 找本 IIFE 的闭合 `})();`(首列或仅前置空白)
    e = next(
        (i for i in range(s + 1, len(lines)) if lines[i].strip() == "})();"),
        None,
    )
    if e is None:
        raise RuntimeError("IIFE closing not found after: " + start_marker)
    return "\n".join(lines[s:e + 1])


APP_IIFE_MARKERS = [
    ("overfit", "(function _initOverfitHelpDelegation()"),
    ("icenote", "(function _initIceNoteDelegation()"),
    ("signal", "(function _initSignalHelpDelegation()"),
    ("strategy", "(function _initStrategyHelpDelegation()"),
]
LAB_IIFE_MARKERS = [
    ("glossdeleg", "(function _initLabGlossaryDelegation()"),
    ("glosshover", "(function _initLabGlossaryHoverPop()"),
]


def build_blocks(app_src, lab_src):
    # 按真实注册顺序排(影响无——stopPropagation 不拦同节点后续 capture listener, 见原 fix 注释;
    # 但保持与页面一致的注册顺序, 贴近真实)。
    blocks = []
    blocks.append(extract_anchor_iiife(app_src, "(function _initOverfitHelpDelegation()"))   # 1725
    blocks.append(extract_anchor_iiife(app_src, "(function _initIceNoteDelegation()"))      # 7328
    blocks.append(extract_anchor_iiife(app_src, "(function _initSignalHelpDelegation()"))   # 7826
    blocks.append(extract_anchor_iiife(app_src, "(function _initTermPop()"))                # 7858 公共委托层(被修处)
    blocks.append(extract_anchor_iiife(app_src, "(function _initStrategyHelpDelegation()")) # 8355
    for name, marker in LAB_IIFE_MARKERS:
        blocks.append(extract_anchor_iiife(lab_src, marker))                                # 871/891
    return blocks


def get_sources():
    """before/after 源码在同一函数内取齐, 自检 git 对象存在。"""
    before_app = git_show_text(BEFORE_COMMIT, "static-site/app.js")
    before_lab = git_show_text(BEFORE_COMMIT, "static-site/lab.js")
    cwd = os.path.dirname(os.path.abspath(__file__))
    # 脚本在仓库内(worktree 或主仓), static-site 相对仓库根
    after_app = open(os.path.join(ROOT, "static-site/app.js"), encoding="utf-8").read()
    after_lab = open(os.path.join(ROOT, "static-site/lab.js"), encoding="utf-8").read()
    return before_app, before_lab, after_app, after_lab


PAGE_JS = r"""
function resetTest() {
  window.__modalCount = 0;
  var p = document.querySelector(".term-pop");
  if (p) { p.style.display = "none"; p.style.visibility = "hidden"; }
  document.body.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  if (p) p.style.visibility = "";
}
function popVisible() {
  var p = document.querySelector(".term-pop");
  return p && p.style.display !== "none";
}
function tapIcon(id) {
  var el = document.getElementById(id);
  if (!el) return { afterHover: null, afterClick: null, modals: null };
  el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
  var afterHover = popVisible();
  el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  return { afterHover: afterHover, afterClick: popVisible(), modals: window.__modalCount };
}
function hoverIcon(id) {
  var el = document.getElementById(id);
  if (!el) return { afterHover: null, modals: null };
  el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
  var afterHover = popVisible();
  el.dispatchEvent(new MouseEvent("mouseout", { bubbles: true }));
  return { afterHover: afterHover, modals: window.__modalCount };
}
"""


def build_html(blocks, ind_attr, is_touch):
    blocks_html = "\n".join("<script>" + b + "</script>" for b in blocks)
    pf_ind_extra = ' data-ind-help=""' if ind_attr else ""
    mm_stub = "true" if is_touch else "false"
    icons = (
        '<span id="icon-overfit" class="term-tip" data-tip="overfit hover tip" data-overfit-help="1">❓</span>'
        '<div data-tip="overfit-parent tip"><span id="icon-overfit2" data-overfit-help="1" style="cursor:pointer">❓完整指南</span></div>'
        '<span id="icon-ice" class="term-tip" data-tip="ice hover tip" data-ice-note="1">❓</span>'
        '<span id="icon-signal" class="term-tip" data-tip="signal hover tip" data-signal-help="1">❓</span>'
        '<span id="icon-strategy" class="term-tip" data-tip="strategy hover tip" data-strategy-help="1">❓</span>'
        '<span id="icon-glossary" class="lab-help-icon" data-glossary="k1" role="button" tabindex="0">❓</span>'
        '<span id="icon-plain" class="term-tip" data-tip="plain tooltip">❓</span>'
        '<span id="pfIndHelpBtn"' + pf_ind_extra
        + ' style="margin-left:6px;cursor:help;color:var(--text-3);font-size:14px;line-height:1;user-select:none" title="行业配置口径说明">❓</span>'
    )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script>
window.matchMedia = function(q){{ return {{ matches: {mm_stub}, media: String(q), addEventListener: function(){{}}, removeEventListener: function(){{}}, addListener: function(){{}}, removeListener: function(){{}} }}; }};
</script>
{icons}
<script>
window.__modalCount = 0;
window._openOverfitHelpModal = function(){{ window.__modalCount++; }};
window._openSignalHelpModal = function(){{ window.__modalCount++; }};
window._openStrategyModal = function(){{ window.__modalCount++; }};
window._openIcepointNoteModal = function(){{ window.__modalCount++; }};
window._labGlossaryOpenModal = function(){{ window.__modalCount++; }};
window._showIndHelpModal = function(){{ window.__modalCount++; }};
window._LAB_GLOSSARY = {{ "k1": {{ "name": "术语", "desc": "测试描述" }} }};
var _helpBtn = document.getElementById("pfIndHelpBtn");
if (_helpBtn) _helpBtn.addEventListener("click", _showIndHelpModal);
</script>
{blocks_html}
<script>{PAGE_JS}</script>
</body></html>"""


def chromium_path():
    import glob
    patterns = [
        os.path.expanduser(
            "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell"
        ),
        os.path.expanduser(
            "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac-x64/chrome-headless-shell"
        ),
    ]
    for pat in patterns:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None  # 让 playwright 用默认通道


def run_case(browser, version, is_touch, blocks_map):
    html = build_html(blocks_map[version], ind_attr=(version == "after"), is_touch=is_touch)
    page = browser.new_page()
    page.set_content(html)
    result = {}
    for icon in [
        "icon-overfit", "icon-overfit2", "icon-ice", "icon-signal",
        "icon-strategy", "icon-glossary", "pfIndHelpBtn", "icon-plain",
    ]:
        r = page.evaluate(
            "(function(){ resetTest(); return tapIcon('" + icon + "'); })()"
        )
        result[icon] = r
    if not is_touch:
        r = page.evaluate(
            "(function(){ resetTest(); return hoverIcon('icon-signal'); })()"
        )
        result["desktop-hover-signal"] = r
    page.close()
    return result


def checks(is_touch, res, version):
    """判定 PASS/FAIL。

    after(修复版)+ tap:  帮助图标全部单弹 modal(hoverPop=False clickPop=False modals=1);
    before(修复前)+ tap: 帮助图标双弹复现(hoverPop=True clickPop=True modals=1)—— 除 ice 例外
                          (base 11073b291 已含 10-02 单点补丁, 故 ice 应已单弹);
    plain term-tip:      tap 仍弹 tooltip(modals=0), 任意版本都要求保真;
    桌面 hover:          signal 仍弹短文本(任意版本)。
    """
    problems = []
    HELP_BOTH_DIMS = [
        "icon-overfit", "icon-overfit2", "icon-signal",
        "icon-strategy", "icon-glossary", "pfIndHelpBtn",
    ]
    if is_touch:
        for icon in HELP_BOTH_DIMS:
            r = res[icon]
            if version == "after":
                want = "单弹(False/False/1)"
                bad = r["afterHover"] or r["afterClick"] or r["modals"] != 1
            else:
                want = "双弹复现(True/True/1)"
                bad = not (r["afterHover"] and r["afterClick"] and r["modals"] == 1)
            if bad:
                problems.append(
                    f"{icon}: hoverPop={r['afterHover']} clickPop={r['afterClick']} modals={r['modals']} (期望 {want})"
                )
        # ice(base 已修): 任意版本都应单弹
        r = res["icon-ice"]
        if r["afterHover"] or r["afterClick"] or r["modals"] != 1:
            problems.append(
                f"icon-ice: hoverPop={r['afterHover']} clickPop={r['afterClick']} modals={r['modals']} (期望 False/False/1, 10-02 已修)"
            )
        r = res["icon-plain"]
        if not r["afterHover"] or not r["afterClick"] or r["modals"] != 0:
            problems.append(
                f"icon-plain: hoverPop={r['afterHover']} clickPop={r['afterClick']} modals={r['modals']} (期望 True/True/0, 普通 tooltip 不被误伤)"
            )
    else:
        r = res["desktop-hover-signal"]
        if not r["afterHover"]:
            problems.append(
                f"desktop-hover-signal: hoverPop={r['afterHover']} (期望桌面 hover 仍弹短文本)"
            )
    return problems


def main():
    before_app, before_lab, after_app, after_lab = get_sources()
    blocks_map = {
        "before": build_blocks(before_app, before_lab),
        "after": build_blocks(after_app, after_lab),
    }
    exe = chromium_path()
    launch_kw = {"headless": True}
    if exe:
        launch_kw["executable_path"] = exe
    launch_kw.setdefault("args", ["--no-sandbox"])

    all_problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kw)
        if not os.path.exists(launch_kw.get("executable_path", "")) and not exe:
            # 数字给 reviewer 手跑用的线索
            pass
        print("== 移动端 tap(isTouch=true) 修前/修后同运行对比 ==")
        for v in ("before", "after"):
            res = run_case(browser, v, is_touch=True, blocks_map=blocks_map)
            print(f"--- {v} ({'拼入 data-ind-help' if v=='after' else '无 data-ind-help'}) ---")
            for k, r in res.items():
                mark = "FAIL" if k.startswith("icon") and checks_immediate(k, r, v) else ""
                print(f"  {k}: hoverPop={r['afterHover']} clickPop={r['afterClick']} modals={r['modals']} {mark}")
            for prob in checks(True, res, v):
                all_problems.append(f"[tap/{v}] " + prob)
        print("== 桌面 hover(isTouch=false) ==")
        for v in ("before", "after"):
            res = run_case(browser, v, is_touch=False, blocks_map=blocks_map)
            print(f"--- {v} ---")
            for k, r in res.items():
                if k.startswith("desktop"):
                    print(f"  {k}: hoverPop={r['afterHover']} modals={r['modals']}")
            for prob in checks(False, res, v):
                all_problems.append(f"[hover/{v}] " + prob)
        browser.close()

    print("\n===== 判定 =====")
    if all_problems:
        print("FAIL:")
        for p_ in all_problems:
            print("  - " + p_)
        sys.exit(1)
    print(
        "PASS: 修前 6 图标(pfIndHelpBtn 在内)tap 双弹复现 → 修后全部单弹 modal; "
        "ice(base 已修)两版均单弹; plain term-tip 仍弹 tooltip 且无 modal; 桌面 hover 行为不变。"
    )


def checks_immediate(k, r, version):
    """单行展示标记(仅信息性; 最终 PASS/FAIL 以 checks() 汇总判定为准)。"""
    if k == "icon-plain" or k == "icon-ice":
        return False
    if k == "desktop-hover-signal":
        return not r["afterHover"]
    if version == "after":
        return bool(r["afterHover"] or r["afterClick"] or r["modals"] != 1)
    return not (r["afterHover"] and r["afterClick"] and r["modals"] == 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("脚本异常: " + repr(exc))
        print("提示: before 提取 git show " + BEFORE_COMMIT + ":static-site/app.js, 若对象不存在请把 BEFORE_COMMIT 改为任意修复前 commit。")
        sys.exit(2)