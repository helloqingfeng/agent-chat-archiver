"""Minimal unittest suite for the parsing and scanning helpers."""
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import agent_chat_archiver as aca

UTC = timezone.utc


def jsonl(path, items):
    path.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items), encoding="utf-8")


def row(role, text, stamp="2026-10-07 10:00"):
    return {"role": role, "text": text, "date": "2026-10-07", "stamp": stamp}


class HelperTests(unittest.TestCase):
    def test_text_of_blocks(self):
        value = [{"type": "text", "text": "a"}, {"type": "input_text", "text": "b"},
                 {"type": "image"}, "c"]
        self.assertEqual(aca.text_of(value), "a\nb\nc")

    def test_text_of_single_block_dict(self):
        self.assertEqual(aca.text_of({"type": "text", "text": "x"}), "x")
        self.assertEqual(aca.text_of({"type": "image"}), "")

    def test_clean_strips_system_reminder(self):
        self.assertEqual(aca.clean("hi\n<system-reminder>x</system-reminder>\n"), "hi")

    def test_extract_message_response_item(self):
        item = {"type": "response_item",
                "payload": {"type": "message", "role": "assistant",
                            "content": [{"type": "text", "text": "hi"}]}}
        self.assertEqual(aca.extract_message(item), ("assistant", "hi"))

    def test_extract_message_ignores_other_payloads(self):
        self.assertIsNone(aca.extract_message({"type": "response_item",
                                               "payload": {"type": "function_call"}}))

    def test_timestamp_of_iso_and_epoch(self):
        fallback = datetime(2020, 1, 1, tzinfo=UTC)
        date, stamp = aca.timestamp_of({"timestamp": "2026-10-07T02:00:00Z"}, fallback)
        self.assertEqual((date, stamp), ("2026-10-07", "2026-10-07 10:00"))
        ms = int(datetime(2026, 10, 7, 2, 0, tzinfo=UTC).timestamp() * 1000)
        self.assertEqual(aca.timestamp_of({"timestamp": ms}, fallback)[0], "2026-10-07")

    def test_epoch_stamp(self):
        ms = int(datetime(2026, 10, 7, 2, 30, tzinfo=UTC).timestamp() * 1000)
        self.assertEqual(aca.epoch_stamp(ms, None), ("2026-10-07", "2026-10-07 10:30"))
        fallback = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)
        self.assertEqual(aca.epoch_stamp(None, fallback)[0], "2026-10-07")

    def test_relocated_home_paths_include_claude_and_cowork(self):
        home = Path(r"E:\Users\someone")
        paths = aca.agent_paths_for_home(home)["Claude"]
        self.assertIn(home / ".claude" / "projects", paths)
        self.assertIn(home / "AppData" / "Local" / "Claude-3p" / "local-agent-mode-sessions", paths)

    def test_meaningful_filters_transport_placeholder(self):
        self.assertFalse(aca.meaningful("[Request interrupted by user]"))
        self.assertTrue(aca.meaningful("真实问题"))

    def test_clean_strips_unclosed_system_reminder(self):
        self.assertEqual(aca.clean("hi\n<system-reminder>truncated instruction"), "hi")

    def test_clean_keeps_text_after_closed_reminder(self):
        self.assertEqual(aca.clean("hi\n<system-reminder>x</system-reminder>\nmore"), "hi\n\nmore")

    def test_dedupe_rows_is_global_not_adjacent(self):
        # Copies of one conversation stored in two profiles interleave on merge.
        rows = [row("user", "q"), row("assistant", "a"), row("user", "q"), row("assistant", "a")]
        self.assertEqual(len(aca.dedupe_rows(rows)), 2)

    def test_dedupe_rows_keeps_real_repeats_at_different_times(self):
        rows = [row("user", "继续", "2026-10-07 10:05"),
                row("user", "继续", "2026-10-07 10:20")]
        self.assertEqual(len(aca.dedupe_rows(rows)), 2)

    def test_is_workbuddy_doc_accepts_journals_and_rejects_project_docs(self):
        for path in (r"C:\u\.workbuddy\memory\2026-05-15.md",
                     r"C:\u\.workbuddy\memory\automations\ai\2026-03-26.md",
                     r"C:\u\.workbuddy\automations\ai\2026-05-02\daily.md",
                     r"C:\u\automation-2026-06-08\report.md",
                     r"C:\u\.workbuddy\brain\note.md"):
            self.assertTrue(aca._is_workbuddy_doc(path), path)
        for path in (r"C:\u\.workbuddy\sessions\deep\notes\unrelated.md",
                     r"C:\u\longbridge\references\rust-sdk\overview.md",
                     r"C:\u\automation-20260101\sdk\references\types.md"):
            self.assertFalse(aca._is_workbuddy_doc(path), path)


