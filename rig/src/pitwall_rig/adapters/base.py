"""The adapter interface every game implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Capabilities, Frame, SessionInfo


class GameAdapter(ABC):
    """Reads one game's telemetry and normalises it.

    The rig loop calls ``poll()`` at a fixed rate. Adapters must never block for
    long and must tolerate the game starting, stopping and restarting.
    """

    #: Short id, e.g. "ac", "acevo", "demo".
    game_id: str = "unknown"
    capabilities: Capabilities = Capabilities()

    @abstractmethod
    def poll(self) -> Frame | None:
        """Return the latest frame, or None if the game isn't available."""

    @abstractmethod
    def session(self) -> SessionInfo | None:
        """Return info about the current session, or None if unavailable."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources."""
