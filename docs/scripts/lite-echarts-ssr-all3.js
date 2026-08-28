const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/tmp/overview_online.json', 'utf8'));
const echarts = require('/Users/linhuichen/code/trade/static-site/vendor/echarts.min.js');
function render(key, pieces, H) {
  const s = data[key];
  const vals = s.map(d => d.value), dates = s.map(d => d.date);
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 640, height: H });
  chart.setOption({
    animation: false,
    grid: { left: 55, right: 20, top: 35, bottom: 35 },
    xAxis: { type: 'category', boundaryGap: true, data: dates },
    yAxis: { type: 'value' },
    series: [{ name: key, type: 'line', smooth: true, symbol: 'none', connectNulls: true, data: vals, lineStyle: { width: 1.5 } }],
    visualMap: { show: false, dimension: 1, pieces },
  });
  const svg = chart.renderToSVGString();
  const pathM = svg.match(/<path\b[^>]* d="M[^"]*C[^"]*"[^>]*>/g) || [];
  const gradM = svg.match(/<linearGradient[^>]*>[\s\S]*?<\/linearGradient>/g) || [];
  const stops = (gradM[0]||'').match(/stop offset="([^"]+)" stop-color="([^"]+)"/g) || [];
  console.log(`${key}: line path=${pathM.length} 条, gradient=${gradM.length} 个, stops=${stops.length}色`);
  if (stops.length) console.log('  ' + stops.slice(0, 12).join(' | '));
  process.exit(0);
}
try { render('a_sentiment_6m', [
  { lte: 20, color: '#42a5f5' }, { gt: 20, lte: 40, color: '#4fc3f7' },
  { gt: 40, lte: 60, color: '#86909c' }, { gt: 60, lte: 80, color: '#e6a23c' }, { gt: 80, color: '#e6492e' }], 250); }
catch(e){ console.log('ERR:', (e&&e.message||'').slice(0,200)); process.exit(1); }
