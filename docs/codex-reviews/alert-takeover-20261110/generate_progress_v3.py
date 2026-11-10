#!/usr/bin/env python3
"""固定私有证据的v3文档归档；只读生成，不访问云、数据库或通知器。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

BASE = "ec307b55954ad674c2dbeb1b0d1b4ca02fa0a216"
RUNS = {42756830475: "quality", 42756830390: "ops",
        42756830500: "worker", 42756830665: "pages"}


def pick(obj, names):
    return {n: obj[n] for n in names if n in obj}


def build(folder, snapshot):
    manifest = json.loads((folder / "progress-v3-evidence.json").read_text())
    src = {}
    for item in manifest["inputs"]:
        data = (snapshot / item["name"]).read_bytes()
        assert len(data) == item["bytes"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"], item["name"]
        src[item["name"]] = json.loads(data)
    parent = src["parent-statement-v3.json"]
    readiness = src["final-code-readiness.json"]
    quarantine = src["local-mirror-quarantine.json"]
    archive = src["private-evidence-archive.json"]
    recovery = src["recovery-execution.json"]
    post = src["recovery-postcheck.json"]
    r4 = src["worker375-diagnostic-result-r4.json"]
    worker_parent = src["parent-statement-v3-worker-r4.json"]
    user_error = src["worker375-user-evidence-addendum.json"]
    decision375 = src["worker375-504-controller-decision.json"]
    retry375 = src["worker375-504-resilience-plan.json"]
    numbering = src["overfit-public-verifier-numbering-correction-addendum.json"]
    verifier_impl = src["overfit-public-verifier-implementation.json"]
    assert decision375["status"] == "DISPOSITION_COMPLETE_OBSERVE_PROVIDER"
    assert retry375["retry_boundary"]["native_version_post_max_total_attempts"] == 3
    assert numbering["correction"]["parent_index"] is None
    assert numbering["correction"]["implementation_status_authority"] == "docs/pending-features-index.md #382"
    assert "parent-routing-374-382.json" not in src
    assert verifier_impl["head"] == "e2e9095ef4bd8148f664c5ff1ec3e0e8a88aec2e"
    persistence = src["takeover-evidence-persistence-v1.json"]
    packets = src["prior-handoff-status.private.json"]
    assert persistence["files"] == 56 and persistence["bytes"] == 2176784
    assert persistence["status"] == "VERIFIED_BYTE_IDENTICAL"
    assert len(packets) == 13 and all(p["ack"] is None and p["integrity"] == "verified"
                                    and p["status"] == "context-emitted" for p in packets)
    runs = []
    for run in src["main-ec307-runs-latest.private.json"]["workflow_runs"]:
        if run["id"] in RUNS:
            assert run["head_sha"] == BASE and run["status"] == "completed"
            assert run["conclusion"] == "success"
            runs.append({"role": RUNS[run["id"]], **pick(run, (
                "id", "name", "head_sha", "status", "conclusion", "html_url", "run_attempt"))})
    assert {r["id"] for r in runs} == set(RUNS)
    assert readiness["fixed_head"] == BASE and readiness["code_review_verdict"] == "PASS"
    assert readiness["unresolved_severity_counts"] == {"P0": 0, "P1": 0, "P2": 0}
    linux = parent["final_linux"]
    assert linux["tests"] == linux["passed"] + linux["skipped"] == 4243
    assert linux["passed"] == 4236 and linux["failures"] == linux["errors"] == 0
    assert quarantine["removed_entries"] == 45
    qpost = quarantine["post_verification"]
    assert qpost["files_verified"] == 6
    assert qpost["code_severe_before_after"]["severe"]["count"] == 50
    assert all(r["restore_exact_before_in_tmp"] and r["head_and_protected_bytes_equal"]
               for r in qpost["results"])
    verified = recovery["final_verification"]
    assert recovery["verdict"] == post["verdict"] == "PASS"
    assert len(recovery["modes"]) == 4
    assert all(m["exit_code"] == m["ssh_exit_code"] == 0 and m["verified"]
               and m["commit_confirmed"] for m in recovery["modes"])
    assert len(verified["NAV_exact_cell_diffs"]) == 12
    assert len(verified["index_exact_three_added_rows"]) == 3
    assert verified["other_fund_control_rows_compared"] == 0
    assert verified["non_target_fund_evidence_boundary"]["positive_row_sample_status"] == "UNKNOWN_NOT_SAMPLED"
    assert post["smoke_results"]["local_receipt_hashes"] == "24/24 PASS"
    notice = next(n["message"] for n in r4["notices"]
                  if n.get("title") == "worker375 fixed-job read-only diagnostic")
    diagnostic = json.loads(notice[notice.index("{"):])
    assert diagnostic["error_type"] == "MALFORMED_API_RESPONSE"
    assert diagnostic["wrangler_log_path_present"] is True
    assert all(diagnostic[k] == "NOT_RECORDED" for k in (
        "http_status", "api_host", "api_method", "api_path", "html_title"))
    assert r4["run_id"] == 42761618507 and all(j["conclusion"] == "success" for j in r4["jobs"])
    assert archive["status"] == "VERIFIED" and archive["file_count"] == 481
    rt = src["runtime-verification-result.json"]
    runtime = {
        "artifact_readonly_acceptance": rt["artifact_readonly_acceptance"],
        "canonical_http": pick(rt["canonical_http"], (
            "result", "source_generated_at", "observed_cst", "risk_score", "risk_level")),
        "formal_selfverify": {**pick(rt["formal_selfverify"], (
            "function", "one_hop", "request_lines", "client", "explicit_headers",
            "custom_user_agent", "curl_fallback", "urls", "error_contract")),
            "file": "scripts/overfit_monitor.py"},
        "client_comparison": pick(rt["runtime_evidence"], (
            "deployed_venv_equivalent_request", "existing_curl_same_paths",
            "complete_delivery_worker_invoked", "actual_worker_readonly_invocation",
            "cause_of_client_difference", "first_probe_rc1")),
        "publisher_mechanism": rt["publisher_mechanism"],
        "production_actions": rt["production_actions"],
        "new_registration": 382,
        "new_P2": "OVERFIT-SELFVERIFY-CLIENT403-P2",
        "status_at_ec307": "OPEN_RUNTIME_FINDING",
        "task_numbering": numbering["correction"],
        "numbering_addendum": "numbering-correction-addendum.json",
        "repair_scope": "独立兼容缺陷#382；同URL/有界预算/TLS/hash不降低，实施状态只见pending-index #382。374仅D1原历史与观察；撤销错误母子路由，不猜其它既有overfit号",
        "author_evidence_at_capture": {
            "head": verifier_impl["head"], "pushed": verifier_impl["pushed"],
            "targeted": pick(verifier_impl["tests"]["final_green"], ("rc", "raw_last_line", "log")),
            "old_red": verifier_impl["tests"]["old_red"],
            "boundary": "仅作者固定提交和定向/旧版负控，不替代独立审查、精确head LinuxOps或发布/云只读验收"},
        "followup_chain_evidence": "overfit-382-closeout-slot.json",
        "publisher_write_GO": False,
        "boundary": "curl四地址200/hash只证明对象已上线；真实默认urllib四地址403，不能称正式投递最终PASS；不猜403厂商根因",
    }
    body = {
        "version": 3,
        "status": "EC307_BASELINE_AND_RECOVERY_FACTS_WITH_SEPARATE_382_FOLLOWUP",
        "source_base": BASE,
        "scope": "单次授权的告警接管归档；v1/v2按各自时点保留，不改长期角色规则",
        "code_delivery": {
            "standard_main_merge_and_cloud_CODE": parent["main_and_cloud"],
            "provenance": "父提供标准main-merge/云CODE同SHA事实；本归档未执行部署",
            "code_readiness": pick(readiness, (
                "fixed_head", "generated_at", "code_review_verdict", "unresolved_severity_counts",
                "resolved_this_round_P2", "summary")),
            "readiness_original_gate": readiness["main_merge_gate"],
            "readiness_time_boundary": "readiness生成时仍待CI；后续同SHA Linux与main四run另行补证，不改写旧报告",
            "final_linux": {**linux, "head": BASE, "provenance": "父提供最终ec Linux原样计数；与7e47旧统计分开"},
            "main_runs": sorted(runs, key=lambda r: r["id"]),
            "merge_execution": parent["merge_execution"],
            "selfcheck_boundary": "480s超时WARN，不能写selfcheck PASS；父后续实核四run成功是另一项检查",
            "new_runtime_P2_after_readiness": "正式runtime后验新P2见#382；旧readiness生成时的P0/P1/P2清单不外推当前机制全绿",
        },
        "local_mirror_quarantine": {
            "status": quarantine["status"], "removed_synthetic_entries": 45,
            "before_backups_verified": 6, "severe_retained": qpost["code_severe_before_after"]["severe"],
            "restore_controls": [{"id": r["id"], **pick(r, (
                "backup_sha256_verified", "backup_mode", "live_after_sha256_verified",
                "head_and_protected_bytes_equal", "same_live_lock_inode",
                "restore_exact_before_in_tmp", "restore_current_drift_refused_in_tmp"))} for r in qpost["results"]],
            "original_audit_raw_mirrors_retained": qpost["original_audit_raw_mirrors_retained"],
            "live_restore_performed": not qpost["no_live_restore_performed"],
            "boundary": "本机镜像假条目隔离；未改发送账本/邮件/飞书记录，原始正文不复制入库",
        },
        "authorized_recovery": {
            "status": recovery["status"], "verdict_scope": recovery["verdict_scope"],
            "modes": [pick(m, ("mode", "status", "actual_start_cst", "actual_end_cst",
                       "timeout_seconds", "exit_code", "ssh_exit_code", "verified",
                       "commit_confirmed", "row_operations", "current_child_PID", "current_session"))
                      for m in recovery["modes"]],
            "final_verification": pick(verified, (
                "final_snapshot_at_cst", "trusted_head", "script_sha256", "NAV_exact_cell_diffs",
                "NAV_window_keyset_unchanged", "NAV_original_nonempty_fields_verified_unchanged",
                "NAV_prev_unit_and_fund_name_unchanged", "index_old15_unchanged",
                "index_exact_three_added_rows", "freeze_and_progress_before_actual_first_write_equal_final",
                "freeze_and_progress_since_initial_1258_preflight_equal_final", "protected_hashes",
                "etf_two_full_rows_unchanged", "target_table_triggers", "no_unplanned_key_writes_proof",
                "lock_file_content_and_inodes_unchanged", "non_target_fund_evidence_boundary")),
            "row_operations": recovery["impact_surface"]["business_row_operations"],
            "ETF_writes": recovery["impact_surface"]["ETF_writes"],
            "postcheck": {"verdict": post["verdict"], "summary": post["summary"],
                          "receipt_hashes": post["smoke_results"]["local_receipt_hashes"],
                          "non_target_fund_assessment": post["non_target_fund_assessment"],
                          "no_new_network_DB_lock_or_write": post["no_new_network_DB_lock_or_write"]},
            "current_state": pick(recovery["current_state"], (
                "mode", "current_child_PID", "current_session", "all_receipts_verified")),
            "boundary": "DB精确恢复与本地窄postcheck通过，不等于public展示/自然export交付链通过；非目标基金正样本UNKNOWN_NOT_SAMPLED",
        },
        "worker375": {
            "diagnostic_head": r4["head"], "diagnostic_run": r4["run_id"],
            "diagnostic_jobs": r4["jobs"], "independent_review": worker_parent["independent_review"],
            "recorded_log_facts": diagnostic,
            "later_user_context": {
                "recorded_facts": user_error["recorded_facts"],
                "interpretation": user_error["interpretation"],
                "not_proven": user_error["not_proven"],
                "prior_diagnostic_preserved": user_error["prior_diagnostic_preserved"],
            },
            "product_main_changed_by_diagnostic": r4["product_main_changed"],
            "current_product_worker_run": 42756830500,
            "historical_symptom": "Worker版本创建POST的Cloudflare API网关504已由用户新增完整上下文证实",
            "historical_internal_root_cause": "OPEN_OBSERVE_NOT_PROVEN",
            "controller_disposition": pick(decision375, (
                "status", "decision", "reason", "root_cause_boundary", "planned_code_changes",
                "current_deployment_success_run", "future_acceptance")),
            "native_retry_scope": pick(retry375["retry_boundary"], (
                "native_version_post_max_total_attempts", "unit", "deployment_post", "valid_terminal_failure")),
            "policy": "DISPOSITION_COMPLETE_OBSERVE_PROVIDER：本轮不叠外层retry、不改权限secret；原生版本POST最多总3尝试，耗尽后真实504FAIL保留。r4未知字段不回写，不称永久根治，不再等待375实施/审查",
        },
        "private_archive": pick(archive, (
            "archive", "archive_sha256", "archive_bytes", "source_bytes", "file_count",
            "manifest", "manifest_sha256", "verification", "permissions", "private_report_copy",
            "source_tmp_deleted", "takeover_running_reports_archived", "uploaded")),
        "fixed_takeover_persistence": {**pick(persistence, (
            "status", "destination", "files", "bytes", "mode", "immutable_inputs_only",
            "source_tmp_deleted", "final_inflight_followup_not_included")),
            "receipt_files_included_as_reported": 24,
            "boundary": "与旧481件tar分开；当前verifier后续及最终master不在56件内，父完成后再补"},
        "prior_handoff_metadata_only": {
            "packets": 13, "integrity_verified": 13, "ack_null": 13,
            "status": "context-emitted", "Claude_received_or_reviewed_claim": False,
            "boundary": "完整性/上下文发出不等于收到或复核；最终master统一覆盖本轮相关历史，不伪造ACK，不复制13packet原文"},
        "runtime": runtime,
        "retained_OPEN": parent["residual_open"] + [
            "两ETF159501/159513 Nov9累积净值现有源仅到Nov6，零写，待发布",
            "七个无可信T0的历史交易键不重造；精确DB恢复不代关public自然链",
            "#375旧症状网关504已知，Cloudflare内部根因/版本是否已创建未知；当前自动Worker绿与历史归因分层",
        ],
        "boundaries": ["仅归档给定证据，未新增云/SQL/网络取证或重新跑源码全量",
                       "v1/v2历史原件保留；没有把原审计FAIL倒改成全部根治",
                       "MAIN_MERGE_SKIP_PYTEST=1是父显式以同SHA完整Linux替代本地重复全量，其余门禁启用",
                       "R2独立cache锁已因并发先后反证否决，最终保留global屏障；长等待实际持有者仍未证实"],
    }
    data = (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode()
    assert not re.search(rb"\b(?:oc|ou|on|cli)_[A-Za-z0-9_-]+|Bearer\s+\S+|sk-[A-Za-z0-9_-]{12,}", data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=Path(
        "/tmp/codex-reports/alert-takeover-20261110/docs-source-snapshot/progress-v3-prepared"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    folder = Path(__file__).absolute().parent
    data = build(folder, args.snapshot)
    output = folder / "progress-v3.json"
    if args.check:
        assert output.read_bytes() == data, "v3归档漂移"
    else:
        tmp = output.with_suffix(".json.tmp")
        tmp.write_bytes(data)
        tmp.replace(output)
    print("PASS: v3 pinned inputs, same-SHA run boundaries, recovery controls and privacy allowlist")


if __name__ == "__main__":
    main()
