#!/usr/bin/env python3
"""从固定私有证据生成允许入库的字段；不复制消息正文、群 ID 或凭证。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

AUDIT_ORIGIN = "/tmp/codex-reports/alert-recheck-20261110"
TAKEOVER_ORIGIN = "/tmp/codex-reports/alert-takeover-20261110"
PINS = {
    "final-audit.json": "c3e77494cb30a8aff69d6ed3759a1ec0e5cceae4bb7eeeefcdb604f737f1fa05",
    "audit-summary.txt": "df946a1a0f224800a31d2698d23923ae6427885982f32776593165b0b68a7c44",
    "authorization.txt": "3c2c224b1949cfaa52b74cb5d09afd81e55fc0164a4348c681de774186785a41",
    "controller-state.json": "0ab97bd0730f3e7d453887f20f3252afe538d767e036f0767d29c0b4d44b48ce",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned(path, expected):
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError(f"证据版本变化，须另建快照，不覆盖本版: {path.name}")
    return data


def select(obj, keys):
    return {k: obj[k] for k in keys if k in obj}


def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode()


def build(audit_dir, takeover_dir):
    inputs = {name: (audit_dir if name in ("final-audit.json", "audit-summary.txt")
                     else takeover_dir) / name for name in PINS}
    raw = {name: pinned(path, PINS[name]) for name, path in inputs.items()}
    audit = json.loads(raw["final-audit.json"])
    controller = json.loads(raw["controller-state.json"])
    assert len(audit["repair_matrix"]) == 21
    assert {f["id"] for f in audit["findings"]} == {
        "PREUPLOAD-DATE-01", "PREUPLOAD-SENTINEL-02", "TEST-MIRROR-03"}
    matrix_fields = ("id", "status", "root_cause", "repair_commit_or_candidate",
                     "deployment", "conclusion", "finding_id")
    finding_fields = ("id", "severity", "title", "path", "origin", "scope",
                      "source_head", "impact", "why", "fix", "recommendation",
                      "trace", "verifier", "source_trace", "sha256", "boundary")
    # 显式允许字段；不递归复制源消息、邮箱、群映射或原始事件对象。
    cov = audit["coverage"]
    coverage = {
        "cloud_sender": select(cov["cloud_sender"], (
            "all_message_records", "operational_message_records",
            "other_business_or_completion_follow_records", "operational_categories",
            "operational_email_true", "operational_feishu_true", "digest_messages",
            "digest_merged_metadata_total", "retained_entry_counts",
            "sender_failure_observations_with_exact_send_time")),
        "feishu_received": select(cov["feishu_actual_received_operational"], (
            "all_visible_messages_in_two_groups", "operational_sender_records",
            "operational_matched_visible_messages", "unmatched_sender_records",
            "operations_explicitly_app_truncated")),
        "platform_mail": select(cov["connected_gmail"], (
            "actual_platform_quota_full_MIME_emails", "distinct_quota_UTC_windows",
            "delayed_until_after_reset", "last_received_cst",
            "last_email_before_latest_optimization_deploy")),
        "local": select(cov["local"], (
            "enumerated_roots", "roots_with_sources", "files_enumerated_unique_inode",
            "files_fullread", "native_sender_ledger_messages",
            "native_operational_email_count", "local_saved_cloud_copies",
            "cloud_copies_counted_as_new_local_sends", "test_CODE_synthetic_entries",
            "test_worktree_synthetic_entries",
            "unread_disappeared_worktree_frozen_missing_archives",
            "unread_bytes_at_initial_stat", "production_business_incident_from_local_proven")),
        "counting_rules": cov["counting_rules"],
    }
    normalized = {
        "archive_version": 1,
        "kind": "sanitized_audit_and_takeover_snapshot_not_release_acceptance",
        "source_audit_sha256": PINS["final-audit.json"],
        "audit": select(audit, ("request_id", "generated_at", "verdict", "verdict_scope",
                                "code_release_verdict", "summary")),
        "window": select(audit["scope"], ("start_inclusive", "cutoff_inclusive", "timezone")),
        "versions_at_audit": audit["versions"],
        "takeover_snapshot": select(controller, (
            "authorization", "phase", "integration_branch", "source_candidate",
            "base_main", "integration_head", "conflicts", "conflicts_resolved", "safety")),
        "coverage": coverage,
        "confirmed_p2": [select(f, finding_fields) for f in audit["findings"]],
        "issue_registration": {
            "379": ["PREUPLOAD-DATE-01", "PREUPLOAD-SENTINEL-02"],
            "380": ["TEST-MIRROR-03"],
            "reserved_elsewhere": {"378": "feat/fix/merge-fastcheck-gate-20261110"},
            "boundary": "编号核验覆盖本地36分支/6种索引blob及现存worktree；不是远端未fetch分支的穷举。",
        },
        "repair_matrix": [select(row, matrix_fields) for row in audit["repair_matrix"]],
        "boundaries": [
            "审计FAIL表示尚未全部根治；不是4d候选发布FAIL，也没有新证P0/P1损坏。",
            "原审计只读；本轮实现审合部署接管有单次用户授权，默认只读外审角色不永久改变。",
            "父整合36b快照不代表3P2已合并、独立审查通过或部署；归档不等待未来自然轮。",
            "QQ未独立读取完整收件原件；Resend读取401/send-only不构成收件回执。",
            "4条飞书发送端截断；7个worktree文件在stat与读取间消失，不证明生产删除。",
            "无时间戳SMTP失败不归入本窗口；发送成功标志与实际收件分层。",
            "136历史键added=0/removed=0不等于已恢复；九键与旧五键不可直接相减判新回归。",
            "旧源身份不足，不用今天备份/映射重造T0，不调低业务风险阈值。",
        ],
    }
    sources = [{"name": name, "sha256": PINS[name], "bytes": len(raw[name]),
                "repository_content": "exact_authorization_only" if name == "authorization.txt"
                else "normalized_fields_or_hash_only"} for name in PINS]
    evidence = []
    for entry in audit["evidence_manifest"]:
        # 文件名定位，原件留私有目录；所有31份实际验hash，不把正文放进输出。
        data = pinned(audit_dir / Path(entry["path"]).name, entry["sha256"])
        assert len(data) == entry["bytes"]
        evidence.append({"name": Path(entry["path"]).name,
                         "sha256": entry["sha256"], "bytes": entry["bytes"]})
    # 身份由hash决定；挪到私有快照重放时仍记录原始来源位置，输出字节保持一致。
    manifest = {"algorithm": "SHA-256", "audit_source_directory": AUDIT_ORIGIN,
                "takeover_source_directory": TAKEOVER_ORIGIN, "inputs": sources,
                "evidence": evidence, "evidence_count": len(evidence),
                "contents": "仅文件名、字节数和hash；私有原件/原始正文不入库"}
    outputs = {"audit-normalized.json": encoded(normalized),
               "evidence-manifest.json": encoded(manifest),
               "authorization.txt": raw["authorization.txt"]}
    for name, data in outputs.items():
        if re.search(rb"\b(?:oc|ou|on|cli)_[A-Za-z0-9_-]+", data):
            raise ValueError(f"输出含私密标识: {name}")
        if re.search(rb"(?:Bearer\s+\S+|sk-[A-Za-z0-9_-]{12,})", data):
            raise ValueError(f"输出疑似凭证: {name}")
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", type=Path,
                        default=Path(AUDIT_ORIGIN))
    parser.add_argument("--takeover-dir", type=Path,
                        default=Path(TAKEOVER_ORIGIN) / "docs-source-snapshot")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).absolute().parent)
    parser.add_argument("--check", action="store_true", help="只读重新生成对账，不改归档")
    args = parser.parse_args()
    outputs = build(args.audit_dir, args.takeover_dir)
    for name, data in outputs.items():
        path = args.output_dir / name
        if args.check:
            assert path.read_bytes() == data, f"归档漂移: {name}"
        else:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
    print(f"{'CHECK' if args.check else 'WRITE'}: 3 artifacts; 21 states; 3 P2; 31 evidence hashes")


if __name__ == "__main__":
    main()
