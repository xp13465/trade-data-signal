-- Dedicated OPS_DB only. D1 batch/SQLite triggers keep state/event/outbox atomic.
CREATE TABLE ops_runs (
  snapshot_id TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL,
  collector_id TEXT NOT NULL,
  collected_ms INTEGER NOT NULL,
  received_ms INTEGER NOT NULL,
  duration_ms INTEGER NOT NULL,
  counts_json TEXT NOT NULL,
  snapshot_json TEXT
);
CREATE INDEX ops_runs_time ON ops_runs(collected_ms DESC, snapshot_id DESC);
CREATE INDEX ops_runs_retention ON ops_runs(received_ms);
CREATE TABLE ops_head (id INTEGER PRIMARY KEY CHECK(id=1), snapshot_id TEXT NOT NULL, collected_ms INTEGER NOT NULL);
CREATE TABLE ops_check_state (
  collector_id TEXT NOT NULL,
  check_id TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ok','warning','critical','unknown')),
  observed_ms INTEGER NOT NULL,
  collected_ms INTEGER NOT NULL,
  snapshot_id TEXT NOT NULL,
  updated_ms INTEGER NOT NULL,
  problem_open INTEGER NOT NULL,
  summary TEXT NOT NULL,
  PRIMARY KEY(collector_id,check_id)
);
CREATE TABLE ops_watchdog (id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL, changed_ms INTEGER NOT NULL);
CREATE TABLE ops_events (
  event_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  check_id TEXT NOT NULL,
  previous_status TEXT,
  status TEXT NOT NULL,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  created_ms INTEGER NOT NULL
);
CREATE INDEX ops_events_time ON ops_events(created_ms DESC,event_id DESC);
CREATE TABLE ops_outbox (
  event_id TEXT PRIMARY KEY REFERENCES ops_events(event_id),
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_ms INTEGER NOT NULL,
  lease_until_ms INTEGER NOT NULL DEFAULT 0,
  lease_token TEXT,
  last_attempt_ms INTEGER,
  delivered_ms INTEGER,
  last_error TEXT,
  created_ms INTEGER NOT NULL
);
CREATE INDEX ops_outbox_due ON ops_outbox(status,next_attempt_ms,lease_until_ms);
CREATE TABLE ops_incident_overrides (
  incident_id TEXT PRIMARY KEY,
  revision INTEGER NOT NULL,
  override_json TEXT NOT NULL,
  updated_ms INTEGER NOT NULL,
  actor TEXT NOT NULL
);
CREATE TABLE ops_incident_revisions (
  incident_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  override_json TEXT NOT NULL,
  updated_ms INTEGER NOT NULL,
  actor TEXT NOT NULL,
  PRIMARY KEY(incident_id,revision)
);
CREATE INDEX ops_revisions_time ON ops_incident_revisions(updated_ms DESC);

CREATE TRIGGER ops_override_insert AFTER INSERT ON ops_incident_overrides BEGIN
  INSERT INTO ops_incident_revisions VALUES(NEW.incident_id,NEW.revision,NEW.override_json,NEW.updated_ms,NEW.actor);
END;
CREATE TRIGGER ops_override_update AFTER UPDATE ON ops_incident_overrides BEGIN
  INSERT INTO ops_incident_revisions VALUES(NEW.incident_id,NEW.revision,NEW.override_json,NEW.updated_ms,NEW.actor);
END;

CREATE TRIGGER ops_event_outbox AFTER INSERT ON ops_events WHEN NEW.kind IN ('alert','recovery') BEGIN
  INSERT INTO ops_outbox(event_id,next_attempt_ms,created_ms) VALUES(NEW.event_id,NEW.created_ms,NEW.created_ms);
END;
CREATE TRIGGER ops_check_initial AFTER INSERT ON ops_check_state WHEN NEW.status IN ('warning','critical') BEGIN
  INSERT INTO ops_events VALUES(lower(hex(randomblob(16))),NEW.collector_id,NEW.check_id,NULL,NEW.status,'alert',NEW.summary,NEW.updated_ms);
