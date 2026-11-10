#!/usr/bin/env python3
"""固定进展证据的允许字段归档；不运行业务、测试套件、网络或通知器。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

PARENT = "52b0ed5f58cccc899ba8bd52fb20ae52798994fa"
ISOLATION = "ace115157617eceb0d1abd20c41cdeab4fb9b503"
PREUPLOAD = "25dccda35abea3ec96a39355abc35231d3534cdf"


def select(obj, keys):
    return {k: obj[k] for k in keys if k in obj}


def build(folder, snapshot):
    manifest = json.loads((folder / "progress-v2-evidence.json").read_text())
    sources = {}
    for item in manifest["inputs"]:
        data = (snapshot / item["name"]).read_bytes()
        assert len(data) == item["bytes"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"], item["name"]
        sources[item["name"]] = json.loads(data)
    isolation = sources["test-isolation-implementation.json"]
    preupload = sources["preupload-test-execution.json"]
    review = sources["integration-review.json"]
    focused = sources["integration-focused-tests.json"]
    recovery = sources["recovery-plan.json"]
    purge = sources["purge-failure-result-proof.json"]
    assert isolation["commit"] == ISOLATION
    assert isolation["tests"]["targeted"]["exact_last_line"] == "22 passed in 0.39s"
    assert isolation["tests"]["full_suite"]["returncode"] == 124
    assert preupload["targeted"]["last_lines"][-1] == "119 passed in 4.70s"
    assert review["checks"]["identity"]["head"] == "36b8a7e58d93dd9930ff020623d7cd849131df83"
    assert all(x["return_value"] is None and x["raised"] is False for x in purge["cases"])
    mutations = {k: select(v, ("exit", "last_line"))
                 for k, v in sources["test-isolation-mutations.json"].items()}
    assert len(mutations) == 5 and all(v["exit"] == 1 for v in mutations.values())
    full = preupload["full"]
    assert full["exit_code"] == 1
    assert any("FileNotFoundError" in s for s in full["last_lines"])
    recovery_items = []
    for item in recovery["recovery_items"]:
        # 源报告包含远端命令与原始源文件定位；这里只取业务键、日期、结果和界限。
        safe = select(item, ("target", "status", "expected_unit_nav", "expected",
                             "trusted_value", "source_boundary", "blocked_behavior"))
        for key in ("official_lsjz_observation", "native_observation"):
            if key in item:
                safe[key] = [select(row, ("fund_code", "code", "latest_date",
                                         "Nov9_present", "sha256")) for row in item[key]]
        recovery_items.append(safe)
    body = {
        "version": 2, "captured_at": manifest["captured_at"],
        "kind": "progress_only_not_final_release_acceptance",
        "prior_docs_commit": "727e35b65ece5c1d202a866edbe804fcce83cea3",
        "parent_integration_head": PARENT,
        "parent_contains": ["4d5c32a7d80c710ef086a1940f7b9beae7f62446",
                            "41c567e6aabbfec13af0d310bcc08df59194fdbf", ISOLATION, PREUPLOAD],
        "test_isolation": {
            "commit": ISOLATION, "registration": 380,
            "targeted": select(isolation["tests"]["targeted"], ("returncode", "exact_last_line")),
            "mutations": mutations,
            "author_full_suite": select(isolation["tests"]["full_suite"], (
                "returncode", "timeout_seconds", "completed", "log_sha256",
                "exact_last_output_line", "pytest_summary", "failure_markers_observed")),
            "gate": "未通过全量门禁；不能称全绿或最终三P2独立审查PASS",
        },
        "preupload": {
            "commit": PREUPLOAD, "registration": 379,
            "targeted": select(preupload["targeted"], ("exit_code", "elapsed_seconds", "last_lines")),
            "user_handoff_status": "派单时作者full进行中",
            "later_observed_author_full": {
                "exit_code": full["exit_code"], "elapsed_seconds": full["elapsed_seconds"],
                "pytest_complete_summary": None,
                "observed_tail": "FileNotFoundError: pytest会话临时仓库路径不存在",
                "boundary": "本轮核证时执行报告已更新；不推断谁删除路径，不据此归因业务代码，也不称全量通过",
            },
        },
        "prior_integration_review": {
            "reviewed_head": review["checks"]["identity"]["head"],
            "verdict": review["verdict"], "scope": review["verdict_scope"],
            "targeted_returncode": focused["returncode"],
            "targeted_exact_last_line": focused["stdout_tail"][-1],
            "boundary": "仅原36b整合+74局部测试；不覆盖52b新三P2最终独立审查、全量、真实CI或生产验收",
        },
        "r2_result_contract": {
            "registration": 381, "id": "R2-PURGE-RESULT", "severity": "P2",
            "status": "OPEN_IMPLEMENTATION_IN_PROGRESS_NOT_DEPLOYED_ACCEPTANCE",
            "source_head": PARENT,
            "anchors": ["scripts/upload_r2.py:2682-2813 purge_cache",
                        "scripts/upload_r2.py:3405-3424 cmd_purge_low_freq",
                        "scripts/r2_upload_async.sh:399-418"],
            "confirmed_cases": [select(row, ("case", "return_value", "raised")) for row in purge["cases"]],
            "observed": "缺secret/全部HTTP503均返回None不抛；CLI忽略结果，async末尾固定exit0。函数故障注入与CLI/async静态路径分层留证。",
            "implementation_owner": "Boyle同任务转实施",
            "expected": "显式完整/空清单成功与缺凭证/失败批失败结果；CLI/async保留失败清单、继续后续有界补传且最终非零",
            "cache_lock": "仅候选；父要求先证明invalidate-before-publish排序安全，未证前不列独立cache锁为必修，不提前拆锁",
            "trace": {"diff_range": PARENT + ":scripts/upload_r2.py:2682-2813,3405-3424; scripts/r2_upload_async.sh:399-418",
                      "linkage": "不满足", "origin": "pre-existing",
                      "user_request": "R2又确证purge缺secret/503仍None且CLI/async成功的结果契约缺陷"},
            "verifier": {
                "command": "固定源码purge_cache AST，HTTP/notify/time全替代：missing_secret及all_batches_http503；证据purge-failure-result-proof.json，另静态追CLI与async收尾",
                "expected": "两失败输入显式失败，不能None后CLI/async成功；失败清单仍可追踪",
                "observed": "两例return_value=null/raised=false；52b源码CLI不检查返回值，async固定exit0；本归档未重跑外部请求或业务脚本",
            },
        },
        "recovery": {"items": recovery_items, "production_write_or_restore_in_this_archive": False,
                     "boundary": "Rawls证明源就绪与恢复方案；016989/三指数生产恢复未验收；两ETF现有可信源只到Nov6，不造数，不外推全世界未公布"},
        "worker_375": {
            "status": "OPEN_ORIGINAL_ERROR_UNAVAILABLE",
            "existing_git_credential_available": sources["worker375-existing-credential-probe.json"]["credential_available"],
            "chrome_bridge": "父本次派单确认桥连通失败，非本归档执行",
            "boundary": "Git凭据不可用与Chrome桥失败只是取证受限；仍无原始错误，不猜原部署失败因凭证",
        },
        "closure_gate": "先等父提供最终固定head独立审查/全量/真实CI/部署与逐键恢复证据，再追加终版；本次进展不得销账。",
    }
    raw = (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode()
    assert not re.search(rb"\b(?:oc|ou|on|cli)_[A-Za-z0-9_-]+", raw)
    assert not re.search(rb"Bearer\s+\S+|sk-[A-Za-z0-9_-]{12,}", raw)
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path,
                        default=Path("/tmp/codex-reports/alert-takeover-20261110/docs-source-snapshot/progress-v2"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    folder = Path(__file__).absolute().parent
    data = build(folder, args.snapshot)
    path = folder / "progress-v2.json"
    if args.check:
        assert path.read_bytes() == data, "进展归档漂移"
    else:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    print("PASS: 12 pinned inputs; progress only; no final CI/deploy/restore claim")


if __name__ == "__main__":
    main()
