# Delivery benefits v1

C1 uses the existing `scripts/ops_monitor.py` collector and ops ingest/admin/D1
transport. There is no new scheduler, daemon, notification channel or public API.
Claude reviews, merges, installs and enables it. The example configuration leaves
`benefits_enabled=false`; old collector configurations remain valid. Enabling
sampling without reviewed controls records local operational observations and an
unknown monitor check. It does not claim delivery success or ROI.

## Evidence and clock contract

The snapshot top level remains schema 1. Delivery checks have finite IDs
`benefit:<chain_id>:<session_date>`, category `monitor`. Their evidence is exactly
the 20 scalar fields in [benefits-v1.json](contracts/benefits-v1.json), including
`record_kind=delivery_v1`, `measurement_kind=real|synthetic|unknown`, `strength`
and `source_at`. Synthetic or unspecified measurement kinds have check status
unknown. They remain diagnostics in the original ops storage. The backend partitions
current/audit facts by measurement kind and selects only real records for real
studies, even when a local native validator verified its synthetic inputs.
Synthetic/unknown observations cannot recover a real failure. The wire omits `attempt_id` to keep exactly 20 keys; real attempts remain in
private receipts and local normalized proof. Missing/unknown measurement kind
is never eligible for a real study, including older saved records. Values contain no file paths,
URLs, private object identities, raw business records or notification text.
`batch_id` is a stable logical slot (normally `<chain_id>:<session_date>`),
`attempt_id` is a real execution identity retained only in private receipts
and the local `attempt_ids` aggregate,
and `receipt_id` identifies an immutable stage fact, retained locally.

`check.observed_at` and `evidence.evaluated_at` are this verification's UTC time.
`source_at` is the maximum immutable `producer_time.completed_at` of the fully
verified receipts, and null for partial/unknown results. Every completion must be
at or before its receipt's actual evaluation time and the present verification.
The proof covers those clocks, the result, approved control identity and source
receipt digests; changing the sample clock does not change the proof.

Backend markers: deduplicate by `proof_sha`; replacement of a verified current
state requires a newer **source** clock with matching code/config/calendar.
`evaluated_at` alone cannot establish recovery. Unknown and partial evidence
cannot revoke verified historical success or recover verified failure. An old
receipt arriving late cannot overwrite newer failure. Conflicting verified facts
need review. `strength=verified` is required for an `ok`/`warning` check; partial
known outcomes remain available in the counts but the check is unknown.

When expected inventory, policy, deadline, calendar or source completeness is
unknown, `expected`, `success`, `failure`, `unknown` are all **null**,
`inventory_complete=false`, `strength=unknown`. Null is not zero and is not
comparable. A known inventory with missing receipts has expected N, success 0,
failure 0, unknown N. No deadline/operator policy is invented. Empty approved
inventory is kept separate and cannot produce a success-rate denominator.

## Local controls and producer facts

Only these new fixed source locations are read beneath the configured canonical
`data_root` (the project root containing `data/`). Root/parent symlinks are rejected:

- `data/ops_delivery/benefits-control.json`: at most 64 KiB, strict JSON.
- `data/ops_delivery/receipts/<session_date>/<chain_id>/<receipt_id>.json`:
  immutable producer facts, at most 64 KiB each. Producer owns their helper.
- Existing `data/alerts/alert_ledger.jsonl` and
  `static-site/data/schedule_stats.json`: at most 64 KiB each, operational
  observations only (digest, bytes and observed record count); never outcomes.

The calendar is an explicitly reviewed, sourced, complete actual trading calendar
embedded in the control; weekdays are not a calendar substitute. Calendar SHA is
SHA-256 of `json.dumps(trading_days,separators=(',',':')).encode()`.
No other data files, environment files, database contents, credentials or
historical notification text are scanned by normalization. Oversized ledgers are
unknown observations, without silently reading an arbitrary tail.

`benefits-control-v1` requires `measurement_kind=real|synthetic`, safe IDs
`contract_id`, `caliber_id`, `population_id`, `schedule_id`,
`exclusion_policy_id`, a 40-hex committed `normalizer_sha`, and:

