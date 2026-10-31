"""Everything we downloaded, in one SQLite file: channels, files and a search index."""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from itertools import islice

from .paths import folder_state
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    title TEXT NOT NULL,
    about TEXT DEFAULT '',
    members INTEGER DEFAULT 0,
    photo TEXT DEFAULT '',
    folder TEXT NOT NULL,
    kinds TEXT NOT NULL,
    year_folders INTEGER DEFAULT 1,
    smart_names INTEGER DEFAULT 1,
    auto_update INTEGER DEFAULT 0,
    last_scanned_id INTEGER DEFAULT 0,
    added_at TEXT NOT NULL,
    last_sync TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS files (
    channel_id INTEGER NOT NULL,
    msg_id INTEGER NOT NULL,
    doc_id INTEGER DEFAULT 0,
    kind TEXT DEFAULT '',
    name TEXT DEFAULT '',
    path TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    mime TEXT DEFAULT '',
    date TEXT DEFAULT '',
    caption TEXT DEFAULT '',
    status TEXT NOT NULL,
    note TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    PRIMARY KEY (channel_id, msg_id)
);
CREATE INDEX IF NOT EXISTS files_doc ON files(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(name, caption, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shelves (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shelf_files (
    shelf_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    msg_id INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (shelf_id, channel_id, msg_id)
);
"""
FAVORITES = 1  # the shelf every library has; the interface names it «المفضلة»
INDEX_NAME = "فهرس تجميعة.csv"

# Columns added after the first release; older libraries get them on open.
ADDED_COLUMNS = {
    "files": {"sha256": "TEXT DEFAULT ''", "topic": "TEXT DEFAULT ''"},
    "channels": {
        "topic_folders": "INTEGER DEFAULT 0",
        # Private channels have no username; Telegram finds them by id and this per-account hash.
        "access_hash": "INTEGER DEFAULT 0",
        "is_group": "INTEGER DEFAULT 0",
        "filter_since": "TEXT DEFAULT ''",
        "filter_until": "TEXT DEFAULT ''",
        "filter_words": "TEXT DEFAULT ''",
        "filter_max_mb": "INTEGER DEFAULT 0",
        "skip_exts": "TEXT DEFAULT '[]'",
        # A download that hasn't finished: 1, or 2 when it was also bringing deleted files back.
        "pending": "INTEGER DEFAULT 0",
    },
}

_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def fold(text: str) -> str:
    """Make Arabic search forgiving: أ/ا/إ, ة/ه, ى/ي and diacritics all match each other."""
    return _DIACRITICS.sub("", (text or "").lower()).translate(_FOLD).translate(_DIGITS)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Library:
    def __init__(self, path: Path):
        self.path = path
        self.recovered_from: Optional[Path] = None
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.db = self._open()
        except sqlite3.DatabaseError:
            # A damaged file must never stop the app from opening: set it aside and start clean.
            self.recovered_from = path.with_name(f"{path.name}.damaged-{int(time.time())}")
            path.rename(self.recovered_from)
            self.db = self._open()

    def _open(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.executescript(SCHEMA)
        for table, columns in ADDED_COLUMNS.items():
            existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for column, kind in columns.items():
                if column not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        db.execute("CREATE INDEX IF NOT EXISTS files_sha ON files(sha256)")
        db.execute("INSERT OR IGNORE INTO shelves (id, name, created_at) VALUES (?, '', ?)", (FAVORITES, now_iso()))
        db.execute("SELECT count(*) FROM channels").fetchone()
        return db

    # Settings

    def setting(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))

    def close(self) -> None:
        self.db.close()

    # Channels

    def save_channel(self, info: Dict[str, Any], options: Dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO channels (id, username, title, about, members, photo, folder, kinds,
                   year_folders, topic_folders, smart_names, auto_update, added_at, access_hash, is_group,
                   filter_since, filter_until, filter_words, filter_max_mb, skip_exts)
               VALUES (:id, :username, :title, :about, :members, :photo, :folder, :kinds,
                   :year_folders, :topic_folders, :smart_names, :auto_update, :added_at, :access_hash, :is_group,
                   :filter_since, :filter_until, :filter_words, :filter_max_mb, :skip_exts)
               ON CONFLICT(id) DO UPDATE SET username=excluded.username, title=excluded.title,
                   about=excluded.about, members=excluded.members, photo=excluded.photo,
                   folder=excluded.folder, kinds=excluded.kinds, year_folders=excluded.year_folders,
                   topic_folders=excluded.topic_folders, smart_names=excluded.smart_names,
                   auto_update=excluded.auto_update, access_hash=excluded.access_hash, is_group=excluded.is_group,
                   filter_since=excluded.filter_since, filter_until=excluded.filter_until,
                   filter_words=excluded.filter_words, filter_max_mb=excluded.filter_max_mb,
                   skip_exts=excluded.skip_exts""",
            {
                **_filter_columns(options.get("filters") or {}),
                "access_hash": int(info.get("accessHash") or 0),
                "skip_exts": json.dumps(sorted({str(e).lower() for e in options.get("skipExts") or []})),
                "is_group": int(bool(info.get("group", False))),
                "id": info["id"],
                "username": info["username"],
                "title": info["title"],
                "about": info.get("about", ""),
                "members": info.get("members", 0),
                "photo": info.get("photo", ""),
                "folder": str(options["folder"]),
                "kinds": json.dumps(sorted(options["kinds"])),
                "year_folders": int(bool(options.get("yearFolders", True))),
                "topic_folders": int(bool(options.get("topicFolders", False))),
                "smart_names": int(bool(options.get("smartNames", True))),
                "auto_update": int(bool(options.get("autoUpdate", False))),
                "added_at": now_iso(),
            },
        )

    def channel(self, channel_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
        return self._channel_dict(row) if row else None

    def channels(self) -> List[Dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM channels ORDER BY added_at").fetchall()
        return [self._channel_dict(row) for row in rows]

    def _channel_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        stats = self.db.execute(
            "SELECT count(*) AS n, coalesce(sum(size), 0) AS bytes FROM files WHERE channel_id=? AND status='done'",
            (row["id"],),
        ).fetchone()
        failed = self.db.execute(
            "SELECT count(*) FROM files WHERE channel_id=? AND status='failed'", (row["id"],)
        ).fetchone()[0]
        return {
            "accessHash": row["access_hash"],
            "group": bool(row["is_group"]),
            "private": not row["username"],
            "filters": {"since": row["filter_since"], "until": row["filter_until"], "words": row["filter_words"],
                        "maxMb": row["filter_max_mb"]},
            "topicFolders": bool(row["topic_folders"]),
            "skipExts": json.loads(row["skip_exts"] or "[]"),
            "pending": row["pending"],
            "folderState": folder_state(row["folder"]),
            "missing": len(self.missing_ids(row["id"])),
            "id": row["id"],
            "username": row["username"],
            "title": row["title"],
            "about": row["about"],
            "members": row["members"],
            "photo": row["photo"],
            "folder": row["folder"],
            "kinds": json.loads(row["kinds"]),
            "yearFolders": bool(row["year_folders"]),
            "smartNames": bool(row["smart_names"]),
            "autoUpdate": bool(row["auto_update"]),
            "lastScannedId": row["last_scanned_id"],
            "addedAt": row["added_at"],
            "lastSync": row["last_sync"],
            "files": stats["n"],
            "bytes": stats["bytes"],
            "failed": failed,
        }

    def set_option(self, channel_id: int, column: str, value: Any) -> None:
        allowed = {"auto_update", "year_folders", "topic_folders", "smart_names", "folder"}
        if column not in allowed:
            raise ValueError(column)
        self.db.execute(f"UPDATE channels SET {column}=? WHERE id=?", (value, channel_id))

    def set_pending(self, channel_id: int, value: int) -> None:
        self.db.execute("UPDATE channels SET pending=? WHERE id=?", (value, channel_id))

    def relink(self, channel_id: int, new_folder: Path) -> Dict[str, Any]:
        """The person moved the channel's folder: point every saved file at its new place.
        Nothing changes when none of the files are there."""
        old = Path(self.db.execute("SELECT folder FROM channels WHERE id=?", (channel_id,)).fetchone()["folder"])
        paths = [row["path"] for row in self.db.execute(
            "SELECT path FROM files WHERE channel_id=? AND status='done' AND path != ''", (channel_id,))]

        def found_in(base: Path) -> Dict[str, str]:
            moves = {}
            for path in paths:
                try:
                    candidate = base / Path(path).relative_to(old)
                except ValueError:
                    continue
                if candidate.is_file():
                    moves[path] = str(candidate)
            return moves

        moves = found_in(new_folder)
        if not moves and (new_folder / old.name).is_dir():  # they picked the folder that holds it
            new_folder = new_folder / old.name
            moves = found_in(new_folder)
        if paths and not moves:
            return {"found": 0, "total": len(paths), "folder": str(new_folder)}
        with self._tx():
            # Every row that points at a moved file, other channels' "same file" rows included.
            self.db.executemany("UPDATE files SET path=? WHERE path=?", [(new, was) for was, new in moves.items()])
            self.db.execute("UPDATE channels SET folder=? WHERE id=?", (str(new_folder), channel_id))
        return {"found": len(moves), "total": len(paths), "folder": str(new_folder)}

    def set_filters(self, channel_id: int, filters: Dict[str, Any]) -> None:
        """New filters apply to the whole channel, so the next update looks through all of it again."""
        columns = _filter_columns(filters)
        self.db.execute(
            "UPDATE channels SET filter_since=:filter_since, filter_until=:filter_until, filter_words=:filter_words, "
            "filter_max_mb=:filter_max_mb, last_scanned_id=0 WHERE id=:id",
            {**columns, "id": channel_id},
        )

    def mark_synced(self, channel_id: int, last_scanned_id: int) -> None:
        self.db.execute(
            "UPDATE channels SET last_scanned_id=max(last_scanned_id, ?), last_sync=? WHERE id=?",
            (last_scanned_id, now_iso(), channel_id),
        )

    def files_only_here(self, channel_id: int) -> Tuple[List[str], int]:
        """Saved files of this channel, minus the ones another channel counts as its copy too.
        Returns (paths still on disk, how many were kept for other channels)."""
        rows = self.db.execute(
            "SELECT path, EXISTS (SELECT 1 FROM files o WHERE o.path = f.path AND o.channel_id != f.channel_id) AS shared "
            "FROM files f WHERE f.channel_id=? AND f.status='done' AND f.path != ''",
            (channel_id,),
        ).fetchall()
        mine = [row["path"] for row in rows if not row["shared"] and Path(row["path"]).is_file()]
        return mine, sum(1 for row in rows if row["shared"])

    def remove_channel(self, channel_id: int) -> None:
        with self._tx():
            self.db.execute(
                "DELETE FROM files_fts WHERE rowid IN (SELECT rowid FROM files WHERE channel_id=?)", (channel_id,)
            )
            self.db.execute("DELETE FROM files WHERE channel_id=?", (channel_id,))
            self.db.execute("DELETE FROM shelf_files WHERE channel_id=?", (channel_id,))
            self.db.execute("DELETE FROM channels WHERE id=?", (channel_id,))

    # Files

    def file(self, channel_id: int, msg_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.execute("SELECT * FROM files WHERE channel_id=? AND msg_id=?", (channel_id, msg_id)).fetchone()
        return dict(row) if row else None

    def done_copy_of(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Any finished copy of the same Telegram document that is still on disk."""
        if not doc_id:
            return None
        for row in self.db.execute("SELECT * FROM files WHERE doc_id=? AND status='done'", (doc_id,)):
            if row["path"] and Path(row["path"]).exists():
                return dict(row)
        return None

    def path_known(self, path: str) -> bool:
        """True when some saved file in the library is at this path."""
        return self.db.execute(
            "SELECT 1 FROM files WHERE path=? AND status IN ('done', 'duplicate') LIMIT 1", (path,)
        ).fetchone() is not None

    def done_copy_by_hash(self, sha256: str) -> Optional[Dict[str, Any]]:
        """A finished file with exactly the same content, still on disk (same file posted twice)."""
        if not sha256:
            return None
        for row in self.db.execute("SELECT * FROM files WHERE sha256=? AND status='done'", (sha256,)):
            if row["path"] and Path(row["path"]).exists():
                return dict(row)
        return None

    def record(self, **fields: Any) -> None:
        fields.setdefault("note", "")
        fields["updated_at"] = now_iso()
        columns = list(fields)
        with self._tx():
            self.db.execute(
                f"INSERT INTO files ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)}) "
                f"ON CONFLICT(channel_id, msg_id) DO UPDATE SET "
                + ", ".join(f"{c}=excluded.{c}" for c in columns if c not in ("channel_id", "msg_id")),
                fields,
            )
            rowid = self.db.execute(
                "SELECT rowid FROM files WHERE channel_id=? AND msg_id=?", (fields["channel_id"], fields["msg_id"])
            ).fetchone()[0]
            self.db.execute("DELETE FROM files_fts WHERE rowid=?", (rowid,))
            if fields.get("status") == "done":
                self.db.execute(
                    "INSERT INTO files_fts (rowid, name, caption) VALUES (?, ?, ?)",
                    (rowid, fold(fields.get("name", "")), fold(fields.get("caption", ""))),
                )

    def missing_ids(self, channel_id: int) -> List[int]:
        """Files we downloaded that are no longer where we put them (the person deleted or moved them).
        When the whole folder is away (moved, or on a drive that isn't plugged in), nothing counts as
        deleted: offering to download it all again would only make copies."""
        row = self.db.execute("SELECT folder FROM channels WHERE id=?", (channel_id,)).fetchone()
        if row and folder_state(row["folder"])["state"] != "ok":
            return []
        return [
            row["msg_id"]
            for row in self.db.execute("SELECT msg_id, path FROM files WHERE channel_id=? AND status='done'", (channel_id,))
            if not (row["path"] and Path(row["path"]).exists())
        ]

    def ids_to_retry(self, channel_id: int, restore_missing: bool = False) -> List[int]:
        """Failed files always get another try; deleted ones only when the person asks for them back."""
        ids = [row[0] for row in self.db.execute(
            "SELECT msg_id FROM files WHERE channel_id=? AND status='failed'", (channel_id,))]
        if restore_missing:
            ids += self.missing_ids(channel_id)
        return ids

    def remove_file(self, channel_id: int, msg_id: int) -> Optional[Dict[str, Any]]:
        """The person took this file out of the library: it leaves search, shelves and Favorites, and no
        update downloads it again. The row keeps its path and shelves for trashed() and «Put Back»."""
        row = self.db.execute(
            "SELECT rowid, * FROM files WHERE channel_id=? AND msg_id=? AND status='done'", (channel_id, msg_id)
        ).fetchone()
        if row is None:
            return None
        with self._tx():
            self.db.execute("UPDATE files SET status='removed', updated_at=? WHERE rowid=?", (now_iso(), row["rowid"]))
            self.db.execute("DELETE FROM files_fts WHERE rowid=?", (row["rowid"],))
        return dict(row)

    def trashed(self, channel_id: int, msg_id: int, moved: bool) -> None:
        """After the Mac app tried the Trash. A file it moved comes back by itself when it is put back;
        one it couldn't move (open in another app) is still in its place, so it stays in the library."""
        row = self.db.execute(
            "SELECT rowid, * FROM files WHERE channel_id=? AND msg_id=? AND status='removed'", (channel_id, msg_id)
        ).fetchone()
        if row is None:
            return
        if moved:
            self.db.execute("UPDATE files SET status='trashed' WHERE rowid=?", (row["rowid"],))
        else:
            self._restore(row)

    def _restore(self, row: sqlite3.Row) -> None:
        with self._tx():
            self.db.execute("UPDATE files SET status='done' WHERE rowid=?", (row["rowid"],))
            self.db.execute("INSERT INTO files_fts (rowid, name, caption) VALUES (?, ?, ?)",
                            (row["rowid"], fold(row["name"]), fold(row["caption"])))

    def _bring_back(self) -> None:
        """A trashed file that is in its place again was put back from the Trash: it is saved again. Same size,
        and no other saved file at that path, so a new file that took its name isn't mistaken for it."""
        for row in self.db.execute("SELECT rowid, * FROM files WHERE status='trashed' AND path != ''").fetchall():
            path = Path(row["path"])
            if not path.is_file() or path.stat().st_size != row["size"]:
                continue
            if not self.db.execute("SELECT 1 FROM files WHERE path=? AND status='done'", (row["path"],)).fetchone():
                self._restore(row)

    def _visible(self, rows: Iterable[sqlite3.Row]) -> Iterator[sqlite3.Row]:
        """Leaves out saved files the person deleted in Finder. When a channel's whole folder is away (moved, or
        on a drive that isn't plugged in) its files stay listed, the same way missing_ids doesn't count them."""
        away: Dict[int, bool] = {}
        for row in rows:
            if row["status"] != "done" or (row["path"] and Path(row["path"]).exists()):
                yield row
                continue
            channel_id = row["channel_id"]
            if channel_id not in away:
                folder = self.db.execute("SELECT folder FROM channels WHERE id=?", (channel_id,)).fetchone()
                away[channel_id] = folder is not None and folder_state(folder["folder"])["state"] != "ok"
            if away[channel_id]:
                yield row

    def recent_files(self, channel_id: int, limit: int = 30) -> List[Dict[str, Any]]:
        self._bring_back()
        rows = self.db.execute(
            "SELECT * FROM files WHERE channel_id=? AND status NOT IN ('removed', 'trashed') "
            "ORDER BY updated_at DESC, msg_id DESC",
            (channel_id,),
        ).fetchall()
        return self._with_shelves([self._file_dict(row) for row in islice(self._visible(rows), limit)])

    def _file_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "channelId": row["channel_id"],
            "msgId": row["msg_id"],
            "kind": row["kind"],
            "name": row["name"],
            "path": row["path"],
            "size": row["size"],
            "date": row["date"],
            "caption": row["caption"],
            "status": row["status"],
            "note": row["note"],
            "topic": row["topic"],
        }

    def search(self, query: str, channel_id: Optional[int] = None, topic: Optional[str] = None,
               limit: int = 60) -> List[Dict[str, Any]]:
        """Search names and captions; a topic on its own lists that topic's newest files."""
        tokens = [t for t in re.split(r"\s+", fold(query)) if t]
        if not tokens and not topic:
            return []
        self._bring_back()
        args: List[Any] = []
        if tokens:
            sql = (
                "SELECT f.*, c.title AS channel_title, c.username AS channel_username, "
                "files_fts.name AS folded_name FROM files_fts "
                "JOIN files f ON f.rowid = files_fts.rowid JOIN channels c ON c.id = f.channel_id "
                "WHERE files_fts MATCH ? AND f.status='done'"
            )
            args.append(" ".join('"' + t.replace('"', "") + '"*' for t in tokens))
        else:
            sql = (
                "SELECT f.*, c.title AS channel_title, c.username AS channel_username, '' AS folded_name "
                "FROM files f JOIN channels c ON c.id = f.channel_id WHERE f.status='done'"
            )
        if channel_id:
            sql += " AND f.channel_id=?"
            args.append(channel_id)
        if topic:
            sql += " AND f.topic=?"
            args.append(topic)
        sql += " ORDER BY bm25(files_fts, 3.0, 1.0)" if tokens else " ORDER BY f.date DESC"
        results = []
        for row in islice(self._visible(self.db.execute(sql, args).fetchall()), limit):
            item = self._file_dict(row)
            item["channelTitle"] = row["channel_title"]
            item["link"] = post_link(row["channel_username"], row["channel_id"], row["msg_id"])
            item["matchedIn"] = "name" if all(t in row["folded_name"] for t in tokens) else "caption"
            results.append(item)
        return self._with_shelves(results)

    def topics(self, limit: int = 16) -> List[Dict[str, Any]]:
        rows = self.db.execute(
            "SELECT topic, count(*) AS n FROM files WHERE status='done' AND topic != '' "
            "GROUP BY topic ORDER BY n DESC, topic LIMIT ?",
            (limit,),
        )
        return [{"topic": row["topic"], "files": row["n"]} for row in rows]

    def done_files(self, kinds: Iterable[str], limit: int) -> List[Dict[str, Any]]:
        kinds = list(kinds)
        marks = ",".join("?" * len(kinds))
        rows = self.db.execute(
            f"SELECT * FROM files WHERE status='done' AND kind IN ({marks}) ORDER BY updated_at DESC LIMIT ?",
            (*kinds, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def channels_with_files(self) -> List[int]:
        return [row[0] for row in self.db.execute("SELECT DISTINCT channel_id FROM files WHERE status='done'")]

    def files_for_sections(self, channel_id: int) -> List[Tuple[int, str, str]]:
        rows = self.db.execute(
            "SELECT msg_id, name, caption FROM files WHERE channel_id=? AND status='done'", (channel_id,)
        )
        return [(row["msg_id"], row["name"], row["caption"]) for row in rows]

    def set_topics(self, channel_id: int, topics: Dict[int, str]) -> None:
        with self._tx():
            self.db.executemany(
                "UPDATE files SET topic=? WHERE channel_id=? AND msg_id=?",
                [(topic, channel_id, msg_id) for msg_id, topic in topics.items()],
            )

    def totals(self) -> Dict[str, int]:
        row = self.db.execute(
            "SELECT count(*) AS n, coalesce(sum(size), 0) AS bytes FROM files WHERE status='done'"
        ).fetchone()
        channels = self.db.execute("SELECT count(*) FROM channels").fetchone()[0]
        return {"files": row["n"], "bytes": row["bytes"], "channels": channels}

    def export_index(self, channel_id: int, folder: Path) -> Optional[Path]:
        """A spreadsheet-friendly index next to the files, for people who live in Excel."""
        rows = self.db.execute(
            "SELECT f.*, c.username FROM files f JOIN channels c ON c.id=f.channel_id "
            "WHERE f.channel_id=? AND f.status='done' ORDER BY f.msg_id",
            (channel_id,),
        ).fetchall()
        target = folder / INDEX_NAME
        try:
            folder.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name("." + target.name + ".part")
            with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["الاسم", "التاريخ", "الحجم", "النوع", "رابط المنشور", "الوصف", "المسار"])
                for row in rows:
                    writer.writerow(
                        [
                            row["name"],
                            row["date"][:10],
                            row["size"],
                            row["kind"],
                            post_link(row["username"], row["channel_id"], row["msg_id"]),
                            (row["caption"] or "").replace("\n", " ")[:500],
                            row["path"],
                        ]
                    )
            tmp.replace(target)
            return target
        except OSError:
            return None

    # Shelves you make yourself (and Favorites); they point at files, nothing is copied

    def shelves(self) -> List[Dict[str, Any]]:
        self._bring_back()
        counts = Counter(row["shelf_id"] for row in self._visible(self.db.execute(
            "SELECT sf.shelf_id, f.channel_id, f.path, f.status FROM shelf_files sf "
            "JOIN files f ON f.channel_id = sf.channel_id AND f.msg_id = sf.msg_id AND f.status='done'"
        ).fetchall()))
        rows = self.db.execute("SELECT id, name FROM shelves ORDER BY id != ?, created_at, id", (FAVORITES,))
        return [{"id": row["id"], "name": row["name"], "files": counts[row["id"]], "favorites": row["id"] == FAVORITES}
                for row in rows]

    def shelf(self, shelf_id: int) -> Optional[Dict[str, Any]]:
        return next((s for s in self.shelves() if s["id"] == shelf_id), None)

    def create_shelf(self, name: str) -> int:
        cursor = self.db.execute("INSERT INTO shelves (name, created_at) VALUES (?, ?)", (name, now_iso()))
        return int(cursor.lastrowid)

    def rename_shelf(self, shelf_id: int, name: str) -> None:
        self.db.execute("UPDATE shelves SET name=? WHERE id=? AND id != ?", (name, shelf_id, FAVORITES))

    def delete_shelf(self, shelf_id: int) -> None:
        if shelf_id == FAVORITES:
            return
        with self._tx():
            self.db.execute("DELETE FROM shelf_files WHERE shelf_id=?", (shelf_id,))
            self.db.execute("DELETE FROM shelves WHERE id=?", (shelf_id,))

    def put_on_shelf(self, shelf_id: int, channel_id: int, msg_id: int, on: bool) -> None:
        if on:
            self.db.execute(
                "INSERT OR IGNORE INTO shelf_files (shelf_id, channel_id, msg_id, added_at) VALUES (?, ?, ?, ?)",
                (shelf_id, channel_id, msg_id, now_iso()),
            )
        else:
            self.db.execute("DELETE FROM shelf_files WHERE shelf_id=? AND channel_id=? AND msg_id=?",
                            (shelf_id, channel_id, msg_id))

    def shelf_files(self, shelf_id: int) -> List[Dict[str, Any]]:
        self._bring_back()
        rows = self.db.execute(
            "SELECT f.*, c.title AS channel_title, c.username AS channel_username FROM shelf_files sf "
            "JOIN files f ON f.channel_id = sf.channel_id AND f.msg_id = sf.msg_id AND f.status='done' "
            "JOIN channels c ON c.id = f.channel_id WHERE sf.shelf_id=? ORDER BY sf.added_at DESC, sf.rowid DESC",
            (shelf_id,),
        ).fetchall()
        items = []
        for row in self._visible(rows):
            item = self._file_dict(row)
            item["channelTitle"] = row["channel_title"]
            item["link"] = post_link(row["channel_username"], row["channel_id"], row["msg_id"])
            items.append(item)
        return self._with_shelves(items)

    def _with_shelves(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        on: Dict[Tuple[int, int], List[int]] = {}
        for row in self.db.execute("SELECT shelf_id, channel_id, msg_id FROM shelf_files"):
            on.setdefault((row["channel_id"], row["msg_id"]), []).append(row["shelf_id"])
        for item in items:
            item["shelves"] = sorted(on.get((item["channelId"], item["msgId"]), []))
        return items

    # Helpers

    class _Tx:
        def __init__(self, db: sqlite3.Connection):
            self.db = db

        def __enter__(self) -> None:
            self.db.execute("BEGIN")

        def __exit__(self, exc_type: Any, *_: Any) -> None:
            self.db.execute("ROLLBACK" if exc_type else "COMMIT")

    def _tx(self) -> "Library._Tx":
        return Library._Tx(self.db)


def post_link(username: str, channel_id: int, msg_id: int) -> str:
    """Public channels link by name; private ones by id, which opens for members only."""
    return f"https://t.me/{username}/{msg_id}" if username else f"https://t.me/c/{channel_id}/{msg_id}"


def _filter_columns(filters: Dict[str, Any]) -> Dict[str, Any]:
    def day(value: Any) -> str:
        value = str(value or "")[:10]
        return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else ""

    try:
        max_mb = max(0, int(float(filters.get("maxMb") or 0)))
    except (TypeError, ValueError):
        max_mb = 0
    return {
        "filter_since": day(filters.get("since")),
        "filter_until": day(filters.get("until")),
        "filter_words": " ".join(str(filters.get("words") or "").split())[:200],
        "filter_max_mb": max_mb,
    }


def chunked(items: Iterable[int], size: int) -> Iterable[List[int]]:
    batch: List[int] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
