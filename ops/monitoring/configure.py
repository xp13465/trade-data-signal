"""Create a private, complete Wrangler candidate. Never apply production config.

Rebase main, assets.directory, $schema and D1 migrations against the source
directory. Unsupported filesystem/custom-build settings fail closed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
OPS_CRON = "*/15 * * * *"
MIGRATIONS_DIR = "ops/monitoring/migrations"


class ConfigurationError(ValueError):
    pass


def _without_comments(text: str) -> str:
    chars = list(text.removeprefix("\ufeff"))
    quoted = escaped = False
    i = 0
    while i < len(chars):
        char = chars[i]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            i += 1
            continue
        if char == '"':
            quoted = True
        elif char == "/" and i + 1 < len(chars) and chars[i + 1] == "/":
            while i < len(chars) and chars[i] not in "\r\n":
                chars[i] = " "
                i += 1
            continue
        elif char == "/" and i + 1 < len(chars) and chars[i + 1] == "*":
            chars[i] = chars[i + 1] = " "
            i += 2
            while i + 1 < len(chars) and not (chars[i] == "*" and chars[i + 1] == "/"):
                if chars[i] not in "\r\n":
                    chars[i] = " "
                i += 1
            if i + 1 >= len(chars):
                raise ConfigurationError("unterminated JSONC block comment")
            chars[i] = chars[i + 1] = " "
            i += 2
            continue
        i += 1
    return "".join(chars)


def _without_trailing_commas(text: str) -> str:
    chars = list(text)
    quoted = escaped = False
    previous = ""
    for i, char in enumerate(chars):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
                previous = '"'
            continue
        if char == '"':
            quoted = True
        elif char == ",":
            j = i + 1
            while j < len(chars) and chars[j].isspace():
                j += 1
            # An empty item/member is not a legal trailing comma.
            if j < len(chars) and chars[j] in "]}" and previous not in ("", "[", "{", ":", ","):
                chars[i] = " "
            previous = ","
        elif not char.isspace():
            previous = char
    return "".join(chars)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _reject_constant(value):
    raise ConfigurationError("non-finite JSON number is forbidden")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ConfigurationError("non-finite JSON number is forbidden")
    return number


def loads_jsonc(text: str):
    """JSON plus comments/trailing commas, without JSON5 or duplicate keys."""
    try:
        return json.loads(_without_trailing_commas(_without_comments(text)),
                          object_pairs_hook=_unique_object, parse_constant=_reject_constant,
                          parse_float=_finite_float)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"invalid JSONC at line {exc.lineno}, column {exc.colno}") from exc


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ConfigurationError("source must be a regular non-symlink file")
        return stream.read()


def verify_source(path: Path, expected: str) -> None:
    if digest(read_regular(path)) != expected:
        raise ConfigurationError("source configuration changed; regenerate from current digest")


def private_tmp_output(path: Path, forbidden=()) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise ConfigurationError("output must be an absolute /tmp path")
    if path.is_symlink():
        raise ConfigurationError("output must not be a symlink")
    resolved = path.resolve()
    if not resolved.is_relative_to(Path("/tmp").resolve()):
        raise ConfigurationError("output must be under /tmp; production writes are not supported")
    if any(resolved == Path(p).resolve() for p in forbidden):
        raise ConfigurationError("output must not overwrite a source file")
    return resolved


def atomic_write(path: Path, data: bytes, before_replace=None) -> None:
    """Private atomic file, strict chmod/fsync, clean temp on any failure."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="." + path.name + ".",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if before_replace is not None:
            before_replace()
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _validate_bindings(config: dict, scope="root") -> None:
    seen = {}

    def register(name, location):
        if not isinstance(name, str) or not name:
            raise ConfigurationError("invalid binding name in " + scope)
        if name in seen:
            raise ConfigurationError(f"duplicate binding {name} in {scope}")
        seen[name] = location

    def visit(value, location):
        if isinstance(value, dict):
            if "binding" in value:
                register(value["binding"], location)
            for key, child in value.items():
                if location == scope and key in ("env", "vars", "durable_objects"):
                    continue
                visit(child, location + "." + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, location + f"[{index}]")

    visit(config, scope)
    variables = config.get("vars", {})
    if not isinstance(variables, dict):
        raise ConfigurationError("vars must be an object")
    for name in variables:
        register(name, scope + ".vars")
    durable = config.get("durable_objects", {})
    if not isinstance(durable, dict):
        raise ConfigurationError("durable_objects must be an object")
    durable_bindings = durable.get("bindings", [])
    if not isinstance(durable_bindings, list):
        raise ConfigurationError("durable_objects.bindings must be an array")
    for item in durable_bindings:
        if not isinstance(item, dict):
            raise ConfigurationError("invalid Durable Object binding")
        register(item.get("name"), scope + ".durable_objects")
    environments = config.get("env", {})
    if not isinstance(environments, dict):
        raise ConfigurationError("env must be an object")
    for name, environment in environments.items():
        if not isinstance(environment, dict):
            raise ConfigurationError("named environment must be an object")
        _validate_bindings(environment, "env." + name)


