#!/usr/bin/env python3
"""Local agent-chat archiver. Stdlib only: GUI + CLI, JSONL/JSON/Markdown scanners."""

import argparse
import html
import json
import os
import re
import sqlite3
import sys
import threading
import time
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:
    tk = None

LOCAL_TZ = timezone(timedelta(hours=8))
HOME = Path.home()
APPDATA = Path(os.environ.get("APPDATA", HOME / "AppData/Roaming"))
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData/Local"))


def resource_path(relative):
    """Locate a bundled data file both in a checkout and inside the frozen exe.

    PyInstaller unpacks bundled data to sys._MEIPASS at run time; running from
    source, the file simply sits next to this module.
    """
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / relative if base else Path(__file__).resolve().parent / relative

def _looks_like_agent_home(path):
    """A cheap marker check used to find relocated Windows profiles."""
    try:
        return path.is_dir() and any((path / name).exists() for name in (
            ".claude", ".codex", ".cursor", ".zcode", ".workbuddy", ".qoder",
            ".qwenworkcn", ".newmax", ".gemini", ".opencodex"))
    except OSError:
        return False


def discover_user_homes():
    """Find normal and relocated profile folders (for example E:\\Users\\name).

    Path.home()/USERPROFILE can be stale after a profile or Documents migration.
    Looking only at those variables was the main reason the packaged app could
    report zero records while the real data was on another drive.
    """
    candidates = [HOME]
    for value in (os.environ.get("USERPROFILE"), os.environ.get("HOME")):
        if value:
            candidates.append(Path(value))
    # User Shell Folders is the most reliable Windows signal for a relocated
    # profile.  The registry is optional so the module remains cross-platform.
    if os.name == "nt":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                for name in ("Personal", "Desktop", "Local AppData", "AppData"):
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except OSError:
                        continue
                    value = Path(os.path.expandvars(str(value))).expanduser()
                    # Documents/Desktop -> profile; AppData/* -> profile.
                    candidates.append(value.parent if name in ("Personal", "Desktop") else value.parent.parent)
        except (ImportError, OSError):
            pass
        # Last-resort, bounded discovery: only one level below X:\Users.
        # This is fast and catches profiles copied/moved to another fixed drive.
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            users = Path(f"{letter}:\\Users")
            try:
                candidates.extend(p for p in users.iterdir() if p.is_dir())
            except OSError:
                pass
    unique = []
    seen = set()
    for path in candidates:
        try:
            path = Path(path).expanduser()
            key = os.path.normcase(os.path.abspath(str(path)))
        except (OSError, TypeError, ValueError):
            continue
        if key not in seen and (_looks_like_agent_home(path) or path == HOME):
            seen.add(key)
            unique.append(path)
    return unique or [HOME]


def agent_paths_for_home(home):
    appdata = home / "AppData" / "Roaming"
    localappdata = home / "AppData" / "Local"
    # Prefer environment paths for the active profile, while still adding the
    # conventional paths below so migrated AppData is not missed.
    if os.path.normcase(os.path.abspath(str(home))) == os.path.normcase(os.path.abspath(str(HOME))):
        appdata, localappdata = APPDATA, LOCALAPPDATA
    return {
    "Claude": [
        home / ".claude" / "projects",
        home / ".claude" / "sessions",
        localappdata / "Claude-3p" / "local-agent-mode-sessions",
        localappdata / "Claude-3p" / "local-agent-mode-sessions (2)",
    ],
    "Codex": [home / ".codex" / "sessions", home / ".codex" / "memories"],
    "Cursor": [appdata / "Cursor" / "User" / "History", home / ".cursor"],
    "QwenWork": [home / ".qwen", appdata / "QwenWork", localappdata / "QwenWork"],
    "OpenClaw": [home / ".openclaw", appdata / "OpenClaw"],
    # These tools keep their readable sessions below the hidden home directory;
    # the Roaming folders are mostly settings/cache and caused false zero-result scans.
    "ZCode": [home / ".zcode" / "cli" / "rollout", home / ".zcode" / "cli" / "log", home / ".zcode" / "workspace", appdata / "ZCode", home / "Documents" / "ZCode"],
    "WorkBuddy": [home / ".workbuddy" / "sessions", home / ".workbuddy" / "brain", home / ".workbuddy" / "projects", appdata / "WorkBuddy", localappdata / "WorkBuddy", home / "WorkBuddy"],
    "豆包": [appdata / "Doubao", localappdata / "Doubao", home / "Doubao", appdata / "ByteDance"],
    "千问办公": [home / ".qwenworkcn" / "projects", appdata / "QwenWorkCN", localappdata / "qwen-work-cn", home / ".qwenworkcn"],
    "Qoder": [home / ".qoder" / "projects", appdata / "com.qoder.app.stable", localappdata / "Qoder", home / ".qoder-cn", home / ".qoder-cli", home / ".qoderwork", home / "Documents" / "Qoder"],
    "opencode": [appdata / "com.opencodex.desktop", localappdata / "com.opencodex.desktop", localappdata / "OpenCodex", home / ".opencodex"],
    "DeepSeekHarness": [appdata / "@deepseek-ai", localappdata / "@deepseek-aidsh-desktop-updater", home / ".deepseek", home / ".deepseek-harness"],
    "antigravity": [appdata / "Antigravity", localappdata / "antigravity", home / ".antigravity", home / ".gemini" / "antigravity" / "brain"],
    "NewMax": [home / ".newmax" / "conversations", home / ".newmax" / "projects", appdata / "NewmaxAI", localappdata / "NewmaxAI", home / "NewMax"],
    }


