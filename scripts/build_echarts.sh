#!/usr/bin/env bash
# build_echarts.sh - 定制构建 echarts（仅含项目用到的 line/bar/heatmap/scatter + 组件）。
#
# 背景：线上 MaoziYun 无服务端压缩（NOTES §21），vendor/echarts.min.js 全量 1MB 原样传输。
# 定制构建只打包用到的图表/组件，1MB -> ~615KB（减约 400KB 首屏传输）。
# 用法校验：grep static-site/app.js + lab.js 确认仅用 line/bar/heatmap/scatter 及
#   grid/tooltip/legend/dataZoom/visualMap/title/markLine/markPoint/markArea/axisPointer，
#   API 仅用 echarts.init + echarts.getInstanceByDom。改前端图表类型后须重跑本脚本核对。
#
# 产出：覆盖 static-site/vendor/echarts.min.js + web/vendor/echarts.min.js（双版同步）。
#   改完跑：python scripts/bump_asset_version.py  刷新 index.html 的 ?v= 破缓存。
#
# 依赖：node + npx esbuild + echarts（首次自动 npm install 到 $ECHARTS_BUILD_DIR）。
# 用法：bash scripts/build_echarts.sh
set -u

REPO="${REPO:-/Users/linhuichen/code/trade}"
SPIKE="${ECHARTS_BUILD_DIR:-/tmp/echarts-spike}"
mkdir -p "$SPIKE"
cd "$SPIKE"

[ -f package.json ] || npm init -y >/dev/null 2>&1
[ -d node_modules/echarts ] || npm install echarts >/dev/null 2>&1
[ -d node_modules/esbuild ] || npm install esbuild >/dev/null 2>&1

# entry：注册用到的图表+组件+Canvas 渲染器；export * 把 init/use/getInstanceByDom/connect/...
# 重新导出到 global（勿用 export default，否则 global 变成 {default:...} 致 echarts.init 失效）。
cat > entry.js <<'ENTRY'
import * as echarts from 'echarts/core';
import { LineChart, BarChart, HeatmapChart, ScatterChart } from 'echarts/charts';
import {
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  VisualMapComponent, TitleComponent, MarkLineComponent, MarkPointComponent,
  MarkAreaComponent, AxisPointerComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
echarts.use([
  LineChart, BarChart, HeatmapChart, ScatterChart,
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  VisualMapComponent, TitleComponent, MarkLineComponent, MarkPointComponent,
  MarkAreaComponent, AxisPointerComponent, CanvasRenderer,
]);
export * from 'echarts/core';
ENTRY

npx esbuild entry.js --bundle --minify --format=iife --global-name=echarts --outfile=echarts.custom.min.js

SZ=$(stat -f%z echarts.custom.min.js 2>/dev/null || stat -c%s echarts.custom.min.js 2>/dev/null)
echo "定制 echarts 构建完成：${SZ} bytes"

cp echarts.custom.min.js "$REPO/static-site/vendor/echarts.min.js"
cp echarts.custom.min.js "$REPO/web/vendor/echarts.min.js"
echo "已覆盖：$REPO/static-site/vendor/echarts.min.js + $REPO/web/vendor/echarts.min.js"
echo "下一步：python $REPO/scripts/bump_asset_version.py  （刷新 index.html 的 ?v= 破缓存）"
