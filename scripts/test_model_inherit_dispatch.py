#!/usr/bin/env python3

import os
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import agent_inbox_watcher as watcher


class ModelInheritDispatchTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sessions_dir = self.root / "sessions"
        self.day_dir = self.sessions_dir / "2026" / "08" / "27"
        self.day_dir.mkdir(parents=True)
        self.config_path = self.root / "config.toml"
        watcher.SESSIONS_DIR = self.sessions_dir

    def tearDown(self):
        self.temporary.cleanup()
        for key in ("CODEX_REVIEWER_MODEL", "CODEX_MAIN_THREAD_ID"):
            os.environ.pop(key, None)

    def write_session(self, name: str, model: str, thread_source="user"):
        payload = {
            "id": f"id-{name}",
            "cwd": "/tmp/trade-codex-model-inherit",
            "thread_source": thread_source,
            "provenance": {"model": model},
        }
        path = self.day_dir / name
        path.write_text(
            '{"type":"session_meta","payload":' + json.dumps(payload) + "}\n",
            encoding="utf-8",
        )
        return path

    def test_explicit_environment_overrides_everything(self):
        self.write_session("newer.jsonl", "test/new")
        with mock.patch.dict(os.environ, {"CODEX_REVIEWER_MODEL": "override/model"}):
            self.assertEqual(watcher.current_main_session_model(), "override/model")

    def test_latest_user_session_is_selected(self):
        older = self.write_session("older.jsonl", "test/older")
        newer = self.write_session("newer.jsonl", "test/newer")
        old_timestamp = time.time() - 30
        os.utime(older, (old_timestamp, old_timestamp))
        new_timestamp = time.time()
        os.utime(newer, (new_timestamp, new_timestamp))
        with mock.patch.object(
            watcher,
            "REPO",
            Path("/tmp/trade-codex-model-inherit"),
        ):
            self.assertEqual(watcher.current_main_session_model(), "test/newer")

    def test_non_user_session_is_ignored_and_config_used_as_fallback(self):
        self.write_session("review.jsonl", "test/reviewer", thread_source="subagent")
        self.config_path.write_text('model = "config/fallback"\n', encoding="utf-8")
        with mock.patch.object(
            watcher,
            "REPO",
            Path("/tmp/trade-codex-model-inherit"),
        ), mock.patch.object(
            watcher,
            "parse_config_model",
            return_value="config/fallback",
        ):
            self.assertEqual(watcher.current_main_session_model(), "config/fallback")

    def test_build_command_pins_reviewer_model(self):
        self.write_session("main.jsonl", "test/main")
        with mock.patch.object(
            watcher,
            "REPO",
            Path("/tmp/trade-codex-model-inherit"),
        ):
            command = watcher.build_command("codex", "test-001")
            index = command.index("-m")
            self.assertEqual(command[index + 1], "test/main")


if __name__ == "__main__":
    unittest.main()