def build_agents(homes):
    merged = defaultdict(list)
    seen = defaultdict(set)
    for home in homes:
        for tool, paths in agent_paths_for_home(home).items():
            for path in paths:
                key = os.path.normcase(os.path.abspath(str(path)))
                if key not in seen[tool]:
                    seen[tool].add(key)
                    merged[tool].append(path)
    return dict(merged)


USER_HOMES = discover_user_homes()
AGENTS = build_agents(USER_HOMES)

MAX_FILE_SIZE = 50 * 1024 * 1024
# Electron/browser cache subdirectories that never hold session data but can
# be enormous; skipping them keeps presets that point at whole app-data roots fast.
SKIP_DIRS = {
    "Cache", "Code Cache", "GPUCache", "ShaderCache", "DawnCache", "Crashpad",
    "Crash Reports", "Service Worker", "IndexedDB", "File System",
    "node_modules", ".git", "__pycache__", ".pytest_cache", ".venv", "venv",
}
CACHE_VERSION = 4
CACHE_FILE = LOCALAPPDATA / "AgentChatArchiver" / "index.json"
STATE_FILE = LOCALAPPDATA / "AgentChatArchiver" / "gui-state.json"

# Cap how often a progress callback is delivered so a long scan does not flood
# the GUI event queue with thousands of updates.
PROGRESS_INTERVAL = 0.1
PROGRESS_EVERY = 25


class Cancelled(Exception):
    """Raised when the caller cancels a scan between files."""


def text_of(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("type") in ("text", "input_text") and isinstance(value.get("text"), str):
            return value["text"]
        return ""
    if isinstance(value, list):
        out = []
        for part in value:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict) and part.get("type") in ("text", "input_text"):
                if isinstance(part.get("text"), str):
                    out.append(part["text"])
        return "\n".join(out)
    return ""


def timestamp_of(item, fallback):
    value = item.get("timestamp") or item.get("created_at") or item.get("createdAt") or fallback
    if isinstance(value, (int, float)):
        value = value / 1000 if value > 10_000_000_000 else value
        dt = datetime.fromtimestamp(value, tz=timezone.utc).astimezone(LOCAL_TZ)
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        except Exception:
            dt = datetime.fromtimestamp(fallback.timestamp(), tz=LOCAL_TZ)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m-%d %H:%M")


def clean(text):
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
    # A truncated transcript can leave the opening tag without its closer, which
    # the paired pass above misses; drop the rest of that block too.
    text = re.sub(r"<system-reminder>.*", "", text, flags=re.S)
    return text.strip()


def meaningful(text):
    """Exclude empty transport placeholders while retaining short real prompts."""
    value = clean(text)
    return bool(value and value not in {
        "[Request interrupted by user]", "[Request interrupted by user for tool use]",
        "<no response requested>", "(no content)",
    })


def session_container_id(path):
    """Map Claude Cowork audit/output files back to their session directory."""
    for parent in (path.parent, *path.parents):
        name = parent.name
        if name.startswith("local_") or re.fullmatch(r"[0-9a-fA-F]{8}", name):
            return name
    return None


def dedupe_rows(rows):
    """Drop empty placeholders and repeated messages, keeping first-seen order.

    Deduplication is global rather than adjacent-only: the same conversation can
    be stored once per user profile, and merging those copies interleaves the
    repeats so that no two identical rows are next to each other.  The key keeps
    the minute-precision stamp, so a prompt the user genuinely sent twice at
    different times survives.
    """
    result = []
    seen = set()
    for row in rows:
        if not meaningful(row.get("text", "")):
            continue
        key = (row.get("role"), row.get("text"), row.get("stamp"))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def extract_message(item):
    kind = item.get("type") or item.get("role")
    # Codex rollout JSONL wraps visible messages in response_item.payload.
    if kind == "response_item" and isinstance(item.get("payload"), dict):
        payload = item["payload"]
        if payload.get("type") == "message":
            kind = payload.get("role")
            msg = payload
        else:
            return None
    else:
        msg = item.get("message") if isinstance(item.get("message"), dict) else item
    if kind not in ("user", "assistant", "human", "model"):
        return None
    text = clean(text_of(msg.get("content", item.get("content", ""))))
    if not text:
        return None
    role = "user" if kind in ("user", "human") else "assistant"
    return role, text


def zcode_message(value):
    """Read the visible part of ZCode's model-io envelope."""
    if not isinstance(value, dict):
        return None
    role = value.get("role")
    content = value.get("content", value.get("text", ""))
    if role not in ("user", "assistant", "human", "model"):
        return None
    text = clean(text_of(content))
    if not text:
        return None
    return ("user" if role in ("user", "human") else "assistant"), text


