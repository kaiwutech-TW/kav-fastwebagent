"""End-to-end over the real MCP stdio protocol: spawn the server, list tools, call status and compare_price.
Needs Kev (:8009) and Chrome (:9333, launched if absent). Not a unit test: it hits live shops.
Usage: uv run python tests/mcp_e2e.py "PS5 Pro" "Sony PlayStation 5 Pro 主機(全新)" "ps5pro,playstation5pro;主機" "數位版"
"""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(query, spec, must, must_not):
    params = StdioServerParameters(command="uv", args=["run", "python", "-m", "kfw.mcp_server"])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = await s.list_tools()
        print("tools:", [t.name for t in tools.tools])
        st = await s.call_tool("status", {})
        print("status:", st.content[0].text)
        res = await s.call_tool("run_recipe", {"name": "tw-shop-compare",
                                               "params": {"query": query, "spec": spec, "must": must, "must_not": must_not}})
        data = json.loads(res.content[0].text)
        print("result status:", data["status"], "total_ms:", data["total_ms"])
        for p in data["per_site"]:
            print(f"  {p['site']:<8} {p['status']:<10} {p['ms']}ms cards={p.get('cards_seen')} kev_calls={p.get('model_calls')} rejected={p.get('rejected')}")
        b = data["best"]
        print(f"BEST: ${b['price']} {b['site']} verified={b.get('verified')} {b['title'][:60]}" if b else "BEST: none")
        print(f"verify_ms: {data.get('verify_ms')}")
        for o in data["offers"][:6]:
            v = o.get("verify", {})
            print(f"  ${o['price']:>6} {o['site']:<8} verified={o.get('verified')!s:<5} {v.get('status', '-'):<14} card=${o.get('card_price', o['price'])} {o['title'][:40]}")
        for o in data.get("dropped_after_verify", []):
            print(f"  DROPPED ${o['price']:>6} {o['site']:<8} {o['verify']['status']:<16} page={(o['verify'].get('page') or {}).get('name', '')[:40]}")
        for o in data.get("suspicious", []):
            print(f"  SUSPICIOUS ${o['price']:>6} {o['site']:<8} {o['flag']} x{o['price_vs_median']} {o['title'][:40]}")
        print("needs_help:", [(h['site'], h['reason']) for h in data["needs_help"]])


if __name__ == "__main__":
    # must: groups separated by ";", terms within a group by ","  e.g. "ps5pro,playstation5pro;主機"
    q, spec, must = sys.argv[1], sys.argv[2], [g.split(",") for g in sys.argv[3].split(";")]
    asyncio.run(main(q, spec, must, sys.argv[4].split(",") if len(sys.argv) > 4 else []))
