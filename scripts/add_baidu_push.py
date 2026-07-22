#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性工具：给 static-site/ 下所有 HTML 注入百度自动推送 JS（SEO 收录）。

修正用户原代码 2 个 bug：
1. window.location.protocol.split(':') 漏 [0] -> curProtocol 是数组，=== 'https' 永远 false
2. document.getElementsByTagName("script") 漏 [0] -> s 是 HTMLCollection 无 parentNode，报错

幂等：文件已含 push.js 或 bdstatic 则跳过，不重复注入。
兼容 </body> 前后空白/换行，以及 </body>\n</html> 末尾有无换行的两种写法。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 百度自动推送代码（修正版，仅 HTTPS，避免 mixed content）
BAIDU_PUSH = """<script>
(function(){
    var bp = document.createElement('script');
    bp.src = 'https://zz.bdstatic.com/linksubmit/push.js';
    var s = document.getElementsByTagName("script")[0];
    s.parentNode.insertBefore(bp, s);
})();
</script>
"""

# 已注入标记：含任一即跳过
MARKERS = ("push.js", "bdstatic")

# 匹配 </body>（前面允许空白/换行），把推送代码插在它前面
BODY_RE = re.compile(rb"(\s*</body>\s*</html>\s*\Z)", re.DOTALL)


def inject_one(path: Path) -> str:
    """返回 'skipped' / 'injected' / 'no-body'。"""
    raw = path.read_bytes()
    # 幂等检查
    if any(m.encode() in raw for m in MARKERS):
        return "skipped"
    m = BODY_RE.search(raw)
    if not m:
        # 兜底：只匹配 </body>
        idx = raw.rfind(b"</body>")
        if idx == -1:
            return "no-body"
        insert_at = idx
    else:
        insert_at = raw.rfind(b"</body>")
    push = BAIDU_PUSH.encode()
    new = raw[:insert_at] + push + raw[insert_at:]
    path.write_bytes(new)
    return "injected"


def main():
    dirs = [ROOT / "web", ROOT / "static-site"]
    counts = {"injected": 0, "skipped": 0, "no-body": 0}
    files_changed = []
    for d in dirs:
        for html in sorted(d.glob("*.html")):
            res = inject_one(html)
            counts[res] += 1
            if res == "injected":
                files_changed.append(str(html.relative_to(ROOT)))
            elif res == "no-body":
                print(f"WARN: no </body> in {html}", file=sys.stderr)
    print(f"injected={counts['injected']} skipped={counts['skipped']} no-body={counts['no-body']}")
    for f in files_changed:
        print(f"  + {f}")


if __name__ == "__main__":
    main()
