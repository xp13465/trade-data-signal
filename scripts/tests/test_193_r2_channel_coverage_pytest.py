# -*- coding: utf-8 -*-
"""#201(2026-10-06): 把 #193 的 R2 通道覆盖机检并入 CI 闸门 ⑧(`python3 -m pytest -q scripts/tests/`)。

为什么需要本文件
  #193 的机检 `scripts/check_r2_channel_coverage.py` 与其自验 `scripts/test_193_r2_channel_coverage.py`
  都落在 `scripts/` 根, 不在 CI 收集路径 `scripts/tests/` ⇒ 现状**无任何自动强制点**(只能人工跑)。
  本文件是**薄包装**: import 原自验模块并调用其 `main()`, **不重复实现任何断言**(与
  `test_repo_paths_ratchet_pytest.py` 同一挂载手法, 同层)。
  用 `test_193_r2_channel_coverage_pytest` 命名, 避免与 scripts/ 根的原脚本模块名撞名。

依赖面判定 = 「纯仓库内输入」⇒ 挂 Job1(FAIL 阻断)而非 Job2(continue-on-error)
  - 输入全部是仓内源码/常量: `scripts/upload_r2.py`(常量 + 待验函数) /
    `scripts/check_r2_channel_coverage.py`(纯 AST 静态分析) + [E] 段的 git 历史回归对照
    (Job1 checkout 带 `fetch-depth: 0`, 满足)。
  - **无生产数据产物**(static-site/data/*.json)/ **无 R2** / **无网络** / **无 DB** ——
    原脚本自建 tempfile 临时树(static-site/data + 独立链台账)作输入, 自带三道打桩
    (`s3_head` / `_upload_glob` / `notify`)把全部外发面封死(见原脚本 docstring §18 L48)。
  - ⚠️ 唯一非仓内项: `upload_r2` 顶层 `load_env()` 找不到 .env 会 `sys.exit`(upload_r2.py:249-251),
    其后 `os.environ["R2_BUCKET"]` 等硬取(270-275)。CI(ubuntu runner)无 .env(`.gitignore:91` 忽略)
    ⇒ 直接 import 会崩。故本包装在 import 前铺一个**临时 .env 垫片**(`GIT_REPO` 指向 tempdir),
    只满足「文件存在 + 键齐」校验; 垫片里全是 dummy 值, 且原脚本已把**全部真实外发路径**打桩
    (下节), 垫片不引入任何真实触达。

零外发自证(§18 L48「先证打桩生效再跑」)
  原脚本 `main()` **开头**(早于任何 cmd_verify_r2 / 上传路径)即装三道防线:
   ① `sys.modules['notify']` 换成 Fake, 且真实 `notify.send` 挂陷阱函数(触达即 AssertionError);
   ② `_upload_glob` 打桩(任何路径都不会真 PUT); ③ `ur.ROOT` 重定向到临时树。
  收尾断言 `not trap and not put_calls` 硬判「真实 notify.send / 真实 _upload_glob 全程零触达」。
  本包装自身零网络、零 subprocess 写、零 DB。

会话卫生(为什么有 finally 还原块)
  原脚本是「进程退出即回收」的独立脚本设计: `main()` 结尾 `sys.exit()` 收尾, 且**不还原**
  `sys.modules['notify']`(Fake)与真实 `notify.send`(陷阱)。在 pytest 长驻会话里若不复原,
  会毒化同一会话内其余 notify 用例(test_196 / test_notify_r4_dedup / test_alertchain)。
  故 finally 显式回滚 `sys.modules['notify']` / `notify.send` / 垫片 env。

跑法: python3 -m pytest -q scripts/tests/test_193_r2_channel_coverage_pytest.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).absolute().parent.parent  # scripts/tests -> scripts
_ENV_KEYS = ("GIT_REPO", "R2_BUCKET", "R2_S3_ENDPOINT", "R2_S3_ACCESS_KEY_ID", "R2_S3_SECRET_ACCESS_KEY")
# 垫片内容: 仅满足 upload_r2 顶层 load_env() 的「文件存在」与 `os.environ[...]` 硬取的「键齐」,
# 值全 dummy; 原脚本的三道打桩已封死一切真实外发, 垫片不产生任何真实触达。
_SHIM_DOTENV = (
    "R2_BUCKET=ci-shim-test\n"
    "R2_S3_ENDPOINT=https://invalid.example\n"
    "R2_S3_ACCESS_KEY_ID=ci-shim\n"
    "R2_S3_SECRET_ACCESS_KEY=ci-shim\n"
)
# 原脚本本地实测 40 条断言(含 [E] 段 git 回归对照 5 条); 若 [E] 的 git rev 不可用会走 [skip]
# 少 2 条 ⇒ 下限取 30, 防「0 断言静默通过」(§18 L49 假样本养绿)又不因 git 环境差异误杀。
_MIN_ASSERTIONS = 30


def test_r2_channel_coverage_gate():
    """#193 机检 + 自验全量在 CI 上必须 ALL_PASS(任一 FAIL ⇒ 本用例 FAIL, 阻断 merge)。"""
    shim = tempfile.mkdtemp(prefix="test201env-")
    (Path(shim) / ".env").write_text(_SHIM_DOTENV, encoding="utf-8")
    saved_env = {k: os.environ.get(k) for k in _ENV_KEYS}
    saved_notify = sys.modules.get("notify")
    saved_send = getattr(saved_notify, "send", None) if saved_notify is not None else None
    os.environ["GIT_REPO"] = shim

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    try:
        import test_193_r2_channel_coverage as t193  # 薄包装: 复用原自验, 不重复实现
        rc = None
        try:
            t193.main()
        except SystemExit as e:  # 原脚本以 sys.exit(0/1) 收尾(进程式设计), pytest 内需接住
            rc = e.code
        assert rc == 0, f"#193 自验脚本非零退出(rc={rc}); 明细见上方 stdout"
        assert t193.FAIL == 0, f"#193 自验 FAIL={t193.FAIL}(明细见上方 stdout)"
        assert t193.PASS >= _MIN_ASSERTIONS, (
            f"#193 自验仅 {t193.PASS} 条断言(下限 {_MIN_ASSERTIONS}), 疑似收集/执行异常"
        )
    finally:
        # 会话卫生: 回滚原脚本为「进程退出」设计而遗留的全局副作用(见模块 docstring)。
        if saved_notify is None:
            sys.modules.pop("notify", None)  # 原为未 import: 清掉 Fake, 下次 import 得真模块
        else:
            sys.modules["notify"] = saved_notify
            if saved_send is not None:
                saved_notify.send = saved_send  # 还原被挂陷阱的真实 send
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(shim, ignore_errors=True)