def zcode_response_text(response):
    """Assistant text of a role-less ZCode model-io response. Responses whose
    whole text is a JSON object are title-generation side calls, not replies."""
    if not isinstance(response, dict):
        return None
    text = response.get("text")
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            if isinstance(json.loads(stripped), dict):
                return None
        except ValueError:
            pass
    return clean(text)


def epoch_stamp(value, fallback):
    """(date, stamp) from a second/millisecond epoch, falling back to a datetime."""
    if isinstance(value, (int, float)) and value > 0:
        seconds = value / 1000 if value > 10_000_000_000 else value
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(LOCAL_TZ)
    else:
        dt = fallback
    return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m-%d %H:%M")


def zcode_db_sessions(db_path):
    """Read complete ZCode conversations (user and assistant) from its SQLite store."""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        parts = {}
        for message_id, data in con.execute("SELECT message_id, data FROM part ORDER BY message_id, sequence"):
            try:
                piece = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(piece, dict) and piece.get("type") == "text" and isinstance(piece.get("text"), str):
                parts.setdefault(message_id, []).append(piece["text"])
        titles = {sid: str(title or "") for sid, title in con.execute("SELECT id, title FROM session")}
        grouped = {}
        for message_id, session_id, created, data in con.execute(
                "SELECT id, session_id, time_created, data FROM message ORDER BY time_created, sequence"):
            try:
                role = json.loads(data).get("role")
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            if role not in ("user", "assistant"):
                continue
            text = clean("\n".join(parts.get(message_id, [])))
            if not text:
                continue
            date, stamp = epoch_stamp(created, datetime.now(LOCAL_TZ))
            grouped.setdefault(session_id, []).append(
                {"role": role, "text": text, "date": date, "stamp": stamp})
    except sqlite3.Error:
        return []
    finally:
        con.close()
    sessions = []
    for session_id, rows in grouped.items():
        # The store can repeat a message across parts; dedupe like the file
        # parsers do so database sessions match the rest of the archive.
        rows = dedupe_rows(rows)
        if not rows:
            continue
        first_user = next((r["text"] for r in rows if r["role"] == "user"), rows[0]["text"])
        title = titles.get(session_id) or next((x.strip() for x in first_user.splitlines() if x.strip()), "未命名会话")
        sessions.append({"tool": "ZCode", "id": str(session_id), "title": title[:160],
                         "date": rows[0]["date"], "stamp": rows[0]["stamp"],
                         "source": f"{db_path} · {session_id}", "rows": rows, "outputs": []})
    return sessions


def load_cache():
    try:
        value = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if isinstance(value, dict) and value.get("app") == CACHE_VERSION and isinstance(value.get("entries"), dict):
        return value["entries"]
    return {}


