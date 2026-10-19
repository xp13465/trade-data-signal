# -*- coding: utf-8 -*-
"""#266 一期 筛选器前端「同构对账」验证器（离线无痕浏览器实测）。

⚠️ 本文件**不是 pytest 用例**（文件名不以 test_ 开头 ⇒ CI 不收集）:
   CI 的 quality-gate 环境没有浏览器, 所以浏览器实测只能本机手动跑、把输出当证据贴进报告。
   跑法: python scripts/tests/ui_fund_screener_verification.py [--head-app /tmp/fscr_head_app.js]

为什么需要它（§5.4⑦ 复现脚本同构对账铁律 / §23.7 冻结契约）:
   「默认视图与现状逐位一致」是本次改动的硬约束, 但默认视图由 app.js 的 `renderOffshoreFund`
   渲染 —— 单元测试碰不到 DOM。本验证器用**无痕浏览器 + 本地 http.server + 路由拦截**:
     ① app.min.js 用**源码**喂（不依赖任何构建产物）; ② /api/fund_* 用**固定假数据**喂;
     ③ 拦掉一切外部域名（零外发）; ④ 禁用 Service Worker（防缓存干扰）。
   然后把「新 app.js」与「HEAD 老 app.js」在**同一份假数据**下的 `#fund-score-body` HTML
   逐字对比 —— 面板收起时两者必须完全一致（默认视图零变化）。

断言清单（PASS/FAIL 逐条打印）:
  1. 默认视图: 面板收起 + 列表 3 行 + body HTML == HEAD 基线
  2. 展开面板: 发出 /api/fund_screener 且带 facets=1
  2b. 首开 facets 定点回填（F1 回归面）: 类型/申购多选 + 公司候选 + 覆盖率标签均已渲染
      （修前首开停在占位「选项加载中…」、覆盖率非空=0; 断言必须跑在「首次展开」后）
  3. 设「成立规模 ≥ 10」: 请求带 min_scale=10 + chip 出现 + 条件计数 1
  4. 统计条: 命中 42 只（服务端 total, 非本页行数）
  5. 缺失提示: 文案与假数据 missing 逐字一致（另有 7 只因「成立规模」缺失被排除）
  6. 删 chip: 重新请求且不再带 min_scale
  7. 清空: chip 清空
  8. 收起面板: 面板隐藏 + body HTML 回到基线 + 收起过程零新增 /api/fund_screener 请求
  9. 排序快照还原（F2 回归面）: 筛选态改排序→收起后 下拉/统计条/localStorage/列表 四方一致
      （修前下拉与统计条仍是筛选态值=夏普、与列表快照序不一致）
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent.parent
SITE = ROOT / "static-site"

# ── 假数据（与固定断言一一对应） ──
FUND_TOTAL = 27000
MISSING_SCALE = 7
HIT_TOTAL = 42
FUND_SCORE_ROWS = [
    {"fund_code": "000001", "fund_name": "测试基金一", "composite_score": 88.5,
     "half_kelly_position": 21.0, "final_suggestion": 19.0, "manager_score": 80.0,
     "star_rating": 5, "score_drawdown": 70.0, "score_stability": 66.0, "scale": 12.5,
     "fund_type": "股票型", "update_date": "2026-10-18"},
    {"fund_code": "000002", "fund_name": "测试基金二", "composite_score": 77.2,
     "half_kelly_position": 15.0, "final_suggestion": 13.0, "manager_score": 72.0,
     "star_rating": 4, "score_drawdown": 60.0, "score_stability": 58.0, "scale": 8.0,
     "fund_type": "混合型", "update_date": "2026-10-18"},
    {"fund_code": "000003", "fund_name": "测试基金三", "composite_score": 66.1,
     "half_kelly_position": 9.0, "final_suggestion": 8.0, "manager_score": 61.0,
     "star_rating": 4, "score_drawdown": 52.0, "score_stability": 50.0, "scale": 4.0,
     "fund_type": "债券型", "update_date": "2026-10-18"},
]
SCREENER_ROWS = [
    {"fund_code": "013579", "fund_name": "筛选命中甲", "composite_score": 91.0,
     "half_kelly_position": 25.0, "final_suggestion": 22.0, "manager_score": 85.0,
     "star_rating": 5, "score_drawdown": 75.0, "score_stability": 70.0, "scale": 30.0,
     "fund_type": "股票型", "update_date": "2026-10-18"},
    {"fund_code": "013580", "fund_name": "筛选命中乙", "composite_score": 84.0,
     "half_kelly_position": 18.0, "final_suggestion": 16.0, "manager_score": 79.0,
     "star_rating": 5, "score_drawdown": 68.0, "score_stability": 64.0, "scale": 22.0,
     "fund_type": "混合型", "update_date": "2026-10-18"},
]
FACETS = {
    "type_counts": [{"type": "股票型", "n": 8000}, {"type": "混合型", "n": 9000}],
    "company_counts": [{"company": "公司A", "n": 300}, {"company": "公司B", "n": 250}],
    "purchase_status_counts": [{"status": "开放申购", "n": 20000}],
    "coverage": {"scale": 26500, "composite_score": 27700},
    "fund_total": FUND_TOTAL,
}
ECHARTS_STUB = ("window.echarts={init:function(){return {setOption:function(){},resize:function(){},"
                "dispose:function(){},on:function(){},clear:function(){}}},"
                "graphic:{LinearGradient:function(){return {}}}};")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SITE), **kw)

    def log_message(self, *a):
        pass


def _start_server():
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


def _install_routes(page, api_log, app_js_path, screener_status=200):
    app_src = Path(app_js_path).read_text(encoding="utf-8")
    pn_src = (SITE / "purpose-notes.js").read_text(encoding="utf-8")
    css_src = (SITE / "style.css").read_text(encoding="utf-8")
    lab_css = (SITE / "lab.css")
    lab_css = lab_css.read_text(encoding="utf-8") if lab_css.exists() else ""

    def route(rt):
        rt.continue_()

    def handler(r):
        url = r.request.url
        u = url.split("?")[0]
        # ── 主站 API（跨域也拦; 一律假数据） ──
        if re.search(r"/api/auth/me", u):
            # 真实机制: window.__authState 由此填充 → hasPrivilege('fund_score') 放行 fund tab
            return r.fulfill(status=200, content_type="application/json", body=json.dumps({
                "logged_in": True, "user": {"name": "验证器", "provider": "local"},
                "privileges": ["fund_score"],
            }, ensure_ascii=False))
        if re.search(r"/api/fund_screener", u):
            api_log.append(("screener", r.request.url))
            if screener_status != 200:
                return r.fulfill(status=screener_status, content_type="application/json",
                                 body='{"error":"boom"}')
            # missing 随条件变: 带 min_scale 才有「因成立规模缺失被排除」铺垫（模拟真实服务端逐条件算）
            missing = {"scale": MISSING_SCALE} if "min_scale=" in url else {}
            return r.fulfill(status=200, content_type="application/json", body=json.dumps({
                "date": "2026-10-19", "built_at": "2026-10-19T16:05:00",
                "fund_total": FUND_TOTAL, "total": HIT_TOTAL, "pages": 1, "page": 1, "size": 50,
                "missing": missing, "facets": FACETS, "data": SCREENER_ROWS,
            }, ensure_ascii=False))
        if "fund_score_top" in u or "fund_score/" in u:
            return r.fulfill(status=200, content_type="application/json", body=json.dumps({
                "date": "2026-10-18", "count": 100, "method": "Top100",
                "data": FUND_SCORE_ROWS,
            }, ensure_ascii=False))
        if re.search(r"/api/fund_score", u):
            api_log.append(("fund_score", r.request.url))
            return r.fulfill(status=200, content_type="application/json", body=json.dumps({
                "date": "2026-10-18", "method": "stable", "total": len(FUND_SCORE_ROWS),
                "pages": 1, "page": 1, "size": 50, "data": FUND_SCORE_ROWS,
            }, ensure_ascii=False))
        if re.search(r"/api/", u):
            return r.fulfill(status=200, content_type="application/json", body="{}")
        # ── 本地静态资源: 只把 .min.* 换成源码, 其余放行 ──
        if url.startswith("http://127.0.0.1"):
            if u.endswith(".json"):
                return r.fulfill(status=200, content_type="application/json", body="{}")
            if re.search(r"app\.min\.js", u):
                return r.fulfill(status=200, content_type="application/javascript", body=app_src)
            if re.search(r"purpose-notes\.min\.js", u):
                return r.fulfill(status=200, content_type="application/javascript", body=pn_src)
            if re.search(r"style\.min\.css", u):
                return r.fulfill(status=200, content_type="text/css", body=css_src)
            if re.search(r"lab\.min\.css", u):
                return r.fulfill(status=200, content_type="text/css", body=lab_css)
            if re.search(r"vendor/echarts\.min\.js", u):
                return r.fulfill(status=200, content_type="application/javascript", body=ECHARTS_STUB)
            return r.continue_()
        if u.endswith(".json"):
            return r.fulfill(status=200, content_type="application/json", body="{}")
        # 零外发: 其余外部域名一律拦掉
        return r.abort()

    page.route("**/*", handler)


def _body_html(page):
    return page.eval_on_selector("#fund-score-body", "el => el.innerHTML")


def _jclick(page, sel):
    page.eval_on_selector(sel, "el => el.click()")


def _safe_html(page, sel):
    """取元素 innerHTML; 元素不存在时返回 ""（供「修前代码」上跑判别力关时不抛异常）。"""
    return page.eval_on_selector(sel, "el => el.innerHTML") if page.query_selector(sel) else ""


def _norm(html):
    """抹平「异步 tooltip 增强」带来的属性差异（title → data-tip/data-from-title）。

    站点有一个全局的 hover 提示增强器把后插入节点的 title 转成 data-tip; 它与渲染时序有关,
    与本改动的默认视图无关。比对前统一抹掉这三类属性, 只比结构与内容。
    """
    html = re.sub(r'\sdata-(?:tip|from-title)="[^"]*"', "", html)
    html = re.sub(r'\stitle="[^"]*"', "", html)
    return html


def _find_chromium():
    """本机已装但版本号与 playwright 期望不符时, 直接指定可执行文件（避免联网 playwright install）。"""
    import glob
    cands = glob.glob(os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium"))
    cands += glob.glob(os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac-*/chrome-headless-shell"))
    return sorted(cands)[-1] if cands else None


def _run(pw, base, app_js_path, api_log, has_screener=True, tag="A"):
    exe = _find_chromium()
    browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
    ctx = browser.new_context(service_workers="block")
    page = ctx.new_page()
    console = []
    page.on("console", lambda m: console.append(m.text))
    _install_routes(page, api_log, app_js_path)
    page.goto(base + "/index.html", wait_until="load")
    # 等登录态就位（fund tab 有 fund_score 特权门; 见 app.js renderFund gating）
    page.wait_for_function("window.__authState && window.__authState.logged_in === true", timeout=20000)
    # 点「基金评分」→ 点「场外基金」二级 tab（真实用户路径, 不靠 hash 注入）
    page.click('button[data-tab="fund"]')
    page.wait_for_selector('button[data-subtab="offshore"]', state="attached", timeout=20000)
    page.click('button[data-subtab="offshore"]')
    if has_screener:
        page.wait_for_selector("#fund-screener-toggle", state="attached", timeout=20000)
    page.wait_for_selector("#fund-score-body .fund-score-row", state="attached", timeout=20000)
    page.wait_for_timeout(400)

    fails = []

    def chk(name, cond, extra=""):
        print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "  | " + str(extra)))
        if not cond:
            fails.append(name)

    # 1) 默认视图（两种场景都要求: 列表 3 行 + 走 /api/fund_score）
    baseline = _norm(_body_html(page))
    chk("[%s] 1 默认视图: 列表 3 行" % tag,
        page.eval_on_selector_all("#fund-score-body .fund-score-row", "els => els.length") == 3)
    chk("[%s] 1 默认视图: 走 /api/fund_score（非筛选器）" % tag,
        any(k == "fund_score" for k, _ in api_log))
    if not has_screener:
        ctx.close()
        browser.close()
        return fails, baseline
    chk("[%s] 1 默认视图: 面板收起" % tag,
        "hidden" in (page.get_attribute("#fund-screener-panel", "class") or ""),
        page.get_attribute("#fund-screener-panel", "class"))

    # 2) 展开面板
    n0 = len([1 for k, _ in api_log if k == "screener"])
    page.click("#fund-screener-toggle")
    page.wait_for_timeout(600)
    scr_urls = [u for k, u in api_log if k == "screener"]
    chk("2 展开: 发出 /api/fund_screener 且带 facets=1",
        len(scr_urls) > n0 and "facets=1" in scr_urls[-1], scr_urls[-1:])

    # 2b) 首开 facets 到达后「定点回填」（F1 回归面）
    #     修前: fetch 成功只重渲染列表, 不重渲染面板 → 每次进 tab 首开都停在占位「选项加载中…」、
    #     各条件覆盖率标签全空（实测首开 0 个非空覆盖率）; 修后: facets 到达即回填这两块。
    #     本断言必须跑在「第一次展开」之后（这正是该 bug 的触发场景, 二开不受影响）。
    tc_html = _safe_html(page, "#fund-screener-type-checks")
    pur_html = _safe_html(page, "#fund-screener-pur-checks")
    chk("2b 首开: 基金类型多选项已渲染（facets.type_counts=2）",
        page.eval_on_selector_all('#fund-screener-type-checks input[data-role="types"]',
                                  "els => els.length") == 2, tc_html[:160])
    chk("2b 首开: 申购状态多选项已渲染（facets.purchase_status_counts=1）",
        page.eval_on_selector_all('#fund-screener-pur-checks input[data-role="purchase"]',
                                  "els => els.length") == 1, pur_html[:160])
    chk("2b 首开: 类型/申购区不残留「选项加载中…」占位",
        "选项加载中" not in tc_html and "选项加载中" not in pur_html, tc_html[:120])
    chk("2b 首开: 基金公司候选已渲染（facets.company_counts=2）",
        page.eval_on_selector_all("#fund-screener-company-dl option", "els => els.length") == 2)
    cov_nonempty = page.eval_on_selector_all(
        ".fund-screener-cov[data-k]", "els => els.filter(e => (e.textContent || '').trim().length > 0).length")
    chk("2b 首开: 覆盖率标签非空 = 2（facets.coverage 命中 scale/composite_score; 修前=0）",
        cov_nonempty == 2, cov_nonempty)
    cov_all = " | ".join(page.eval_on_selector_all(
        ".fund-screener-cov[data-k]", "els => els.map(e => e.getAttribute('data-k') + '=' + e.textContent)"))
    chk("2b 首开: 覆盖率数值与 facets.coverage 逐字一致（scale 26500 / composite_score 27700）",
        "scale=覆盖 26500/27000" in cov_all and "composite_score=覆盖 27700/27000" in cov_all, cov_all)

    # 3) 设「成立规模 ≥ 10」
    page.fill('input[data-k="scale"][data-role="min"]', "10")
    page.wait_for_timeout(900)  # 350ms 防抖
    scr_urls = [u for k, u in api_log if k == "screener"]
    chk("3 条件: 请求带 min_scale=10", "min_scale=10" in scr_urls[-1], scr_urls[-1])
    chips = page.eval_on_selector("#fund-screener-chips", "el => el.textContent")
    chk("3 条件: chip 出现（成立规模）", "成立规模" in chips, chips)
    chk("3 条件: 条件计数 = 1", "1 个条件" in page.eval_on_selector("#fund-score-body", "el => el.textContent"),
        page.eval_on_selector("#fund-score-body", "el => el.textContent")[:160])

    # 4) 统计条用服务端 total（42）
    stat = page.eval_on_selector("#fund-score-body .fund-score-stat", "el => el.textContent")
    chk("4 统计条: 命中 42 只（服务端 total, 非本页 2 行）", "42 只" in stat, stat)
    chk("4 列表: 本页 2 行（服务端分页）",
        page.eval_on_selector_all("#fund-score-body .fund-score-row", "els => els.length") == 2)

    # 5) 缺失提示逐字一致
    chk("5 缺失提示: 与 missing 一致（另有 7 只因「成立规模」缺失被排除）",
        "另有 7 只因「成立规模」缺失被排除" in chips, chips)

    # 6) 删 chip → 重新请求且不带 min_scale
    page.click("#fund-screener-chips .fund-screener-chip-x")
    page.wait_for_timeout(700)
    scr_urls = [u for k, u in api_log if k == "screener"]
    chk("6 删 chip: 重请求且不带 min_scale",
        len(scr_urls) >= 2 and "min_scale" not in scr_urls[-1], scr_urls[-1])
    chk("6 删 chip: chip 区不再含成立规模",
        "成立规模" not in page.eval_on_selector("#fund-screener-chips", "el => el.textContent"))

    # 7) 清空
    page.fill('input[data-k="scale"][data-role="min"]', "10")
    page.wait_for_timeout(700)
    page.click("#fund-screener-clear")
    page.wait_for_timeout(700)
    chk("7 清空: chip 清空",
        "成立规模" not in page.eval_on_selector("#fund-screener-chips", "el => el.textContent"),
        page.eval_on_selector("#fund-screener-chips", "el => el.textContent"))

    # 8) 收起面板 → 回到基线 + 零新增筛选请求
    n_before = len([1 for k, _ in api_log if k == "screener"])
    page.click("#fund-screener-collapse")
    page.wait_for_timeout(700)
    chk("8 收起: 面板隐藏",
        "hidden" in (page.get_attribute("#fund-screener-panel", "class") or ""))
    chk("8 收起: 零新增 /api/fund_screener 请求",
        len([1 for k, _ in api_log if k == "screener"]) == n_before)
    after = _norm(_body_html(page))
    same = after == baseline
    chk("8 收起: body HTML == 默认基线（逐字）", same, after[:200])
    if not same:
        n = min(len(after), len(baseline))
        i = next((k for k in range(n) if after[k] != baseline[k]), n)
        print("    首个差异 @%d: baseline=%r  after=%r" % (i, baseline[i - 40:i + 60], after[i - 40:i + 60]))

    # 9) 排序快照还原（F2 回归面）
    #    修前: prevSnapshot 未记 sortKey/sortDir, 收起也不还原 #fund-score-sort 的 value ⇒
    #    筛选态改排序后收起, 列表回快照序但下拉/统计条/localStorage 仍是筛选态值, 四处不一致。
    #    修后: 收起时 st/下拉/localStorage/列表 四方一致（均为进筛选器前的快照值）。
    pre_sort = page.input_value("#fund-score-sort")
    page.click("#fund-screener-toggle")        # 重开面板（第二次进筛选态, 复用同一上下文）
    page.wait_for_timeout(600)
    page.select_option("#fund-score-sort", "sharpe-desc")
    page.wait_for_timeout(900)
    scr_urls = [u for k, u in api_log if k == "screener"]
    chk("9 筛选态: 改排序为夏普 → 请求带 sort=sharpe&dir=desc",
        "sort=sharpe" in scr_urls[-1] and "dir=desc" in scr_urls[-1], scr_urls[-1])
    chk("9 筛选态: 统计条显示「夏普」（与列表一致）",
        "夏普" in page.eval_on_selector("#fund-score-body .fund-score-stat", "el => el.textContent"))
    page.click("#fund-screener-collapse")
    page.wait_for_timeout(700)
    sort_after = page.input_value("#fund-score-sort")
    chk("9 收起: 排序下拉还原为快照值（%s）" % pre_sort, sort_after == pre_sort, sort_after)
    stat_after = page.eval_on_selector("#fund-score-body .fund-score-stat", "el => el.textContent")
    chk("9 收起: 统计条不再显示「夏普」（与列表一致）", "夏普" not in stat_after, stat_after[:160])
    ls_sort = page.evaluate("() => localStorage.getItem('fund_score_sort')")
    chk("9 收起: localStorage 排序回写为快照值（控件==持久偏好）", ls_sort == pre_sort, str(ls_sort))
    after9 = _norm(_body_html(page))
    chk("9 收起: body HTML == 默认基线（逐字, 列表回快照序）", after9 == baseline, after9[:160])

    if any("ERROR" in c for c in console):
        print("note  console errors: " + " | ".join(c for c in console if "ERROR" in c)[:300])
    ctx.close()
    browser.close()
    return fails, baseline


def _run_degrade(pw, base, api_log):
    """场景 C: 筛选器服务 500 → 明示降级 + 回 Top100 兜底榜单（不白屏）。"""
    browser = pw.chromium.launch(**({"executable_path": _find_chromium()} if _find_chromium() else {}))
    ctx = browser.new_context(service_workers="block")
    page = ctx.new_page()
    _install_routes(page, api_log, str(SITE / "app.js"), screener_status=500)
    page.goto(base + "/index.html", wait_until="load")
    page.wait_for_function("window.__authState && window.__authState.logged_in === true", timeout=20000)
    page.click('button[data-tab="fund"]')
    page.wait_for_selector('button[data-subtab="offshore"]', state="attached", timeout=20000)
    page.click('button[data-subtab="offshore"]')
    page.wait_for_selector("#fund-screener-toggle", state="attached", timeout=20000)
    page.wait_for_selector("#fund-score-body .fund-score-row", state="attached", timeout=20000)
    fails = []

    def chk(name, cond, extra=""):
        print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "  | " + str(extra)))
        if not cond:
            fails.append(name)

    page.click("#fund-screener-toggle")
    page.wait_for_selector(".fund-screener-degraded", state="attached", timeout=20000)
    page.wait_for_timeout(400)
    ban = page.eval_on_selector(".fund-screener-degraded", "el => el.textContent")
    chk("C 降级: 明示「筛选服务暂不可用…已降级为 Top100 榜单」",
        "筛选服务暂不可用" in ban and "Top100" in ban, ban)
    stat = page.eval_on_selector("#fund-score-body .fund-score-stat", "el => el.textContent")
    chk("C 降级: 列表回到 Top100 兜底（共 3 只 / Top 100）", "Top 100" in stat, stat)
    chk("C 降级: 兜底榜单 3 行可读",
        page.eval_on_selector_all("#fund-score-body .fund-score-row", "els => els.length") == 3)
    ctx.close()
    browser.close()
    return fails


def _run_mobile(pw, base, api_log):
    """场景 D: 手机视口（390×844）→ 面板成为底部抽屉（position:fixed）。"""
    browser = pw.chromium.launch(**({"executable_path": _find_chromium()} if _find_chromium() else {}))
    ctx = browser.new_context(service_workers="block", viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    _install_routes(page, api_log, str(SITE / "app.js"))
    page.goto(base + "/index.html", wait_until="load")
    page.wait_for_function("window.__authState && window.__authState.logged_in === true", timeout=20000)
    # 手机视口下桌面导航是隐藏的 → 用 JS click 绕过可见性要求（点的是真实处理器）
    _jclick(page, 'button[data-tab="fund"]')
    page.wait_for_selector('button[data-subtab="offshore"]', state="attached", timeout=20000)
    _jclick(page, 'button[data-subtab="offshore"]')
    page.wait_for_selector("#fund-screener-toggle", state="attached", timeout=20000)
    page.wait_for_selector("#fund-score-body .fund-score-row", state="attached", timeout=20000)
    fails = []

    def chk(name, cond, extra=""):
        print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "  | " + str(extra)))
        if not cond:
            fails.append(name)

    _jclick(page, "#fund-screener-toggle")
    page.wait_for_timeout(500)
    pos = page.eval_on_selector("#fund-screener-panel", "el => getComputedStyle(el).position")
    chk("D 手机: 面板为底部抽屉（position:fixed）", pos == "fixed", pos)
    chk("D 手机: 面板可见（非 hidden）",
        "hidden" not in (page.get_attribute("#fund-screener-panel", "class") or ""))
    ctx.close()
    browser.close()
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--head-app", default="", help="HEAD 版 app.js 路径（做默认视图基线对比）")
    ap.add_argument("--app", default="", help="被测 app.js 路径（默认 static-site/app.js; 用于判别力关: 指向修前版本应 FAILED）")
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright 未安装（本机手动验证用, CI 不跑）")
        return 0

    srv, port = _start_server()
    base = "http://127.0.0.1:%d" % port
    head_app = a.head_app or "/tmp/fscr_head_app.js"
    all_fails = []
    try:
        with sync_playwright() as pw:
            print("== 场景 A: 新 app.js（含筛选器） ==")
            log_a = []
            app_path = Path(a.app) if a.app else (SITE / "app.js")
            fails_a, base_a = _run(pw, base, str(app_path), log_a, True, "A")
            all_fails += fails_a
            if Path(head_app).exists():
                print("== 场景 B: HEAD 老 app.js（默认视图基线） ==")
                log_b = []
                fails_b, base_b = _run(pw, base, head_app, log_b, False, "B")
                all_fails += fails_b
                same = base_a == base_b
                print(("PASS  " if same else "FAIL  ")
                      + "★ 跨版本: 默认视图 #fund-score-body HTML 与 HEAD 逐字一致")
                if not same:
                    all_fails.append("跨版本默认视图不一致")
                    print("  A[:200]=" + base_a[:200])
                    print("  B[:200]=" + base_b[:200])
            else:
                print("note  未提供 --head-app, 跳过跨版本基线对比")
            print("== 场景 C: 筛选器服务 500（降级链） ==")
            all_fails += _run_degrade(pw, base, [])
            print("== 场景 D: 手机视口（底部抽屉） ==")
            all_fails += _run_mobile(pw, base, [])
    finally:
        srv.shutdown()

    print("=" * 60)
    print("RESULT: " + ("ALLPASS" if not all_fails else "FAILED " + str(len(all_fails))))
    return 0 if not all_fails else 1


if __name__ == "__main__":
    sys.exit(main())