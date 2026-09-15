"""Interactive terminal search for jobsh."""
from contextlib import closing
from pathlib import Path
import webbrowser

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import Button, Input, ListItem, ListView, Select, Static

from .adapters import ADAPTERS
from .db import connect, connect_readonly
from .discovery import discover
from .search import get_job, search
from .sync import sync


MODES = (("All work modes", ""), ("Remote", "remote"), ("Hybrid", "hybrid"),
         ("On-site", "onsite"), ("Unknown", "unknown"))
DISCOVERY_PROVIDERS = tuple((name.title(), name) for name, adapter in ADAPTERS.items() if adapter.domains)


class SearchInput(Input):
    """Text input that returns to the result list without losing its query."""

    BINDINGS = Input.BINDINGS + [Binding("escape", "focus_results", show=False)]

    def action_focus_results(self) -> None:
        self.app.action_focus_results()


class JobList(ListView):
    """A result list with Vim navigation when it has focus."""

    BINDINGS = ListView.BINDINGS + [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g", "first_result", show=False),
        Binding("G", "last_result", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("l", "open_details", show=False),
        Binding("o", "open_url", show=False),
    ]

    def action_first_result(self) -> None:
        self.index = 0

    def action_last_result(self) -> None:
        self.index = len(self) - 1

    def action_open_details(self) -> None:
        self.app.action_open_details()

    def action_open_url(self) -> None:
        self.app.action_open_url()


class JobDetails(VerticalScroll):
    """Scrollable job details with Vim navigation when it has focus."""

    BINDINGS = [
        Binding("j", "scroll_down", show=False),
        Binding("k", "scroll_up", show=False),
        Binding("g", "scroll_home", show=False),
        Binding("G", "scroll_end", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("h", "close_details", show=False),
        Binding("escape", "close_details", show=False),
        Binding("enter", "close_details", show=False),
        Binding("l", "close_details", show=False),
        Binding("o", "open_url", show=False),
    ]

    def action_close_details(self) -> None:
        self.app.action_close_details()

    def action_open_url(self) -> None:
        self.app.action_open_url()


class JobshApp(App[None]):
    """Search jobs without leaving the keyboard."""

    CSS = """
    Screen { background: $background; }
    #topbar { height: 3; padding: 0 2; background: $surface; content-align: left middle; border-bottom: solid $primary 10%; }
    #brand { width: 8; text-style: bold; color: $accent; }
    #prompt { width: 2; color: $accent; content-align: center middle; }
    #count { color: $text-muted; }
    #count { width: 1fr; content-align: right middle; }
    #query { width: 1fr; }
    #filters, #updates { height: 3; padding: 0 2; layout: horizontal; background: $surface; border-bottom: solid $primary 10%; }
    Input { width: 30; margin-right: 1; border: none; background: transparent; }
    Input:focus { border-bottom: tall $accent; }
    Select { width: 20; margin-right: 1; border: none; background: transparent; }
    Select:focus { border-bottom: tall $accent; }
    #updates Button { margin-right: 1; }
    #shell { height: 1fr; layout: grid; grid-size: 2; grid-columns: 2fr 3fr; }
    #results-pane { border-right: solid $primary 10%; }
    ListView { height: 1fr; padding: 0 1; background: $background; }
    ListItem { padding: 0 1; margin: 0; }
    #more { width: 1fr; height: 1; margin: 0; border: none; background: $background; color: $text-muted; }
    #details-pane { height: 1fr; }
    #detail { height: auto; padding: 1 2; }
    #status { height: 1; padding: 0 2; color: $text-muted; background: $surface; }
    """
    BINDINGS = [
        ("/", "focus_search", "Search"),
        ("f", "toggle_filters", "Filters"),
        ("u", "toggle_updates", "Updates"),
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
        self.search_timer: Timer | None = None
        self.work_mode = ""
        self.details_open = False
        self.selected_url: str | None = None

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("jobsh", id="brand"), Static("›", id="prompt"),
            SearchInput(placeholder="Search jobs", id="query"), Static("", id="count"), id="topbar",
        )
        with Horizontal(id="filters"):
            yield SearchInput(placeholder="Title", id="title")
            yield SearchInput(placeholder="Location", id="location")
            yield Select(MODES, value="", id="work-mode")
        with Horizontal(id="updates"):
            yield Select(DISCOVERY_PROVIDERS, value=DISCOVERY_PROVIDERS[0][1], id="provider")
            yield Button("Refresh", id="refresh", variant="primary")
        with Horizontal(id="shell"):
            with Vertical(id="results-pane"):
                yield JobList(id="results")
                yield Button("n  Load more", id="more", variant="default")
            with JobDetails(id="details-pane"):
                yield Static("Search to browse open jobs.", id="detail")
        yield Static("/ search · f filters · u refresh · j/k navigate · Enter details · ? help", id="status")

    def on_mount(self) -> None:
        self._set_layout(self.size.width)
        self.query_one("#filters").display = False
        self.query_one("#updates").display = False
        self.query_one("#query", Input).focus()
        self._start_search()

    def on_resize(self) -> None:
        self._set_layout(self.size.width)

    def _set_layout(self, width: int) -> None:
        shell = self.query_one("#shell")
        results = self.query_one("#results-pane")
        details = self.query_one("#details-pane")
        narrow = width < 90
        results.display = not self.details_open or not narrow
        details.display = self.details_open
        shell.styles.grid_size_columns = 2 if self.details_open and not narrow else 1
        shell.styles.grid_columns = "2fr 3fr" if self.details_open and not narrow else "1fr"
        results.styles.height = "1fr"
        self._set_toolbar_layout("#filters", width)
        self._set_toolbar_layout("#updates", width)

    def _set_toolbar_layout(self, selector: str, width: int) -> None:
        toolbar = self.query_one(selector, Horizontal)
        narrow = width < 70
        toolbar.styles.layout = "vertical" if narrow else "horizontal"
        toolbar.styles.height = 9 if narrow else 3
        toolbar.styles.width = "1fr" if narrow else (88 if selector == "#filters" else 40)
        for child in toolbar.children:
            child.styles.width = "1fr" if narrow else None
        if not narrow:
            if selector == "#filters":
                self.query_one("#title", Input).styles.width = 30
                self.query_one("#location", Input).styles.width = 30
                self.query_one("#work-mode", Select).styles.width = 20
            else:
                self.query_one("#provider", Select).styles.width = 20
                self.query_one("#refresh", Button).styles.width = "auto"

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._cancel_scheduled_search()
        self._start_search()

    def on_input_changed(self, _: Input.Changed) -> None:
        self._schedule_search()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "work-mode":
            return
        if str(event.value) == self.work_mode:
            return
        self.work_mode = str(event.value)
        self._schedule_search()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "more":
            self.action_load_more()
        elif event.button.id == "refresh":
            self.action_refresh()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is not None and event.item.id:
            self.action_open_details()

    def action_focus_search(self) -> None:
        self.query_one("#query", Input).focus()

    def action_toggle_filters(self) -> None:
        filters = self.query_one("#filters")
        self.query_one("#updates").display = False
        self.details_open = False
        self._set_layout(self.size.width)
        filters.display = not filters.display
        if filters.display:
            self.query_one("#title", Input).focus()
        else:
            self.action_focus_results()

    def action_toggle_updates(self) -> None:
        updates = self.query_one("#updates")
        self.query_one("#filters").display = False
        self.details_open = False
        self._set_layout(self.size.width)
        updates.display = not updates.display
        if updates.display:
            self.query_one("#provider", Select).focus()
        else:
            self.action_focus_results()

    def _schedule_search(self) -> None:
        self._cancel_scheduled_search()
        self.search_timer = self.set_timer(0.15, self._start_scheduled_search)

    def _cancel_scheduled_search(self) -> None:
        if self.search_timer is not None:
            self.search_timer.stop()
            self.search_timer = None

    def _start_scheduled_search(self) -> None:
        self.search_timer = None
        self._start_search()

    def action_focus_results(self) -> None:
        if self.query_one("#filters").display:
            self.query_one("#filters").display = False
        if self.query_one("#updates").display:
            self.query_one("#updates").display = False
        if self.details_open:
            self.action_close_details()
            return
        self.query_one("#results", JobList).focus()

    def action_open_details(self) -> None:
        result = self.query_one("#results", JobList).highlighted_child
        if result is None or result.id is None:
            return
        self.details_open = True
        self._set_layout(self.size.width)
        self.query_one("#details-pane", JobDetails).focus()
        self._start_detail(int(result.id.removeprefix("job-")))

    def action_close_details(self) -> None:
        self.details_open = False
        self.selected_id = None
        self.selected_url = None
        self._set_layout(self.size.width)
        self.query_one("#results", JobList).focus()

    def action_open_url(self) -> None:
        url = self.selected_url
        if url is None:
            selected = self.query_one("#results", JobList).highlighted_child
            if selected is not None and selected.id is not None:
                job_id = int(selected.id.removeprefix("job-"))
                url = next((job["original_url"] for job in self.jobs if job["id"] == job_id), None)
        if url and webbrowser.open(url):
            self.query_one("#status", Static).update("Opened website" if not self.details_open else "Opened website · Enter/l back")
        elif url:
            self.query_one("#status", Static).update("Could not open website")

    def action_load_more(self) -> None:
        if self.next_cursor is not None:
            self._start_search(append=True)

    def action_help(self) -> None:
        self.notify(
            "Search: / focus · Enter apply · f show or hide filters\n"
            "Results: j/k move · g/G first/last · Ctrl-U/D page · Enter/l details · n more\n"
            "Details: j/k scroll · g/G top/bottom · Enter/l/h/Esc back · o website",
            title="Keyboard shortcuts",
        )

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
            self.selected_url = None
            self.details_open = False
            self._set_layout(self.size.width)
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
        new_jobs = page["jobs"]
        if append:
            self.jobs.extend(new_jobs)
        else:
            self.jobs = new_jobs
        self.next_cursor = page["next_cursor"]
        results = self.query_one("#results", JobList)
        if version != self.search_version:
            return
        if not append:
            await results.clear()
        if self.jobs:
            if append:
                await results.extend(self._result_item(job) for job in new_jobs)
            else:
                await results.extend(self._result_item(job) for job in self.jobs)
                results.index = 0
            self.query_one("#status", Static).update("j/k navigate · Enter details · u refresh · ? help")
            self.query_one("#count", Static).update(f"{len(self.jobs)} results")
        else:
            await results.append(ListItem(Static("No open jobs match these filters."), disabled=True))
            self.query_one("#detail", Static).update("Try a broader search or clear a filter.")
            self.query_one("#status", Static).update("No matching jobs")
            self.query_one("#count", Static).update("")
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

    def action_refresh(self) -> None:
        provider = str(self.query_one("#provider", Select).value)
        self._start_update(f"Refreshing {provider} feeds…")
        self._refresh(provider)

    def _start_update(self, message: str) -> None:
        self.query_one("#updates").display = False
        self.query_one("#refresh", Button).disabled = True
        self.query_one("#status", Static).update(message)

    @work(thread=True, exclusive=True, group="update")
    def _refresh(self, provider: str) -> None:
        try:
            with closing(connect(self.database_path)) as database:
                feeds = discover(
                    provider, limit=100, workers=8, timeout=15, database=database,
                    show_progress=False, report=False,
                )
                succeeded, failed = sync(database, timeout=15, workers=16, provider=provider, show_progress=False)
        except Exception as error:  # Network and SQLite errors are displayed in the TUI.
            self.call_from_thread(self._show_update_error, str(error))
        else:
            self.call_from_thread(self._show_refresh_result, provider, len(feeds), succeeded, failed)

    def _finish_update(self) -> None:
        self.query_one("#refresh", Button).disabled = False

    def _show_update_error(self, error: str) -> None:
        self._finish_update()
        self.query_one("#status", Static).update(f"Update failed: {error}")

    def _show_refresh_result(self, provider: str, feeds: int, succeeded: int, failed: int) -> None:
        self._finish_update()
        self.notify(
            f"{provider}: {feeds} feeds verified · {succeeded} synced · {failed} failed",
            title="Refresh complete",
        )
        self._start_search()

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
        if job["published_at"]:
            detail.append(f"Posted {job['published_at'][:10]}\n", style="dim")
        detail.append("\n")
        detail.append(job["description"] or "No description supplied by the source.")
        self.selected_url = job["original_url"]
        self.query_one("#detail", Static).update(detail)
        self.query_one("#status", Static).update("j/k scroll · o website · Enter/l back")


def run(database_path: Path) -> None:
    """Start the interactive application."""
    with closing(connect(database_path)):
        pass
    JobshApp(database_path).run()
