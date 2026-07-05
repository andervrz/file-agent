# app/data_layer.py
"""Custom SQLite DataLayer for Chainlit — fixes phantom parentId bug."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite
from chainlit.data import BaseDataLayer
from chainlit.element import ElementDict
from chainlit.step import StepDict
from chainlit.types import (
    Feedback,
    PageInfo,
    PaginatedResponse,
    Pagination,
    ThreadDict,
    ThreadFilter,
)
from chainlit.user import PersistedUser, User

logger = logging.getLogger(__name__)

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL UNIQUE,
    metadata TEXT NOT NULL,
    createdAt TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    createdAt TEXT,
    name TEXT,
    userId TEXT,
    userIdentifier TEXT,
    tags TEXT,
    metadata TEXT,
    FOREIGN KEY (userId) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    threadId TEXT NOT NULL,
    parentId TEXT,
    streaming INTEGER NOT NULL DEFAULT 0,
    waitForAnswer INTEGER,
    isError INTEGER,
    metadata TEXT,
    tags TEXT,
    input TEXT,
    output TEXT,
    createdAt TEXT,
    command TEXT,
    start TEXT,
    end TEXT,
    generation TEXT,
    showInput TEXT,
    language TEXT,
    indent INTEGER,
    defaultOpen INTEGER,
    modes TEXT,
    disableFeedback INTEGER,
    FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS elements (
    id TEXT PRIMARY KEY,
    threadId TEXT,
    type TEXT,
    url TEXT,
    chainlitKey TEXT,
    name TEXT NOT NULL,
    display TEXT,
    objectKey TEXT,
    size TEXT,
    page INTEGER,
    language TEXT,
    forId TEXT,
    mime TEXT,
    props TEXT,
    FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedbacks (
    id TEXT PRIMARY KEY,
    forId TEXT NOT NULL,
    threadId TEXT NOT NULL,
    value INTEGER NOT NULL,
    comment TEXT,
    FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
);
"""


