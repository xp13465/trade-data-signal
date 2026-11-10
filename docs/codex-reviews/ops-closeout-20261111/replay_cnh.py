"""Read-only replay of fixed production pure functions; never imports the app."""
import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

BASE = 'f35437a699d199076b5654dcde58780be89ee6b4'
SOURCE_SHA = '219d901764a70004710971cb3be7b9807cc21dde3c3f18c2135de5d6084c9490'


def replay(repo, fixture):
    import pandas as pd
    source = subprocess.check_output(
        ['git', '-C', str(repo), 'show', BASE + ':app/compute/signals.py'], timeout=15)
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('fixed source mismatch')
    names = {'_rsi', '_bollinger', '_macd', '_compute_value_signals', '_buy_type_cn'}
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    nodes += [n for n in tree.body if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == '_STD_SELL_IDS' for t in n.targets)]
    scope = {'pd': pd}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'fixed-signal-functions', 'exec'), scope)
    rows = json.loads(fixture.read_text())['rows']
    results = {}
    for name, normalize in [('observed', False), ('unit_only_counterfactual', True)]:
        values = [x['value'] / 100 if normalize and x['source'] == 'akshare' and x['value'] > 100
                  else x['value'] for x in rows]
        series = pd.Series(values, index=[x['date'] for x in rows], dtype=float)
        signals = scope['_compute_value_signals'](
            series, 'g.usdcnh', skip_buy=True, sell_no_trend_filter=True)
        results[name] = [list(x) for x in signals if x[0] >= '20261101']
    results['production_changed'] = False
    results['counterfactual_is_not_an_approved_migration'] = True
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--fixture', type=Path, default=Path(__file__).with_name('cnh-input.json'))
    args = parser.parse_args()
    print(json.dumps(replay(args.repo, args.fixture), ensure_ascii=False, indent=2))
