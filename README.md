# A股/港股/全球 情绪数据复盘看板

盘后复盘用的金融情绪数据看板。每日收盘后定时采集 A股/港股/全球的情绪、宽度、资金、结构类指标，存 SQLite，前端 ECharts 按天折线展示趋势与拐点，计算两个综合分（A股综合情绪分 + 跨市场综合评分），并在指数图上标注买点/卖点。

需求详见 [REQUIREMENTS.md](REQUIREMENTS.md)，实现方案详见 [PLAN.md](PLAN.md)，**使用方法与注意事项详见 [HELP.md](HELP.md)**。

## 环境约束
- pypi.org / github.com DNS 不通 → 依赖经国内镜像安装，akshare 数据源（东财/新浪/腾讯）可直连
- akshare 1.18.64 已验证可用

## 安装
```bash
python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

## 初始化数据库
```bash
.venv/bin/python -m app.db
```

## 首次回填（1 年历史）
```bash
.venv/bin/python -m app.backfill
```

## 手动跑一次当日采集
```bash
.venv/bin/python -m app.scheduler
```

## 启动看板
```bash
.venv/bin/uvicorn app.main:app --port 8000
# 浏览器打开 http://localhost:8000
```

## 定时任务（launchd，每交易日 15:30）
```bash
cp launchd/com.trade.sentiment.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.trade.sentiment.plist
```

## 指标增删
改 `config/indicators.yaml`，无需动代码（采集与展示均配置驱动）。
