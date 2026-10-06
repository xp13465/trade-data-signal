# -*- coding: utf-8 -*-
"""#219 治本自测: parts 元数据撤出 → 两把尺子合流(2026-10-06)。

背景(根因报告 docs/ops/219-verify-r2-backfill-rootcause-20261006.md):
  上传链 `upload_r2._kelly_parts_md5` 用 B 档结构化指纹(剔除 generated_at/period_cutoffs/
  buy_amount)判「内容没变→跳过」; 而 verify-r2 用**整文件 md5**(`_file_md5`)对账。
  export 每轮重写这三字段 ⇒ 整文件 md5 每轮都变 ⇒ verify 每轮必然全量「对不上」⇒ 每轮补传
  整目录(~179MB/轮 × 5~7 轮/天 ≈ 0.9~1.2GB/天跨境), 数据本体其实零变化。

  治本 = 生成端(`signal_kelly_backtest._export_trades_parts._dump`)**撤出**这三字段(且
  sort_keys 规范化), 令 parts 文件只含数据本体 {fields,quadrants}。则 file_md5 ≡ B 档指纹。

本测试覆盖三条硬要求:
  ① 连续两次生成(gen/period_cutoffs 不同)的 parts 整文件 md5 稳定。
  ② 负控:「内容真变」与「R2 真丢/破坏」两种情形, 上传判据与 verify 判据仍判「要补传」。
  ③ 前端 `_simParseTrades`(app.js)/ `_labKellyParseTrades`(lab.js) 解析结果逐字段不变
     (用 node 抽取**真实函数源码**在旧/新两格式文件上运行对比, 非复述实现)。

另含「登记点守护」: 断言 verify-r2 判据仍 = `_file_md5` + ETag 比对、B 档指纹仍剔除三字段,
  防未来两侧尺子被单边改动造成口径再次错位。
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]          # trade/ 仓库根
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO))

import signal_kelly_backtest as skb  # noqa: E402
# upload_r2 顶层 load_env() 在无 .env(CI)时会 sys.exit(收集期崩 → ⑧ 全灭);
# 所需的临时 .env 垫片由 conftest.py §④ 在收集期统一铺好(GIT_REPO 指向垫片), 本文件无需自建。
import upload_r2 as ur  # noqa: E402

FIELDS = ["signal_date", "index_id", "signal", "profit"]
FE_META = ("generated_at", "buy_amount", "period_cutoffs")


def _row(sd, idx, sig, profit):
    return [sd, idx, sig, profit]


def _body_quadrants():
    """真实结构的最小 quadrants: 含 recent 窗口内 + 跨年份行。"""
    return {
        "rating_high": {
            "m_greedy": [_row("20260110", "IDX1", "buy", 5.0),
                          _row("20250101", "IDX2", "buy", 3.0)],
            "m_aux": [_row("20240101", "IDX3", "sell", -2.0)],
        },
        "rating_low": {
            "m_greedy": [_row("20150101", "IDX4", "buy", 1.0)],
        },
    }


def _trades_data(gen_at, cutoffs):
    return {
        "generated_at": gen_at,
        "buy_amount": 10000,
        "period_cutoffs": dict(cutoffs),
        "fields": list(FIELDS),
        "quadrants": _body_quadrants(),
    }


def _export(tmpdir, data):
    """跑真实导出, 返回 {name: bytes} 与 parts 目录。"""
    trades_path = os.path.join(tmpdir, "signal_kelly_trades.json")
    skb._export_trades_parts(data, trades_path)
    parts_dir = skb._trades_parts_dir(trades_path)
    out = {}
    for p in sorted(Path(parts_dir).glob("*.json")):
        out[p.name] = p.read_bytes()
    return out, Path(parts_dir)


def _md5(b):
    return hashlib.md5(b).hexdigest()


# ── ① 连续两次生成 → 整文件 md5 稳定 ────────────────────────────────────────
def test_c1_two_rounds_stable(tmp_path):
    cut_a = {"y1": "20251006", "y3": "20231007", "y5": "20211007",
             "y10": "20161008", "all": "0"}
    cut_b = {"y1": "20251007", "y3": "20231008", "y5": "20211008",
             "y10": "20161009", "all": "0"}   # 次日的滚动切点(每天变)
    d1 = tmp_path / "r1"
    d2 = tmp_path / "r2"
    d1.mkdir()
    d2.mkdir()
    files_a, _ = _export(str(d1), _trades_data("2026-10-06 17:56", cut_a))
    files_b, _ = _export(str(d2), _trades_data("2026-10-06 21:12", cut_b))  # 元数据全变、本体不变
    assert files_a, "导出应产出至少 recent.json"
    assert set(files_a) == set(files_b)
    for name in files_a:
        assert _md5(files_a[name]) == _md5(files_b[name]), (
            f"{name}: 本体不变时两次生成的整文件 md5 应逐位一致"
            f"(实测 {_md5(files_a[name])} vs {_md5(files_b[name])})")
    print(f"① 稳定 OK: {len(files_a)} 片跨两轮 md5 逐位一致")


# ── 文件只含数据本体 + 两尺合流 + 状态指纹连续 ──────────────────────────────
def test_c2_shape_and_ruler_convergence(tmp_path):
    files, parts_dir = _export(str(tmp_path), _trades_data("2026-10-06 17:56",
                                                           {"y1": "20251006", "all": "0"}))
    recent = parts_dir / "recent.json"
    payload = json.loads(recent.read_text(encoding="utf-8"))
    # 只含数据本体, 三字段全撤出
    assert set(payload.keys()) == {"fields", "quadrants"}, f"顶层键异常: {set(payload.keys())}"
    for k in FE_META:
        assert k not in payload, f"元数据字段 {k} 未撤出"
    assert payload["fields"] == FIELDS

    # 两把尺子合流: 整文件 md5 == B 档指纹
    assert ur._file_md5(recent) == ur._kelly_parts_md5(recent), (
        "撤出后应满足 file_md5 ≡ B 档指纹(两把尺子同一把)")

    # 状态指纹连续: 旧格式(含三字段)文件的 B 档指纹 == 新格式文件指纹
    # (⇒ 切换后上传链不会因状态失配误判"全变"再来一次上传风暴)
    # 同一分片本体(注意 recent.json 是窗口子集, 不可用全量 quadrants 拼旧文件)
    oldfmt = tmp_path / "old_recent.json"
    old_payload = dict(payload)
    old_payload["generated_at"] = "2026-10-06 17:56"
    old_payload["buy_amount"] = 10000
    old_payload["period_cutoffs"] = {"y1": "20251006", "all": "0"}
    oldfmt.write_text(json.dumps(old_payload, ensure_ascii=False, separators=(",", ":")),
                      encoding="utf-8")
    assert ur._kelly_parts_md5(oldfmt) == ur._kelly_parts_md5(recent), (
        "旧(含三字段)与新(仅本体)文件的 B 档指纹应一致 ⇒ 状态连续, 无上传风暴")
    print("② 形态/合流/状态连续 OK")


# ── ③ 负控 A: 内容真变 → 两侧尺子都发现 ─────────────────────────────────────
def test_c3a_neg_control_content_change(tmp_path):
    d1 = tmp_path / "a";  d1.mkdir()
    d2 = tmp_path / "b";  d2.mkdir()
    base = _trades_data("2026-10-06 17:56", {"y1": "20251006", "all": "0"})
    files_a, dir_a = _export(str(d1), base)

    mutated = _trades_data("2026-10-06 17:56", {"y1": "20251006", "all": "0"})
    mutated["quadrants"]["rating_high"]["m_greedy"][0][3] = 99.0  # profit 真变
    files_b, dir_b = _export(str(d2), mutated)

    ra, rb = dir_a / "recent.json", dir_b / "recent.json"
    # 上传链判据(B 档)发现变化 ⇒ 会传
    assert ur._kelly_parts_md5(ra) != ur._kelly_parts_md5(rb), "内容真变时 B 档指纹必须变(上传链须传)"
    # verify 判据(整文件 md5)发现变化 ⇒ 会补传
    assert ur._file_md5(ra) != ur._file_md5(rb), "内容真变时整文件 md5 必须变(verify 须补传)"
    print("③-A 内容真变 OK: 上传/verify 两侧均发现")


# ── ③ 负控 B: R2 真丢 / 被破坏 → verify 仍判补传 ────────────────────────────
def test_c3b_neg_control_r2_loss(tmp_path):
    files, parts_dir = _export(str(tmp_path), _trades_data("2026-10-06 17:56",
                                                           {"y1": "20251006", "all": "0"}))
    recent = parts_dir / "recent.json"
    local_md5 = ur._file_md5(recent)

    # verify-r2 判据(upload_r2.py cmd_verify_r2._check L3504-3509):
    #   ok = etag is not None and etag.strip('"') == local_md5
    def _verify_ok(etag):
        return etag is not None and etag.strip('"') == local_md5

    assert _verify_ok(f'"{local_md5}"') is True, "R2 与本地一致时应判 ok"
    assert _verify_ok(None) is False, "R2 对象丢失(404, etag=None)应判不一致→补传"
    assert _verify_ok('"deadbeef"') is False, "R2 被破坏(etag≠本地)应判不一致→补传"
    other = tmp_path / "other.json"
    other.write_bytes(recent.read_bytes() + b"X")  # 同前缀异内容近似
    assert _verify_ok(f'"{ur._file_md5(other)}"') is False, "同/近大小异内容应判不一致"
    print("③-B R2 真丢/破坏 OK: verify 仍判补传")


# ── ③ 前端解析逐字段不变(node 抽取真实函数源码比对) ─────────────────────────
def test_c3c_frontend_parse_equivalent(tmp_path):
    files, parts_dir = _export(str(tmp_path), _trades_data("2026-10-06 17:56",
                                                           {"y1": "20251006", "all": "0"}))
    new_file = parts_dir / "recent.json"
    old_file = tmp_path / "old_recent.json"
    # 旧格式 = 同一分片本体 + 三字段(模拟改前产物); 保证两文件仅差这三个顶层键
    new_payload = json.loads(new_file.read_text(encoding="utf-8"))
    old_payload = dict(new_payload)
    old_payload["generated_at"] = "2026-10-06 17:56"
    old_payload["buy_amount"] = 10000
    old_payload["period_cutoffs"] = {"y1": "20251006", "all": "0"}
    old_file.write_text(json.dumps(old_payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")

    node = ("/Users/linhuichen/.nvm/versions/node/v25.8.0/bin/node"
            if Path("/Users/linhuichen/.nvm/versions/node/v25.8.0/bin/node").exists()
            else "node")
    js = r"""
