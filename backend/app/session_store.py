"""
In-memory per-session state (chat session + any PDF-extracted context).

Fine for a small free-tier pilot (single process, handful of concurrent
users); state is lost on server restart. If usage grows, swap this for a
Redis- or SQLite-backed store without touching callers.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .gemini_client import ChatSession

_SESSION_TTL_SECONDS = 60 * 60 * 4  # 4 hours


@dataclass
class SessionState:
    chat_session: Optional[ChatSession] = None
    last_seen: float = field(default_factory=time.time)
    pdf_context: Optional[str] = None


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def _get_state(self, session_id: str) -> SessionState:
        self._evict_stale()
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState()
            self._sessions[session_id] = state
        state.last_seen = time.time()
        return state

    def get_chat_session(self, session_id: str, mode: str) -> SessionState:
        """Returns the session state, creating (or recreating on mode change)
        the live Gemini chat session - this is the only path that needs an
        API key, so it must not be triggered by unrelated operations like a
        PDF upload."""
        with self._lock:
            state = self._get_state(session_id)
            if state.chat_session is None or state.chat_session.mode != mode:
                state.chat_session = ChatSession(mode=mode)
            return state

    def set_pdf_context(self, session_id: str, context: str) -> None:
        with self._lock:
            state = self._get_state(session_id)
            state.pdf_context = context

    def _evict_stale(self):
        now = time.time()
        stale = [sid for sid, s in self._sessions.items() if now - s.last_seen > _SESSION_TTL_SECONDS]
        for sid in stale:
            del self._sessions[sid]


store = SessionStore()
