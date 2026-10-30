# -*- coding: utf-8 -*-
"""test_356_export_code_fingerprint.py — #356 export 代码指纹: 内容哈希 + 全量覆盖。

来源(真实依据): static-site/export.py 旧 `_code_fingerprint()` 只取 3 个文件的 st_mtime
  (export.py / app/queries.py / app/compute/signal_stats.py),导出实际还依赖 app/ 下其它模块与
  config/site.yaml ⇒ 改这些代码指纹不变 ⇒ 增量跳过 ⇒ 陈旧产物上线。
修复: 指纹改为 app/**/*.py + export.py 自身 + config/site.yaml 的 sha256(路径字节也进摘要),
  读失败/扫空 ⇒ 返回随机不可匹配串(走全量),绝不返回恒定值。

覆盖(对应任务书证据用例 T3/T4/T5/T6):
  [T3] 改依赖代码内容 ⇒ 指纹变(触发强制全量)
  [T4] 只 touch(mtime 变、内容不变) ⇒ 指纹不变
  [T5] 改内容 + 还原 mtime ⇒ 指纹仍变
  [T6] 覆盖范围: app/**.py 数量非空且不含 data/;config/site.yaml 与 export.py 自身在覆盖内;
       云上 ROOT/app 为目录符号链接时仍能扫描(不跟随 ⇒ 空集 = 永久误命中)
  [兜底] 文件读不到 ⇒ 不返回正常指纹(不可匹配)

补(config/indicators.yaml,reviewer F1):
  [补1] config/indicators.yaml 在覆盖内(指数宇宙/中文名/per-index 阈值 = app/ 代码的输入)
  [补2] 判别力: 改它内容 ⇒ 指纹必须变;改回 ⇒ 恢复(不靠断言常量字面量自证)
  [补3] config/ 下参与哈希的恰好 site.yaml + indicators.yaml,不含 data/DB/log
  [补4] 反向对照: 不产出 export 产物的 config(daily_brief.yaml/email.json.example)改了不许让指纹变

零生产触达: 只在 pytest tmp_path 副本里改文件;不读生产 DB、不写仓库文件、不上传 R2、零网络。
"""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORT_PY = ROOT / "static-site" / "export.py"