class ZcodeTests(unittest.TestCase):
    def test_session_from_zcode_new_format(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            envelopes = [
                {"completedAt": "2026-10-07T02:00:00Z", "request": {"body": {}},
                 "response": {"text": "回答一"}},
                {"completedAt": "2026-10-07T02:01:00Z",
                 "request": {"body": {"messages": [{"role": "user", "content": "问题"}]}},
                 "response": {"text": "回答二"}},
                {"completedAt": "2026-10-07T02:02:00Z", "request": {"body": {}},
                 "response": {"text": "{\"title\":\"侧路调用\"}"}},
            ]
            path = tmp / "model-io-sess_abc.jsonl"
            jsonl(path, envelopes)
            session = aca.session_from_zcode(path, "ZCode")
            self.assertIsNotNone(session)
            self.assertEqual(session["id"], "sess_abc")
            self.assertEqual([(r["role"], r["text"]) for r in session["rows"]],
                             [("assistant", "回答一"), ("user", "问题"), ("assistant", "回答二")])
            self.assertTrue(session["title"].startswith("问题"))

    def make_db(self, db):
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE session (id text primary key, title text, time_created integer);
            CREATE TABLE message (id text primary key, session_id text,
                                  time_created integer, data text, sequence integer);
            CREATE TABLE part (id text primary key, message_id text, session_id text,
                               sequence integer, data text);
        """)
        ms = int(datetime(2026, 10, 7, 2, 0, tzinfo=UTC).timestamp() * 1000)
        con.execute("INSERT INTO session VALUES ('sess_a', '测试标题', ?)", (ms,))
        con.execute("INSERT INTO message VALUES ('m1', 'sess_a', ?, ?, 1)",
                    (ms, json.dumps({"role": "user"})))
        con.execute("INSERT INTO part VALUES ('p1', 'm1', 'sess_a', 0, ?)",
                    (json.dumps({"type": "text", "text": "用户提问"}),))
        con.execute("INSERT INTO message VALUES ('m2', 'sess_a', ?, ?, 2)",
                    (ms + 1000, json.dumps({"role": "assistant"})))
        con.execute("INSERT INTO part VALUES ('p2', 'm2', 'sess_a', 0, ?)",
                    (json.dumps({"type": "text", "text": "助手回答"}),))
        con.execute("INSERT INTO part VALUES ('p3', 'm2', 'sess_a', 1, ?)",
                    (json.dumps({"type": "reasoning", "text": "思考过程"}),))
        con.commit()
        con.close()

    def test_zcode_db_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "db.sqlite"
            self.make_db(db)
            sessions = aca.zcode_db_sessions(db)
            self.assertEqual(len(sessions), 1)
            session = sessions[0]
            self.assertEqual(session["title"], "测试标题")
            self.assertEqual([(r["role"], r["text"]) for r in session["rows"]],
                             [("user", "用户提问"), ("assistant", "助手回答")])

    def test_zcode_db_sessions_dedupes_repeated_parts(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "db.sqlite"
            self.make_db(db)
            con = sqlite3.connect(db)
            ms = int(datetime(2026, 10, 7, 2, 0, tzinfo=UTC).timestamp() * 1000)
            # A second part repeating the same message text in the same minute.
            con.execute("INSERT INTO message VALUES ('m3', 'sess_a', ?, ?, 3)",
                        (ms, json.dumps({"role": "user"})))
            con.execute("INSERT INTO part VALUES ('p4', 'm3', 'sess_a', 0, ?)",
                        (json.dumps({"type": "text", "text": "用户提问"}),))
            con.commit()
            con.close()
            session = aca.zcode_db_sessions(db)[0]
            self.assertEqual([(r["role"], r["text"]) for r in session["rows"]],
                             [("user", "用户提问"), ("assistant", "助手回答")])

    def test_zcode_db_sessions_missing_table(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "db.sqlite"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE other (x integer)")
            con.commit()
            con.close()
            self.assertEqual(aca.zcode_db_sessions(db), [])

    def test_scan_merges_zcode_db_over_rollout(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            rollout_dir = home / ".zcode" / "cli" / "rollout"
            rollout_dir.mkdir(parents=True)
            db_dir = home / ".zcode" / "cli" / "db"
            db_dir.mkdir(parents=True)
            jsonl(rollout_dir / "model-io-sess_a.jsonl",
                  [{"completedAt": "2026-10-07T02:00:00Z", "request": {"body": {}},
                    "response": {"text": "助手回答"}}])
            self.make_db(db_dir / "db.sqlite")
            agents = {**aca.AGENTS, "ZCode": [rollout_dir]}
            with mock.patch.dict(aca.AGENTS, agents), mock.patch.object(aca, "HOME", home):
                sessions = aca.scan(["ZCode"], [], use_cache=False)
            self.assertEqual(len(sessions), 1)
            self.assertEqual([r["role"] for r in sessions[0]["rows"]], ["user", "assistant"])
            self.assertEqual(sessions[0]["title"], "测试标题")


class ScanTests(unittest.TestCase):
    def test_scan_dedupes_prunes_and_collects_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "sessions" / "Cache").mkdir(parents=True)
            (root / "sessions" / "outputs").mkdir(parents=True)
            jsonl(root / "sessions" / "chat.jsonl",
                  [{"type": "user", "message": {"role": "user", "content": "你好"}}])
            (root / "sessions" / "Cache" / "junk.json").write_text(
                json.dumps({"message": {"role": "user", "content": "缓存里不该出现"}}), encoding="utf-8")
            (root / "sessions" / "outputs" / "note.md").write_text("# 笔记", encoding="utf-8")
            sessions = aca.scan([], [str(root)], use_cache=False)
            blob = json.dumps(sessions, ensure_ascii=False)
            self.assertEqual(len(sessions), 2)
            self.assertIn("你好", blob)
            self.assertIn("note.md", blob)
            self.assertNotIn("缓存里不该出现", blob)

    def test_scan_repeats_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            jsonl(root / "chat.jsonl",
                  [{"type": "user", "message": {"role": "user", "content": "你好"}}])
            sessions = aca.scan([], [str(root), str(root)], use_cache=False)
            self.assertEqual(len(sessions), 1)

    def test_cowork_output_markdown_is_attached_to_session(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "local-agent-mode-sessions" / "account" / "workspace" / "local_abc"
            (root / "outputs").mkdir(parents=True)
            jsonl(root / "audit.jsonl", [
                {"type": "user", "timestamp": "2026-10-07T02:00:00Z",
                 "message": {"role": "user", "content": "做一份报告"}},
                {"type": "assistant", "timestamp": "2026-10-07T02:01:00Z",
                 "message": {"role": "assistant", "content": "已完成"}},
            ])
            (root / "outputs" / "结论.md").write_text("# 最终结论", encoding="utf-8")
            agents = {**aca.AGENTS, "Claude": [root.parent.parent.parent]}
            with mock.patch.dict(aca.AGENTS, agents):
                sessions = aca.scan(["Claude"], [], use_cache=False)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["id"], "local_abc")
            self.assertEqual(sessions[0]["outputs"][0]["name"], "结论.md")

    def test_workbuddy_collects_memory_and_automation_docs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "Claw" / ".workbuddy" / "memory").mkdir(parents=True)
            (root / "Claw" / ".workbuddy" / "automations" / "ai").mkdir(parents=True)
            (root / "automation-2026-06-08").mkdir(parents=True)
            (root / "rust-sdk" / "docs").mkdir(parents=True)
            (root / "Claw" / ".workbuddy" / "memory" / "2026-05-15.md").write_text("记忆", encoding="utf-8")
            (root / "Claw" / ".workbuddy" / "automations" / "ai" / "2026-03-26.md").write_text("日报", encoding="utf-8")
            (root / "automation-2026-06-08" / "report.md").write_text("报告", encoding="utf-8")
            (root / "rust-sdk" / "docs" / "readme.md").write_text("noise", encoding="utf-8")
            agents = {**aca.AGENTS, "WorkBuddy": [root]}
            with mock.patch.dict(aca.AGENTS, agents):
                sessions = aca.scan(["WorkBuddy"], [], use_cache=False)
            blob = json.dumps(sessions, ensure_ascii=False)
            self.assertEqual(len(sessions), 3)
            self.assertIn("记忆", blob)
            self.assertIn("日报", blob)
            self.assertIn("报告", blob)
            self.assertNotIn("noise", blob)

    def test_same_session_in_two_profiles_merges_without_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            items = [
                {"type": "user", "timestamp": "2026-10-07T02:00:00Z", "sessionId": "sess-dup",
                 "message": {"role": "user", "content": "同一个问题"}},
                {"type": "assistant", "timestamp": "2026-10-07T02:01:00Z", "sessionId": "sess-dup",
                 "message": {"role": "assistant", "content": "同一个回答"}},
            ]
            roots = []
            for profile in ("new", "old"):
                folder = root / profile / ".claude" / "projects" / "proj"
                folder.mkdir(parents=True)
                jsonl(folder / "sess-dup.jsonl", items)
                roots.append(root / profile / ".claude")
            agents = {**aca.AGENTS, "Claude": roots}
            with mock.patch.object(aca, "CACHE_FILE", root / "index.json"), \
                    mock.patch.dict(aca.AGENTS, agents):
                sessions = aca.scan(["Claude"], [], use_cache=False)
            self.assertEqual(len(sessions), 1)
            self.assertEqual([r["text"] for r in sessions[0]["rows"]], ["同一个问题", "同一个回答"])
            self.assertIn("\n", sessions[0]["source"])

    def test_scan_honours_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            jsonl(root / "chat.jsonl",
                  [{"type": "user", "message": {"role": "user", "content": "你好"}}])
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(aca.Cancelled):
                aca.scan([], [str(root)], use_cache=False, cancel=cancel)

    def test_scan_reports_monotonic_progress_up_to_total(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for i in range(4):
                jsonl(root / f"chat{i}.jsonl",
                      [{"type": "user", "message": {"role": "user", "content": f"问题{i}"}}])
            seen = []
            sessions = aca.scan([], [str(root)], use_cache=False,
                                on_progress=lambda done, total: seen.append((done, total)))
            self.assertEqual(len(sessions), 4)
            self.assertTrue(seen)
            self.assertEqual(seen[-1], (4, 4))
            self.assertEqual([done for done, _ in seen], sorted(done for done, _ in seen))
            self.assertTrue(all(total == 4 for _, total in seen))

    def test_cache_reuses_unchanged_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            jsonl(root / "chat.jsonl",
                  [{"type": "user", "message": {"role": "user", "content": "第一次"}}])
            with mock.patch.object(aca, "CACHE_FILE", Path(d) / "index.json"):
                first = aca.scan([], [str(root)])
                self.assertTrue((Path(d) / "index.json").is_file())
                second = aca.scan([], [str(root)])
            self.assertEqual(len(first), len(second), 1)
            self.assertIn("第一次", json.dumps(second, ensure_ascii=False))

    def test_render_escapes_and_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "a.html"
            session = {"tool": "T", "id": "s1", "title": "t", "date": "2026-10-07",
                       "stamp": "2026-10-07 10:00", "source": "x", "outputs": [],
                       "rows": [{"role": "user", "text": "<script>alert(1)</script>",
                                 "date": "2026-10-07", "stamp": "2026-10-07 10:00"}]}
            aca.render([session], out)
            text = out.read_text(encoding="utf-8")
            self.assertIn("&lt;script&gt;", text)
            self.assertNotIn("<script>alert", text)
            self.assertEqual(list(Path(d).glob("*.tmp")), [])

    def test_output_path_collision_suffix(self):
        with tempfile.TemporaryDirectory() as d:
            fixed = datetime(2026, 10, 7, 12, 0, 0, tzinfo=aca.LOCAL_TZ)
            with mock.patch.object(aca, "datetime") as fake:
                fake.now.return_value = fixed
                first = aca.output_path(Path(d), ["Claude"])
                first.touch()
                second = aca.output_path(Path(d), ["Claude"])
            self.assertEqual(first.name, "Claude_20261007-120000.html")
            self.assertEqual(second.name, "Claude_20261007-120000_01.html")

    def test_output_path_caps_long_source_lists(self):
        with tempfile.TemporaryDirectory() as d:
            tools = [f"Tool{i}" for i in range(14)]
            name = aca.output_path(Path(d), tools).name
            self.assertTrue(name.startswith("Tool0-等14个来源_"), name)


if __name__ == "__main__":
    unittest.main()