def _database_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ConfigurationError("database-id must be a UUID") from exc
    if not parsed.int:
        raise ConfigurationError("database-id must not be an all-zero placeholder")
    return str(parsed)


def _rebase_filesystem_paths(config: dict, source_dir: Path, scope="root") -> list[str]:
    """Preserve config-relative meaning when its complete copy lives in /tmp.

    This version audits main, assets.directory, $schema and every D1 migration
    directory. Other filesystem/custom-build settings fail closed rather than
    silently changing their interpretation after relocation. Binding IDs, vars,
    routes and non-filesystem values are never rewritten by this pass.
    """
    unsupported = {"tsconfig", "base_dir", "build", "site", "pages_build_output_dir",
                   "wasm_modules", "text_blobs", "data_blobs", "alias", "unsafe",
                   "containers", "python_modules", "dev"}
    for key in config:
        if key in unsupported or (key.endswith(("_path", "_file", "_dir")) and key not in {"name"}):
            raise ConfigurationError("unsupported relocated filesystem setting: " + scope + "." + key)
    changed = []

    def absolute(value, field, schema=False):
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ConfigurationError("invalid filesystem path: " + field)
        if schema and value.startswith(("https://", "http://")):
            return value
        if "://" in value:
            raise ConfigurationError("filesystem path must not be a URL: " + field)
        resolved = str((source_dir / value).resolve())
        if resolved != value:
            changed.append(field)
        return resolved

    for key in ("main", "$schema"):
        if key in config:
            config[key] = absolute(config[key], scope + "." + key, schema=key == "$schema")
    if "assets" in config:
        assets = config["assets"]
        if not isinstance(assets, dict):
            raise ConfigurationError("assets must be an object")
        if "directory" in assets:
            assets["directory"] = absolute(assets["directory"], scope + ".assets.directory")
    databases = config.get("d1_databases", [])
    if not isinstance(databases, list) or any(not isinstance(item, dict) for item in databases):
        raise ConfigurationError("d1_databases must be an array of objects")
    for index, database in enumerate(databases):
        if "migrations_pattern" in database:
            raise ConfigurationError("unsupported relocated filesystem setting: D1 migrations_pattern")
        key = scope + f".d1_databases[{index}].migrations_dir"
        # Wrangler's omitted migration directory defaults to ./migrations next
        # to the ORIGINAL config, not next to the external candidate.
        database["migrations_dir"] = absolute(database.get("migrations_dir", "migrations"), key)
    for name, environment in config.get("env", {}).items():
        changed.extend(_rebase_filesystem_paths(environment, source_dir, scope + ".env." + name))
    return changed


