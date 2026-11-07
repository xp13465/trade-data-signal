"""Deterministic private server baseline; no business imports or remote access."""
from __future__ import annotations

import argparse
import copy
import datetime
import json
from pathlib import Path
import re
import sys

if __package__:
    from .configure import ConfigurationError, atomic_write, digest, loads_jsonc, private_tmp_output, read_regular
else:
    from configure import ConfigurationError, atomic_write, digest, loads_jsonc, private_tmp_output, read_regular

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs/ops/architecture/inventory"
MODULE = ROOT / "worker/ops_baseline.js"
SOURCE_NAMES = tuple(sorted(("data_assets.json", "data_edges.json", "foundation.json", "incidents.json",
                            "monitors.json", "repository_tasks.json", "runtime_cloud.json",
                            "runtime_local.json", "surfaces.json")))
DERIVED_NAMES = {"schema.json", "catalog.json", "reconciliation.json"}
PRIVATE_PATH = re.compile(r"(?:~/(?:[^\s\"'<>;,\]\[{}|]*)|/(?:private/)?tmp(?:/[^\s\"'<>;,\]\[{}|]*)?|/(?:Users|home|root|var|etc|opt|mnt|srv|private|usr|bin|sbin|Library|Applications|Volumes|run|dev|proc|sys)(?:/[^\s\"'<>;,\]\[{}|]*)?|[A-Za-z]:[\\/][^\s\"'<>;,]*)")
SENSITIVE_KEY = re.compile(r"(?i)(?:token|secret|password|credential|authorization|cookie|environment|environ|arguments|(?:^|[_-])(?:argv|args|env|vars|raw_env|api_key)(?:$|[_-]))")
SENSITIVE_VALUE = re.compile(r"(?i)(?:\b(?:Bearer|Basic)\s+\S+|-----BEGIN [^-]*PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{16,}|https?://[^\s]*?(?:webhook|bot/v2/hook|services)/[^\s]+|--(?:api[-_]key|token|secret|password|authorization)[=\s]+\S+)|(?:^|\s)[A-Z][A-Z0-9_]+\s*=\s*\S+")


def normalize_string(value: str) -> str:
    if SENSITIVE_VALUE.search(value):
        return "[redacted sensitive value]"
    # Preserve useful repository anchors while never exporting host-specific roots.
    def replace(match):
        path = match.group(0)
        for anchor in ("docs/", "scripts/", "app/", "worker/", "ops/"):
            marker = "/trade/" + anchor
            if marker in path:
                return anchor + path.split(marker, 1)[1]
        return "[redacted private path]"
    value = PRIVATE_PATH.sub(replace, value)
    value = re.sub(r"https?://[^\s\"<>]+", "[redacted connection]", value)
    value = re.sub(r"\b[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[redacted account]", value)
    return value


def sanitize(value):
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            safe_key = normalize_string(key)
            if safe_key in result:
                raise ConfigurationError("redaction would collide object keys")
            result[safe_key] = "[redacted sensitive field]" if SENSITIVE_KEY.search(key) else sanitize(child)
        return result
    if isinstance(value, list):
        return [sanitize(child) for child in value]
    return normalize_string(value) if isinstance(value, str) else value


def inventory_paths(directory: Path):
    return tuple(sorted(p for p in directory.glob("*.json") if p.name not in DERIVED_NAMES))


def read_snapshot(directory: Path):
    paths = inventory_paths(directory)
    if tuple(p.name for p in paths) != SOURCE_NAMES:
        raise ConfigurationError("baseline requires the exact nine source inventory paths")
    raw = {p: read_regular(p) for p in paths}
    hashes = {p: digest(data) for p, data in raw.items()}
    verify_snapshot(directory, paths, hashes)
    data = {p: loads_jsonc(content.decode("utf-8")) for p, content in raw.items()}
    return paths, hashes, data


def verify_snapshot(directory: Path, paths, hashes):
    if inventory_paths(directory) != paths or any(digest(read_regular(p)) != hashes[p] for p in paths):
        raise ConfigurationError("source inventories changed; regenerate from a stable snapshot")


