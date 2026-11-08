"""Pure configuration/baseline tests. Real temporary IO; no business imports."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

MONITORING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MONITORING))
import configure as config  # noqa: E402
import build_baseline as baseline  # noqa: E402

DB_ID = "11111111-2222-4333-8444-555555555555"
OTHER_ID = "66666666-7777-4888-8999-aaaaaaaaaaaa"


@pytest.fixture
def private_dir():
    # Candidate policy is /tmp specifically, including when pytest's default
    # tmp_path on macOS is under /var/folders.
    with tempfile.TemporaryDirectory(prefix="ops-config-test-", dir=Path("/tmp").resolve()) as name:
        yield Path(name)


def original():
    return {"name": "existing-worker", "main": "worker/headers.js", "compatibility_date": "2026-01-01",
            "vars": {"FLAG": "keep", "nested": {"binding": "OPS_DB"}},
            "routes": [{"pattern": "example.invalid/*", "zone_name": "example.invalid"}],
            "kv_namespaces": [{"binding": "SUBSCRIBE_KV", "id": "unchanged", "remote": True}],
            "r2_buckets": [{"binding": "R2_BUCKET", "bucket_name": "existing"}],
            "d1_databases": [{"binding": "FUND_SCORE_DB", "database_id": OTHER_ID}],
            "triggers": {"crons": ["0 * * * *", "0 * * * *"], "events": [{"type": "artifact.completed"}]},
            "env": {"preview": {"kv_namespaces": [{"binding": "SUBSCRIBE_KV", "id": "preview"}]}}}


def test_jsonc_preserves_strings_and_nested_trailing_commas():
    text = r'''// heading
    {"url":"https://example.invalid/a//b/*text*/", /* real comment */
     "quote":"escaped \" // still a string", "commas":"x,} y,]",
     "nested":{"items":[1,{"value":"😀",},],},}
    '''
    parsed = config.loads_jsonc(text)
    assert parsed == {"url": "https://example.invalid/a//b/*text*/",
                      "quote": 'escaped " // still a string', "commas": "x,} y,]",
                      "nested": {"items": [1, {"value": "😀"}]}}


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"nested":{"a":1,"\\u0061":2}}',
                                 '[,]', '{,}', '{"a":,}', '[1,,]', '{"a":1,,}',
                                 '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}', '{a:1}', "{'a':1}",
                                 '{"a":1} /* unterminated', '{"a":"unterminated}'])
def test_strict_jsonc_rejects_invalid_or_duplicate_input(text):
    with pytest.raises(config.ConfigurationError):
        config.loads_jsonc(text)


def test_candidate_preserves_existing_values_and_deduplicates_cron():
    source = original()
    before = copy.deepcopy(source)
    candidate, changes = config.make_candidate(source, DB_ID)
    assert source == before
    for key in source:
        if key not in ("d1_databases", "triggers", "main"):
            assert candidate[key] == source[key]
    assert candidate["main"] == str(config.ROOT / source["main"])
    assert all(candidate["d1_databases"][0][key] == value for key, value in source["d1_databases"][0].items())
    assert candidate["d1_databases"][0]["migrations_dir"] == str(config.ROOT / "migrations")
    assert candidate["triggers"] == {"crons": ["0 * * * *", config.OPS_CRON],
                                     "events": source["triggers"]["events"]}
    assert candidate["d1_databases"][1] == {"binding": "OPS_DB", "database_name": "trade-ops-monitoring",
                                            "database_id": DB_ID, "migrations_dir": str(config.ROOT / config.MIGRATIONS_DIR)}
    assert config.make_candidate(candidate, DB_ID)[0] == candidate
    assert changes


def test_relocated_candidate_paths_include_schema_assets_default_sql_and_env(private_dir):
    source_dir = private_dir / "source"
    absolute_sql = private_dir / "absolute-sql"
    source = original()
    source.update({"$schema": "./node_modules/wrangler/config-schema.json",
                   "assets": {"binding": "ASSETS", "directory": "./static-site", "run_worker_first": ["/api/*"]}})
    source["d1_databases"].append({"binding": "EXPLICIT_SQL", "database_id": "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff",
                                    "migrations_dir": str(absolute_sql)})
    source["env"]["preview"].update({"main": "preview/index.js", "assets": {"directory": "preview/static"},
                                     "d1_databases": [{"binding": "PREVIEW_DB", "database_name": "preview"}]})
    source["vars"]["CUSTOM_PATH"] = "leave-this-relative-value"
    before = copy.deepcopy(source)
    candidate, changes = config.make_candidate(source, DB_ID, source_dir=source_dir)
    assert source == before
    assert candidate["main"] == str(source_dir / "worker/headers.js")
    assert candidate["$schema"] == str(source_dir / "node_modules/wrangler/config-schema.json")
    assert candidate["assets"] == {**source["assets"], "directory": str(source_dir / "static-site")}
    assert candidate["d1_databases"][0]["migrations_dir"] == str(source_dir / "migrations")
    assert candidate["d1_databases"][1]["migrations_dir"] == str(absolute_sql)
    assert candidate["d1_databases"][2]["migrations_dir"] == str(source_dir / config.MIGRATIONS_DIR)
    preview = candidate["env"]["preview"]
    assert preview["main"] == str(source_dir / "preview/index.js")
    assert preview["assets"]["directory"] == str(source_dir / "preview/static")
    assert preview["d1_databases"][0]["migrations_dir"] == str(source_dir / "migrations")
    assert candidate["vars"] == source["vars"] and candidate["routes"] == source["routes"]
    assert config.make_candidate(candidate, DB_ID, source_dir=source_dir)[0] == candidate
    assert any("root.env.preview.main" in note for note in changes)


@pytest.mark.parametrize("setting", [
    {"tsconfig": "./tsconfig.json"}, {"base_dir": "./src"}, {"build": {"cwd": "./build"}},
    {"build": {"watch_dir": ["./src", "./public"]}}, {"site": {"bucket": "./public"}},
    {"wasm_modules": {"WASM": "./module.wasm"}}, {"alias": {"dep": "./replacement.js"}},
    {"pages_build_output_dir": "./dist"}, {"extra_path": "./unknown"},
])
@pytest.mark.parametrize("named_env", [False, True])
def test_unaudited_filesystem_settings_fail_closed(setting, named_env):
    source = original()
    (source["env"]["preview"] if named_env else source).update(setting)
    with pytest.raises(config.ConfigurationError, match="unsupported relocated filesystem"):
        config.make_candidate(source, DB_ID)


def test_unaudited_d1_pattern_fails_closed():
    source = original()
    source["d1_databases"][0]["migrations_pattern"] = "migrations/**/*.sql"
    with pytest.raises(config.ConfigurationError, match="migrations_pattern"):
        config.make_candidate(source, DB_ID)


def test_external_candidate_actual_wrangler_dry_run_and_local_sql_discovery(private_dir, capsys):
    """Real pinned Wrangler, fake OPS UUID, isolated home/state, no deployment.

    Both commands keep the candidate under /tmp rather than copying it back to
    the repository. The local-only D1 list proves Wrangler discovers the SQL,
    which deploy --dry-run itself does not inspect.
    """
    root = MONITORING.parents[1]
    source = root / "wrangler.jsonc"
    raw = source.read_bytes()
    candidate_path = private_dir / "candidate.jsonc"
    # The root wrangler.jsonc now persists a real OPS_DB binding (deployed by
    # ops/monitoring/configure.py main). configure.py refuses to silently
    # replace a differing OPS_DB database_id (safety guard), so read the real
    # value from the source instead of using the synthetic DB_ID placeholder.
    source_config = config.loads_jsonc(source.read_text("utf-8-sig"))
    ops_db = next((x for x in source_config.get("d1_databases", [])
                   if x.get("binding") == "OPS_DB"), None)
    assert ops_db is not None, "root wrangler.jsonc must persist OPS_DB binding"
    assert config.main(["--source", str(source), "--database-id", ops_db["database_id"],
                        "--output", str(candidate_path)]) == 0
    metadata = json.loads(capsys.readouterr().out)
    candidate = config.loads_jsonc(candidate_path.read_text())
    assert metadata["source_sha256"] == config.digest(raw)
    assert candidate["main"] == str(root / "worker/headers.js")
    assert candidate["assets"]["directory"] == str(root / "static-site")
    ops = next(db for db in candidate["d1_databases"] if db["binding"] == "OPS_DB")
    assert ops["migrations_dir"] == str(root / config.MIGRATIONS_DIR)
    for db in candidate["d1_databases"]:
        assert Path(db["migrations_dir"]).is_absolute()
    spec = importlib.util.spec_from_file_location("candidate_deployment_preflight", MONITORING / "verify_deployment.py")
    deployment = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deployment)
    checks = deployment.worker_config_checks(candidate, config_path=candidate_path, source_root=root)
    assert all(row["status"] == "ok" for row in checks), checks

    home = private_dir / "home"
    home.mkdir()
    guard = private_dir / "offline.cjs"
    guard.write_text(r'''
const fs = require('node:fs'), net = require('node:net'), dns = require('node:dns');
const path = require('node:path');
let external = 0, protectedReads = 0, positive = 0, denied = [];
const deny = (kind, host) => { external++; denied.push({kind,host}); throw new Error('OFFLINE_EXTERNAL_FORBIDDEN'); };
const local = host => ['localhost','127.0.0.1','::1','[::1]'].includes(String(host));
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function(...args) {
  const first = args[0];
  const host = first && typeof first === 'object' ? first.host || 'localhost' : typeof args[1] === 'string' ? args[1] : 'localhost';
  if (!local(host)) return deny('socket',String(host));
  return connect.apply(this, args);
};
const lookup = dns.lookup;
dns.lookup = function(host, ...args) { if (!local(host)) return deny('dns',String(host)); return lookup.call(this, host, ...args); };
const originalFetch = globalThis.fetch;
globalThis.fetch = function(input, ...args) {
  const host = new URL(typeof input === 'string' || input instanceof URL ? input : input.url).hostname;
  if (!local(host)) return deny('fetch',host);
  return originalFetch.call(this,input,...args);
};
for (const action of [() => net.connect({host:'blocked.invalid',port:443}), () => fetch('https://blocked.invalid')]) {
  try { action(); throw new Error('missing positive trap'); }
  catch (error) { if (error.message !== 'OFFLINE_EXTERNAL_FORBIDDEN') throw error; positive++; }
}
external = 0; denied = [];
const promises = require('node:fs/promises');
for (const [owner,key] of [[fs,'readFileSync'],[fs,'readFile'],[promises,'readFile']]) {
  const original = owner[key];
  owner[key] = function(file, ...args) {
    const name = typeof file === 'string' ? file : file instanceof URL ? file.pathname : '';
    const resolved = name ? path.resolve(name) : '';
    if (resolved && !resolved.startsWith(process.env.OPS_TEST_PRIVATE + path.sep) &&
        (/^(?:\.env(?:\.|$)|\.dev\.vars(?:\.|$))/.test(path.basename(name)) || /[\/]\.wrangler[\/]config[\/]/.test(resolved))) {
      protectedReads++; throw new Error('OFFLINE_CREDENTIAL_READ_FORBIDDEN');
    }
    return original.call(this, file, ...args);
  };
}
try { fs.readFileSync('/forbidden/.env'); throw new Error('missing credential trap'); }
catch (error) { if (error.message !== 'OFFLINE_CREDENTIAL_READ_FORBIDDEN') throw error; positive++; }
protectedReads = 0;
require('node:module').syncBuiltinESMExports();
process.on('exit', () => fs.writeFileSync(path.join(process.env.OPS_TEST_PRIVATE, 'audit-'+process.pid+'.json'), JSON.stringify({external,denied,protectedReads,positive})));
''')
    environment = {"PATH": os.defpath, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                   "TMPDIR": str(private_dir), "LANG": "en_US.UTF-8", "CI": "true",
                   "WRANGLER_SEND_METRICS": "false", "CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV": "false",
                   "NODE_OPTIONS": "--require=" + str(guard), "OPS_TEST_PRIVATE": str(private_dir)}
    node = shutil.which("node")
    assert node is not None, "Node is required for the real candidate integration test"
    wrangler = root / "node_modules/wrangler/bin/wrangler.js"
    assert wrangler.is_file(), "Install the pinned npm dependencies before integration tests"

    def run(arguments):
        result = subprocess.run([node, str(wrangler), *arguments], cwd=private_dir, env=environment,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert source.read_bytes() == raw
        return result.stdout + result.stderr

    bundle = private_dir / "bundle"
    output = run(["deploy", "--dry-run", "--config", str(candidate_path), "--outdir", str(bundle)])
    assert (bundle / "headers.js").is_file(), output
    assert "dry-run" in output.lower()
    listing = run(["d1", "migrations", "list", "OPS_DB", "--local", "--config", str(candidate_path),
                   "--persist-to", str(private_dir / "d1-state")])
    migrations = list((root / config.MIGRATIONS_DIR).glob("*.sql"))
    assert migrations, "Real OPS migration files must be present for discovery verification"
    for migration in migrations:
        assert migration.name in listing, "Wrangler did not discover " + migration.name
    audits = [json.loads(p.read_text()) for p in private_dir.glob("audit-*.json")]
    # Wrangler may make optional discovery/telemetry attempts even in dry-run.
    # All non-loopback egress remains synchronously denied; record rather than
    # hide those denied attempts. Local Miniflare RPC is explicitly allowed.
    assert audits and all(a["protectedReads"] == 0 and a["positive"] == 3
                          and a["external"] == len(a["denied"]) for a in audits), audits
    assert candidate_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("mutate", [
    lambda d: d["kv_namespaces"].append({"binding": "SUBSCRIBE_KV", "id": "duplicate"}),
    lambda d: d["d1_databases"].extend([{"binding": "OPS_DB"}, {"binding": "OPS_DB"}]),
    lambda d: d["kv_namespaces"].append({"binding": "OPS_DB", "id": "wrong-type"}),
    lambda d: d["vars"].update(OPS_DB="wrong-type"),
    lambda d: d.update(durable_objects={"bindings": [{"name": "OPS_DB", "class_name": "Other"}]}),
])
def test_duplicate_or_wrong_type_binding_rejected(mutate):
    source = original()
    mutate(source)
    with pytest.raises(config.ConfigurationError):
        config.make_candidate(source, DB_ID)


def test_dedicated_database_not_alias_or_silent_replacement():
    with pytest.raises(config.ConfigurationError, match="dedicated"):
        config.make_candidate(original(), OTHER_ID)
    candidate, _ = config.make_candidate(original(), DB_ID)
    with pytest.raises(config.ConfigurationError, match="differs"):
        config.make_candidate(candidate, "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    candidate["d1_databases"][1]["database_name"] = "keep-existing-name"
    candidate["d1_databases"][1]["remote"] = False
    assert config.make_candidate(candidate, DB_ID)[0] == candidate


@pytest.mark.parametrize("bad", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_database_id_rejects_placeholder(bad):
    with pytest.raises(config.ConfigurationError):
        config.make_candidate(original(), bad)


def test_cli_complete_private_candidate_and_read_only_digest_check(private_dir, capsys):
    source, target = private_dir / "source.jsonc", private_dir / "candidate.jsonc"
    raw = ("/* preserve semantics */\n" + json.dumps(original())).encode()
    source.write_bytes(raw)
    before = source.stat().st_mtime_ns
    expected = config.digest(raw)
    args = ["--source", str(source), "--database-id", DB_ID, "--output", str(target), "--check-current", expected]
    assert config.main(args) == 0
    metadata = json.loads(capsys.readouterr().out)
    assert metadata["source_sha256"] == expected and metadata["candidate_sha256"] == config.digest(target.read_bytes())
    assert source.read_bytes() == raw and source.stat().st_mtime_ns == before
    assert target.stat().st_mode & 0o777 == 0o600
    assert config.loads_jsonc(target.read_text())["d1_databases"][-1]["binding"] == "OPS_DB"
    old = target.read_bytes()
    assert config.main(["--source", str(source), "--check-current", expected]) == 0
    assert target.read_bytes() == old
    capsys.readouterr()
    assert config.main(["--source", str(source), "--check-current", "f" * 64]) == 2
    assert target.read_bytes() == old


def test_source_drift_stops_before_atomic_replace(private_dir, monkeypatch):
    source, target = private_dir / "source.jsonc", private_dir / "candidate.jsonc"
    source.write_text(json.dumps(original()))
    target.write_bytes(b"previous candidate")
    verify = config.verify_source

    def changed(path, expected):
        source.write_text('{"changed":true}')
        verify(path, expected)

    monkeypatch.setattr(config, "verify_source", changed)
    assert config.main(["--source", str(source), "--database-id", DB_ID, "--output", str(target)]) == 2
    assert target.read_bytes() == b"previous candidate"
    assert sorted(p.name for p in private_dir.iterdir()) == ["candidate.jsonc", "source.jsonc"]


def test_digest_check_uses_the_initial_snapshot(private_dir, monkeypatch):
    source = private_dir / "source.jsonc"
    source.write_bytes(b'{}')
    reads = iter([b'{}', b'{"new":true}'])
    monkeypatch.setattr(config, "read_regular", lambda p: next(reads))
    # A later reread matching the requested digest must not validate different
    # bytes captured by the first read or report their digest as a match.
    assert config.main(["--source", str(source), "--check-current", config.digest(b'{"new":true}')]) == 2


def test_existing_candidate_is_replaced_with_private_mode(private_dir):
    target = private_dir / "candidate.jsonc"
    target.write_bytes(b"old")
    target.chmod(0o644)
    config.atomic_write(target, b"new")
    assert target.read_bytes() == b"new" and target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["fchmod", "fsync", "replace"])
def test_atomic_failure_preserves_previous_and_cleans_temporary(private_dir, monkeypatch, failure):
    target = private_dir / "candidate.jsonc"
    target.write_bytes(b"previous")
    monkeypatch.setattr(config.os, failure, lambda *a, **k: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OSError):
        config.atomic_write(target, b"new")
    assert target.read_bytes() == b"previous"
    assert [p.name for p in private_dir.iterdir()] == ["candidate.jsonc"]


def test_output_cannot_overwrite_source_or_leave_tmp(private_dir):
    source = private_dir / "source.jsonc"
    source.write_text('{}')
    for path in [Path("relative.jsonc"), MONITORING / "production.jsonc", source]:
        with pytest.raises(config.ConfigurationError):
            config.private_tmp_output(path, forbidden=[source])
    link = private_dir / "link.jsonc"
    link.symlink_to(source)
    with pytest.raises(config.ConfigurationError):
        config.private_tmp_output(link)


def test_baseline_sanitization_preserves_structure_without_private_payload():
    raw = {"id": "data:test", "kind": "data", "evidence": [{"location": "/home/private/code/trade/scripts/check.py:12",
            "note": "proof /tmp/private/report.json; host /Users/person/db.sqlite"}],
           "EnvironmentVariables": {"KEY": "do-not-export"}, "env": {"ANY": "do-not-export"},
           "vars": {"ARBITRARY": "do-not-export"}, "ProgramArguments": ["do-not-export"],
           "api_key": "do-not-export", "headers": "Bearer do-not-export",
           "home": "~/private/whatever", "exec": "/usr/bin/private", "url": "https://internal.invalid/private",
           "command": "some-cli --token do-not-export", "sample_env": "SOME_VALUE=do-not-export"}
    safe = baseline.sanitize(raw)
    encoded = json.dumps(safe)
    assert safe["id"] == raw["id"] and len(safe["evidence"]) == 1
    assert safe["evidence"][0]["location"] == "scripts/check.py:12"
    assert not any(s in encoded for s in ["/home/", "/tmp/", "/Users/", "~/", "/usr/", "do-not-export", "internal.invalid"])


def inventory_fixture(directory):
    for i, name in enumerate(baseline.SOURCE_NAMES):
        record = {"id": "data:shared" if i < 2 else f"data:item-{i}", "name": f"source-{i}",
                  "kind": "data", "health": "unknown", "evidence_status": "code_confirmed",
                  "evidence": [{"location": f"/tmp/secret-{i}", "kind": "test", "note": "safe"} for _ in range(8)]}
        (directory / name).write_text(json.dumps({"schema_version": 1, "baseline_code_ref": "a" * 40,
                                                "observed_at": f"2026-11-0{i+1}T00:00:00+00:00", "records": [record]}))


def test_baseline_full_observations_reproducible_and_non_mutating(private_dir):
    inventory_fixture(private_dir)
    before = {p.name: p.read_bytes() for p in private_dir.iterdir()}
    module, data, verify = baseline.build_module(private_dir)
    again, _, _ = baseline.build_module(private_dir)
    assert module == again
    assert data["source_record_count"] == 9 and data["unique_record_count"] == 8
    shared = next(r for r in data["records"] if r["id"] == "data:shared")
    assert len(shared["observations"]) == 2
    assert "record" not in shared["observations"][0]
    assert len(shared["observations"][1]["record"]["evidence"]) == 8
    restored = 0
    for merged in data["records"]:
        for i, observation in enumerate(merged["observations"]):
            original = json.loads(before[observation["source_file"]])["records"][0]
            assert baseline.reconstruct_record(merged, i) == baseline.sanitize(original)
            restored += 1
    assert restored == 9 and data["observation_contract"]["version"] == 1
    assert b"/tmp/secret" not in module and b"export default BASELINE" in module
    verify()
    assert {p.name: p.read_bytes() for p in private_dir.iterdir()} == before


def test_baseline_reserved_observations_field_remains_reconstructable(private_dir):
    inventory_fixture(private_dir)
    path = private_dir / baseline.SOURCE_NAMES[0]
    source = json.loads(path.read_text())
    source["records"][0]["observations"] = [{"source_fact": "retained"}]
    path.write_text(json.dumps(source))
    _, data, _ = baseline.build_module(private_dir)
    merged = next(r for r in data["records"] if r["id"] == "data:shared")
    assert "record" not in merged["observations"][0]
    assert baseline.reconstruct_record(merged, 0) == baseline.sanitize(source["records"][0])


@pytest.mark.parametrize("change", ["add", "remove", "modify"])
def test_baseline_source_set_and_digest_guard(private_dir, change):
    inventory_fixture(private_dir)
    _, _, verify = baseline.build_module(private_dir)
    if change == "add":
        (private_dir / "extra.json").write_text('{}')
    elif change == "remove":
        (private_dir / baseline.SOURCE_NAMES[0]).unlink()
    else:
        (private_dir / baseline.SOURCE_NAMES[0]).write_text('{}')
    with pytest.raises(config.ConfigurationError, match="changed"):
        verify()
