"""Officer preferences in the mock e-Office (ADR-0041; plan §11).

How the screens look and behave for ONE officer: text size, dates, landing screen, the
assistant panel. Kept by the server so they follow the officer to any browser, as a real
e-Office keeps a user's settings.

Nothing here can widen what an officer sees or does. Access (post, section, clearance, search
scope) comes from the profile and the access policy, never from preferences, and the API
rejects any field it does not know. Stored in memory: lost on restart, like the rest of the
sandbox state.
"""

from __future__ import annotations

import threading
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # display
    theme: Literal["light", "dark", "system"] = "light"
    text_size: Literal["normal", "large", "larger"] = "normal"
    density: Literal["comfortable", "compact"] = "comfortable"
    contrast: Literal["standard", "high"] = "standard"
    reduce_motion: bool = False
    date_style: Literal["dd-mm-yyyy", "dd Mon yyyy"] = "dd-mm-yyyy"
    note_font: Literal["serif", "sans"] = "serif"
    # start and lists
    landing: Literal["inbox", "receipts", "search", "monitor"] = "inbox"
    due_soon_days: int = Field(default=3, ge=0, le=30)
    # assistant
    assistant_panel: Literal["open", "collapsed"] = "open"
    stream_answers: bool = True
    shortcuts: bool = True
    show_notices: bool = True


class PreferenceStore:
    """One record per officer; bounded by the number of sandbox profiles."""

    def __init__(self) -> None:
        self._by_user: dict[str, Preferences] = {}
        self._lock = threading.Lock()

    def get(self, user_id: str) -> Preferences:
        with self._lock:
            return self._by_user.get(user_id, Preferences())

    def put(self, user_id: str, prefs: Preferences) -> Preferences:
        with self._lock:
            self._by_user[user_id] = prefs
            return prefs

    def reset(self, user_id: str) -> Preferences:
        with self._lock:
            self._by_user.pop(user_id, None)
            return Preferences()
