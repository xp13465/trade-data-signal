#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机检: static-site/index.html critical-css 内联块 与 static-site/style.css 的双源一致性。

背景(CLAUDE.md §24 + §22 一致性精神, 2026-09-23 a11y-cleanup-v5 建立):
  index.html <style id="critical-css"> 是首屏防 FOUC 的内联手抄样式, 其中移动端按钮样式
  (@media(max-width:768px) 块的 .h5-periods button/.h5-bottomnav button 等)与 style.css
  同名块重复。历史教训: style.css 改过(安全区修复 5562373f5、字号a11y ba33784c5、44px 触控
  ba33784c5)而 critical-css 未同步, 形成 4 处静默漂移(header safe-area padding / .h5-collect-time
  字号 / .h5-period-bar top safe-area / .h5-bottomnav button min-height)。

防漂移机制 = 本机检:
  critical-css 内联块的每条规则(选择器 + 规范化声明集)必须能在 style.css 全文件中
  找到「同一选择器 + 同一规范化声明集」的规则。任一 critical 规则在 style.css 无等值副本
  即 FAIL。style.css 是权威源(改 style.css 漏同步 critical → critical 旧值不再匹配 → FAIL;
  critical 擅自改 → 新声明在 style.css 找不到 → FAIL)。

允许差异: 纯空白/注释/尾分号/声明顺序不同(规范化后仍等值)。
格式说明: critical-css 为单行压缩、style.css 为展开带注释, 文本级 diff 不可行,
          但语法级解析+规范化(拆选择器组/去注释/压空白/去尾分号)后逐条等值比对可行。