```json
{
  "policy": {
    "reviewed": true,
    "approval_sha256": "<64-hex digest of independently reviewed approval>",
    "approved_at": "<aware timestamp before the delivery deadline>"
  },
  "calendar": {
    "timezone": "Asia/Shanghai",
    "verified_complete": true,
    "source_ref": "<local authoritative calendar evidence reference>",
    "trading_days": ["2026-11-05", "2026-11-06"],
    "sha256": "<digest of these actual declared sessions>"
  },
  "sessions": [{
    "date": "2026-11-06",
    "chains": {
      "market_signal_freeze_plan": {
        "inventory_complete": true,
        "inventory_id": "reviewed-required-set-v1",
        "deadline_at": "<operator approved aware deadline>",
        "code_sha": "<40-hex release identity>",
        "config_sha": "<64-hex approved pipeline config identity>",
        "batches": ["market_signal_freeze_plan:2026-11-06"],
        "required": [
          {"stage": "signal", "object_id": "signal-validator", "inputs": ["raw-input"], "outputs": ["signal-result"]},
          {"stage": "freeze", "object_id": "freeze-validator", "inputs": ["signal-result"], "outputs": ["freeze-result"]},
          {"stage": "plan", "object_id": "plan-validator", "inputs": ["freeze-result"], "outputs": ["plan-result"], "consumer_scope": "<approved actual reader scope>"}
        ],
        "edges": [
          {"from": ["signal", "signal-validator"], "to": ["freeze", "freeze-validator"], "object_id": "signal-result"},
          {"from": ["freeze", "freeze-validator"], "to": ["plan", "plan-validator"], "object_id": "freeze-result"}
        ]
      }
    }
  }]
}
```

The strings in angle brackets are required operator evidence, not usable defaults.
The executable **synthetic only** complete control/receipt fixture is
`ops/monitoring/tests/test_benefits.py:fixture`. It invents no production policy.
Controls are attestations, not cryptographic authentication: only an authorized
local operator may write them. Keep them private; hashes do not prove their truth.
A study freezes common policy/calendar/rollout identities. Adding another
session's inventory does not invalidate unchanged earlier slots; changing that
slot's approved required set or common calendar requires a new study/review.

Required stage sets are `signal,freeze,plan`, `backtest,publish,consumer`, and
`backup,restore` for `market_signal_freeze_plan`, `backtest_publish_consume`, and
`backup_isolated_restore`, respectively. A requirement may bind stage-specific
`code_sha`/`config_sha` if actual loaded stage configurations differ from the
pipeline's aggregate identities. `inputs` and `outputs` name actual validated
object identities, not arbitrary filenames. Each later node needs a forward edge.
Every edge must match **the same strong output/input object digest**, session and
actual ordering; a common date, batch or attempt does not establish lineage.

Local stage validation requires `evidence_quality=strong`, verified actual loaded
code/config identities and nonnegative **integer** counts
`inventory_complete=1,expected,validated,failed,unknown`, with
`expected=validated+failed+unknown`. Success requires failed=unknown=0 and a
nonempty validated inventory (or explicitly approved `allow_empty=true`).
This flag is an integer because producer counts reject booleans. Intermediate
consumer witnesses can remain unknown. The final required stage must carry an
actual consumer witness `{status:"success",output_sha256,session_date,batch_id}`
matching its outputs and stable slot. The witness `consumer_scope` must equal
the last requirement's reviewed `consumer_scope`; an isolated local reader
cannot satisfy a production browser or offsite consumer contract. A generic receipt, stage exit code, HTTP 200,
or a config switch never upgrades unknown to strong. Deployment also needs the
producer's actual stage-specific validator hooks; see producer handoff for their
verified local-consumer scope. A local isolated-reader contract does not prove
remote R2 or public frontend consumption.

Success requires the entire compatible validated chain completed before the
approved deadline. A verified business failure or verified late complete chain
is failure. Missing/weak/ambiguous facts are unknown. Current mutable artifact
hashes are never re-read to retroactively establish failure or erase old success.
No notification history is promoted into a delivery receipt.

## Budgets and persistence

Default sampling examines the latest two declared sessions (not guessed dates),
up to three chains each. Fixed session/chain partitions retain old receipts while
keeping current sampling independent of lifetime directory size. A slot permits
128 entries and all selected slots permit 256 total entries; all evidence reads together permit 2 MiB, with per-read and wall
budgets. Exceeding a limit, invalid facts, unreadable data or symlinks make the
slot incomplete, with null inventory counts. It never selects an arbitrary newest
subset and calls it complete. Partition compaction, if ever needed, requires a
separate approved manifest contract; this version does not discard old facts.

