"""Outbound triage bridge: request context -> Hermes -> verdict.

Phase 1 (this code) only describes: it pushes a request's context to a Hermes
webhook route and renders the verdict as a threaded reply. It never mutates a
video's status. See docs/triage.md.
"""

from .context import build_request_context
from .service import TriageService, VerdictError, render_reply
from .signing import sign, verify
from .store import TriageStore

__all__ = [
    "TriageService",
    "TriageStore",
    "VerdictError",
    "build_request_context",
    "render_reply",
    "sign",
    "verify",
]
