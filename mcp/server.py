"""
Optional MCP server for Tutor Feedback Pipeline.

Install with: pip install -e ".[mcp]"
Run with: python -m mcp.server (or see README).

Exposes tools:
- trigger_processing(recording_path, student, platforms, metadata)
- get_job_status(job_id)
- list_styles()
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _run_mcp_server():
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Tool, TextContent
    except ImportError:
        print('MCP dependencies not installed. Run: pip install -e ".[mcp]"', file=sys.stderr)
        sys.exit(1)

    server = Server("tutor-feedback")

    @server.list_tools()
    async def list_tools() -> list:
        return [
            Tool(
                name="trigger_processing",
                description="Enqueue a tutor feedback job. Returns job_id.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "recording_path": {"type": "string"},
                        "student": {"type": "string"},
                        "platforms": {"type": "array", "items": {"type": "string"}},
                        "metadata": {"type": "object"},
                    },
                    "required": ["recording_path", "student", "platforms"],
                },
            ),
            Tool(
                name="get_job_status",
                description="Get status and result for a job by job_id.",
                inputSchema={
                    "type": "object",
                    "properties": {"job_id": {"type": "string"}},
                    "required": ["job_id"],
                },
            ),
            Tool(
                name="list_styles",
                description="List available platform style names.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name == "trigger_processing":
            from tutor_feedback.config import get_settings
            from tutor_feedback.automation.jobs import enqueue
            from tutor_feedback.automation.state import upsert_job
            from tutor_feedback.automation.watcher import process_job
            import threading
            settings = get_settings()
            data_dir = Path(settings.data_dir)
            path = arguments.get("recording_path", "")
            student = arguments.get("student", "Student")
            platforms = arguments.get("platforms") or ["intergreat", "simpletext"]
            metadata = arguments.get("metadata") or {}
            job = enqueue(path, student=student, platforms=platforms, trigger="mcp", metadata=metadata)
            upsert_job(
                data_dir, job.job_id, job.fingerprint, path, student, platforms, "mcp", metadata, status="queued"
            )
            threading.Thread(target=process_job, args=(job,), daemon=True).start()
            return [TextContent(type="text", text=job.job_id)]
        if name == "get_job_status":
            from tutor_feedback.config import get_settings
            from tutor_feedback.automation.state import get_job
            import json
            row = get_job(Path(get_settings().data_dir), arguments.get("job_id", ""))
            return [TextContent(type="text", text=json.dumps(row or {"error": "Job not found"}))]
        if name == "list_styles":
            from tutor_feedback.config import get_settings
            from tutor_feedback.styles import list_styles
            names = list_styles(Path(get_settings().styles_dir))
            return [TextContent(type="text", text="\n".join(names))]
        return [TextContent(type="text", text="Unknown tool")]

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    _run_mcp_server()
