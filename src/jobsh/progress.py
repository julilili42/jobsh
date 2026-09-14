"""Shared terminal progress display."""
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)


def display() -> Progress:
    return Progress(
        TextColumn("{task.description}"), BarColumn(), TaskProgressColumn(), TimeRemainingColumn(),
        console=Console(stderr=True), transient=True,
    )
