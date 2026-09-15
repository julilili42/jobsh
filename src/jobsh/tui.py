"""Interactive terminal search for jobsh."""
from contextlib import closing
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Input, ListItem, ListView, Select, Static

from .db import connect_readonly
from .search import get_job, search


MODES = (("All work modes", ""), ("Remote", "remote"), ("Hybrid", "hybrid"),
         ("On-site", "onsite"), ("Unknown", "unknown"))


class JobshApp(App[None]):
    """Search jobs without leaving the keyboard."""

    CSS = """
    Screen { background: $background; }
    #topbar { height: 3; padding: 0 2; background: $surface; content-align: left middle; }
    #brand { width: 12; text-style: bold; color: $accent; }
    #subtitle { color: $text-muted; }
    #filters { height: auto; padding: 1 2; layout: horizontal; background: $surface; }
    Input { width: 1fr; margin-right: 1; }
    #query { width: 2fr; }
    Select { width: 24; margin-right: 1; }
    #shell { height: 1fr; layout: grid; grid-size: 2; grid-columns: 2fr 3fr; }
    #results-pane { border-right: solid $primary 15%; }
    #results-title, #details-title { height: 2; padding: 0 2; color: $text-muted; }
    ListView { height: 1fr; padding: 0 1; background: $background; }
    ListItem { padding: 1 1; margin: 0 0 1 0; }
    #more { width: 1fr; margin: 1; }
    #details-pane { height: 1fr; }
    #detail { height: auto; padding: 1 2; }
    #status { height: 2; padding: 0 2; color: $text-muted; background: $surface; }
    """
    BINDINGS = [
        ("/", "focus_search", "Search"),
        ("f", "focus_filters", "Filters"),
        ("n", "load_more", "More"),
        ("escape", "focus_results", "Results"),
        ("question_mark", "help", "Help"),
    ]

    def __init__(self, database_path: Path) -> None:
        super().__init__()
        self.database_path = database_path
        self.jobs: list[dict] = []
        self.next_cursor: int | None = None
        self.search_version = 0
        self.selected_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Horizontal(Static("jobsh", id="brand"), Static("Job search", id="subtitle"), id="topbar")
        with Horizontal(id="filters"):
            yield Input(placeholder="Search jobs · Enter", id="query")
            yield Input(placeholder="Title", id="title")
            yield Input(placeholder="Location", id="location")
            yield Select(MODES, value="", id="work-mode")
        with Horizontal(id="shell"):
            with Vertical(id="results-pane"):
                yield Static("RESULTS", id="results-title")
                yield ListView(id="results")
                yield Button("Load more", id="more", variant="default")
            with VerticalScroll(id="details-pane"):
                yield Static("DETAIL", id="details-title")
                yield Static("Search to browse open jobs.", id="detail")
        yield Static("Press / to search · ↑ ↓ to browse · Enter to view · ? for help", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._set_layout(self.size.width)
        self.query_one("#query", Input).focus()
        self._start_search()

    def on_resize(self) -> None:
        self._set_layout(self.size.width)

    def _set_layout(self, width: int) -> None:
        shell = self.query_one("#shell")
        results = self.query_one("#results-pane")
        narrow = width < 90
        shell.styles.grid_size_columns = 1 if narrow else 2
        shell.styles.grid_columns = "1fr" if narrow else "2fr 3fr"
        results.styles.height = 14 if narrow else "1fr"

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._start_search()

    def on_select_changed(self, _: Select.Changed) -> None:
        self._start_search()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "more":
            self.action_load_more()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is not None and event.item.id:
            self._start_detail(int(event.item.id.removeprefix("job-")))

    def action_focus_search(self) -> None:
        self.query_one("#query", Input).focus()

    def action_focus_filters(self) -> None:
        self.query_one("#location", Input).focus()

    def action_focus_results(self) -> None:
        self.query_one("#results", ListView).focus()

    def action_load_more(self) -> None:
        if self.next_cursor is not None:
            self._start_search(append=True)

    def action_help(self) -> None:
        self.notify("/ search · f filters · ↑↓ browse · Enter view · n load more · Esc results", title="Keyboard shortcuts")

    def _search_filters(self) -> tuple[str, str, str, str | None]:
        mode = self.query_one("#work-mode", Select).value
        return (
            self.query_one("#query", Input).value,
            self.query_one("#title", Input).value,
            self.query_one("#location", Input).value,
            str(mode) or None,
        )

    def _start_search(self, append: bool = False) -> None:
        if not append:
            self.search_version += 1
            self.selected_id = None
        query, title, location, mode = self._search_filters()
        cursor = self.next_cursor if append else 0
        if cursor is None:
            return
        self.query_one("#status", Static).update("Loading jobs…")
        self._load_results(self.search_version, query, title, location, mode, cursor, append)

    @work(thread=True, exclusive=True, group="search")
    def _load_results(
        self, version: int, query: str, title: str, location: str, mode: str | None, cursor: int, append: bool,
    ) -> None:
        try:
            with closing(connect_readonly(self.database_path)) as database:
                page = search(database, query, title=title, location=location, work_mode=mode, cursor=cursor)
        except Exception as error:  # SQLite errors are displayed in the TUI.
            self.call_from_thread(self._show_search_error, version, str(error))
        else:
            self.call_from_thread(self._show_results, version, page, append)

    def _show_search_error(self, version: int, error: str) -> None:
        if version == self.search_version:
            self.query_one("#status", Static).update(f"Could not search: {error}")

    async def _show_results(self, version: int, page: dict, append: bool) -> None:
        if version != self.search_version:
            return
        if append:
            self.jobs.extend(page["jobs"])
        else:
            self.jobs = page["jobs"]
        self.next_cursor = page["next_cursor"]
        results = self.query_one("#results", ListView)
        await results.clear()
        if version != self.search_version:
            return
        if self.jobs:
            await results.extend(self._result_item(job) for job in self.jobs)
            results.index = 0
            self.query_one("#status", Static).update(f"{len(self.jobs)} jobs loaded")
        else:
            await results.append(ListItem(Static("No open jobs match these filters."), disabled=True))
            self.query_one("#detail", Static).update("Try a broader search or clear a filter.")
            self.query_one("#status", Static).update("No matching jobs")
        self.query_one("#more", Button).display = self.next_cursor is not None

    @staticmethod
    def _result_item(job: dict) -> ListItem:
        label = Text(job["title"], style="bold")
        label.append(f"\n{job['provider_account']} · {job['location_text'] or 'Location unknown'}")
        label.append(f" · {job['work_mode'].replace('_', ' ').title()}", style="dim")
        return ListItem(Static(label), id=f"job-{job['id']}")

    def _start_detail(self, job_id: int) -> None:
        self.selected_id = job_id
        self.query_one("#detail", Static).update("Loading job…")
        self._load_detail(job_id)

    @work(thread=True, exclusive=True, group="detail")
    def _load_detail(self, job_id: int) -> None:
        try:
            with closing(connect_readonly(self.database_path)) as database:
                job = get_job(database, job_id)
        except Exception as error:  # A concurrent sync can close or remove a job.
            self.call_from_thread(self._show_detail_error, job_id, str(error))
        else:
            self.call_from_thread(self._show_detail, job_id, job)

    def _show_detail_error(self, job_id: int, error: str) -> None:
        if job_id == self.selected_id:
            self.query_one("#detail", Static).update(f"Could not load job: {error}")

    def _show_detail(self, job_id: int, job: dict) -> None:
        if job_id != self.selected_id:
            return
        detail = Text(job["title"] + "\n", style="bold")
        detail.append(f"{job['provider_account']} · {job['location_text'] or 'Location unknown'} · {job['work_mode'].title()}\n", style="dim")
        detail.append(f"Last seen: {job['last_seen_at']}\n")
        if job["published_at"]:
            detail.append(f"Posted: {job['published_at']}\n")
        detail.append(f"{job['original_url']}\n\n", style="underline")
        detail.append(job["description"] or "No description supplied by the source.")
        self.query_one("#detail", Static).update(detail)


def run(database_path: Path) -> None:
    """Start the interactive application."""
    JobshApp(database_path).run()
