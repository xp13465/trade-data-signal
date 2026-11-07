-- Private normalized delivery evidence, separate from the 30-day ops summary.
CREATE TABLE ops_benefit_audit (
  receipt_key TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL,
  chain_id TEXT NOT NULL,
  session_date TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  measurement_kind TEXT NOT NULL DEFAULT 'unknown' CHECK(measurement_kind IN ('real','synthetic','unknown')),
  evaluated_ms INTEGER NOT NULL,
  received_ms INTEGER NOT NULL,
  source TEXT NOT NULL,
  snapshot_id TEXT NOT NULL,
  record_json TEXT NOT NULL
);
CREATE INDEX ops_benefit_audit_batch ON ops_benefit_audit(chain_id,session_date,batch_id,measurement_kind,evaluated_ms DESC);
CREATE TABLE ops_benefit_current (
  chain_id TEXT NOT NULL,
  session_date TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  measurement_kind TEXT NOT NULL DEFAULT 'unknown' CHECK(measurement_kind IN ('real','synthetic','unknown')),
  receipt_key TEXT NOT NULL REFERENCES ops_benefit_audit(receipt_key),
  evaluated_ms INTEGER NOT NULL,
  strength TEXT NOT NULL,
  code_sha TEXT,
  config_sha TEXT,
  calendar_sha TEXT,
  record_json TEXT NOT NULL,
  conflict_json TEXT,
  PRIMARY KEY(chain_id,session_date,batch_id,measurement_kind)
);
CREATE TABLE ops_benefit_studies (
  study_id TEXT PRIMARY KEY,
  revision INTEGER NOT NULL,
  identity_hash TEXT NOT NULL,
  study_json TEXT NOT NULL,
  created_ms INTEGER NOT NULL
);
CREATE TABLE ops_benefit_imports (
  import_id TEXT PRIMARY KEY,
  study_id TEXT NOT NULL REFERENCES ops_benefit_studies(study_id),
  content_hash TEXT NOT NULL,
  received_ms INTEGER NOT NULL,
  import_json TEXT NOT NULL
);
-- No change to original ops triggers, public storage, or notification owner.
