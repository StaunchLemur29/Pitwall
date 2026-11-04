"""The adapter interface every game implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..models import Capabilities, Frame, SessionInfo

if TYPE_CHECKING:
    from ..tracks.model import TrackModel


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

    def watch(self) -> None:
        """Cheap check between polls, so the moment the car's position changes
        is known precisely. Called often (every ~2 ms); must be very fast."""

    def track_model(self, session: SessionInfo) -> TrackModel | None:
        """The track's layout from the game's own data, if the game provides it."""
        return None

    def close(self) -> None:
        """Release resources."""
