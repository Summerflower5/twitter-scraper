# src/cli.py
import argparse
import asyncio
import json
from pathlib import Path

from scraper import Scraper


def save_output(path: str, data, fmt: str = "json"):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        with p.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        with p.open("w", encoding="utf-8") as f:
            for d in data:
                f.write((d.get("content") or d.get("text") or "") + "\n")

async def _run(user: str, limit: int, out: str, fmt: str):
    scr = Scraper(user, limit)
    data = await scr.scrape()
    save_output(out, data, fmt)
    print(f">>> 已保存 {len(data)} 条到 {out} (format={fmt})")

def main():
    parser = argparse.ArgumentParser(description="Twitter single-user scraper (requests + Playwright fallback)")
    parser.add_argument("--user", "-u", required=True, help="目标用户名，不带 @")
    parser.add_argument("--limit", "-n", type=int, default=50, help="最多抓取条数")
    parser.add_argument("--out", "-o", default="examples/output.json", help="输出文件路径")
    parser.add_argument("--format", "-f", choices=["json","txt"], default="json", help="输出格式")
    args = parser.parse_args()
    asyncio.run(_run(args.user, args.limit, args.out, args.format))

if __name__ == "__main__":
    main()