const fs=require('fs');
function extract(src,name){
  const sig='function '+name+'(';
  const i=src.indexOf(sig); if(i<0) throw new Error('fn not found: '+name);
  let depth=0,started=false,k=i;
  for(;k<src.length;k++){const c=src[k];
    if(c==='{'){depth++;started=true;}
    else if(c==='}'){depth--; if(started&&depth===0){k++;break;}}
  }
  return src.slice(i,k);
}
const appSrc=fs.readFileSync(process.argv[1],'utf8');
const labSrc=fs.readFileSync(process.argv[2],'utf8');
eval(extract(appSrc,'_simParseTrades'));
eval(extract(labSrc,'_labKellyParseTrades'));
function canon(o){ if(Array.isArray(o)) return o.map(canon);
  if(o&&typeof o==='object'){const r={}; Object.keys(o).sort().forEach(k=>r[k]=canon(o[k])); return r;} return o; }
const oldF=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const newF=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
const pa = _simParseTrades(oldF), pb = _simParseTrades(newF);
const la = _labKellyParseTrades(oldF), lb = _labKellyParseTrades(newF);
const SA=JSON.stringify(canon(pa)), SB=JSON.stringify(canon(pb));
const LA=JSON.stringify(canon(la)), LB=JSON.stringify(canon(lb));
if(SA!==SB){console.error('app._simParseTrades 结果不一致:\n'+SA+'\n'+SB); process.exit(1);}
if(LA!==LB){console.error('lab._labKellyParseTrades 结果不一致:\n'+LA+'\n'+LB); process.exit(1);}
// 解析结果只应含 fields/fIdx/quadrants 三键, 无元数据泄漏
const keys=Object.keys(pb).sort().join(',');
if(keys!=='fIdx,fields,quadrants'){console.error('解析结果键异常: '+keys); process.exit(1);}
console.log('OK app+lab parse identical; keys='+keys);
"""
    r = subprocess.run([node, "-e", js,
                        str(REPO / "static-site" / "app.js"),
                        str(REPO / "static-site" / "lab.js"),
                        str(old_file), str(new_file)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"node 解析等价检查失败:\n{r.stdout}\n{r.stderr}"
    assert "OK" in r.stdout
    print("③-C 前端解析等价 OK:", r.stdout.strip())


# ── 登记点守护: 两侧尺子语义未被单边改动 ───────────────────────────────────
def test_c4_ruler_registration_guard():
    up_src = (SCRIPTS / "upload_r2.py").read_text(encoding="utf-8")
    # verify 判据仍 = 整文件 md5 vs ETag(小文件分支)
    assert "local_md5 = _file_md5(f)" in up_src, "verify 判据应仍取 _file_md5(整文件)"
    assert """etag.strip('"') == local_md5""" in up_src, "verify 判据应仍比对 ETag==本地 md5"
    # B 档指纹仍剔除三字段(过渡兼容 + 防御回流)
    for k in FE_META:
        assert f'payload.pop("{k}", None)' in up_src, f"_kelly_parts_md5 应仍剔除 {k}"
    # 生成端已撤出三字段: _dump 内不再写这三键
    skb_src = (SCRIPTS / "signal_kelly_backtest.py").read_text(encoding="utf-8")
    assert '"generated_at": trades_data["generated_at"]' not in skb_src, (
        "生成端不应再把 generated_at 写进分片")
    assert 'shard = {\n            "fields": fields,\n            "quadrants": {},' in skb_src, (
        "分片 shard 应只含 fields+quadrants")
    print("④ 登记点守护 OK")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))