def reconstruct_record(merged: dict, observation_index: int) -> dict:
    """Restore the complete sanitized source record using the wire contract."""
    observation = merged["observations"][observation_index]
    if "record" in observation:
        return copy.deepcopy(observation["record"])
    primary = copy.deepcopy({key: value for key, value in merged.items() if key != "observations"})
    primary.update(copy.deepcopy(observation.get("record_overrides", {})))
    return primary


def build_module(directory: Path = INVENTORY):
    paths, hashes, data = read_snapshot(directory)
    refs = {data[p]["baseline_code_ref"] for p in paths}
    if len(refs) != 1 or not re.fullmatch(r"[0-9a-f]{40}", next(iter(refs))):
        raise ConfigurationError("source baseline_code_ref values disagree or are invalid")
    by_id = {}
    times = []
    source_files = []
    count = 0
    for path in paths:
        source = data[path]
        stamp = datetime.datetime.fromisoformat(source["observed_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ConfigurationError("inventory observation time requires timezone")
        times.append(stamp)
        seen = set()
        for record in source["records"]:
            identifier = record["id"]
            if identifier in seen:
                raise ConfigurationError("duplicate id within source inventory")
            seen.add(identifier)
            safe = sanitize(record)
            observation = dict(source_file=path.name, source_inventory_time=source["observed_at"],
                               source_inventory_code_ref=source["baseline_code_ref"])
            if identifier not in by_id:
                by_id[identifier] = copy.deepcopy(safe)
                by_id[identifier]["observations"] = []
                # Only the generated observations field can shadow a source
                # field. Preserve that rare case explicitly for lossless replay.
                if "observations" in safe:
                    observation["record_overrides"] = {"observations": safe["observations"]}
            elif by_id[identifier]["kind"] != safe["kind"]:
                raise ConfigurationError("cross-source kind collision")
            else:
                observation["record"] = safe
            by_id[identifier]["observations"].append(observation)
            count += 1
        source_files.append(dict(file=path.name, sha256=hashes[path], records=len(source["records"])))
    baseline = dict(schema_version=1, baseline_code_ref=next(iter(refs)),
                    observed_at=max(times).astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                    records=[by_id[key] for key in sorted(by_id)],
                    source_files=source_files, source_record_count=count, unique_record_count=len(by_id),
                    observation_contract={"version": 1,
                        "primary": "First observation uses top-level record fields excluding generated observations; apply optional record_overrides.",
                        "additional": "Subsequent observations contain the complete sanitized source record in record.",
                        "source_metadata": ["source_file", "source_inventory_time", "source_inventory_code_ref"]})
    encoded = json.dumps(baseline, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    module = ("// Generated by ops/monitoring/build_baseline.py. Server-only; do not embed in public assets.\n"
              "function freeze(value) {\n"
              "  if (value && typeof value === 'object') {\n"
              "    for (const child of Object.values(value)) freeze(child);\n"
              "    Object.freeze(value);\n"
              "  }\n  return value;\n}\n"
              "const BASELINE = freeze(" + encoded + ");\nexport default BASELINE;\n").encode("utf-8")
    verify_snapshot(directory, paths, hashes)
    return module, baseline, lambda: verify_snapshot(directory, paths, hashes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Read-only reproducibility check (default)")
    mode.add_argument("--write-module", action="store_true", help="Generate only owned worker/ops_baseline.js")
    parser.add_argument("--output", type=Path, help="Optional candidate under absolute /tmp; not a production write")
    args = parser.parse_args(argv)
    try:
        if args.output and (args.check or args.write_module):
            raise ConfigurationError("--output is a separate candidate mode")
        module, baseline, verify = build_module()
        if args.output:
            target = private_tmp_output(args.output, forbidden=list(inventory_paths(INVENTORY)))
            atomic_write(target, module, before_replace=verify)
        elif args.write_module:
            atomic_write(MODULE, module, before_replace=verify)
        else:
            if read_regular(MODULE) != module:
                raise ConfigurationError("server baseline differs; regenerate owned module")
            verify()
        print(json.dumps(dict(mode="candidate" if args.output else "write-module" if args.write_module else "check",
                              sha256=digest(module), baseline_code_ref=baseline["baseline_code_ref"],
                              source_records=baseline["source_record_count"], records=len(baseline["records"]))))
        return 0
    except (ConfigurationError, OSError, ValueError, KeyError, TypeError) as exc:
        print("build_baseline: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