def save_cache(entries):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        doc = json.dumps({"app": CACHE_VERSION, "entries": entries}, ensure_ascii=False)
        CACHE_FILE.write_text(doc, encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def session_from_zcode(path, tool):
    rows = []
    sid = path.stem
    if sid.startswith("model-io-"):
        sid = sid[len("model-io-"):]
    try:
        fallback = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(envelope, dict):
            continue
        stamp_source = envelope.get("completedAt") or envelope.get("createdAt") or envelope
        date, stamp = timestamp_of(stamp_source if isinstance(stamp_source, dict) else {"timestamp": stamp_source}, fallback)
        request = envelope.get("request")
        body = request.get("body") if isinstance(request, dict) else None
        messages = body.get("messages", []) if isinstance(body, dict) else []
        for message in messages if isinstance(messages, list) else []:
            extracted = zcode_message(message)
            if extracted:
                rows.append({"role": extracted[0], "text": extracted[1], "date": date, "stamp": stamp})
        response = envelope.get("response")
        extracted = zcode_message(response) if isinstance(response, dict) else None
        if not extracted:
            text = zcode_response_text(response)
            extracted = ("assistant", text) if text else None
        if extracted:
            rows.append({"role": extracted[0], "text": extracted[1], "date": date, "stamp": stamp})
    if not rows:
        return None
    first_user = next((r["text"] for r in rows if r["role"] == "user"), rows[0]["text"])
    title = next((x.strip() for x in first_user.splitlines() if x.strip()), "未命名会话")
    return {"tool": tool, "id": str(sid), "title": title[:160], "date": rows[0]["date"],
            "stamp": rows[0]["stamp"], "source": str(path), "rows": rows, "outputs": []}


def session_from_file(path, tool):
    """Extract human-visible JSONL/JSON messages. Unsupported files become empty."""
    if path.suffix.lower() not in (".jsonl", ".json"):
        return None
    if tool == "ZCode" and path.suffix.lower() == ".jsonl":
        return session_from_zcode(path, tool)
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        fallback = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    items = []
    if path.suffix.lower() == ".jsonl":
        for line in raw.splitlines():
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    else:
        try:
            value = json.loads(raw)
            items = value if isinstance(value, list) else [value]
        except json.JSONDecodeError:
            return None
    # Some desktop clients store a conversation envelope rather than one
    # message per top-level object.  Pull only well-known message collections;
    # do not recursively mine arbitrary settings/cache JSON.
    expanded = []
    for item in items:
        expanded.append(item)
        if isinstance(item, dict):
            for key in ("messages", "chatMessages", "conversation", "history", "entries"):
                value = item.get(key)
                if isinstance(value, list):
                    expanded.extend(x for x in value if isinstance(x, dict))
                elif isinstance(value, dict):
                    nested = value.get("messages")
                    if isinstance(nested, list):
                        expanded.extend(x for x in nested if isinstance(x, dict))
    items = expanded
    rows = []
    title = ""
    sid = path.stem
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "ai-title" and item.get("aiTitle"):
            title = str(item["aiTitle"])
        extracted = extract_message(item)
        if not extracted or item.get("isMeta"):
            continue
        date, stamp = timestamp_of(item, fallback)
        rows.append({"role": extracted[0], "text": extracted[1], "date": date, "stamp": stamp})
        sid = item.get("sessionId") or item.get("session_id") or sid
    rows = dedupe_rows(rows)
    if not rows:
        return None
    first_user = next((r["text"] for r in rows if r["role"] == "user"), rows[0]["text"])
    title = title or next((x.strip() for x in first_user.splitlines() if x.strip()), "未命名会话")
    if tool == "Claude" and path.name.lower() == "audit.jsonl":
        sid = session_container_id(path) or sid
    return {"tool": tool, "id": str(sid), "title": title[:160], "date": rows[0]["date"],
            "stamp": rows[0]["stamp"], "source": str(path), "rows": rows, "outputs": []}


def markdown_output(path, tool):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        date = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
    except OSError:
        return None
    if not text.strip():
        return None
    container = session_container_id(path) if tool == "Claude" else None
    return {"tool": tool, "id": container or ("output:" + str(path)), "title": path.name, "date": date,
            "stamp": date, "source": str(path), "rows": [], "outputs": [{"name": path.name, "text": text}]}


def merge_session_outputs(sessions):
    """Attach outputs/*.md to the matching Cowork conversation card."""
    result = []
    by_key = {}
    for item in sessions:
        key = (item.get("tool"), item.get("id"))
        current = by_key.get(key)
        if current is None:
            by_key[key] = item
            result.append(item)
            continue
        if item.get("rows") and not current.get("rows"):
            current["rows"] = item["rows"]
            current["title"] = item["title"]
            current["date"] = item["date"]
            current["stamp"] = item["stamp"]
            current["source"] = item["source"]
        elif item.get("rows"):
            current["rows"] = dedupe_rows(current.get("rows", []) + item["rows"])
        current.setdefault("outputs", []).extend(item.get("outputs", []))
        # The same conversation can live in more than one user profile; keep
        # every physical source so a merged card can be traced back to each.
        sources = current.setdefault("sources", [])
        for value in (current.get("source"), item.get("source")):
            if value and value not in sources:
                sources.append(value)
        if len(sources) > 1:
            current["source"] = "\n".join(sources)
    return result


def _is_workbuddy_doc(path):
    """Whether a Markdown file is a WorkBuddy journal/report rather than noise.

    WorkBuddy writes memory journals to `.workbuddy\\memory` (and its
    `automations` subfolders) and reports to `automation-*` folders.  The
    enclosing folder must be within two levels of the file: matching anywhere in
    the path instead archives unrelated project documentation that merely sits
    below an `automation-*` directory, such as an SDK's `references/*.md`.
    """
    parent = Path(path).parent
    names = (parent.name, parent.parent.name, parent.parent.parent.name)
    if any(name in ("memory", "brain", "automations") for name in names):
        return True
    return names[0].startswith("automation") or names[1].startswith("automation")


def iter_candidate_files(root, tool, progress=None, cancel=None, on_file=None):
    """Walk one root, yielding (path, size, mtime_ns, is_markdown) candidates.

    A generator so callers can report progress and honour cancellation between
    files.  Cache directories are pruned and oversized files skipped.
    """
    root_key = os.path.normcase(os.path.abspath(str(root)))
    stack = [str(root)]
    while stack:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            if progress and os.path.normcase(os.path.abspath(directory)) == root_key:
                progress(f"无法读取目录：{tool} · {root}（{exc}）")
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in SKIP_DIRS:
                        stack.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat = entry.stat(follow_symlinks=False)
                if stat.st_size > MAX_FILE_SIZE:
                    if progress:
                        progress(f"跳过大文件：{entry.path}（超过 50 MB）")
                    continue
                lower = entry.name.lower()
                if lower.endswith((".jsonl", ".json")):
                    kind = "json"
                elif lower.endswith(".md"):
                    parent = Path(entry.path).parent.name
                    if not (parent == "outputs"
                            or (tool == "WorkBuddy" and _is_workbuddy_doc(entry.path))
                            or (tool == "ZCode" and parent == "reports")
                            or tool == "antigravity"):
                        continue
                    kind = "md"
                else:
                    continue
                if on_file is not None:
                    on_file()
                yield entry.path, stat.st_size, stat.st_mtime_ns, kind == "md"
            except OSError:
                continue


def collect_files(root, tool, progress=None):
    """Single scandir pass with cache-directory pruning; returns
    (json_files, md_files) as (path, size, mtime_ns) tuples."""
    json_files, md_files = [], []
    for path, size, mtime, is_md in iter_candidate_files(root, tool, progress):
        (md_files if is_md else json_files).append((path, size, mtime))
    return json_files, md_files


def scan(tools, custom_dirs=None, progress=None, use_cache=True,
         on_progress=None, cancel=None):
    """Scan every selected source and return merged session records.

    progress  -- callable(str) log lines (unchanged behaviour)
    on_progress -- callable(done, total) file counts for a progress bar
    cancel    -- threading.Event; raises Cancelled between files when set
    """
    sessions, seen = [], set()
    roots = []
    for tool in tools:
        roots.extend((tool, p) for p in AGENTS.get(tool, []))
    for raw in custom_dirs or []:
        roots.append(("自定义", Path(raw)))
    cache = load_cache() if use_cache else {}
    fresh = {}
    existing = [(tool, root) for tool, root in roots if root.exists()]
    if progress:
        progress(f"自动检测到 {len(USER_HOMES)} 个用户数据位置；本次找到 {len(existing)} 个可扫描目录")

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise Cancelled()

    # Count candidates first so the progress bar can show a real percentage.
    # This walk only stats entries, it does not read file contents.
    total = 0
    for tool, root in existing:
        check_cancel()
        for _ in iter_candidate_files(root, tool, cancel=cancel):
            total += 1
    done = 0
    last_report = 0.0

    def tick():
        nonlocal done, last_report
        done += 1
        if on_progress is None:
            return
        now = time.monotonic()
        if done >= total or done % PROGRESS_EVERY == 0 or now - last_report >= PROGRESS_INTERVAL:
            last_report = now
            on_progress(done, total)

    def cached_sessions(key, path, mtime, size, parser):
        """Parse a file unless the mtime/size index says it is unchanged."""
        entry = cache.get(key)
        if entry and entry.get("mtime") == mtime and entry.get("size") == size:
            # Carry the entry over so a fully-warm run still rewrites the
            # index instead of pruning it down to nothing.
            fresh[key] = entry
            return entry.get("sessions") or []
        parsed = parser(Path(path))
        item_list = [parsed] if parsed else []
        fresh[key] = {"mtime": mtime, "size": size, "sessions": item_list}
        return item_list

    for tool, root in existing:
        before = len(sessions)
        count = 0
        for path, size, mtime, is_md in iter_candidate_files(root, tool, progress, cancel, tick):
            count += 1
            check_cancel()
            # A broad preset can contain a more specific preset as a
            # subdirectory. Deduplicate by physical source, not by the
            # session id/stem (different tools often reuse the same id).
            kind = "md" if is_md else "json"
            key = "\x00".join((kind, tool, os.path.normcase(os.path.abspath(path))))
            if key in seen:
                continue
            seen.add(key)
            if is_md:
                parser = lambda p: markdown_output(p, tool)
            else:
                parser = lambda p: session_from_file(p, tool)
            sessions.extend(cached_sessions(key, path, mtime, size, parser))
        if progress:
            progress(f"已扫描：{tool} · 文件 {count} 个，新增记录 {len(sessions) - before} 条")
    if "ZCode" in tools:
        db_files = []
        candidates = [HOME / ".zcode" / "cli" / "db" / "db.sqlite"]
        for root_tool, root in roots:
            if root_tool != "ZCode":
                continue
            parts = [p.lower() for p in root.parts]
            if ".zcode" in parts:
                index = parts.index(".zcode")
                zhome = Path(*root.parts[:index + 1])
                candidates.append(zhome / "cli" / "db" / "db.sqlite")
        for candidate in candidates:
            if candidate.is_file() and candidate not in db_files:
                db_files.append(candidate)
        for db_file in db_files:
            # The database holds the full conversation (user + assistant);
            # rollout files only carry assistant replies. Prefer it on clash.
            db_items = zcode_db_sessions(db_file)
            by_id = {item["id"]: item for item in db_items}
            sessions = [by_id.pop(item["id"], item) for item in sessions] + list(by_id.values())
            if progress:
                progress(f"已扫描：ZCode · {db_file} · 数据库会话 {len(db_items)} 条")
    if use_cache:
        save_cache(fresh)
    sessions = merge_session_outputs(sessions)
    sessions = [s for s in sessions if s.get("rows") or s.get("outputs")]
    sessions.sort(key=lambda x: (x["date"], x["stamp"], x["title"]), reverse=True)
    return sessions


def output_path(folder, tools, custom_dirs=None):
    """Create a non-overwriting HTML filename from the selected sources."""
    folder = Path(folder).expanduser()
    labels = list(tools) + (["自定义"] if custom_dirs else [])
    label = "-".join(labels) or "Agent"
    label = re.sub(r'[<>:"/\\|?*]+', "-", label).strip(" .-") or "Agent"
    if len(label) > 60:
        label = f"{labels[0]}-等{len(labels)}个来源"
    stamp = datetime.now(LOCAL_TZ).strftime("%Y%m%d-%H%M%S")
    candidate = folder / f"{label}_{stamp}.html"
    suffix = 1
    while candidate.exists():
        candidate = folder / f"{label}_{stamp}_{suffix:02d}.html"
        suffix += 1
    return candidate


def esc(value):
    return html.escape(str(value), quote=True)


def render(sessions, output):
    groups = defaultdict(list)
    for item in sessions:
        groups[item["date"]].append(item)
    dates = sorted(groups, reverse=True)
    nav = "".join(f'<a href="#d-{esc(d)}">{esc(d)} <span>{len(groups[d])}</span></a>' for d in dates)
    sections = []
    for date in dates:
        cards = []
        for item in groups[date]:
            messages = "".join(
                f'<div class="msg {r["role"]}"><b>{"用户" if r["role"] == "user" else "Agent"}</b> '
                f'<time>{esc(r["stamp"])}</time><pre>{esc(r["text"])}</pre></div>' for r in item["rows"])
            docs = "".join(f'<details><summary>{esc(o["name"])}</summary><pre>{esc(o["text"])}</pre></details>' for o in item["outputs"])
            if docs:
                docs = f'<div class="outputs"><strong>输出文档</strong>{docs}</div>'
            cards.append(f'''<article class="card"><button class="head"><span><i>{esc(item["tool"])}</i> {esc(item["title"])}</span><small>{esc(item["stamp"])}</small></button>
<div class="body"><div class="source">来源：{esc(item["source"])}</div>{messages}{docs}</div></article>''')
        sections.append(f'<section id="d-{esc(date)}"><h2>{esc(date)} <small>{len(groups[date])} 条</small></h2>{"".join(cards)}</section>')
    doc = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent聊天记录归档</title><style>
:root{{--clay:#D97757;--soft:#F6E3D8;--bg:#F4F1EA;--paper:#FBFAF6;--ink:#2B2A28;--muted:#6B6660;--line:#E4DFD6}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 Arial,"Microsoft YaHei",sans-serif}}.layout{{display:grid;grid-template-columns:230px 1fr;max-width:1500px;margin:auto;min-height:100vh}}aside{{position:sticky;top:0;height:100vh;padding:28px 18px;border-right:1px solid var(--line)}}aside h1{{font:700 26px Georgia,serif;margin:0 0 8px}}aside p,.source,small,time{{color:var(--muted);font-size:12px}}.stat{{background:var(--paper);padding:10px;border:1px solid var(--line);border-radius:8px;margin:14px 0 20px}}.stat b{{font-size:24px;display:block}}nav a{{display:flex;justify-content:space-between;text-decoration:none;color:var(--muted);padding:5px 7px}}nav a:hover{{background:var(--soft)}}main{{padding:42px clamp(18px,5vw,70px)}}h1{{font:700 clamp(34px,5vw,54px)/1.1 Georgia,serif;margin:0 0 14px}}.intro{{background:var(--soft);border-left:4px solid var(--clay);padding:14px 16px;margin-bottom:34px}}section{{margin:34px 0 48px}}h2{{font-size:21px;border-bottom:1px solid var(--line);padding-bottom:8px}}h2 small{{font-weight:400}}.card{{background:var(--paper);border:1px solid var(--line);border-radius:10px;margin:10px 0;overflow:hidden}}button.head{{width:100%;border:0;background:none;padding:14px 16px;text-align:left;display:flex;justify-content:space-between;gap:10px;font:inherit;cursor:pointer}}button.head:hover{{background:#f8f3eb}}button.head i{{font-style:normal;color:var(--clay);font-weight:700;font-size:12px;margin-right:6px}}.body{{display:none;border-top:1px solid var(--line);padding:0 16px 16px}}.body.open{{display:block}}.source{{padding:10px 0;border-bottom:1px dashed var(--line);word-break:break-all;white-space:pre-line}}.msg{{margin-top:14px;padding:12px;border-radius:8px}}.msg.user{{background:#f6eee6;border-left:3px solid var(--clay)}}.msg.assistant{{background:#f0f3ed;border-left:3px solid #7A8B6F}}.msg pre,details pre{{white-space:pre-wrap;word-break:break-word;margin:6px 0 0;font:13px/1.7 Consolas,"Microsoft YaHei",monospace}}.outputs{{margin-top:18px;border-top:2px solid var(--soft);padding-top:12px}}details{{border:1px solid var(--line);border-radius:7px;margin:8px 0;background:white}}summary{{cursor:pointer;padding:9px 11px;font-weight:600}}details pre{{padding:12px;border-top:1px solid var(--line);max-height:700px;overflow:auto}}@media(max-width:750px){{.layout{{display:block}}aside{{position:relative;height:auto;border-right:0;border-bottom:1px solid var(--line)}}main{{padding:26px 14px}}button.head{{display:block}}button.head small{{display:block;margin-top:3px}}}}@media print{{aside{{display:none}}.layout{{display:block}}.body{{display:block!important}}}}
</style></head><body><div class="layout"><aside><h1>Agent<br>归档器</h1><p>本地会话扫描结果<br>生成日期：{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}</p><div class="stat"><b>{len(sessions)}</b>条有内容记录</div><nav>{nav}</nav></aside><main><h1>Agent 聊天记录</h1><div class="intro">已扫描所选工具的本地会话目录，筛选出 <b>{len(sessions)}</b> 条可提取内容；支持按日期浏览、会话折叠和浏览器关键词查找。原始文件未修改。</div>{''.join(sections)}</main></div><script>document.querySelectorAll('.head').forEach(b=>b.onclick=()=>b.nextElementSibling.classList.toggle('open'))</script></body></html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    try:
        tmp.write_text(doc, encoding="utf-8")
        os.replace(tmp, output)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return output


def cli(args):
    tools = args.tools or list(AGENTS)
    sessions = scan(tools, args.custom, print, use_cache=not args.no_cache)
    path = render(sessions, output_path(args.output, tools, args.custom))
    print(json.dumps({"output": str(path), "records": len(sessions)}, ensure_ascii=False))


def load_gui_state():
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_gui_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def set_window_icon(root):
    """Give the window the app icon; harmless if the asset is missing.

    iconbitmap takes the .ico (taskbar and title bar); iconphoto also covers
    non-Windows window managers.  Both are best-effort so a source checkout
    without assets/ still starts.
    """
    try:
        ico = resource_path("assets/icon.ico")
        if ico.exists():
            root.iconbitmap(default=str(ico))
    except Exception:
        pass
    try:
        png = resource_path("assets/icon.png")
        if png.exists() and tk is not None:
            root.iconphoto(True, tk.PhotoImage(file=str(png)))
    except Exception:
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("Agent 聊天记录归档器")
        root.geometry("780x760")
        set_window_icon(root)
        state = load_gui_state()
        checked = set(state.get("tools") or ["Claude"])
        self.vars = {name: tk.BooleanVar(value=name in checked) for name in AGENTS}
        tools_row = ttk.Frame(root); tools_row.pack(fill="x", padx=22, pady=(20, 8))
        ttk.Label(tools_row, text="选择要扫描的 Agent 工具", font=("Microsoft YaHei", 14, "bold")).pack(side="left")
        ttk.Button(tools_row, text="全不选", width=7, command=lambda: self.set_all_tools(False)).pack(side="right")
        ttk.Button(tools_row, text="全选", width=7, command=lambda: self.set_all_tools(True)).pack(side="right", padx=(0, 6))
        box = ttk.Frame(root); box.pack(fill="x", padx=22)
        for index, (name, var) in enumerate(self.vars.items()):
            ttk.Checkbutton(box, text=name, variable=var).grid(row=index // 4, column=index % 4, sticky="w", padx=(0, 18), pady=3)
        ttk.Label(root, text="可选：添加要扫描的自定义文件夹").pack(anchor="w", padx=22, pady=(20, 4))
        self.custom_dirs = [d for d in state.get("custom") or [] if isinstance(d, str)]
        custom_box = ttk.Frame(root); custom_box.pack(fill="x", padx=22)
        self.custom_list = tk.Listbox(custom_box, height=5, activestyle="none")
        self.custom_list.pack(side="left", fill="both", expand=True)
        for folder in self.custom_dirs:
            self.custom_list.insert(tk.END, folder)
        custom_buttons = ttk.Frame(custom_box); custom_buttons.pack(side="left", padx=(10, 0), fill="y")
        ttk.Button(custom_buttons, text="添加文件夹", command=self.add_custom_folder).pack(fill="x", pady=(0, 6))
        ttk.Button(custom_buttons, text="移除选中", command=self.remove_custom_folder).pack(fill="x")
        ttk.Label(root, text="输出文件夹（文件名自动生成）").pack(anchor="w", padx=22, pady=(14, 4))
        output_box = ttk.Frame(root); output_box.pack(fill="x", padx=22)
        self.output = tk.StringVar(value=state.get("output") or str(HOME / "Documents/Codex"))
        ttk.Entry(output_box, textvariable=self.output).pack(side="left", fill="x", expand=True)
        ttk.Button(output_box, text="选择文件夹", command=self.choose_output_folder).pack(side="left", padx=(8, 0))
        options = ttk.Frame(root); options.pack(fill="x", padx=22, pady=(12, 2))
        self.no_cache = tk.BooleanVar(value=bool(state.get("no_cache", False)))
        ttk.Checkbutton(options, text="强制全量重新扫描（忽略缓存）", variable=self.no_cache).pack(side="left")
        detected = "；".join(str(p) for p in USER_HOMES)
        ttk.Label(root, text=f"自动检测的数据位置：{detected}", foreground="#6B6660", wraplength=730).pack(anchor="w", padx=22, pady=(8, 2))
        self.status = tk.StringVar(value="就绪")
        ttk.Label(root, textvariable=self.status, foreground="#6B6660").pack(anchor="w", padx=22, pady=(8, 4))
        self.progress = ttk.Progressbar(root, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=22, pady=(0, 8))
        self.log = tk.Text(root, height=7, wrap="word", font=("Microsoft YaHei", 9), state="disabled")
        self.log.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        actions = ttk.Frame(root); actions.pack(fill="x", padx=22)
        self.start_button = ttk.Button(actions, text="开始扫描并生成 HTML", command=self.start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="取消", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.open_button = ttk.Button(actions, text="打开生成的 HTML", command=self.open_last, state="disabled")
        self.open_button.pack(side="left", padx=(8, 0))
        self.last_path = None
        self.cancel_event = threading.Event()
        ttk.Label(root, text="提示：日志会列出实际扫描路径；如果自动检测不到，也可添加自定义目录。", foreground="#6B6660").pack(anchor="w", padx=22, pady=12)

    def start(self):
        tools = [n for n, v in self.vars.items() if v.get()]
        if not tools and not self.custom_dirs:
            messagebox.showwarning("未选择来源", "请选择至少一个工具或添加自定义文件夹。"); return
        # Snapshot every widget value here, on the main thread: Tk variables must
        # not be read from the worker thread the scan runs in.
        output = self.output.get().strip()
        use_cache = not self.no_cache.get()
        save_gui_state({"tools": tools, "custom": self.custom_dirs[:], "output": output,
                        "no_cache": self.no_cache.get()})
        self.start_button.config(state="disabled")
        self.open_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self.progress.config(value=0)
        self.log.config(state="normal"); self.log.delete("1.0", tk.END); self.log.config(state="disabled")
        self.status.set("扫描中，请稍候……")
        self.cancel_event.clear()
        threading.Thread(target=self.run, args=(tools, self.custom_dirs[:], use_cache, output),
                         daemon=True).start()

    def cancel(self):
        self.cancel_event.set()
        self.status.set("正在取消……")
        self.cancel_button.config(state="disabled")

    def set_all_tools(self, value):
        for var in self.vars.values():
            var.set(value)

    def add_custom_folder(self):
        folder = filedialog.askdirectory(title="选择要扫描的会话文件夹")
        if folder and folder not in self.custom_dirs:
            self.custom_dirs.append(folder)
            self.custom_list.insert(tk.END, folder)

    def choose_output_folder(self):
        folder = filedialog.askdirectory(title="选择 HTML 输出文件夹", initialdir=self.output.get())
        if folder:
            self.output.set(folder)

    def remove_custom_folder(self):
        selected = list(self.custom_list.curselection())
        for index in reversed(selected):
            self.custom_list.delete(index)
            del self.custom_dirs[index]

    def report_progress(self, message):
        self.status.set(message)
        self.log.config(state="normal")
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")

    def open_last(self):
        if self.last_path and Path(self.last_path).is_file():
            webbrowser.open(Path(self.last_path).resolve().as_uri())

    def show_progress(self, done, total):
        percent = (done * 100.0 / total) if total else 0.0
        self.progress.config(value=percent)
        self.status.set(f"扫描中 {done}/{total}（{percent:.0f}%）")

    def finish_run(self):
        """Reset the action buttons once a scan ends, however it ended."""
        self.start_button.config(state="normal")
        self.cancel_button.config(state="disabled")

    def run(self, tools, custom, use_cache, output):
        try:
            sessions = scan(tools, custom, lambda x: self.root.after(0, self.report_progress, x),
                            use_cache=use_cache, cancel=self.cancel_event,
                            on_progress=lambda d, t: self.root.after(0, self.show_progress, d, t))
            path = render(sessions, output_path(output, tools, custom))
        except Cancelled:
            self.root.after(0, lambda: (self.status.set("已取消"), self.progress.config(value=0),
                                        self.finish_run()))
            return
        except Exception as exc:
            message = f"扫描或生成失败：{exc}"
            self.root.after(0, lambda: (self.status.set("失败"), messagebox.showerror("失败", message),
                                        self.finish_run()))
            return
        if sessions:
            detail = f"已生成：\n{path}"
        else:
            detail = ("没有扫描到可提取的内容。\n可尝试勾选其他工具，或用“添加自定义文件夹”指向实际的会话目录。\n\n已生成空归档：\n" + str(path))
        def finish():
            self.last_path = path
            self.progress.config(value=100)
            self.status.set(f"完成：{len(sessions)} 条记录")
            self.open_button.config(state="normal")
            messagebox.showinfo("完成", detail)
            self.finish_run()
        self.root.after(0, finish)


def main():
    parser = argparse.ArgumentParser(description="扫描本机 Agent 会话并生成 HTML 归档")
    parser.add_argument("--tool", dest="tools", action="append", choices=list(AGENTS), help="要扫描的工具，可重复")
    parser.add_argument("--custom", action="append", default=[], help="自定义会话目录，可重复")
    parser.add_argument("--output", default=str(HOME / "Documents/Codex"), help="HTML 输出文件夹；文件名自动按工具和生成时间命名")
    parser.add_argument("--cli", action="store_true", help="命令行模式；不启动 GUI")
    parser.add_argument("--no-cache", action="store_true", help="不使用/不更新扫描缓存索引，强制重新解析全部文件")
    args = parser.parse_args()
    if args.cli or tk is None:
        cli(args)
    else:
        root = tk.Tk(); App(root); root.mainloop()


if __name__ == "__main__":
    main()