class SQLiteDataLayer(BaseDataLayer):
    def __init__(self, db_path: str | Path):
        self.db_path = str(Path(db_path))
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.executescript(_SCHEMA)
            await self._conn.commit()
        return self._conn

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ---------- Users ----------
    async def get_user(self, identifier: str) -> Optional[PersistedUser]:
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT id, identifier, metadata, createdAt FROM users WHERE identifier = ?",
            (identifier,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return PersistedUser(
                    id=row["id"],
                    identifier=row["identifier"],
                    createdAt=row["createdAt"],
                    metadata=json.loads(row["metadata"]),
                )
        return None

    async def create_user(self, user: User) -> Optional[PersistedUser]:
        conn = await self._get_conn()
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        meta = json.dumps(user.metadata) if user.metadata else "{}"
        await conn.execute(
            "INSERT OR REPLACE INTO users (id, identifier, metadata, createdAt) VALUES (?, ?, ?, ?)",
            (user_id, user.identifier, meta, now),
        )
        await conn.commit()
        return PersistedUser(
            id=user_id, identifier=user.identifier, createdAt=now, metadata=user.metadata or {}
        )

    # ---------- Threads ----------
    async def get_thread(self, thread_id: str) -> Optional[ThreadDict]:
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT id, createdAt, name, userId, userIdentifier, tags, metadata "
            "FROM threads WHERE id = ?", (thread_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None

            thread: ThreadDict = {
                "id": row["id"],
                "createdAt": row["createdAt"],
                "name": row["name"],
                "userId": row["userId"],
                "userIdentifier": row["userIdentifier"],
                "tags": json.loads(row["tags"]) if row["tags"] else [],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                "steps": [],
            }

        async with conn.execute(
            "SELECT * FROM steps WHERE threadId = ? ORDER BY createdAt ASC", (thread_id,)
        ) as cur:
            rows = await cur.fetchall()
            thread["steps"] = [self._row_to_step(r) for r in rows]

        return thread

    async def update_thread(
        self,
        thread_id: str,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """
            INSERT INTO threads (id, createdAt, name, userId, metadata, tags)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=COALESCE(excluded.name, threads.name),
                userId=COALESCE(excluded.userId, threads.userId),
                metadata=COALESCE(excluded.metadata, threads.metadata),
                tags=COALESCE(excluded.tags, threads.tags)
            """,
            (
                thread_id, now, name, user_id,
                json.dumps(metadata) if metadata else None,
                json.dumps(tags) if tags else None,
            ),
        )
        await conn.commit()

    async def delete_thread(self, thread_id: str) -> None:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        await conn.commit()

    async def get_thread_author(self, thread_id: str) -> str:
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT userId FROM threads WHERE id = ?", (thread_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["userId"] if row else ""

    async def list_threads(
        self, pagination: Pagination, filters: ThreadFilter
    ) -> PaginatedResponse[ThreadDict]:
        conn = await self._get_conn()
        user_id = getattr(filters, "userId", None) if filters else None

        if user_id:
            sql = (
                "SELECT id, createdAt, name, userId, userIdentifier, tags, metadata "
                "FROM threads WHERE userId = ? ORDER BY createdAt DESC LIMIT ?"
            )
            params = (user_id, pagination.first or 50)
        else:
            sql = (
                "SELECT id, createdAt, name, userId, userIdentifier, tags, metadata "
                "FROM threads ORDER BY createdAt DESC LIMIT ?"
            )
            params = (pagination.first or 50,)

        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()

        data: List[ThreadDict] = []
        for row in rows:
            data.append(
                {
                    "id": row["id"],
                    "createdAt": row["createdAt"],
                    "name": row["name"],
                    "userId": row["userId"],
                    "userIdentifier": row["userIdentifier"],
                    "tags": json.loads(row["tags"]) if row["tags"] else [],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "steps": [],
                }
            )

        return PaginatedResponse(
            data=data,
            pageInfo=PageInfo(hasNextPage=False, startCursor=None, endCursor=None),
        )

    # ---------- Steps (FIX) ----------
    def _row_to_step(self, row: aiosqlite.Row) -> StepDict:
        return {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "threadId": row["threadId"],
            "parentId": row["parentId"],
            "streaming": bool(row["streaming"]),
            "waitForAnswer": bool(row["waitForAnswer"]) if row["waitForAnswer"] is not None else None,
            "isError": bool(row["isError"]) if row["isError"] is not None else None,
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "input": row["input"],
            "output": row["output"],
            "createdAt": row["createdAt"],
            "command": row["command"],
            "start": row["start"],
            "end": row["end"],
            "generation": json.loads(row["generation"]) if row["generation"] else None,
            "showInput": row["showInput"],
            "language": row["language"],
            "indent": row["indent"],
            "defaultOpen": bool(row["defaultOpen"]) if row["defaultOpen"] is not None else None,
            "modes": json.loads(row["modes"]) if row["modes"] else None,
            "disableFeedback": bool(row["disableFeedback"]) if row["disableFeedback"] is not None else False,
        }

    async def _fix_parent_id(self, conn: aiosqlite.Connection, step_dict: StepDict) -> StepDict:
        """Si parentId no existe en DB, lo setea a NULL para evitar crash frontend."""
        parent_id = step_dict.get("parentId")
        if not parent_id:
            return step_dict
        async with conn.execute("SELECT 1 FROM steps WHERE id = ?", (parent_id,)) as cur:
            if await cur.fetchone():
                return step_dict
        logger.warning("Step %s: parentId %s fantasma -> NULL", step_dict.get("id"), parent_id)
        fixed = dict(step_dict)
        fixed["parentId"] = None
        return fixed

    async def _save_step(self, step_dict: StepDict) -> None:
        conn = await self._get_conn()
        step_dict = await self._fix_parent_id(conn, step_dict)

        await conn.execute(
            """
            INSERT INTO steps (
                id, name, type, threadId, parentId, streaming, waitForAnswer,
                isError, metadata, tags, input, output, createdAt, command,
                start, end, generation, showInput, language, indent,
                defaultOpen, modes, disableFeedback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, type=excluded.type, threadId=excluded.threadId,
                parentId=excluded.parentId, streaming=excluded.streaming,
                waitForAnswer=excluded.waitForAnswer, isError=excluded.isError,
                metadata=excluded.metadata, tags=excluded.tags, input=excluded.input,
                output=excluded.output, createdAt=excluded.createdAt,
                command=excluded.command, start=excluded.start, end=excluded.end,
                generation=excluded.generation, showInput=excluded.showInput,
                language=excluded.language, indent=excluded.indent,
                defaultOpen=excluded.defaultOpen, modes=excluded.modes,
                disableFeedback=excluded.disableFeedback
            """,
            (
                step_dict.get("id"),
                step_dict.get("name"),
                step_dict.get("type"),
                step_dict.get("threadId"),
                step_dict.get("parentId"),
                1 if step_dict.get("streaming") else 0,
                1 if step_dict.get("waitForAnswer") else 0 if step_dict.get("waitForAnswer") is not None else None,
                1 if step_dict.get("isError") else 0 if step_dict.get("isError") is not None else None,
                json.dumps(step_dict.get("metadata")) if step_dict.get("metadata") else None,
                json.dumps(step_dict.get("tags")) if step_dict.get("tags") else None,
                step_dict.get("input"),
                step_dict.get("output"),
                step_dict.get("createdAt"),
                step_dict.get("command"),
                step_dict.get("start"),
                step_dict.get("end"),
                json.dumps(step_dict.get("generation")) if step_dict.get("generation") else None,
                step_dict.get("showInput"),
                step_dict.get("language"),
                step_dict.get("indent"),
                1 if step_dict.get("defaultOpen") else 0 if step_dict.get("defaultOpen") is not None else None,
                json.dumps(step_dict.get("modes")) if step_dict.get("modes") else None,
                1 if step_dict.get("disableFeedback") else 0 if step_dict.get("disableFeedback") is not None else None,
            ),
        )
        await conn.commit()

    async def create_step(self, step_dict: StepDict) -> None:
        await self._save_step(step_dict)

    async def update_step(self, step_dict: StepDict) -> None:
        await self._save_step(step_dict)

    async def delete_step(self, step_id: str) -> None:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM steps WHERE id = ?", (step_id,))
        await conn.commit()

    async def get_step(self, step_id: str) -> Optional[StepDict]:
        conn = await self._get_conn()
        async with conn.execute("SELECT * FROM steps WHERE id = ?", (step_id,)) as cur:
            row = await cur.fetchone()
            return self._row_to_step(row) if row else None

    async def get_steps(self, thread_id: str, filters: Optional[Dict] = None) -> List[StepDict]:
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT * FROM steps WHERE threadId = ? ORDER BY createdAt ASC", (thread_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [self._row_to_step(r) for r in rows]

    # ---------- Favorite Steps (FIX) ----------
    async def get_favorite_steps(self, thread_id: Optional[str] = None) -> List[StepDict]:
        """Retorna steps marcados como favoritos (vacío por defecto)."""
        return []

    # ---------- Elements ----------
    async def create_element(self, element: ElementDict) -> ElementDict:
        conn = await self._get_conn()
        await conn.execute(
            """
            INSERT INTO elements (
                id, threadId, type, url, chainlitKey, name, display,
                objectKey, size, page, language, forId, mime, props
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                threadId=excluded.threadId, type=excluded.type, url=excluded.url,
                chainlitKey=excluded.chainlitKey, name=excluded.name,
                display=excluded.display, objectKey=excluded.objectKey,
                size=excluded.size, page=excluded.page,
                language=excluded.language, forId=excluded.forId,
                mime=excluded.mime, props=excluded.props
            """,
            (
                element.get("id"), element.get("threadId"), element.get("type"),
                element.get("url"), element.get("chainlitKey"), element.get("name"),
                element.get("display"), element.get("objectKey"), element.get("size"),
                element.get("page"), element.get("language"), element.get("forId"),
                element.get("mime"), json.dumps(element.get("props")) if element.get("props") else None,
            ),
        )
        await conn.commit()
        return element

    async def get_element(self, element_id: str) -> Optional[ElementDict]:
        conn = await self._get_conn()
        async with conn.execute("SELECT * FROM elements WHERE id = ?", (element_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "id": row["id"], "threadId": row["threadId"], "type": row["type"],
                "url": row["url"], "chainlitKey": row["chainlitKey"],
                "name": row["name"], "display": row["display"],
                "objectKey": row["objectKey"], "size": row["size"],
                "page": row["page"], "language": row["language"],
                "forId": row["forId"], "mime": row["mime"],
                "props": json.loads(row["props"]) if row["props"] else {},
            }

    async def delete_element(self, element_id: str, thread_id: Optional[str] = None) -> None:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM elements WHERE id = ?", (element_id,))
        await conn.commit()

    # ---------- Feedback ----------
    async def upsert_feedback(self, feedback: Feedback) -> str:
        conn = await self._get_conn()
        feedback_id = feedback.id or str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO feedbacks (id, forId, threadId, value, comment)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                value=excluded.value, comment=excluded.comment
            """,
            (feedback_id, feedback.forId, feedback.threadId, feedback.value, feedback.comment),
        )
        await conn.commit()
        return feedback_id

    async def delete_feedback(self, feedback_id: str) -> bool:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM feedbacks WHERE id = ?", (feedback_id,))
        await conn.commit()
        return True

    # ---------- Misc ----------
    async def build_debug_url(self) -> str:
        return ""
