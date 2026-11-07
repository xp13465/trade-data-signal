#!/usr/bin/env python3
"""Publish bounded, credential-free failure IDs; preserve the pytest exit code upstream."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

LIMIT = 16 * 1024 * 1024

def escape(value):
    return str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')

def safe_id(value):
    value = re.sub(r'(?:gh[opsu]_|github_pat_)[A-Za-z0-9_]+', '[redacted]', value)
    value = re.sub(r'/(?:Users|home|private|var|tmp)/[^\s\]]+', '[private-path]', value)
    return value[:400]

def read_report(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('test report exceeds bounded size')
    root = ET.fromstring(raw)
    cases = list(root.iter('testcase'))
    if not cases:
        raise ValueError('no executed test cases in report')
    failures, errors, skipped = [], [], 0
    for case in cases:
        name = safe_id(case.get('classname', '')+'::'+case.get('name', ''))
        if case.find('failure') is not None: failures.append(name)
        if case.find('error') is not None: errors.append(name)
        if case.find('skipped') is not None: skipped += 1
    return {'tests': len(cases), 'failures': len(failures), 'errors': len(errors),
            'skipped': skipped, 'failed_ids': (failures + errors)[:20],
            'omitted_failure_ids': max(0, len(failures)+len(errors)-20)}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('junit', type=Path)
    args = parser.parse_args(argv)
    try:
        report = read_report(args.junit)
    except (OSError, ValueError, ET.ParseError):
        print('::error title=脚本回归报告不可用::没有可核验的完整测试报告，不能视为通过。')
        return 2
    summary = json.dumps({k:v for k,v in report.items() if k != 'failed_ids'}, ensure_ascii=False)
    print('::notice title=脚本回归统计::'+escape(summary))
    for name in report['failed_ids']:
        print('::error title=脚本用例失败::'+escape(name))
    if report['omitted_failure_ids']:
        print('::error title=其余失败未在批注展开::'+str(report['omitted_failure_ids'])+' 项；原始失败计数完整保留。')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write('\n脚本回归统计：'+summary+'\n\n')
            for name in report['failed_ids']:
                stream.write('- '+name.replace('\n',' ').replace('\r',' ')+'\n')
    return 0

if __name__ == '__main__':
    sys.exit(main())
