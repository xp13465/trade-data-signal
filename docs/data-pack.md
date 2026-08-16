# 历史数据包（知识商店数字资产）

> 2026-08-17 上线 · B 级新功能 · 为 UUMit 平台「历史数据包」知识商店数字资产做可交付物。

## 是什么

核心衍生数据全史打包成 zip，带版本号 + 包级 README + SHA256 校验和，可上架 UUMit 知识商店。
**只含自研衍生加工数据，绝不打包第三方原始行情**（global/hk/industry/a-stock 的 indices 一律不含）。

## 打包清单（11 个文件）

| 包内文件 | 源文件 | 内容 |
|---|---|---|
| sentiment-all.json | static-site/data/sentiment-all.json | 恐贪/情绪/跨市场全史序列 |
| etf_national_team-all.json | static-site/data/etf_national_team-all.json | 国家队 ETF 持仓历史 |
| etf_score_list.json | static-site/data/etf_score_list.json | ETF 综合评分列表 |
| signal_freq.json | static-site/data/signal_freq.json | 买卖信号频率聚合 |
| rotation.json | static-site/data/rotation.json | 板块轮动速度 |
| ma_alignment.json | static-site/data/ma_alignment.json | 均线多空排列家数 |
| volume_ratio.json | static-site/data/volume_ratio.json | 全市场量能 |
| new_high_low.json | static-site/data/new_high_low.json | 52周/20日新高新低家数 |
| futures.json | static-site/data/futures.json | 期货机构多空持仓/多空比 |
| overview.json | static-site/data/overview.json | 每日综合评分/信号灯/今日信号 |
| a-stock-3m_metrics.json | static-site/data/a-stock-3m.json | A股宽度指标（**已剥离 indices 原始行情**，只取 metrics 部分） |

## 怎么生成

```bash
# 打包今天
python3 scripts/gen_data_pack.py

# 打包指定日
python3 scripts/gen_data_pack.py --date 20260814

# 列历史包
python3 scripts/gen_data_pack.py --list
```

输出到 `data_packs/<YYYYMMDD>/`：

- `financial-data-pack-<YYYYMMDD>.zip` — 内含各 JSON + `README.md`
- `SHA256SUMS` — 每个文件 sha256（未裁剪文件与 `static-site/data/` 源文件**逐位一致**）
- `README.md` — 包级说明（版本号/生成日期/数据截止日期/字段说明/合规声明）

每次跑输出新目录（不同日期），不覆盖旧包。

## 数据一致性（§22）

- **未裁剪文件**：zip 内字节 = `static-site/data/` 源文件字节（原样写入，不重序列化），sha256 与源文件逐位一致。
- **裁剪文件**：`a-stock-3m_metrics.json` 是重序列化的裁剪版（只含 `metrics`，剥离 `indices`），sha256 对应 zip 内字节。
- 校验：`shasum -a 256 -c SHA256SUMS`（macOS）或 `sha256sum -c SHA256SUMS`（Linux）。

## 怎么上架知识商店（数字资产形态）

1. 生成包：`python3 scripts/gen_data_pack.py`（生成当日常态）。
2. 上架：把 `data_packs/<YYYYMMDD>/financial-data-pack-<YYYYMMDD>.zip` + `SHA256SUMS` + `README.md` 作为 UUMit 知识商店数字资产上架，商品描述引用 `README.md` 的字段说明/数据口径/合规声明。
3. 交付校验：买家下载后 `shasum -a 256 -c SHA256SUMS` 验完整性；未裁剪文件可与站点公开 JSON 逐位比对。

## 合规

- **绝不打包原始第三方行情**：`a-stock-3m_metrics.json` 已剥离 `indices`；global/hk/industry 类原始行情不在打包清单内。
- 包级 README 附合规声明：**衍生加工数据，原始行情不包含**。

## 复现

- 生成脚本：`scripts/gen_data_pack.py`（依赖 `static-site/data/` 源文件 + 仓库 `.venv`）
- 生成命令：`python3 scripts/gen_data_pack.py --date YYYYMMDD`
- 数据截止日期：取 `overview.json.date`（权威主源）
- 校验：`shasum -a 256 -c SHA256SUMS`