def _load_export(path: Path):
    spec = importlib.util.spec_from_file_location(
        "export_356_" + str(abs(hash(str(path)))), str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_tree(tmp_path: Path) -> Path:
    """搭一个最小可 import 的 ROOT: app 全量 + util_atomic + config + export.py。"""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "app", root / "app",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (root / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "util_atomic.py", root / "scripts" / "util_atomic.py")
    shutil.copytree(ROOT / "config", root / "config",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (root / "static-site").mkdir()
    shutil.copy2(EXPORT_PY, root / "static-site" / "export.py")
    return root


def test_fingerprint_format_and_deterministic():
    m = _load_export(EXPORT_PY)
    fp1 = m._code_fingerprint()
    fp2 = m._code_fingerprint()
    assert fp1 == fp2, "同内容两次指纹不一致"
    assert fp1.startswith("v2:"), f"指纹格式不对: {fp1}"
    assert len(fp1) == len("v2:") + 64, f"不是 sha256 hex: {fp1}"


def test_content_change_invalidates(tmp_path):
    root = _make_tree(tmp_path)
    m = _load_export(root / "static-site" / "export.py")
    fp1 = m._code_fingerprint()
    target = root / "app" / "compute" / "signals.py"
    with open(target, "a", encoding="utf-8") as f:
        f.write("\n# fingerprint regression test\n")
    assert m._code_fingerprint() != fp1, "改依赖代码内容后指纹未变(会增量跳过陈腐产物)"


def test_mtime_only_does_not_invalidate(tmp_path):
    root = _make_tree(tmp_path)
    m = _load_export(root / "static-site" / "export.py")
    fp1 = m._code_fingerprint()
    target = root / "app" / "compute" / "signals.py"
    st = target.stat()
    os.utime(target, (st.st_atime + 100, st.st_mtime + 100))
    assert m._code_fingerprint() == fp1, "mtime 变化不应让指纹变(内容哈希口径)"


def test_content_change_with_restored_mtime_still_invalidates(tmp_path):
    root = _make_tree(tmp_path)
    m = _load_export(root / "static-site" / "export.py")
    target = root / "app" / "compute" / "signals.py"
    st = target.stat()
    fp1 = m._code_fingerprint()
    with open(target, "a", encoding="utf-8") as f:
        f.write("\n# t5 restored mtime\n")
    os.utime(target, (st.st_atime, st.st_mtime))
    assert target.stat().st_mtime == st.st_mtime
    assert m._code_fingerprint() != fp1, "内容变 + mtime 还原后指纹必须仍变"


def test_coverage_excludes_data_and_counts_nonempty(tmp_path):
    root = _make_tree(tmp_path)
    m = _load_export(root / "static-site" / "export.py")
    fp1 = m._code_fingerprint()
    py_files = [p for p in (root / "app").rglob("*.py") if "__pycache__" not in str(p)]
    assert len(py_files) > 0, "app/ 扫不到 .py(空集 = 永久误命中)"
    # data/ 与日志不进覆盖: 改它们的 mtime/内容都不该影响指纹
    (root / "data").mkdir()
    datafile = root / "data" / "some.json"
    datafile.write_text("{}", encoding="utf-8")
    assert m._code_fingerprint() == fp1, "data/ 文件被纳入指纹了"
    datafile.write_text('{"changed": 1}', encoding="utf-8")
    assert m._code_fingerprint() == fp1, "data/ 内容进了指纹"
    # config/site.yaml 必须在覆盖内
    cfg = root / "config" / "site.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "\n# touched\n", encoding="utf-8")
    assert m._code_fingerprint() != fp1, "config/site.yaml 未纳入指纹"


def test_symlinked_app_dir_is_scanned(tmp_path):
    """云上 ROOT/app 可能是目录符号链接: os.walk 默认不跟随 ⇒ 空集。"""
    root = _make_tree(tmp_path)
    real_app = tmp_path / "real_app"
    os.rename(str(root / "app"), str(real_app))
    os.symlink(str(real_app), str(root / "app"))
    m = _load_export(root / "static-site" / "export.py")
    fp_link = m._code_fingerprint()
    assert not fp_link.startswith("v2:unreadable-"), "app 是符号链接时扫描失败(空集)"
    # 与真实目录形态的指纹一致 = 扫到了同一批文件
    direct = _make_tree(tmp_path / "direct")
    md = _load_export(direct / "static-site" / "export.py")
    assert fp_link == md._code_fingerprint()


def test_util_atomic_change_invalidates(tmp_path):
    """scripts/util_atomic.py 经 sys.path 注入被 export 依赖(:40 import)，改它必须失效"""
    root = _make_tree(tmp_path)
    m = _load_export(root / "static-site" / "export.py")
    fp1 = m._code_fingerprint()
    target = root / "scripts" / "util_atomic.py"
    with open(target, "a", encoding="utf-8") as f:
        f.write("\n# fingerprint regression test: util_atomic\n")
    assert m._code_fingerprint() != fp1, "改 scripts/util_atomic.py 后指纹未变(会增量跳过陈腐产物)"


def test_indicators_yaml_in_fingerprint_config():
    """#356 补(config/indicators.yaml): 指数宇宙/中文名/per-index 阈值都是 app/ 代码的输入,
    改它必须让指纹变,否则 index-*.json 增量跳过 => 旧名字/旧阈值/缺新品种。"""
    m = _load_export(EXPORT_PY)
    assert "config/indicators.yaml" in m._CODE_FINGERPRINT_CONFIG, \
        "config/indicators.yaml 未纳入指纹覆盖"
    assert (ROOT / "config" / "indicators.yaml").exists(), "生产仓缺 config/indicators.yaml"


def test_indicators_yaml_change_invalidates(tmp_path):
    """判别力用例:改 indicators.yaml 内容(临时副本) => 指纹必须变;改回 => 恢复原值。
    不是断言常量字面量,而是真跑两次 _code_fingerprint()。"""
    root = _make_tree(tmp_path)
    m = _load_export(root / "static-site" / "export.py")
    target = root / "config" / "indicators.yaml"
    original = target.read_text(encoding="utf-8")
    fp1 = m._code_fingerprint()
    target.write_text(original + "\n# fingerprint regression test: indicators\n", encoding="utf-8")
    fp2 = m._code_fingerprint()
    assert fp2 != fp1, "改 config/indicators.yaml 后指纹未变(index 详情会增量跳过用旧名字/旧阈值)"
    target.write_text(original, encoding="utf-8")
    assert m._code_fingerprint() == fp1, "改回原内容后指纹未恢复(内容哈希口径被破坏)"


def test_config_coverage_only_product_inputs(tmp_path):
    """覆盖范围核对: 指纹真正参与哈希的 config/ 文件 = `_CODE_FINGERPRINT_CONFIG` 里存在的那些,
    必须恰好是 site.yaml + indicators.yaml,不含 data/DB/log/凭据(凭据文件改了只会平白全量重算)。"""
    m = _load_export(EXPORT_PY)
    picked = [rel for rel in m._CODE_FINGERPRINT_CONFIG if rel.startswith("config/")]
    assert sorted(picked) == ["config/indicators.yaml", "config/site.yaml"], \
        f"config/ 下参与指纹的文件集不符: {picked}"
    for rel in picked:
        assert (ROOT / rel).exists(), f"{rel} 不存在,指纹会静默少算一个输入"
        assert not rel.endswith((".db", ".log")), f"{rel} 是数据/日志,不该进代码指纹"


def test_non_product_config_does_not_invalidate(tmp_path):
    """反向对照(§23.3 逐个判定): 不产出 export 产物的 config 改动不许让指纹变——
    daily_brief.yaml(→gen_daily_brief.py 写 daily_brief.json,不在 export 产物内)
    与 email.json.example(通知凭据模板)改了都只该触发各自链路,不该强制全量重算。"""
    root = _make_tree(tmp_path)
    m = _load_export(root / "static-site" / "export.py")
    fp1 = m._code_fingerprint()
    for rel in ("config/daily_brief.yaml", "config/email.json.example"):
        p = root / rel
        assert p.exists(), f"测试前置: 临时仓缺 {rel}"
        p.write_text(p.read_text(encoding="utf-8") + "\n# not a product input\n", encoding="utf-8")
    assert m._code_fingerprint() == fp1, "非产物输入配置进了代码指纹(会平白触发全量重算)"


def test_missing_app_dir_is_unreadable(tmp_path):
    """app/ 缺失(或符号链接断链)时扫描为空 -> 必须失效，不许哈希退化"""
    m = _load_export(EXPORT_PY)
    empty_root = tmp_path / "empty_root"
    empty_root.mkdir()
    m.ROOT = empty_root
    fp = m._code_fingerprint()
    m.ROOT = ROOT
    assert fp.startswith("v2:unreadable-"), f"app/ 扫不到时未走失效兜底: {fp}"


def test_unreadable_file_never_matches(tmp_path):
    root = _make_tree(tmp_path)
    m = _load_export(root / "static-site" / "export.py")
    fp1 = m._code_fingerprint()
    target = root / "app" / "queries.py"
    os.chmod(target, 0o000)
    try:
        still_readable = os.access(target, os.R_OK)  # root 无视文件权限
        if still_readable:
            import pytest
            pytest.skip("以 root 运行时 chmod 000 仍可读,读失败路径无法构造")
        fp2 = m._code_fingerprint()
    finally:
        os.chmod(target, 0o644)
    assert fp2 != fp1, "读失败时指纹与正常值相同 = 会误命中陈旧产物"
    assert fp2.startswith("v2:unreadable-"), f"读失败未走失效兜底: {fp2}"