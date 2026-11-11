const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '../..');
const src = fs.readFileSync(path.join(root,'static-site/app.js'),'utf8');
const block = (a,b) => src.slice(src.indexOf(a),src.indexOf(b,src.indexOf(a)));
(async()=>{
  const browser=await chromium.launch({headless:true});
  let checks=0;
  try {
    const page=await browser.newPage({viewport:{width:390,height:844}});
    await page.route('**/*',route=>route.abort());
    await page.setContent('<main id="content"></main>');
    await page.addStyleTag({path:path.join(root,'static-site/style.css')});
    await page.evaluate(code => { (0, eval)(code); }, block('function _guardFxPayload(', '// P1-8(2026-08-05): boot.json'));
    const result=await page.evaluate(async()=>{
      const old={today:{scores:{cross_market:{value:99,is_overheat:1,components:{}},fear_greed:{value:99,components:{}}}},signals_today:[{index_id:'g.usdcnh',signal:'sell'},{index_id:'sh',signal:'buy'}]};
      old.recent_freeze=[{score_id:'cross_market',value:1},{score_id:'a_sentiment',value:10}];
      old.sentiment_calendar=[{date:'20261111',freeze:[{score_id:'cross_market',value:1}],signals:[{index_id:'s.fear_greed'}]}];
      const boot={overview:old,signal_stats:{'g.usdcnh':{sell:1},sh:{buy:2}},alert:{date:'20261111',high:{triggered:true,score:99}}};
      _guardFxPayload('boot.json',boot);
      const fresh={value:43,components:{_fx_contract:'fx-excluded-v1',_fx_available:true}};
      const global={indices:{},extras:{usdcnh:[{date:'20261110',value:700}]},extras_signals:{usdcnh:[{signal:'sell'}]}};
      _guardFxPayload('global-all.json',global);
      const archive={signals_today:[{index_id:'g.usdcnh'}]};
      const quote={fx:{code:'133.USDCNH',price:7.1}};
      _guardFxPayload('trades.json',archive);_guardFxPayload('intraday_snapshot.json',quote);
      const newScores={today:{scores:{cross_market:fresh}}};_guardFxPayload('overview.json',newScores);
      // Exercise the real shared fetchJSON success/cache path with a local transport stub.
      Object.assign(window,{_isMainSite:()=>true,_NO_CACHE_URLS:/$^/,_NO_R2_CACHE_URLS:/$^/,_resultCache:new Map(),_inflightFetch:new Map(),_CACHE_TTL:300000,_R2_FALLBACK_BASE:'http://invalid/',_tdsSsdUrlFor:()=>null});
      let calls=0;
      window.fetch=async()=>{calls++;return new Response(JSON.stringify({extras:{usdcnh:[{value:700}]},extras_signals:{usdcnh:[{signal:'sell'}]},indices:{}}));};
      const fetched=await fetchJSON('./data/global-all.json');
      const cached=await fetchJSON('./data/global-all.json');
      const notifications={signals_today:[{index_id:'g.usdcnh'}],signals:[{index_id:'g.usdcnh'},{index_id:'sh'}],alerts:{high:{score:99,triggered:true},low:{score:99,triggered:true}},fear_greed:{value:99}};
      _guardFxPayload('notifications.json',notifications);
      const summaries={items:[{date:'20261111',summary_short:'旧过热99',fear_greed_value:99,buy_count:99}]};
      _guardFxPayload('summary_history.json',summaries);
      return {boot,global,archive,quote,newScores,fetched,cached,calls,notifications,summaries};
    });
    assert.equal(result.boot.overview.today.scores.cross_market.value,null);checks++;
    assert.equal(result.boot.overview.today.scores.fear_greed.value,null);checks++;
    assert.deepEqual(result.boot.overview.signals_today.map(x=>x.index_id),['sh']);checks++;
    assert.equal(result.boot.signal_stats['g.usdcnh'],undefined);checks++;
    assert.equal(result.boot.alert.availability,'unavailable');checks++;
    assert.deepEqual(result.boot.overview.recent_freeze.map(x=>x.score_id),['a_sentiment']);checks++;
    assert.equal(result.boot.overview.sentiment_calendar.length,0);checks++;
    assert.equal(result.newScores.today.scores.cross_market.value,43);checks++;
    assert.equal(result.global.extras.usdcnh.length,0);checks++;
    assert.equal(result.archive.signals_today.length,1);checks++;
    assert.equal(result.quote.fx.code,'133.USDCNH');checks++;
    assert.equal(result.fetched.extras.usdcnh.length,0);checks++;
    assert.equal(result.cached.extras.usdcnh.length,0);checks++;
    assert.equal(result.calls,1);checks++;
    assert.equal(result.notifications.alerts.high.score,null);checks++;
    assert.equal(result.notifications.alerts.low.triggered,false);checks++;
    assert.equal(result.notifications.fear_greed,null);checks++;
    assert.equal(result.summaries.items[0].fear_greed_value,null);checks++;
    assert.equal(result.summaries.items[0].buy_count,null);checks++;
    assert.doesNotMatch(result.summaries.items[0].summary_short,/99|中性/);checks++;
    assert.deepEqual(result.notifications.signals.map(x=>x.index_id),['sh']);checks++;
    await page.evaluate(()=>{
      Object.assign(window,{content:document.getElementById('content'),state:{range:'all',intradaySnapshot:null},dataUrl:x=>'./data/'+x,
        renderLoadingState:()=>{},renderErrorState:(_,e)=>{throw e;},fetchIntradaySnapshot:async()=>null,
        renderPurposeNote:()=>{},PURPOSE_NOTES:{},_renderUSFuturesExpect:()=>{},
        buildIndexAnchorBar:()=>{const d=document.createElement('nav');d._observeIndexCard=()=>{};return d;}});
    });
    await page.evaluate(code => { (0, eval)(code); }, block('async function renderGlobal(', '// 情绪分组成因子展开区'));
    await page.evaluate(()=>renderGlobal());
    const liteStart=src.indexOf('function _lwSignalLiteCfg(');
    const liteEnd=src.indexOf('\nfunction ',liteStart+10);
    await page.evaluate(code => { (0,eval)(code); },src.slice(liteStart,liteEnd));
    const nullChart=await page.evaluate(()=>{
      window._lwSignalMarkPoints=()=>({markPoints:[],gradients:[]});window.fmtDate=x=>x;
      const c=_lwSignalLiteCfg('跨市场',[{date:'20261111',value:null,availability:'unavailable'}],[],{},null,true);
      return {values:c.series[0].data,tip:c.tipFn(0,'20261111')};
    });
    assert.deepEqual(nullChart.values,[null]);checks++;
    assert.match(nullChart.tip,/不可用/);checks++;
    assert.doesNotMatch(nullChart.tip,/0\.00|50\.00|中性/);checks++;

    assert.match(await page.locator('#idx-card-usdcnh').innerText(),/指标不可用/);checks++;
    assert.match(await page.locator('#idx-card-usdcnh').innerText(),/每1美元/);checks++;
    assert.match(await page.locator('#idx-card-usdcnh').innerText(),/日线待重建/);checks++;
    assert.doesNotMatch(await page.locator('#idx-card-usdcnh').innerText(),/700|卖点|中性/);checks++;
    for(const fn of ['sentimentTag','fearGreedLabel','fearGreedColor','latestSuffix','latestSuffixPct','_calc6mPercentile']) {
      const start=src.indexOf('function '+fn+'(');const end=src.indexOf('\nfunction ',start+10);
      await page.evaluate(code=>{(0,eval)(code);},src.slice(start,end));
    }
    const labels=await page.evaluate(()=>({sentiment:sentimentTag(null),fear:fearGreedLabel(null),suffix:latestSuffixPct([{date:'20261111',value:null}]),percentile:_calc6mPercentile([{value:0},{value:50}],null)}));
    assert.deepEqual(labels,{sentiment:'',fear:'',suffix:'',percentile:null});checks++;
    for(const fn of ['_ntSparkGeom','_ntSparkSVG','ntIndexSparkline','_niceNumber','_intervalPrecision','_roundTo','_getPrecision']) {
      const start=src.indexOf('function '+fn+'(');const end=src.indexOf('\nfunction ',start+10);
      await page.evaluate(code=>{(0,eval)(code);},src.slice(start,end));
    }
    const spark=await page.evaluate(()=>({
      values:_ntSparkGeom([null,null],['a','b'],200,30)._vals,
      empty:ntIndexSparkline([null,null],['a','b'],'red',200,30),
      gaps:_ntSparkSVG([0,1,null,2,3],['a','b','c','d','e'],'red',200,30),
      positive:_ntSparkSVG([0,1],['a','b'],'red',200,30)
    }));
    assert.deepEqual(spark.values,[null,null]);checks++;
    assert.equal(spark.empty,'');checks++;
    assert.equal((spark.gaps.match(/<path/g)||[]).length,4);checks++;
    assert.doesNotMatch(spark.gaps,/NaN|Infinity/);checks++;
    assert.equal((spark.positive.match(/<path/g)||[]).length,2);checks++;
    const flushStart=src.indexOf('function _flushNtSpark('), flushEnd=src.indexOf('\nfunction ',flushStart+10);
    await page.evaluate(code=>{(0,eval)(code);},src.slice(flushStart,flushEnd));
    const ech=await page.evaluate(()=>{
      const host=document.createElement('div');host.className='nt-spark-ech';host.dataset.sid='test-null';document.body.appendChild(host);
      window._ntSparkPending=new Map([['test-null',{closes:[0,null,2],dates:['a','b','c'],color:'red'}]]);
      window.charts=[];window.withTheme=x=>x;
      let cfg;window.echarts={getInstanceByDom:()=>null,init:()=>({setOption:c=>{cfg=c;}})};
      _flushNtSpark();host.remove();
      return {data:cfg.series[0].data,tip:cfg.tooltip.formatter([{dataIndex:1}])};
    });
    assert.deepEqual(ech.data,[0,null,2]);checks++;
    assert.equal(ech.tip,'b<br/>-');checks++;
    const out=process.env.FX_EVIDENCE_DIR;
    if(out)await page.screenshot({path:path.join(out,'fx-mobile.png'),fullPage:true});
    await page.setViewportSize({width:1440,height:900});
    assert.equal(await page.locator('#idx-card-usdcnh').count(),1);checks++;
    if(out)await page.screenshot({path:path.join(out,'fx-desktop.png'),fullPage:true});
    console.log(`FX browser: ${checks} assertions passed; actual fetch/cache/renderGlobal; no external network`);
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
