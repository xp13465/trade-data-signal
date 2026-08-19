// 需求B 仿真: tooltip formatter 输出格式(与 app.js 改后 valueChartWithSignals formatter / _lwSignalLiteCfg tipFn 等价)
// 场景: s.sentiment_kc50 情绪分弹窗, 叠科创50指数(idxOv.name="科创50")
const fmtDate = (d) => { const y=d.slice(0,4),m=d.slice(4,6),dd=d.slice(6,8); return y+"-"+m+"-"+dd; };

function echartsTooltip(dt, p, idxOv, idxAlign, isSentiment) {
  const _sentimentLabel = isSentiment ? ((idxOv && idxOv.name) ? idxOv.name + " 情绪分" : "情绪分") : null;
  let tip = fmtDate(dt);
  if (_sentimentLabel && p && p.value != null) {
    tip += "  " + _sentimentLabel + " " + "<b>" + Number(p.value).toFixed(2) + "</b>";
  } else if (p && p.value != null) {
    tip += "<br/>" + Number(p.value).toFixed(2);
  }
  if (idxOv && idxAlign) {
    const iv = idxAlign[0];
    if (iv != null && !isNaN(iv)) tip += '<br/><span style="display:inline-block;width:8px;height:2px;background:#b08d57;margin-right:4px;vertical-align:middle"></span>' + (idxOv.name || "指数") + "指数: " + Number(iv).toFixed(2);
  }
  return tip;
}

// 测试1: s.* 弹窗 叠指数(用户点名格式) —— dt=2026-07-17, value=15.82, 指数=1715.40
let out = echartsTooltip("20260717", {value:15.82}, {name:"科创50"}, [1715.40], true);
console.log("T1 s.*叠指数 弹窗(应'07-17 科创50 情绪分 15.82' + '科创50指数:1715.40'):");
console.log("  >>", out);
console.log("  含'科创50 情绪分':", out.includes("科创50 情绪分"));
console.log("  含'创业指数'误拼检查(应false):", out.includes("创业指数"), "| 含'科创50指数:':", out.includes("科创50指数:"));
console.log("  含日期+情绪值一行:", out.replace(/<[^>]+>/g,'').includes("2026-07-17  科创50 情绪分 15.82"));

// 测试2: 综合类(恐贪/跨市场/a_sentiment, isSentiment=true, 无指数) → 情绪分标签, 无指数行
const out2 = echartsTooltip("20260717", {value:55.3}, null, null, true);
console.log("\nT2 综合类无指数(应带'情绪分'标签, 无指数行):");
console.log("  >>", out2);
console.log("  含'情绪分':", out2.includes("情绪分"), "| 无指数名:", !out2.includes("指数:"));

// 测试3: 全球extras(g.*, isSentiment=false) → 保持 日期+裸值, 无标签无指数
const out3 = echartsTooltip("20260717", {value:550.2}, null, null, false);
console.log("\nT3 全球extras(isSentiment=false, 应保持'日期'+换行'值'):");
console.log("  >>", out3);
console.log("  无情绪分标签:", !out3.includes("情绪分"), "| 值独立换行:", out3.includes("<br/>550.20"));

// 测试4: lite 态 tipFn(i=索引) 同口径
function liteTip(i, dt, p, idxVals, idxOv, isSentiment) {
  const _sentimentLabel = isSentiment ? ((idxOv && idxOv.name) ? idxOv.name + " 情绪分" : "情绪分") : null;
  let tip = fmtDate(dt);
  if (_sentimentLabel && p && p.value != null) {
    tip += "  " + _sentimentLabel + " " + "<b>" + Number(p.value).toFixed(2) + "</b>";
  } else if (p && p.value != null) {
    tip += "<br/>" + Number(p.value).toFixed(2);
  }
  if (idxOv) {
    const iv = idxVals[i];
    if (iv != null && !isNaN(iv)) tip += '<br/><span style="display:inline-block;width:8px;height:2px;background:#b08d57;margin-right:4px;vertical-align:middle"></span>' + (idxOv.name || "指数") + "指数: " + Number(iv).toFixed(2);
  }
  return tip;
}
const out4 = liteTip(5, "20260717", {value:15.82}, [1715.40], {name:"科创50"}, true);
console.log("\nT4 lite 态 s.*叠指数(应与T1一致):");
console.log("  >>", out4);
console.log("  lite==echarts 一致:", out4 === out);

// 修正 T4: idxVals 应为完整对齐数组, tipFn 的 i 是正确索引
function liteTip2(i, dt, p, idxVals, idxOv, isSentiment) {
  const _sentimentLabel = isSentiment ? ((idxOv && idxOv.name) ? idxOv.name + " 情绪分" : "情绪分") : null;
  let tip = fmtDate(dt);
  if (_sentimentLabel && p && p.value != null) {
    tip += "  " + _sentimentLabel + " " + "<b>" + Number(p.value).toFixed(2) + "</b>";
  } else if (p && p.value != null) {
    tip += "<br/>" + Number(p.value).toFixed(2);
  }
  if (idxOv) {
    const iv = idxVals[i];
    if (iv != null && !isNaN(iv)) tip += '<br/><span style="display:inline-block;width:8px;height:2px;background:#b08d57;margin-right:4px;vertical-align:middle"></span>' + (idxOv.name || "指数") + "指数: " + Number(iv).toFixed(2);
  }
  return tip;
}
const fullIdxVals = [1715.40];
const out4b = liteTip2(0, "20260717", {value:15.82}, fullIdxVals, {name:"科创50"}, true);
console.log("\nT4b lite 态正确索引(i=0):");
console.log("  >>", out4b);
console.log("  lite==echarts 一致:", out4b === out);
