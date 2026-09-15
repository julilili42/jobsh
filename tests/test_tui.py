import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import ANY, patch

from jobsh.db import connect, connect_readonly
from jobsh.tui import JobshApp, run
from textual.widgets import Input

from tests.test_search import seed


class TuiTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_opens_details_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            with closing(connect(path)) as database, database:
                seed(database)
            app = JobshApp(path)
            async with app.run_test() as pilot:
                await pilot.pause(delay=0.1)
                results = app.query_one("#results")
                self.assertTrue(results.children)
                self.assertIsNone(app.selected_id)
                results.focus()
                await pilot.press("j")
                await pilot.pause(delay=0.25)
                self.assertEqual(results.index, 1)
                self.assertIsNone(app.selected_id)
                with patch("jobsh.tui.webbrowser.open", return_value=True) as open_url:
                    await pilot.press("o")
                open_url.assert_called_once_with(app.jobs[1]["original_url"])
                await pilot.press("enter")
                await pilot.pause(delay=0.1)
                self.assertEqual(app.selected_id, app.jobs[1]["id"])
                self.assertTrue(app.query_one("#details-pane").display)
                self.assertIn(app.jobs[1]["title"], str(app.query_one("#detail").render()))
                with patch("jobsh.tui.webbrowser.open", return_value=True) as open_url:
                    await pilot.press("o")
                open_url.assert_called_once_with(app.jobs[1]["original_url"])
                await pilot.press("l")
                self.assertFalse(app.query_one("#details-pane").display)
                await pilot.press("enter")
                self.assertTrue(app.query_one("#details-pane").display)
                await pilot.press("enter")
                self.assertFalse(app.query_one("#details-pane").display)
                query = app.query_one("#query", Input)
                query.value = "Rust"
                query.focus()
                await pilot.press("escape")
                self.assertEqual(query.value, "Rust")
                self.assertIs(app.focused, results)
                query.value = ""
                await pilot.pause(delay=0.2)
                await pilot.press("g")
                self.assertEqual(results.index, 0)
                await pilot.press("f")
                self.assertTrue(app.query_one("#filters").display)
                title = app.query_one("#title", Input)
                title.focus()
                await pilot.press("f")
                self.assertEqual(title.value, "f")
                title.value = "Go Developer"
                await pilot.pause(delay=0.2)
                self.assertEqual([job["title"] for job in app.jobs], ["Go Developer"])
                await pilot.press("escape")
                self.assertEqual(title.value, "Go Developer")
                self.assertIs(app.focused, results)

    async def test_load_more_keeps_the_selected_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            with closing(connect(path)) as database, database:
                seed(database)
            app = JobshApp(path)
            async with app.run_test() as pilot:
                await pilot.pause(delay=0.1)
                results = app.query_one("#results")
                results.index = 1
                count = len(app.jobs)
                job = app.jobs[0] | {"id": 999}
                await app._show_results(app.search_version, {"jobs": [job], "next_cursor": None}, True)
                self.assertEqual(len(app.jobs), count + 1)
                self.assertEqual(results.index, 1)

    async def test_filters_stack_on_a_narrow_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            with closing(connect(path)) as database, database:
                seed(database)
            app = JobshApp(path)
            async with app.run_test(size=(60, 36)) as pilot:
                await pilot.pause(delay=0.1)
                app.query_one("#results").focus()
                await pilot.press("f")
                filters = app.query_one("#filters")
                self.assertTrue(filters.display)
                self.assertEqual(filters.styles.height.value, 9)
                app.query_one("#results").focus()
                await pilot.press("u")
                self.assertTrue(app.query_one("#updates").display)
                self.assertIsNotNone(app.query_one("#refresh"))

    async def test_refresh_rediscovers_then_syncs_the_selected_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            with closing(connect(path)) as database, database:
                seed(database)
            app = JobshApp(path)
            async with app.run_test() as pilot:
                await pilot.pause(delay=0.1)
                provider = str(app.query_one("#provider").value)
                with patch("jobsh.tui.discover", return_value=[]) as rediscover, \
                        patch("jobsh.tui.sync", return_value=(0, 0)) as sync_due:
                    app.action_refresh()
                    await pilot.pause(delay=0.1)
                rediscover.assert_called_once_with(
                    provider, limit=100, workers=8, timeout=15, database=ANY,
                    show_progress=False, report=False,
                )
                sync_due.assert_called_once_with(
                    ANY, timeout=15, workers=16, provider=provider, show_progress=False,
                )

    def test_tui_startup_runs_database_migrations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            with patch.object(JobshApp, "run") as app_run:
                run(path)
            app_run.assert_called_once()
            with closing(connect_readonly(path)) as database:
                self.assertIn("remove_diacritics 0", database.execute(
                    "SELECT sql FROM sqlite_master WHERE name = 'jobs_fts'"
                ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
