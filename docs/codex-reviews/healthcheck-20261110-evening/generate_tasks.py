#!/usr/bin/env python3
"""离线生成中文任务清单；--check 仅比较全文，不写文件。"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = {
    'id': '临时编号', 'lane': '处理路径', 'title': '任务',
    'sources': '依据', 'files': '文件边界',
    'minimum_change': '最小改法', 'acceptance': '验收',
    'dependencies_and_limits': '依赖', 'state': '状态',
    'proposed_owner': '拟负责人', 'production_done': '生产实施完成',
    'priority': '优先级', 'priority_basis': '优先级依据',
    'parallel_boundary': '并行边界', 'rollback': '回退',
}

def render(payload):
    tasks = payload['tasks']
    if len(tasks) != 22 or len({t['id'] for t in tasks}) != 22:
        raise ValueError('必须包含22个唯一任务编号')
    if any(t['production_done'] is not False for t in tasks):
        raise ValueError('全部任务的production_done必须为false')
    lines = ['# 22项建议任务（全部未实施、未认领）', '', payload['scope'], '',
             '任务状态权威为pending-index；tasks.json仅本报告固定输入。HC为临时编号，优先级为建议排序，拟负责人尚未认领。', '']
    for task in tasks:
        lines += ['## ' + task['id'] + ' ' + task['title'], '']
        for key, value in task.items():
            if key not in LABELS:
                raise ValueError('字段缺少中文标签：' + key)
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
            lines += ['- **' + LABELS[key] + '**：' + text, '']
    return '\n'.join(lines).rstrip() + '\n'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='只校验全文一致，不写文件')
    args = parser.parse_args()
    rendered = render(json.loads((HERE / 'tasks.json').read_text(encoding='utf-8')))
    target = HERE / 'tasks.md'
    if args.check:
        if not target.is_file() or target.read_bytes() != rendered.encode('utf-8'):
            parser.exit(1, 'FAIL: tasks.md与tasks.json渲染全文不一致；未写文件。\n')
        print('PASS: 22个唯一编号、production_done全false、渲染全文一致；未写文件。')
        return
    temporary = HERE / 'tasks.md.tmp'
    temporary.write_text(rendered, encoding='utf-8')
    temporary.replace(target)
    print('已生成tasks.md。')

if __name__ == '__main__':
    main()