The original collector total remains 20 seconds by default, upload reserve 8
seconds. Benefits run **after** existing operational checks in a bounded child
(max 2 seconds of collection time; 0.8 seconds of evidence reads). A blocked
filesystem/SQLite child is killed. Its result permits at most 24 KiB. New checks
respect 250 checks/256 KiB and cannot displace old checks or the optional transport
probe; no benefit failure can prevent the original push. `collect-only` has no
outbound requests. Unconfigured or timed-out collection emits an unknown monitor
check when capacity permits.

`output_dir/benefits.sqlite3` is private (directory 0700, file 0600), local and
persistent only if the deployment chooses a persistent output directory; the
example `/run` location is volatile across reboot. D1 carries remote observations
through the existing ops transport when enabled. Immutable rows key on
chain/session/proof, so repeated sampling and concurrent inserts do not double
count. Different fact versions remain reviewable; raw receipt detail stays local.
The operational observation table retains first/last actual sampling clocks.
SQLite write/lock failure makes the collector result unknown. No automatic
retention of raw evidence or daemon is introduced.

Explicit offline history import reads approved partitions and stores observations;
it never inserts historical times into the current ops snapshot:

```sh
python3 ops/monitoring/benefits.py import-history --data-root /canonical/project --output-dir /private/persistent/ops --session-date 2026-11-06
python3 ops/monitoring/benefits.py export --data-root /canonical/project --output-dir /private/persistent/ops --chain market_signal_freeze_plan --as-of 2026-11-07T12:00:00Z > /private/comparison-input.json
python3 ops/monitoring/compare_benefits.py /private/comparison-input.json
```

The exporter creates before/after normalized periods for one chain population.
Missing historical receipts remain unknown; only unique verified proof under the
same approved slot identity is used. Conflicting verified versions do not choose
a winner by database insertion order. All-unknown re-sampling cannot erase an
existing verified version. A later partial record with any proven failure
conflicts with an earlier complete version and makes the day not ready; it
cannot disappear behind the old success. Imports should target a single session to keep total
read budgets explicit; retry any incomplete partition after fixing its source.

The stdlib comparator preserves the previous 21 synthetic controls. It requires
10 nearest **actual** sessions strictly before and 10 after the rollout's
Asia/Shanghai date, excluding the whole rollout date, and closed deadlines through
the last day. Declare `rollout.effective_at`, `evidence_ref`, paired
`before_code_sha/after_code_sha` and
`before_config_sha256/after_config_sha256`. Missing evidence yields `not_ready`
(exit 2), malformed input yields `invalid_input` (exit 1). The input is bounded to
2 MiB; no personal temporary path is embedded. Synthetic input is refused by
default and requires `--allow-synthetic` for demonstration.

Aggregate by sum(success)/sum(eligible), never average daily percentages. Preserve
unknown outcome lower/upper logical bounds (not confidence intervals), unequal
denominators, version pairing, policy/caliber/calendar identity and confounders.
All unknown outcomes are not ready. Manual work is unavailable without complete
measured minutes and exactly matched eligible-batch scope; no inference from
execution duration or alerts. Comparisons remain descriptive, attribution is not
established, and `real_benefit_claim=false`. The 519 notification records and 275
timing records in prior observations are not a business-delivery denominator.

The export query selects only the declared 20-session population through the
SQLite index rather than loading the lifetime database. It refuses more than
320 matching proof versions or 32 MiB of selected evidence and applies a
2-second SQL progress budget; it never silently drops versions.

Offline verification:

```sh
python3 -m unittest discover -s ops/monitoring/tests -p 'test_benefits*.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_ops_monitor.py' -q
python3 -m unittest discover -s scripts/tests -p 'test_delivery_evidence_20261107.py' -q
```

The actual-hook integration invokes the existing original backtest functions via
AST in an isolated namespace with synthetic engine inputs/statistics, real atomic
writers, real run-proof publication and the real local reader validator. It then
normalizes actual immutable receipt files, including missing-consumer and wrong
consumer-scope negative controls. This tests the production hook plumbing and
local validation logic; it does not execute a production generation or establish
production R2/browser delivery or realized benefit.
