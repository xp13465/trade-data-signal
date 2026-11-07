#!/usr/bin/env python3
"""Offline real-Chrome MR tests from current app.js; optional frozen 21+6 replay.

python3 scripts/tests/risk-assessment-browser-20261107.py --legacy-dir /tmp/codex-reports/ops-benefit-validation-20261107
No business imports, production requests, actual notifications, or shared old tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

import websocket  # Existing websocket-client: local Chrome DevTools only.

from test_overfit_assessment_20261107 import ROOT, NS, DATE, point, derive


def cut(source, start, end):
    i = source.index(start)
    return source[i:source.index(end, i)]


def bank(bt, act, daily=None):
    seq = derive(bt, act) if daily is None else daily
    return {'generated_at': '2026-11-06 21:40', 'accuracy': {'rolling': {
        'backtest': {'15': bt, '60': bt}, 'actual': {'15': act, '60': act}}},
        'overfit': {'current': {'date': DATE}, 'daily': seq, 'daily_by_win': {'15': seq, '60': seq}}}


def fixtures():
    d1, d2, d3, d4, d5 = ['20261102', '20261103', '20261104', '20261105', '20261106']
    bt = [point(d, 50) for d in [d1, d2, d3, d4, d5]]
    act = [point(d1, 55), point(d3, 50), point(d4, 45), point(d5, 60)]
    b = bank(bt, act)
    rows = [{'case': 'new_gap_internal', 'bank': b}]
    # Valid 40 is a deliberately supplied old complete point; validation must not guess from score.
    legacy = bank(bt, act, [{'date': p['date'], 'risk_score': 40, 'level': 'yellow', 'win_rate': 50} for p in bt])
    rows.append({'case': 'legacy_40_same_date_proof', 'bank': legacy})
    # Dimension/roll evidence must come from the chosen population and matching window.
    for kind, key, selector in [('by_signal', 'buy_aux', {'sigType': 'buy_aux'}), ('by_grade', 'high', {'grade': 'high'})]:
        b = bank(bt, bt)
        b['accuracy']['rolling'][kind] = {key: {'backtest': {'15': bt}, 'actual': {'15': act}}}
        dim = 'sig_type' if kind == 'by_signal' else 'grade'
        b['overfit']['daily_by_dim'] = {dim: {key: {'15': legacy['overfit']['daily']}}}
        rows.append({'case': 'legacy_dimension_' + key, 'bank': b, 'state': selector})
    b = bank(bt, bt)
    b['overfit']['daily_by_win'] = {'60': legacy['overfit']['daily']}
    b['accuracy']['rolling']['actual']['60'] = act
    rows.append({'case': 'legacy_roll_fallback_60', 'bank': b})
    b = bank(bt, bt, legacy['overfit']['daily'])
    b['accuracy'] = {}
    rows.append({'case': 'legacy_no_rolling_evidence', 'bank': b})
    b = bank(bt, act, legacy['overfit']['daily'])
    b['filtered'] = bank(bt, bt, legacy['overfit']['daily'])
    b['filtered']['accuracy']['rolling']['actual']['15'] = []
    rows.append({'case': 'legacy_filtered_exact_population', 'bank': b, 'fade': True})
    b = bank(bt, bt, legacy['overfit']['daily'])
    b['by_k'] = {'1': bank(bt, [], legacy['overfit']['daily'])}
    b['filtered_by_k'] = {}
    rows.append({'case': 'legacy_by_k_exact_population', 'bank': b, 'state': {'k': 1}})
    for side in ['actual', 'backtest']:
        for label, invalid in [('null', None), ('string', '50'), ('bool', False), ('object', {})]:
            b = bank([point()], [point()])
            b['accuracy']['rolling'][side]['15'][0]['win_rate'] = invalid
            # Explicitly exercise old JSON: strip marks so raw rolling must establish validity.
            b['overfit']['daily_by_win']['15'] = [{'date': DATE, 'risk_score': 40, 'level': 'yellow'}]
            rows.append({'case': 'legacy_invalid_' + side + '_' + label, 'bank': b})
    # Mandatory controls including both zero, zero score, absent backtest, sell, tail/all-null.
    rows += [
        {'case': 'new_both_zero', 'bank': bank([point(wr=0)], [point(wr=0)])},
        {'case': 'new_valid_score_zero', 'bank': bank([point()], [point()], [dict(date=DATE, risk_score=0, level='green', **NS['daily_assessment'](DATE, 50, 50))])},
        {'case': 'new_no_backtest', 'bank': bank([], [point()])},
        {'case': 'new_all_missing_actual', 'bank': bank([point()], [])},
        {'case': 'new_tail_missing_backtest', 'bank': bank([point('20261105')], [point('20261105'), point()])},
        {'case': 'new_all_null', 'bank': bank([point(wr=None)], [point()])},
    ]
    b = bank(bt, bt)
    b['accuracy']['rolling']['by_signal'] = {'sell': {'backtest': {}, 'actual': {'15': act}}}
    b['overfit']['daily_by_dim'] = {'sig_type': {'sell': {'15': []}}}
    rows.append({'case': 'new_sell', 'bank': b, 'state': {'sigType': 'sell'}})
    b = bank(bt[:4], bt[:4], [dict(date=p['date'], risk_score=v, level=NS['risk_level'](v)) for p, v in zip(bt, [29, 30, 60, 61])])
    rows.append({'case': 'new_frozen_curve_boundaries', 'bank': b})
    return rows


BOOTSTRAP = r'''
const errors=[], charts=[];window.onerror=(m)=>errors.push(String(m));
const state={};function siteCfg(k,d){return d};function _t(x){return x};
function fmtDate(x){return x};function withTheme(x){return x};function dzOpts(){return []};
function loadEcharts(){return Promise.resolve()};let activeBank=null;
function fetchJSON(){return Promise.resolve(activeBank)};
'''
RUNNER = r'''
_fetchOverfitMonitor=()=>Promise.resolve(activeBank);_watchOverfitCard=()=>{};
function check(ok,msg){if(!ok)throw new Error(msg)};
function describe(host){const el=host.querySelector('#overfit-risk-chart'),cfg=_lwCfgMap.get(el);
 return {scores:cfg?cfg.series[0].data:[],dates:cfg?cfg.xLabels:[],tips:cfg?cfg.xLabels.map((_,i)=>cfg.tipFn(i)):[],
 colors:cfg?cfg.series[0].data.map((v,i)=>cfg.series[0].itemColor(i,v)):[],connectNulls:cfg?cfg.series[0].connectNulls:null,
 text:host.innerText,svg:host.querySelectorAll('svg').length};}
async function run(){const out=[];
for(const f of FIXTURES){activeBank=structuredClone(f.bank);localStorage.setItem('tds_overfit_fade',f.fade?'1':'0');
 window._KELLY_FADE_DEFAULT_MODE='p8';_overfitState={win:60,roll:15,grade:null,sigType:null,k:null,...f.state};
 const host=document.createElement('section');host.style.width=Math.max(280,innerWidth-32)+'px';document.body.append(host);await _appendOverfitCard(host,{},{});
 const observed=describe(host);const renderedBank=f.fade?(activeBank.filtered||activeBank):(_overfitState.k?(activeBank.by_k?.[String(_overfitState.k)]||activeBank):activeBank);const seq=_overfitRiskSeries(renderedBank);
 const expected=seq.map(p=>_ovRiskPointValid(p)?p.risk_score:null);
 check(!observed.scores.length||JSON.stringify(observed.scores)===JSON.stringify(expected),f.case+': plotted missing data');
 for(let i=0;i<observed.scores.length;i++)if(observed.scores[i]===null)check(/不可评估/.test(observed.tips[i]),f.case+': missing tooltip');
 if(f.case==='legacy_40_same_date_proof')check(JSON.stringify(observed.scores)==='[40,null,40,40,40]','valid 40 vs missing 40');
 if(f.case==='new_gap_internal'){
  check(observed.scores[1]===null&&!observed.connectNulls,'must gap missing actual');
  const svg=host.querySelector('#overfit-risk-chart svg');const rect=svg.getBoundingClientRect();
  svg.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,clientX:rect.left+40+(rect.width-56)*1.5/5,clientY:rect.top+70}));
  const tip=host.querySelector('#overfit-risk-chart .lw-tip');check(tip.textContent.includes('缺实盘数据'),'actual pointer tooltip');
  observed.pointerTip=tip.textContent;
  const paths=[...svg.querySelectorAll('path[stroke-width="2"]')].map(p=>p.getAttribute('d'));
  check(paths.length>0,'real risk paths rendered');observed.paths=paths;
 }
 if(f.case==='new_valid_score_zero')check(observed.scores[0]===0,'valid zero suppressed');
 if(f.case==='new_frozen_curve_boundaries')check(JSON.stringify(observed.colors)==='["#52c41a","#52c41a","#e6a23c","#e6492e"]','frozen 30/60 curve colours');
 if(f.case.startsWith('legacy_invalid_'))check(observed.scores.length===0&&/不可评估|无回测对照/.test(observed.text)&&!observed.text.includes('加载失败'),'invalid rate consumed as valid '+f.case);
 if(['legacy_dimension_buy_aux','legacy_dimension_high','legacy_roll_fallback_60'].includes(f.case))check(observed.scores[1]===null,'wrong dimension/window evidence');
 if(['legacy_no_rolling_evidence','legacy_filtered_exact_population','legacy_by_k_exact_population','new_all_missing_actual'].includes(f.case))check(observed.scores.length===0&&observed.text.includes('不可评估'),f.case+': unknown population painted '+observed.text);
 if(f.case==='new_sell')check(observed.text.includes('无回测对照'),'sell protection');
 if(f.case==='new_tail_missing_backtest')check(observed.text.includes('末端1日')&&observed.text.includes('无回测对照'),'tail note');
 out.push({case:f.case,...observed});host.remove();
}
// Python/JS numerical + missing semantics parity, including every invalid primitive supported by JS.
for(const f of PARITY){const b=structuredClone(f.bt),a=structuredClone(f.act);if(f.special){(f.side==='bt'?b:a)[0].win_rate=({nan:NaN,inf:Infinity,neg_inf:-Infinity})[f.special]}
 const actual=_ovDeriveDaily(b,a);check(JSON.stringify(actual)===JSON.stringify(f.expected),'Python/JS daily parity '+f.case);}
// Source helpers retain numerical 0 and reject non-finite, booleans and non-numeric values.
for(const v of [null,undefined,NaN,Infinity,-Infinity,true,false,'0',{},[]])check(!_ovValidNumber(v),'invalid numeric accepted');
check(_ovValidNumber(0),'zero invalid');
// Actual S06 current source presets and per-date common.js lookup, using isolated synthetic rows.
const dates=['20261102','20261103','20261104','20261105','20261106'];
_tdsS06State={daily:dates.map(date=>({date,effective_mode:'new14'})),off_base:'new14'};_tdsS06ByDate={};
for(const r of _tdsS06State.daily)_tdsS06ByDate[r.date]=r;
const recent={rows:dates.map((d,i)=>({d,i:'fixture_'+i,s:'buy',g:'mid',t:90,k:'',v:i===1?null:1,w:[1,0,1],gr:'mid'}))};
const agg=_ovAggregateRecent(recent,'s06',false,true,1);check(agg&&agg._s6,'S06 aggregate unavailable');
for(const seq of Object.values(agg.overfit.daily_by_win))for(const p of seq)check(p.assessment_status&&typeof p.missing_actual==='boolean','S06 missing marks');
const s06Seq=agg.overfit.daily_by_win['15'];check(s06Seq.some(p=>p.missing_actual),'S06 missing actual synthetic control');
// Frozen six default scenarios, rerun current source with old public market fixture if supplied.
const defaults=[];
if(LEGACY_BASE){_tdsS06State=LEGACY_S06;_tdsS06ByDate={};for(const r of LEGACY_S06.daily)_tdsS06ByDate[_tdsS06NormalizeDate(r.date)]=r;
 for(const cur of DEFAULT_CURRENTS){activeBank=structuredClone(LEGACY_BASE);activeBank.overfit.current=cur;window._KELLY_FADE_DEFAULT_MODE='s06';localStorage.setItem('tds_overfit_fade','1');_overfitState={win:60,roll:15,grade:null,sigType:null,k:1};
 const host=document.createElement('section');host.style.width=Math.max(280,innerWidth-32)+'px';document.body.append(host);await _appendOverfitCard(host,{},{});defaults.push(describe(host));host.remove();}
 check(defaults.every(x=>JSON.stringify(x.scores)===JSON.stringify(defaults[0].scores)),'current changed default curves');}
// ECharts fallback: capture actual generated option, no fake success from SVG test.
const fallback=[];const savedSetup=_lwSetup;_lwSetup=(el,cfg,fn)=>fn(el);window.echarts={init:()=>({setOption:opt=>fallback.push(opt)})};
_overfitState={win:60,roll:15,grade:null,sigType:null,k:null};const host=document.createElement('section');host.innerHTML='<h3 class="overfit-risk-title"></h3><div></div>';document.body.append(host);_overfitRiskEl=host.lastElementChild;
_renderOverfitRisk(FIXTURES.find(f=>f.case==='new_gap_internal').bank);const opt=fallback.at(-1);check(opt.series[0].data[1]===null&&!opt.series[0].connectNulls,'fallback gap');
check(opt.tooltip.formatter([{dataIndex:1}]).includes('缺实盘数据'),'fallback reason');host.remove();_lwSetup=savedSetup;
check(!errors.length,'browser errors '+errors.join(','));
document.getElementById('result').textContent=JSON.stringify({viewport:innerWidth,cases:out,default_cases:defaults,parity_cases:PARITY.length,s06:s06Seq,fallback_checked:true,errors,userAgent:navigator.userAgent});
}
run().catch(e=>document.getElementById('result').textContent=JSON.stringify({fatal:String(e),stack:e.stack,errors}));
'''


def verify_frozen_snapshot(base):
    """Compare every stored date/score/level/win_rate; state additions are separate."""
    counts = {'banks': 0, 'sequences': 0, 'points': 0, 'both_valid_points': 0, 'missing_actual_40': 0, 'complete_current': 0}
    for b in [base, base['filtered']]:
        counts['banks'] += 1
        rolling, ov = b['accuracy']['rolling'], b['overfit']
        groups = [(rolling, ov['daily_by_win'])]
        for axis, source_key in [('grade', 'by_grade'), ('sig_type', 'by_signal')]:
            groups += [(rolling[source_key][key], daily) for key, daily in ov['daily_by_dim'][axis].items()]
        for rolls, daily_by_win in groups:
            for win, stored in daily_by_win.items():
                bt, act = rolls.get('backtest', {}).get(win, []), rolls.get('actual', {}).get(win, [])
                seq = NS['_derive_daily_series']({win: bt}, {win: act}, None, DATE, win=int(win))
                by_date = {p['date']: p for p in seq}
                counts['sequences'] += 1
                for p in stored:
                    new = by_date[p['date']]
                    for field in ['date', 'risk_score', 'level', 'win_rate']:
                        assert p[field] == new[field], (win, p['date'], field, p[field], new[field])
                    counts['points'] += 1
                    if new['assessment_status'] == 'complete': counts['both_valid_points'] += 1
                    elif new['missing_actual'] and new['risk_score'] == 40: counts['missing_actual_40'] += 1
        cur = ov['current']
        sc, detail = NS['compute_risk'](*(cur[f'd{i}'] for i in range(1,5)), as_of=cur['date'])
        if detail['assessment_status'] == 'complete':
            assert sc == cur['risk_score'] and detail['weighted'] == cur['weighted']
            counts['complete_current'] += 1
    return counts


def run_chrome(cmd, tmp, fixture, width):
    """Use device metrics: Chrome CLI alone clamps narrow windows to 500px."""
    stderr = (tmp/'chrome-stderr.txt').open('w')
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=stderr)
    ws = None
    try:
        port_file = tmp/'profile/DevToolsActivePort'
        deadline = time.monotonic()+15
        while not port_file.exists():
            assert proc.poll() is None and time.monotonic() < deadline, 'Chrome DevTools startup failed'
            time.sleep(.05)
        port = int(port_file.read_text().splitlines()[0])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        tabs = json.load(opener.open(f'http://127.0.0.1:{port}/json/list', timeout=5))
        url = next(t['webSocketDebuggerUrl'] for t in tabs if t['type'] == 'page')
        ws = websocket.create_connection(url, suppress_origin=True, timeout=5, http_proxy_host=None)
        sequence = 0
        def call(method, params=None):
            nonlocal sequence
            sequence += 1
            ws.send(json.dumps({'id': sequence, 'method': method, 'params': params or {}}))
            while True:
                message = json.loads(ws.recv())
                if message.get('id') == sequence:
                    assert 'error' not in message, message
                    return message.get('result', {})
        call('Network.enable')
        call('Network.setBlockedURLs', {'urls': ['http://*', 'https://*']})
        call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': width == 390})
        call('Page.navigate', {'url': fixture.as_uri()})
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            result = call('Runtime.evaluate', {'expression': "document.getElementById('result')?.textContent || ''", 'returnByValue': True})
            value = result.get('result', {}).get('value')
            if value: return json.loads(value)
            time.sleep(.05)
        raise AssertionError('Chrome fixture timed out')
    finally:
        if ws: ws.close()
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        stderr.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--legacy-dir', type=Path)
    parser.add_argument('--width', type=int, choices=[390, 1440], default=1440)
    args = parser.parse_args()
    app = (ROOT/'static-site/app.js').read_text()
    common = (ROOT/'static-site/common.js').read_text()
    parts = [BOOTSTRAP, cut(common, 'var _KELLY_FADE_MODE_PRESETS =', 'function _tdsFadeModeApply('),
             cut(common, 'var _TDS_S06_MODE_ID =', 'var _TDS_DROUGHT_THRESHOLD ='),
             cut(app, 'function _niceNumber(', 'function _etfTrendGeom('),
             cut(app, 'function _lwValueExtent(', 'function _lwSetHeight('),
             cut(app, 'let _overfitAccEl =', 'let _sigEtfCache =')]
    rows = fixtures()
    base, s06 = None, None
    frozen_counts = None
    if args.legacy_dir:
        old = json.loads((args.legacy_dir/'browser-fixtures.json').read_text())
        rows += [dict(f, case='replay_'+f['case']) for f in old]
        base = json.loads((args.legacy_dir/'live-overfit.raw').read_text())
        s06 = json.loads((args.legacy_dir/'live-s06.raw').read_text())
        frozen_counts = verify_frozen_snapshot(base)
    parity = []
    for wr in [0, 10, 24, 25, 30, 39, 40, 49, 50, 50.5, 51, 55, 60, 61, 65, 70, 100, None, True, False, '50', {}, []]:
        for side in ['bt', 'act']:
            b, a = [point()], [point()]
            (b if side == 'bt' else a)[0]['win_rate'] = wr
            parity.append({'case': str(wr)+side, 'bt': b, 'act': a, 'expected': derive(b, a)})
    for side in ['bt', 'act']:
        for label, value in [('nan', float('nan')), ('inf', float('inf')), ('neg_inf', -float('inf'))]:
            b, a = [point()], [point()]
            (b if side == 'bt' else a)[0]['win_rate'] = value
            expected = derive(b, a)
            (b if side == 'bt' else a)[0]['win_rate'] = None
            parity.append({'case': label+side, 'bt': b, 'act': a, 'special': label, 'side': side, 'expected': expected})
    parity += [{'case': f['case'], 'bt': f['bank']['accuracy']['rolling']['backtest']['15'],
                'act': f['bank']['accuracy']['rolling']['actual']['15'],
                'expected': derive(f['bank']['accuracy']['rolling']['backtest']['15'], f['bank']['accuracy']['rolling']['actual']['15'])}
               for f in fixtures() if 'rolling' in f['bank'].get('accuracy', {})]
    currents = []
    for dims in [[None]*4, [None,90,None,None], [None,90,90,90], [None,None,None,100], [0]*4, [90]*4]:
        score, detail = NS['compute_risk'](*dims, as_of=DATE)
        currents.append({'date': DATE, 'risk_score': score, 'level': NS['risk_level'](score), **detail})
    parts += ['const FIXTURES='+json.dumps(rows)+';const PARITY='+json.dumps(parity)+';const LEGACY_BASE='+json.dumps(base)+';const LEGACY_S06='+json.dumps(s06)+';const DEFAULT_CURRENTS='+json.dumps(currents)+';', RUNNER]
    page = '''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src data:"><style>body{font:14px sans-serif;--text-3:#777;--text-1:#222;--bg-card:white;--border:#ddd;--border-strong:#aaa}</style><pre id="result"></pre>'''
    page += ''.join('<script>'+part.replace('</script', '<\\/script')+'</script>' for part in parts)
    with tempfile.TemporaryDirectory(prefix='risk-assessment-20261107-') as tmp:
        tmp = Path(tmp)
        fixture = tmp/'fixture.html'
        fixture.write_text(page)
        cmd = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '--headless=new', '--no-first-run',
               '--no-default-browser-check', '--disable-background-networking', '--disable-component-update',
               '--disable-sync', '--disable-crash-reporter', '--no-proxy-server', '--host-resolver-rules=MAP * ~NOTFOUND',
               '--user-data-dir='+str(tmp/'profile'), '--window-size='+str(args.width)+',1000', '--disable-gpu', 
               '--remote-debugging-port=0', 'about:blank']
        result = run_chrome(cmd, tmp, fixture, args.width)
        assert not result.get('fatal'), result
        assert not result['errors'], result['errors']
        assert result['viewport'] == args.width, (result['viewport'], args.width)
        numerical = [{key: row[key] for key in ['scores', 'dates', 'tips', 'colors', 'connectNulls']} for row in result['cases']+result['default_cases']]
        assert result['fallback_checked']
        print(json.dumps({'status': 'PASS', 'viewport': result['viewport'], 'browser_cases': len(result['cases']), 'frozen_replay_cases': 27 if base else 0,
                          'default_cases': len(result['default_cases']), 'parity_cases': result['parity_cases'],
                          'frozen_snapshot_comparison': frozen_counts,
                          'fallback_checked': True, 'errors': result['errors'], 'userAgent': result['userAgent'],
                          'source_sha256': hashlib.sha256(app.encode()).hexdigest(),
                          'result_sha256': hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
                          'numerical_sha256': hashlib.sha256(json.dumps(numerical, sort_keys=True).encode()).hexdigest(),
                          'boundary': 'Offline fixture, current source + actual SVG/hover + captured fallback options; no production/ROI claim'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
