#!/usr/bin/env python3
"""给 index.html 的 CSS/JS 引用注入 ?v=<日期+批次> 版本号,破浏览器/CDN 缓存(§24 #46 根治)。

<2026-08-15 版本串机制改日期+批次,§24#46 根治指纹断链>
原机制: ?v= 取 static-site/<asset> 的内容 md5 前 8 位 -> 内容不变则版本号不变
  -> CDN/浏览器缓存滞留「孤儿旧快照」(引不存在对应内容产物的版本串)
  -> SW更新清缓存重建时裸崩全白(P0 事故)。
改后:  ?v=<YYYYMMDD>-a<M> 与 sw.js CACHE_VERSION 同源(日期+批次),每次部署强制换新串
  - YYYYMMDD = Asia/Shanghai 当天日期
  - a<M>     = 从 sw.js 当前 CACHE_VERSION 读出的批次号 +1(每次跑必递增,内容相同也换)
  - 同步 sw.js CACHE_VERSION 为同一日期+批次 => 两处天然一致,不再手工维护

每次改动 static-site/style.css 或 static-site/app.js（源码）后：
  1. python scripts/build_min.py        # 重新生成 app.min.js / lab.min.js + source map
  2. python scripts/bump_asset_version.py  # 刷新 ?v= 版本号(日期+批次) + 同步 sw.js CACHE_VERSION
  3. commit + push

- static-site/index.html: ./<asset>       -> ./<asset>?v=<YYYYMMDD>-a<M+1>
- 幂等：同一天重复跑 -> 批次连续递增(a236->a237->a238),每次必换新串。

动态站 (FastAPI / 路由) 会动态注入版本号（防忘跑脚本）；
静态站 (Cloudflare Pages) 依赖本脚本 + static-site/_headers 的 no-cache 策略。
"""
import glob
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(__file__))
ASSETS = ["style.min.css", "common.min.js", "purpose-notes.min.js", "kelly-review-notes.min.js", "app.min.js", "lab.min.css", "lab.min.js", "qr.js", "vendor/echarts.min.js", "i18n.js", "inline-init.js"]

# 显式 Asia/Shanghai 时区，根治日期逻辑隐患：
# datetime.now() 不带 tz 时取系统本地时区，若系统 TZ 配错或脚本在 UTC 环境(如某些 CI/Launchd
# 缺 TZ 继承)下跑，UTC 16:00-24:00 会落到"昨天"（UTC 16:00 = 北京次日 00:00）。
# 2026-07-29 事故：sw.js CACHE_VERSION 曾被手工误写为 v2-20260720-a54（应为 20260729），
# 根因是无脚本约束、纯手工编辑易错。本脚本用该时区自动生成日期根治此隐患。
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

# 匹配 sw.js: const CACHE_VERSION = 'v6-20260815-a235';
# 分五组：句首 'const CACHE_VERSION = '/ 前缀 'v6-' / 日期 '20260815' / '-a' / 批次 '235'
SW_CACHE_VER_RE = re.compile(r"(const CACHE_VERSION = ')(v\d+-)(\d{8})(-a)(\d+)'")


def today_version():
    """返回 Asia/Shanghai 当天日期 YYYYMMDD（8 位字符串）。

    显式指定时区根治两类隐患：
      1. UTC 边界：UTC 16:00 = 北京次日 00:00，用 datetime.now()/date.today()
         不带 tz 在 UTC 16:00-24:00 会取到"昨天"（launchd/CI 环境易缺 TZ 继承）。
      2. 手工写错：sw.js CACHE_VERSION 曾手工误写 20260720（应为 20260729），
         脚本化生成消除人为出错。
    """
    return datetime.now(TZ_SHANGHAI).strftime("%Y%m%d")


def read_sw_batch(sw_path):
    """从 sw.js 读取当前 CACHE_VERSION 的批次号 M(数字部分) 与大版本前缀。

    返回 (major_prefix, current_batch_int)；未匹配/文件不存在返回 (None, None)。
    major_prefix 形如 'v6-'，批次号是 '-a235' 里的 235。
    """
    if not os.path.exists(sw_path):
        print(f"  · {os.path.relpath(sw_path, BASE)}（sw.js 不存在，跳过）")
        return None, None
    with open(sw_path, encoding="utf-8") as f:
        content = f.read()
    m = SW_CACHE_VER_RE.search(content)
    if not m:
        print(f"  · {os.path.relpath(sw_path, BASE)}（未匹配 CACHE_VERSION 'vN-YYYYMMDD-aM'，跳过）")
        return None, None
    return m.group(2), int(m.group(5))


