import fs from 'fs';
const r = JSON.parse(fs.readFileSync('/tmp/sentiment-all.json','utf8'));
const keyId = 's.sentiment_sz50';   // 弹窗 indexId 完整带 s. 前缀
const dataRaw = r.sentiment_sz50 || [];
const chartDataRaw = dataRaw.map((d) => ({ date: d.date, value: d.value, is_freeze: d.is_freeze }));

function freezeCheck(chartData, indexId) {
  const startS = String(indexId).startsWith("s.");
  if (!startS) return [];
  return chartData.filter((d) => (d.value != null && (d.is_freeze === 1 || d.value <= 20)))
    .map((d) => ({ date: d.date, signal: "freeze", value: d.value }));
}

const fromBuy = freezeCheck(chartDataRaw, keyId);
console.log("场景1 买卖点cell进 s.* 弹窗 → 冰点 pin 数:", fromBuy.length);
console.log("  首个:", JSON.stringify(fromBuy[0]));

const fromFreeze = freezeCheck(chartDataRaw, keyId);
console.log("场景2 冰点cell进 s.* 弹窗 → 冰点 pin 数:", fromFreeze.length, "(==场景1 恒显不减)");

const oldCt = chartDataRaw.filter(d => d.value != null && d.value <= 20).length;
console.log("旧口径 value<=20:", oldCt, "| 新口径 is_freeze优先:", fromBuy.length, "| 恒显不减少:", fromBuy.length >= oldCt);

// 只有 is_freeze===1(数据标记准)才不影响? 验证 is_freeze 独立贡献
const onlyMark = chartDataRaw.filter(d => d.is_freeze === 1).length;
console.log("纯 is_freeze=1 标记数:", onlyMark);
const onlyVal = chartDataRaw.filter(d => d.value != null && d.value <= 20).length;
console.log("纯 value<=20 数:", onlyVal);

// 全球extras / 恐贪(g.* / 非s.*) 不补冰点
console.log("全球extras(gold 弹窗) ice pin(应0):", freezeCheck(chartDataRaw, "gold").length);
console.log("恐贪弹窗(fear_greed 非s.*) ice pin(应0):", freezeCheck(chartDataRaw, "fear_greed").length);
