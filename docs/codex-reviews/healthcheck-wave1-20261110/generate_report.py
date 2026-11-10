#!/usr/bin/env python3
"""Offline deterministic README generator. --check never creates or writes files."""
import argparse
import json
from pathlib import Path


def render(facts):
    lines = ['# HC01-04修复与交接', '', facts['opening'], '',
             '已测实现head：`' + facts['implementation_head'] + '`；最终交接head/hash见native packet。', '',
             '基线：`' + facts['base'] + '`。新固定头CI：' + facts['ci']['status'] + '。', '']
    for section in facts['sections']:
        lines += ['## ' + section['title'], '', section['text'], '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    expected = render(json.loads((root/'verification.json').read_text(encoding='utf-8'))).encode('utf-8')
    target = root/'README.md'
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            print('README与固定facts不一致')
            return 1
        print('README与固定facts一致（只读）')
        return 0
    target.write_bytes(expected)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