def make_candidate(config: dict, database_id: str, database_name="trade-ops-monitoring", *, source_dir=ROOT):
    if not isinstance(config, dict):
        raise ConfigurationError("Wrangler config must be an object")
    _validate_bindings(config)
    candidate = copy.deepcopy(config)
    databases = candidate.setdefault("d1_databases", [])
    if not isinstance(databases, list) or any(not isinstance(x, dict) for x in databases):
        raise ConfigurationError("d1_databases must be an array of objects")
    database_id = _database_id(database_id)
    for item in databases:
        if item.get("binding") != "OPS_DB" and item.get("database_id"):
            if str(item["database_id"]).lower() == database_id:
                raise ConfigurationError("OPS_DB requires a dedicated database; existing database cannot be reused")
    existing = next((x for x in databases if x.get("binding") == "OPS_DB"), None)
    if existing is not None:
        if existing.get("database_id") and _database_id(existing["database_id"]) != database_id:
            raise ConfigurationError("existing OPS_DB database_id differs; refusing to replace it")
        existing.setdefault("database_id", database_id)
        existing.setdefault("database_name", database_name)
        existing.setdefault("migrations_dir", MIGRATIONS_DIR)
    else:
        # A different binding type or vars cannot reserve OPS_DB.
        def occupied(value):
            if isinstance(value, dict):
                return value.get("binding") == "OPS_DB" or any(
                    occupied(v) for k, v in value.items() if k not in ("env", "vars", "durable_objects"))
            return isinstance(value, list) and any(occupied(v) for v in value)
        if occupied(candidate) or "OPS_DB" in candidate.get("vars", {}) or any(
                x.get("name") == "OPS_DB" for x in candidate.get("durable_objects", {}).get("bindings", [])):
            raise ConfigurationError("OPS_DB already used by a different binding")
        databases.append(dict(binding="OPS_DB", database_name=database_name,
                              database_id=database_id, migrations_dir=MIGRATIONS_DIR))
    triggers = candidate.setdefault("triggers", {})
    if not isinstance(triggers, dict):
        raise ConfigurationError("triggers must be an object")
    crons = triggers.get("crons", [])
    if not isinstance(crons, list) or any(not isinstance(x, str) for x in crons):
        raise ConfigurationError("triggers.crons must be an array of strings")
    triggers["crons"] = list(dict.fromkeys(crons + [OPS_CRON]))
    _validate_bindings(candidate)
    rebased = _rebase_filesystem_paths(candidate, Path(source_dir).resolve())
    changes = ["Ensure dedicated d1_databases binding OPS_DB; preserve existing bindings and values",
               "Merge/deduplicate triggers.crons with */15 * * * *; preserve other triggers",
               "Preserve vars, routes and non-filesystem binding/settings values",
               "Rebase audited filesystem paths against original config directory: " + (", ".join(rebased) or "already absolute"),
               "Unsupported relocated filesystem/custom-build settings fail closed (including tsconfig/base_dir/build/site/alias/unsafe)",
               "Candidate only: no database creation, secrets, production write or deployment"]
    return candidate, changes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "wrangler.jsonc")
    parser.add_argument("--database-id")
    parser.add_argument("--database-name", default="trade-ops-monitoring")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-current", metavar="SOURCE_SHA256")
    args = parser.parse_args(argv)
    try:
        source = args.source.absolute()
        raw = read_regular(source)
        source_digest = digest(raw)
        if args.check_current:
            if not re.fullmatch(r"[0-9a-f]{64}", args.check_current):
                raise ConfigurationError("check-current requires a lowercase source SHA-256")
            if source_digest != args.check_current:
                raise ConfigurationError("source configuration differs from check-current digest")
            verify_source(source, args.check_current)
        if not args.database_id and not args.output and args.check_current:
            print(json.dumps(dict(mode="check", source_sha256=source_digest, matches=True)))
            return 0
        if not args.database_id or not args.output:
            raise ConfigurationError("--database-id and --output are required for candidate generation")
        target = private_tmp_output(args.output, forbidden=[source])
        candidate, changes = make_candidate(loads_jsonc(raw.decode("utf-8-sig")), args.database_id,
                                            args.database_name, source_dir=source.parent)
        header = "// Candidate only. source_sha256=" + source_digest + "\n"
        header += "".join("// " + note + "\n" for note in changes)
        data = (header + json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        atomic_write(target, data, before_replace=lambda: verify_source(source, source_digest))
        print(json.dumps(dict(mode="candidate", source_sha256=source_digest,
                              candidate_sha256=digest(data), output=str(target), changes=changes)))
        return 0
    except (ConfigurationError, OSError, UnicodeError) as exc:
        print("configure: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
