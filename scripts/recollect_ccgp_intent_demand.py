"""Re-collect ccgp_intent_demand using latest parser (PR #82).

Triggered manually after bug fixes to:
1. Fix existing 1952 rows via ON CONFLICT DO UPDATE (URL / budget / deadline / full_content)
2. Capture any new items in the days window

Usage:
  docker exec tender-scraper-scheduler python /app/scripts/recollect_ccgp_intent_demand.py [--days N]
"""
import asyncio
import sys

from app.core.harvest.pipeline import run_ccgp_intent_demand_collection


async def main():
    days = 30
    if "--days" in sys.argv:
        i = sys.argv.index("--days")
        days = int(sys.argv[i + 1])

    print(f"=== Re-collecting ccgp_intent_demand (days={days}) ===")
    print("Will trigger full list API + detail API fetch for last {} days".format(days))
    print("Existing 1952 rows will be updated via ON CONFLICT DO UPDATE")
    print()

    result = await run_ccgp_intent_demand_collection(days=days)

    print()
    print("=== Result ===")
    print(f"  total (API list): {result.get('total')}")
    print(f"  matched (keywords): {result.get('matched')}")
    print(f"  by_type: {result.get('by_type')}")
    print(f"  data_path: {result.get('data_path')}")


if __name__ == "__main__":
    asyncio.run(main())