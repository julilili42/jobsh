import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from jobsh.db import connect
from jobsh.tui import JobshApp
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
                await pilot.press("enter")
                await pilot.pause(delay=0.1)
                self.assertEqual(app.selected_id, app.jobs[1]["id"])
                self.assertTrue(app.query_one("#details-pane").display)
                self.assertIn(app.jobs[1]["title"], str(app.query_one("#detail").render()))
                await pilot.press("h")
                self.assertFalse(app.query_one("#details-pane").display)
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
                self.assertEqual(title.value, "")

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


if __name__ == "__main__":
    unittest.main()
