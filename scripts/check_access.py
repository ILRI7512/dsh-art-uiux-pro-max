#!/usr/bin/env python3
"""对注册表里的资源做一次真实访问探测，把结论写进运行期状态。

用法：
    python3 scripts/check_access.py            # 全部
    python3 scripts/check_access.py --limit 5  # 只测前 5 条
    python3 scripts/check_access.py --only m3-material,nng
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from art_uiux.checker import probe_many          # noqa: E402
from art_uiux.registry import Registry           # noqa: E402

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    reg = Registry(ROOT)
    items = reg.view()
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        items = [i for i in items if i["resource_id"] in wanted]
    if args.limit:
        items = items[: args.limit]

    print("探测 %d 个资源……" % len(items))
    results = probe_many([i["url"] for i in items], workers=args.workers)
    by_url = {r.url: r for r in results}

    for item in items:
        r = by_url[item["url"]]
        reg.record_check(
            item["resource_id"],
            access_status=r.access_status,
            http_status=r.http_status,
            final_url=r.final_url,
            content_type=r.content_type,
            bytes_read=r.bytes_read,
            robots_allowed=r.robots_allowed,
            error=r.error,
        )
        print("%-22s %-10s %-4s bytes=%-7s robots=%-5s %s" % (
            item["resource_id"], r.access_status, r.http_status,
            r.bytes_read, r.robots_allowed, (r.title or r.error)[:60]))

    print()
    stats = reg.stats()
    print("汇总:", stats["access_status"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
