import asyncio

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession


async def main():
    server = StdioServerParameters(
        command="python",
        args=["-m", "HDT_SOURCES_MCP.server"],
        env={"MCP_TRANSPORT": "stdio"},
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("\nTOOLS:")
            for t in tools.tools:
                print("-", t.name)

            print("\nCALL sources.status@v1(user_id=1):")
            res = await session.call_tool("sources.status@v1", {"user_id": 1})
            # In many MCP versions, tool output is returned as text content
            if getattr(res, "content", None):
                for c in res.content:
                    print(getattr(c, "text", c))
            else:
                print(res)

            print("\nCALL source.gamebus.walk.fetch@v1(user_id=1, limit=5):")
            res = await session.call_tool(
                "source.gamebus.walk.fetch@v1",
                {"user_id": 1, "start_date": None, "end_date": None, "limit": 5, "offset": 0},
            )
            if getattr(res, "content", None):
                for c in res.content:
                    print(getattr(c, "text", c))
            else:
                print(res)


if __name__ == "__main__":
    asyncio.run(main())
