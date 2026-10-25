"""Shared test setup."""
import asyncio
import sys

# psycopg's async mode cannot run on Windows' default ProactorEventLoop. Only matters when the tests run
# on a Windows host; inside the Linux container this does nothing.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
