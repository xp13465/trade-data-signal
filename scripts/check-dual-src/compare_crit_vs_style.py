#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比对 critical-css(static-site/index.html) 与 style.css 的 @media(max-width:768px) 块重复规则。
用于人工分析 + 输出"同一选择器两处都有"清单。实际防漂移机检见 check_dual_src_sync.py。
"""
import re
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
for _ in range(4):
    if os.path.exists(os.path.join(ROOT, 'static-site')):
        break
    ROOT = os.path.dirname(ROOT)

HTML = os.path.join(ROOT, 'static-site', 'index.html')
CSS = os.path.join(ROOT, 'static-site', 'style.css')


def extract_critical_media(html_text):
    """抽取 index.html critical-css 内联块里的 @media(max-width:768px) 内层。"""
    m = re.search(r'<style id="critical-css">(.*?)</style>', html_text, re.S)
    if not m:
        return None
    block = m.group(1)
    mob = re.search(r'@media\s*\(max-width:\s*768px\)\{(.*?)\}\s*$', block, re.S)
    if not mob:
        return None
    return mob.group(1)


def extract_style_media_at_line(css_text, start_line):
    """抽取 style.css 从指定行号开始的 @media(max-width:768px) 内层。"""
    lines = css_text.split('\n')
    offset = sum(len(l) + 1 for l in lines[:start_line - 1])
    idx = css_text.find('@media (max-width: 768px)', offset)
    if idx < 0:
        return None
    head = css_text.find('{', idx)
    depth = 1
    j = head + 1
    while j < len(css_text) and depth > 0:
        if css_text[j] == '{':
            depth += 1
        elif css_text[j] == '}':
            depth -= 1
        j += 1
    return css_text[head + 1:j - 1]


def parse_rules(css_block):
    """把 CSS 内层拆成 [(selector, body)]，body 可含嵌套 {}。"""
    rules = []
    i, n = 0, len(css_block)
    while i < n:
        c = css_block[i]
        if c in ' \t\r\n':
            i += 1
            continue
        if css_block.startswith('/*', i):
            j = css_block.find('*/', i)
            i = j + 2 if j >= 0 else n
            continue
        b = css_block.find('{', i)
        if b < 0:
            break
        sel = css_block[i:b].strip()
        depth = 1
        j = b + 1
        while j < n and depth > 0:
            if css_block[j] == '{':
                depth += 1
            elif css_block[j] == '}':
                depth -= 1
            j += 1
        if sel:
            rules.append((sel, css_block[b + 1:j - 1]))
        i = j
    return rules


def norm(body):
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
    body = body.strip()
    body = re.sub(r'\s+', ' ', body)
    body = re.sub(r'\s*([:;{}])\s*', r'\1', body)
    return body


def main():
    html = open(HTML, encoding='utf-8').read()
    css = open(CSS, encoding='utf-8').read()
    crit = extract_critical_media(html)
    style = extract_style_media_at_line(css, 3902)
    if crit is None or style is None:
        print('extract fail')
        sys.exit(2)
    cr = parse_rules(crit)
    sr = parse_rules(style)
    crit_map, style_map = {}, {}
    for sel, body in cr:
        crit_map.setdefault(sel, []).append(body)
    for sel, body in sr:
        style_map.setdefault(sel, []).append(body)
    common = set(crit_map) & set(style_map)
    print('critical 规则数:', len(cr), ' style 规则数:', len(sr))
    print('共同选择器:', len(common))
    print()
    for sel in sorted(common):
        cb = norm(';'.join(crit_map[sel]))
        sb = norm(';'.join(style_map[sel]))
        flag = '相同' if cb == sb else '★不同'
        print('[%s] %s' % (flag, sel))
        if flag == '★不同':
            print('  crit : %s' % cb)
            print('  style: %s' % sb)
    # 选择器不同但语义近似的情况（critical 有 / style 有的子串关系）
    print()
    print('=== critical 独有(style 该块没有) ===')
    for sel in sorted(set(crit_map) - common):
        print(' ', sel)
    print('=== style 该块独有(critical 没有) ===')
    for sel in sorted(set(style_map) - common):
        print(' ', sel)


if __name__ == '__main__':
    main()
