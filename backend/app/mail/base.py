"""Mail provider abstraction (brief section 5). Only Gmail is implemented;
IMAP or Outlook would implement the same interface."""
from dataclasses import dataclass, field
from typing import Protocol


class AuthRevoked(Exception):
    """The stored grant no longer works. `blocked` means an administrator policy blocks the app."""

    def __init__(self, detail: str, blocked: bool = False):
        super().__init__(detail)
        self.blocked = blocked


class CursorExpired(Exception):
    """The stored change cursor (Gmail historyId) is too old to list changes from."""


@dataclass
class Changes:
    message_ids: list[str] = field(default_factory=list)  # new incoming messages, oldest first, no duplicates
    cursor: int = 0  # store this after the changes are processed
    # label edits on existing mail (read/unread in Gmail), in order: (message id, added, removed)
    label_changes: list[tuple[str, list[str], list[str]]] = field(default_factory=list)


@dataclass
class Profile:
    email: str
    cursor: int  # current position; changes are listed from here on


@dataclass
class Watch:
    cursor: int
    expires_at_ms: int


class MailProvider(Protocol):
    def profile(self) -> Profile: ...
    def list_changes(self, since: int) -> Changes: ...
    def start_watch(self, topic: str) -> Watch: ...
    def stop_watch(self) -> None: ...
    def get_metadata(self, message_id: str) -> dict: ...  # Gmail API message resource, headers only
    def get_full(self, message_id: str) -> dict: ...  # with body parts
    # Phase 4: send(...)
