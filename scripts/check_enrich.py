#!/usr/bin/env python3
import json
from pathlib import Path

OUTPUT_FILE = Path("/app/output/latest.json")
with open(OUTPUT_FILE) as f:
    data = json.load(f)

projects = data.get("projects", [])
total = len(projects)
filled = sum(1 for p in projects if p.get("content_preview"))
print(f"Filled: {filled}/{total}")
print(f"Enriched at: {data.get('enriched_at', 'N/A')}")

# Show first 3 filled items
for p in projects[:5]:
    cp = p.get("content_preview", "")
    print(f"  - {p.get('title','')[:40]}")
    print(f"    content_preview={repr(cp[:60]) if cp else '(empty)'}")
    print(f"    budget={p.get('budget','')}, region={p.get('region','')}")
