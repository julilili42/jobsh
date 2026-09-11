import asyncio
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from jobsh.db import connect
from tests.test_search import SAMPLE, seed


class ServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_search_pagination_details_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            with closing(connect(path)) as database, database:
                seed(database)
                database.execute("UPDATE jobs SET closed_at = '2026-09-11' WHERE id = 2")
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "jobsh", "--db", str(path), "serve"],
            )
            async with asyncio.timeout(30), stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    self.assertEqual({tool.name for tool in tools}, {"search_jobs", "get_job"})
                    self.assertTrue(all(tool.annotations.readOnlyHint for tool in tools))
                    ids, cursor = [], 0
                    while cursor is not None:
                        result = await session.call_tool("search_jobs", {"limit": 5, "cursor": cursor})
                        self.assertFalse(result.isError)
                        page = result.structuredContent
                        ids.extend(job["id"] for job in page["jobs"])
                        self.assertTrue(all("description" not in job for job in page["jobs"]))
                        cursor = page["next_cursor"]
                    self.assertEqual(ids, [i for i in range(1, len(SAMPLE) + 1) if i != 2])
                    result = await session.call_tool("search_jobs", {"location": "France"})
                    self.assertEqual(result.structuredContent["jobs"][0]["title"], "Pflegefachkraft")
                    result = await session.call_tool("get_job", {"id": 2})
                    self.assertEqual(result.structuredContent["closed_at"], "2026-09-11")
                    self.assertIn("description", result.structuredContent)
                    self.assertIn("original_url", result.structuredContent)
                    for tool, args in (("search_jobs", {"limit": 101}),
                                       ("search_jobs", {"cursor": -1}),
                                       ("search_jobs", {"work_mode": "invalid"}),
                                       ("get_job", {"id": 999})):
                        self.assertTrue((await session.call_tool(tool, args)).isError)