def bump(html_path, prefix, asset_dir, ver):
    """把 html 里所有 `?v=...` 替换为 `?v=<ver>`。

    ver = '<YYYYMMDD>-a<M+1>'（日期+批次，随每次跑必换新串）。
    prefix='/static' (web) 或 '' (static-site 用 './')；asset_dir 为资源所在目录。
    正则 `\?v=[A-Za-z0-9-]+` 兼容存量 md5 十六进制串(a-f0-9)与新日期+批次串(含 -)，
    二者都能被正确替换为最新变量串。
    """
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    changed = False
    for a in ASSETS:
        ref = f"{prefix}/{a}" if prefix else f"./{a}"
        pattern = re.compile(re.escape(ref) + r"(\?v=[A-Za-z0-9-]+)?")
        html, n = pattern.subn(f"{ref}?v={ver}", html)
        if n:
            changed = True
    if changed:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  ✓ {os.path.relpath(html_path, BASE)} ?v={ver}")
    else:
        print(f"  · {os.path.relpath(html_path, BASE)}（未找到资源引用，跳过）")
    return changed


def sync_sw_version(sw_path, major_prefix, date_str, batch):
    """同步 sw.js CACHE_VERSION 为 'v<N>-<today>-a<M+1>'(日期+批次,与 index 同源)。

    每次跑批次必 +1(读出的 M 已是 new_batch)，故不判断"日期已今天就跳过"——
    这里只做纯机械同步: 把 CACHE_VERSION 整段替换为大版本前缀 + 今天日期 + 新批次。
    返回 True 表示改写，False 表示跳过（未匹配/文件不存在）。
    """
    if not os.path.exists(sw_path):
        print(f"  · {os.path.relpath(sw_path, BASE)}（sw.js 不存在，跳过）")
        return False
    with open(sw_path, encoding="utf-8") as f:
        content = f.read()
    old_m = SW_CACHE_VER_RE.search(content)
    if not old_m:
        print(f"  · {os.path.relpath(sw_path, BASE)}（未匹配 CACHE_VERSION 'vN-YYYYMMDD-aM'，跳过）")
        return False
    new_ver = f"{major_prefix}{date_str}-a{batch}"   # 例: v6-20260815-a236
    # 把整个 CACHE_VERSION = 'v6-20260815-a235' 值替换为新值(仅单引号内版本串), 不动行尾注释
    new_content, n = re.subn(
        r"(const CACHE_VERSION = ')(v\d+-\d{8}-a\d+)(')", f"\\g<1>{new_ver}\\g<3>", content, count=1
    )
    if not n:
        print(f"  · {os.path.relpath(sw_path, BASE)}（未匹配 CACHE_VERSION 'vN-YYYYMMDD-aM'，跳过）")
        return False
    with open(sw_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  ✓ {os.path.relpath(sw_path, BASE)} CACHE_VERSION -> {new_ver}")
    return True


def main():
    print("注入 CSS/JS 版本号（日期+批次，§24#46 根治指纹断链）：")
    ss_dir = os.path.join(BASE, "static-site")
    sw_path = os.path.join(ss_dir, "sw.js")

    # 1. 读 sw.js 当前批次号 + 大版本前缀 -> 下一批次 M+1
    major_prefix, cur_batch = read_sw_batch(sw_path)
    if cur_batch is None:
        print("中断：sw.js CACHE_VERSION 未解析（不更新 index 防两处版本不同源）。")
        return
    new_batch = cur_batch + 1  # 每次跑必 +1，同一天重复跑连续递增
    date_str = today_version()
    ver = f"{date_str}-a{new_batch}"

    # 2. 替换 index.html 及各 HTML 的 ?v= 为 日期+批次
    for html_path in sorted(glob.glob(os.path.join(ss_dir, "*.html"))):
        bump(html_path, "", ss_dir, ver)

    # 3. 同步 sw.js CACHE_VERSION 为同源 日期+批次
    sync_sw_version(sw_path, major_prefix, date_str, new_batch)

    print("完成。记得 commit + push。")


if __name__ == "__main__":
    main()
