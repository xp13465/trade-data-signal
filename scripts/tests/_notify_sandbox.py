"""通知测试共用隔离；成功返回值仅模拟渠道结果，不是真实送达回执。"""
from contextlib import contextmanager
import os
from pathlib import Path

import pytest

from _zero_outbound import ZeroOutboundTrap


# 对齐 test_245_l2_budget_digest_20261010.py::_iso，补配置读取面。
# notify 在导入时派生这些路径；只改 REPO/ALERTS_DIR 不会让它们重新计算。
NOTIFY_PATHS = {
    "REPO": ".",
    "EMAIL_CONFIG": "config/email.json",
    "TELEGRAM_CONFIG": "config/telegram.json",
    "FEISHU_CONFIG": "config/feishu.json",
    "ALERTS_DIR": "data/alerts",
    "ALERTS_FILE": "data/alerts/latest.md",
    "DEDUP_FILE": "data/notify_dedup.json",
    "WARNING_BUFFER_FILE": "data/alerts/warning_buffer.jsonl",
    "INFO_LOG_FILE": "data/alerts/info_log.jsonl",
    "WARNING_FLUSH_LOCK_FILE": "data/alerts/warning_buffer.flushlock",
    "WARNING_DEDUP_STATE_FILE": "data/alerts/warning_dedup_state.json",
    "WARNING_DEDUP_LOCK_FILE": "data/alerts/warning_dedup.lock",
    "ALERT_DIGEST_FILE": "data/alerts/alert_digest.jsonl",
    "ALERT_DIGEST_LOCK_FILE": "data/alerts/alert_digest.flushlock",
    "ALERT_DIGEST_STATE_FILE": "data/alerts/alert_digest_state.json",
}


@contextmanager
def isolated_notify(notify, root, monkeypatch):
    """同时隔离固定路径和 env 动态派生的账本/状态，退出时恢复全局量。

    monkeypatch 与测试共用同一个撤销栈，先撤销测试后加的 patch，再撤销沙箱。
    避免权限用例修改 ALERT_DIGEST_FILE 后，fixture 收尾次序把沙箱路径泄漏出去。
    """
    root = Path(root)
    names = (*NOTIFY_PATHS, "_RESULT_FILE", "_send_email", "send_telegram",
             "send_feishu", "_load_feishu_credentials")
    before = {name: getattr(notify, name) for name in names}
    old_repo_env = os.environ.get("REPO")
    calls = []

    def fake(kind):
        def send(*_args, **_kwargs):
            calls.append(kind)
            return True  # 只模拟成功；所有镜像/账本/回执都必须留在本沙箱。
        return send

    try:
        for name, relative in NOTIFY_PATHS.items():
            monkeypatch.setattr(notify, name, root / relative)
        notify.ALERTS_DIR.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("REPO", str(root))
        for name in ("ALERT_DIGEST_DISABLE", "ALERT_BUDGET_DISABLE", "NOTIFY_SOURCE"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(notify, "_RESULT_FILE", None)
        # 不读真实 .env，也不让外部 FEISHU_APP_* 改变摘要路由要求。
        monkeypatch.setattr(notify, "_load_feishu_credentials", lambda: ("", ""))
        for name, kind in (("_send_email", "email"), ("send_telegram", "telegram"),
                           ("send_feishu", "feishu")):
            monkeypatch.setattr(notify, name, fake(kind))
        assert all(value.is_relative_to(root) for value in vars(notify).values()
                   if isinstance(value, Path)), "有导入时派生路径未被沙箱覆盖"
        assert notify._ledger_path().is_relative_to(root)
        assert notify._state_path(notify.ALERT_DOMAIN_STATE_FILE_NAME).is_relative_to(root)
        assert notify._state_path(notify.ALERT_DIGEST_SEEN_FILE_NAME).is_relative_to(root)
        with ZeroOutboundTrap() as trap:
            try:
                yield {"root": root, "digest": notify.ALERT_DIGEST_FILE,
                       "lock": notify.ALERT_DIGEST_LOCK_FILE, "calls": calls, "trap": trap}
            finally:
                assert trap.hits == [], f"零外发防线被触达: {trap.hits}"
    finally:
        monkeypatch.undo()
        assert all(getattr(notify, name) is value for name, value in before.items()), (
            "通知测试结束后模块全局量未恢复")
        assert os.environ.get("REPO") == old_repo_env


@pytest.fixture
def notify_sandbox(tmp_path, monkeypatch):
    import notify

    with isolated_notify(notify, tmp_path / "sandbox", monkeypatch) as sandbox:
        yield sandbox


def run_workers(*workers, timeout=20):
    """有界运行 fork 用例；失败或超时也回收本次创建的子进程。"""
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=timeout)
        assert all(worker.exitcode == 0 for worker in workers), (
            f"子进程退出码: {[worker.exitcode for worker in workers]}")
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
                if worker.is_alive():
                    worker.kill()
                    worker.join(timeout=5)
