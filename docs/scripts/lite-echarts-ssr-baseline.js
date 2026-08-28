// 用 echarts SSR 渲染真实数据的恐贪图(与 app.js 的 echarts 完整版配置对齐), 看输出
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/tmp/overview_online.json', 'utf8'));
const echarts = require('/Users/linhuichen/code/trade/static-site/vendor/echarts.min.js');

const fg = data.fear_greed_6m;
const vals = fg.map(d => d.value);
const dates = fg.map(d => d.date);

const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 640, height: 300 });
chart.setOption({
  animation: false,
  grid: { left: 55, right: 20, top: 35, bottom: 35 },
  xAxis: { type: 'category', boundaryGap: true, data: dates },
  yAxis: { type: 'value' },
  series: [{ name: 'fg', type: 'line', smooth: true, symbol: 'none', connectNulls: true, data: vals, lineStyle: { width: 1.5 } }],
  visualMap: {
    show: false, dimension: 1,
    pieces: [
      { lte: 25, color: '#42a5f5' }, { gt: 25, lte: 40, color: '#4fc3f7' },
      { gt: 40, lte: 60, color: '#86909c' }, { gt: 60, lte: 75, color: '#e6a23c' }, { gt: 75, color: '#e6492e' },
    ],
  },
});
try {
  const svg = chart.renderToSVGString();
  // 找数据 polyline path
  const paths = [];
  const re = /<path\b([^>]*)>/g; let m;
  while ((m = re.exec(svg)) !== null) {
    const a = m[1];
    if (a.includes('C') || a.includes(' stroke=') || a.includes('url(#')) {
      const ds = (a.match(/ d="([^"]+)"/)||[])[1];
      const st = (a.match(/ stroke="([^"]+)"/)||[])[1];
      if (ds && ds.includes('C')) paths.push({ st: st||'(gradient)', d: ds });
    }
  }
  console.log('数据 polyline path 数量:', paths.length);
  for (const p of paths.slice(0, 5)) {
    console.log(' stroke=' + p.st + ' d=' + p.d.slice(0, 150));
  }
  // 找 gradient
  const gm = svg.match(/<linearGradient[\s\S]*?<\/linearGradient>/g) || [];
  console.log('gradient 数量:', gm.length);
  for (const g of gm.slice(0,1)) console.log(g.replace(/></g,'>\n<').slice(0, 1200));
} catch (e) { console.log('ERR:', (e&&e.message||'').slice(0,300)); }
process.exit(0);
