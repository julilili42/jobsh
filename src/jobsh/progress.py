"""Shared terminal progress display."""
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)


class QuietProgress:
    """Progress API used when another interface owns the terminal."""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def add_task(self, *_args, **_kwargs) -> int:
        return 0

    def remove_task(self, *_args, **_kwargs) -> None:
        pass

    def update(self, *_args, **_kwargs) -> None:
        pass

    def advance(self, *_args, **_kwargs) -> None:
        pass


def display(show: bool = True) -> Progress | QuietProgress:
    if not show:
        return QuietProgress()
    return Progress(
        TextColumn("{task.description}"), BarColumn(), TaskProgressColumn(), TimeRemainingColumn(),
        console=Console(stderr=True), transient=True,
    )
