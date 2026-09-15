import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from jobsh.db import connect
from jobsh.tui import JobshApp
from textual.widgets import Input

from tests.test_search import seed


class TuiTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_shows_a_job_and_its_detail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            with closing(connect(path)) as database, database:
                seed(database)
            app = JobshApp(path)
            async with app.run_test() as pilot:
                await pilot.pause(delay=0.1)
                results = app.query_one("#results")
                self.assertTrue(results.children)
                self.assertEqual(app.selected_id, app.jobs[0]["id"])
                self.assertIn(app.jobs[0]["title"], str(app.query_one("#detail").render()))
                results.focus()
                await pilot.press("j")
                await pilot.pause(delay=0.1)
                self.assertEqual(app.selected_id, app.jobs[1]["id"])
                await pilot.press("g")
                self.assertEqual(results.index, 0)
                await pilot.press("f")
                self.assertTrue(app.query_one("#filters").display)
                title = app.query_one("#title", Input)
                title.focus()
                await pilot.press("f")
                self.assertEqual(title.value, "f")
                title.value = "Go Developer"
                await pilot.press("enter")
                await pilot.pause(delay=0.1)
                self.assertEqual([job["title"] for job in app.jobs], ["Go Developer"])


if __name__ == "__main__":
    unittest.main()
