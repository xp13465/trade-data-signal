#!/usr/bin/env node
/** kelly_ghi_stability_v117.mjs — G/H/I 定稿档 稳定性+极端窗口补充分析 (v1.1.7 baseline)
 * 输入: kelly_ghi_sweep_out.json 同源管道(复用 kelly_ghi_sweep_v117.mjs 的 vm 提取与 recompute 数组).
 * 分析: ①分半(<=2018 vs >=2019) ②多起点(2015/2018/2021 起) ③极端窗口(2011-12/2015股灾/2018熊/2022回撤)
 * 输出: 终端 + kelly_ghi_stability_out.json
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..", "..", "..");

// --- 复用 sweep 脚本的 sliceDecl/extract/ctx 构建(sweep 脚本结构一章复制, 防止文件自动漂移) ---
const SWEEP = path.join(__dirname, "kelly_ghi_sweep_v117.mjs");
const sweepSrc = fs.readFileSync(SWEEP, "utf8");

/** 从 sweep 脚本源码里提取「函数定义的都带行需依赖」简化法: 直接构造 ctx 一时难以绝对复用,
 *  这里不 eval 整个 sweep(会跑主流程), 改为: 把 sweep 里已计算好的 recon 数组从输出 JSON 的
 *  _reconCache 一眼不可取 → 因此本条脚本从零缓? 不如让 sweep 脚本把 recon 数组落盘, 本脚本读之。 */
console.error("请先让 sweep 脚本落盘 recon 数组。见脚本头部说明。");
