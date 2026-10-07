"""Author a recipe the way the kav-fastweb skill says, over the real MCP protocol:
find_recipe -> (none) -> dry_run -> save_recipe -> find_recipe -> run_recipe.
Usage: uv run python tests/mcp_recipe_flow.py recipe.json '{"param": "value"}' [--save]"""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def j(res):
    return json.loads(res.content[0].text)


async def main(recipe, params, save):
    async with stdio_client(StdioServerParameters(command="uv", args=["run", "python", "-m", "kfw.mcp_server"])) as (r, w), \
            ClientSession(r, w) as s:
        await s.initialize()
        print("find_recipe before:", j(await s.call_tool("find_recipe", {"request": recipe["description"]})))
        dr = j(await s.call_tool("dry_run", {"recipe": recipe, "params": params}))
        res = dr.get("result", {})
        print("dry_run passed:", dr.get("passed"), "| status:", res.get("status"), res.get("reason"), res.get("hint"),
              "| total_ms:", res.get("total_ms"), "| error:", dr.get("error"))
        for st in res.get("steps", []):
            print("   step", st)
        for row in (res.get("rows") or [])[:5]:
            print("   row", row)
        print("   rows_total:", res.get("rows_total"), "missing:", res.get("expect_text_missing"), "evidence:", res.get("evidence"))
        if save and dr.get("passed"):
            print("save:", j(await s.call_tool("save_recipe", {"recipe": recipe, "dry_run_id": dr["dry_run_id"]})))
            print("find_recipe after:", j(await s.call_tool("find_recipe", {"request": recipe["description"]})))


if __name__ == "__main__":
    asyncio.run(main(json.load(open(sys.argv[1])), json.loads(sys.argv[2]), "--save" in sys.argv))
