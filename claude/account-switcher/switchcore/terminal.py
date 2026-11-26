"""The terminal a Claude session runs in, as the restart helper finds, reads and types into it."""

from collections.abc import Mapping
from typing import Protocol


class TerminalUnavailable(OSError):
    """The pane could not be read now; a later read may work."""


class Terminal(Protocol):
    """A terminal a local setting picks by name from TERMINALS in switchcore/choices.py; the restart
    helper builds it as cls()."""

    def pane_in(self, environment: Mapping[str, str]) -> str | None:
        """The pane a process with this environment runs in; None outside this terminal."""

    def read_screen(self, pane: str, lines: int) -> str:
        """The pane's last lines; TerminalUnavailable when it cannot be read now."""

    def submit(self, pane: str, text: str) -> None:
        """Type text and Enter in one request, so nothing the user types can fall between them.
        OSError when the terminal does not confirm the submit: the text may have been typed. Only
        code constants go in, never text from settings or transcripts, since a Claude Code prompt
        runs a line that starts with ! as a shell command."""
