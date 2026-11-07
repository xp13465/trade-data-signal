-- OPS-R1: retain the exact observation selected by the existing per-check clock.
-- Status and evidence must not be reconstructed from a newer-but-regressed envelope.
ALTER TABLE ops_check_state ADD COLUMN observation_json TEXT;

UPDATE ops_check_state SET observation_json=(
  SELECT c.value FROM ops_runs r, json_each(r.snapshot_json,'$.checks') c
  WHERE r.snapshot_id=ops_check_state.snapshot_id
    AND json_extract(c.value,'$.id')=ops_check_state.check_id LIMIT 1
);

CREATE TRIGGER ops_check_observation_insert AFTER INSERT ON ops_check_state BEGIN
  UPDATE ops_check_state SET observation_json=(
    SELECT c.value FROM ops_runs r, json_each(r.snapshot_json,'$.checks') c
    WHERE r.snapshot_id=NEW.snapshot_id AND json_extract(c.value,'$.id')=NEW.check_id LIMIT 1
  ) WHERE collector_id=NEW.collector_id AND check_id=NEW.check_id;
END;
CREATE TRIGGER ops_check_observation_update AFTER UPDATE ON ops_check_state
WHEN NEW.snapshot_id<>OLD.snapshot_id BEGIN
  UPDATE ops_check_state SET observation_json=(
    SELECT c.value FROM ops_runs r, json_each(r.snapshot_json,'$.checks') c
    WHERE r.snapshot_id=NEW.snapshot_id AND json_extract(c.value,'$.id')=NEW.check_id LIMIT 1
  ) WHERE collector_id=NEW.collector_id AND check_id=NEW.check_id;
END;
