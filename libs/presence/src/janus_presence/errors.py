from __future__ import annotations


class PresenceError(Exception):
    pass


class PresenceUnavailableError(PresenceError):
    pass


class PersonNotFoundError(PresenceError):
    pass