挂载: scripts/deploy.sh 1.2.4(任一 FAIL 非0退出阻断上线)。
"""
import argparse
import os
import re
import sys

# ------------------------------------------------------------------
# selectors: 整个 critical-css 内联块(主题变量 + base + @media 媒体块)
# 全部纳入机检, 因为 critical-css 的每条规则都应在 style.css 有等值副本
# (主题变量 4 块实测与 style.css 逐字一致; base 规则一致; 媒体块规则是本机检的主对象)。
# ------------------------------------------------------------------


def strip_comments(text):
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


def normalize_css_decls(text, split_decls=True):
    """规范化声明集: 去注释→压空白→统一符号后空格均为无→拆声明去尾分号→保持顺序列表。
    split_decls=False 时整块归一为单元素(@keyframes 嵌套体用, 不按 ';' 拆)。"""
    text = strip_comments(text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s*([{}])\s*', r'\1', text)  # 花括号两侧空白统一无(@keyframes 嵌套体差异)
    text = text.replace(', ', ',')
    text = text.replace('; ', ';').replace(': ', ':')
    text = text.replace(' > ', '>').replace('> ', '>').replace(' >', '>')
    text = text.replace(';}', '}')  # @keyframes 嵌套体尾分号差异(展开 vs 压缩)
    text = text.strip()
    text = text.strip(';')
    if not split_decls:
        return [text] if text else []
    decls = [d.strip() for d in text.split(';') if d.strip()]
    return decls


def norm_selector(s):
    """选择器轻归一: 压空白 + 组合符 > 两侧去空格(critical 压缩 vs style 展开差异)。"""
    s = strip_comments(s).strip()
    s = re.sub(r'\s+', ' ', s)
    s = s.replace(' > ', '>').replace('> ', '>').replace(' >', '>')
    s = s.replace(' , ', ',').replace(', ', ',').replace(' ,', ',')
    return s


def expand_selector(sel):
    """拆选择器组(顶层逗号分隔)为单选择器列表(规范归一后); 保留伪类/属性选择器内容。"""
    sel = sel.strip()
    out = []
    depth = 0
    cur = []
    for ch in sel:
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(norm_selector(''.join(cur)))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append(norm_selector(''.join(cur)))
    return [s for s in out if s]


def _scan_rules(css_text, start):
    """从 start 处扫描返回 [(selector, body)] 列表, body 保留嵌套。"""
    rules = []
    i, n = start, len(css_text)
    while i < n:
        c = css_text[i]
        if c in ' \t\r\n':
            i += 1
            continue
        if css_text.startswith('/*', i):
            j = css_text.find('*/', i)
            i = j + 2 if j >= 0 else n
            continue
        b = css_text.find('{', i)
        if b < 0:
            break
        sel = css_text[i:b].strip()
        depth = 1
        j = b + 1
        while j < n and depth > 0:
            if css_text[j] == '{':
                depth += 1
            elif css_text[j] == '}':
                depth -= 1
            j += 1
        body = css_text[b + 1:j - 1]
        if sel:
            rules.append((sel, body))
        i = j
    return rules


def parse_rules(css_text):
    """把 CSS 拆成叶规则列表, 返回 [(selector, decls_normalized)]。
    @media 容器被展平(其内层规则上提为独立叶规则, 容器本身不比较);
    @keyframes 视为叶(selector=@keyframes name, body 保留嵌套 to{...})。"""
    rules = []
    for sel, body in _scan_rules(css_text, 0):
        if sel.lower().startswith('@media'):
            for sub_sel, sub_body in _scan_rules(body, 0):
                decls = normalize_css_decls(sub_body)
                rules.append((sub_sel, decls))
        elif sel.lower().startswith('@keyframes'):
            decls = normalize_css_decls(body, split_decls=False)
            rules.append((sel, decls))
        else:
            decls = normalize_css_decls(body)
            rules.append((sel, decls))
    return rules


def extract_critical_block(site_dir):
    """读 index.html critical-css 内联块全文。"""
    path = os.path.join(site_dir, 'index.html')
    if not os.path.exists(path):
        raise FileNotFoundError('index.html not found: %s' % path)
    html = open(path, encoding='utf-8').read()
    m = re.search(r'<style id="critical-css">(.*?)</style>', html, re.S)
    if not m:
        raise ValueError('critical-css inline block not found in index.html')
    return m.group(1)


def build_style_index(style_text):
    """全部规则展开为 {selector: [set-of-decl-tuples]} 查找索引。"""
    rules = parse_rules(style_text)
    index = {}
    for sel, decls in rules:
        key = tuple(decls)
        for s in expand_selector(sel):
            index.setdefault(s, set()).add(key)
    return index


def check(site_dir):
    crit_block = extract_critical_block(site_dir)
    style_path = os.path.join(site_dir, 'style.css')
    style_text = open(style_path, encoding='utf-8').read()
    style_index = build_style_index(style_text)

    crit_rules = parse_rules(crit_block)
    failures = []
    total = 0
    detail = []
    for sel, decls in crit_rules:
        total += 1
        key = tuple(decls)
        missing = []
        for s in expand_selector(sel):
            candidates = style_index.get(s, set())
            if key not in candidates:
                missing.append(s)
        if missing:
            failures.append((sel, decls, missing))
            detail.append('  [FAIL] %s' % sel)
            detail.append('        声明: {%s}' % '; '.join(decls))
            detail.append('        在 style.css 无等值副本的选择器: %s' % ', '.join(missing))
    return total, failures, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site-dir', default='static-site')
    ap.add_argument('--deploy-mode', action='store_true')
    args = ap.parse_args()

    site_dir = args.site_dir
    # 相对路径: 若 cwd 存在 static-site 视为仓库根; 否则退到脚本所在仓库根(scripts/check-dual-src/../..)
    if not os.path.isabs(site_dir):
        if os.path.isdir(os.path.join(os.getcwd(), site_dir)):
            site_dir = os.path.join(os.getcwd(), site_dir)
        else:
            site_dir = os.path.abspath(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), site_dir))
    try:
        total, failures, detail = check(site_dir)
    except (FileNotFoundError, ValueError) as e:
        print('✗ critical-css/双源机检无法执行: %s' % e)
        return 2

    if failures:
        print('✗ critical-css 与 style.css 双源一致性机检失败: %d/%d 规则在 style.css 无等值副本' % (
            len(failures), total))
        for line in detail:
            print(line)
        print('  修法: 若 style.css 改了(safe-area/字号/触控等), 必须同步 index.html critical-css 内联块同规则;')
        print('        若 critical-css 有 style.css 不存在的规则, 移除或补进 style.css(§24 双源防漂移)。')
        return 1

    print('✓ critical-css 与 style.css 双源一致性机检通过: %d/%d 规则均可在 style.css 找到等值副本' % (
        total, total))
    return 0


if __name__ == '__main__':
    sys.exit(main())