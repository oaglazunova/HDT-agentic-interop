import asyncio

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession


async def main():
    server = StdioServerParameters(
        command="python",
        args=["-m", "HDT_MCP.server_option_d"],
        env={"MCP_TRANSPORT": "stdio"},
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("\nTOOLS:")
            for t in tools.tools:
                print("-", t.name)

            print("\nCALL hdt.sources.status@v1(user_id=1):")
            res = await session.call_tool("hdt.sources.status@v1", {"user_id": 1})
            print(res.content[0].text)

            print('\nCALL hdt.walk.fetch@v1(user_id=1, limit=5, prefer_data="vault"):')
            res = await session.call_tool("hdt.walk.fetch@v1", {"user_id": 1, "limit": 5, "prefer_data": "vault"})
            print(res.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