END;
CREATE TRIGGER ops_check_transition AFTER UPDATE ON ops_check_state WHEN NEW.status<>OLD.status BEGIN
  INSERT INTO ops_events VALUES(lower(hex(randomblob(16))),NEW.collector_id,NEW.check_id,OLD.status,NEW.status,
    CASE WHEN NEW.status='ok' AND OLD.problem_open=1 THEN 'recovery'
         WHEN NEW.status IN ('warning','critical') AND OLD.problem_open=0 THEN 'alert'
         WHEN NEW.status IN ('warning','critical') THEN 'continuing' ELSE 'transition' END,
    NEW.summary,NEW.updated_ms);
END;
CREATE TRIGGER ops_watchdog_initial AFTER INSERT ON ops_watchdog WHEN NEW.status='stale' BEGIN
  INSERT INTO ops_events VALUES(lower(hex(randomblob(16))),'watchdog','collector',NULL,'stale','alert','Collector snapshot overdue; data freshness unknown',NEW.changed_ms);
END;
CREATE TRIGGER ops_watchdog_transition AFTER UPDATE ON ops_watchdog WHEN NEW.status<>OLD.status BEGIN
  INSERT INTO ops_events VALUES(lower(hex(randomblob(16))),'watchdog','collector',OLD.status,NEW.status,
    CASE WHEN NEW.status='stale' THEN 'alert' WHEN NEW.status='fresh' AND OLD.status='stale' THEN 'recovery' ELSE 'transition' END,
    CASE WHEN NEW.status='stale' THEN 'Collector snapshot overdue; data freshness unknown' ELSE 'Collector freshness changed; not incident closure' END,
    NEW.changed_ms);
END;

-- Only a strictly newer global head may advance current checks or collector status.
-- The per-check clock is independent: a fresh envelope cannot regress a check's observation.
CREATE TRIGGER ops_run_insert AFTER INSERT ON ops_runs BEGIN
  INSERT INTO ops_check_state(collector_id,check_id,name,status,observed_ms,collected_ms,snapshot_id,updated_ms,problem_open,summary)
    SELECT NEW.collector_id,json_extract(c.value,'$.id'),json_extract(c.value,'$.name'),json_extract(c.value,'$.status'),
      json_extract(c.value,'$._observed_ms'),NEW.collected_ms,NEW.snapshot_id,NEW.received_ms,
      CASE WHEN json_extract(c.value,'$.status') IN ('warning','critical') THEN 1 ELSE 0 END,json_extract(c.value,'$.summary')
    FROM json_each(NEW.snapshot_json,'$.checks') c
    WHERE NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
      (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)))
    ON CONFLICT(collector_id,check_id) DO UPDATE SET
      name=excluded.name,status=excluded.status,observed_ms=excluded.observed_ms,collected_ms=excluded.collected_ms,
      snapshot_id=excluded.snapshot_id,updated_ms=excluded.updated_ms,summary=excluded.summary,
      problem_open=CASE WHEN excluded.status='ok' THEN 0 WHEN excluded.status IN ('warning','critical') THEN 1 ELSE ops_check_state.problem_open END
    WHERE excluded.observed_ms>ops_check_state.observed_ms OR
      (excluded.observed_ms=ops_check_state.observed_ms AND excluded.collected_ms>ops_check_state.collected_ms);
  UPDATE ops_check_state SET status='unknown',summary='Missing from latest snapshot; coverage unknown; not a recovery',
    collected_ms=NEW.collected_ms,updated_ms=NEW.received_ms
    WHERE collector_id=NEW.collector_id AND check_id NOT IN
      (SELECT json_extract(value,'$.id') FROM json_each(NEW.snapshot_json,'$.checks'))
    AND NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
      (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)));
  INSERT INTO ops_watchdog(id,status,changed_ms)
    SELECT 1,'fresh',NEW.received_ms WHERE NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
      (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)))
    ON CONFLICT(id) DO UPDATE SET status='fresh',changed_ms=excluded.changed_ms WHERE ops_watchdog.status<>'fresh';
  INSERT INTO ops_head VALUES(1,NEW.snapshot_id,NEW.collected_ms)
    ON CONFLICT(id) DO UPDATE SET snapshot_id=excluded.snapshot_id,collected_ms=excluded.collected_ms
    WHERE excluded.collected_ms>ops_head.collected_ms OR (excluded.collected_ms=ops_head.collected_ms AND excluded.snapshot_id>ops_head.snapshot_id);
END;
