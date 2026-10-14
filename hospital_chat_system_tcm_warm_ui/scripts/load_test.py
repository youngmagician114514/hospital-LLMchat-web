from __future__ import annotations

import argparse
import asyncio
import time

import httpx


async def _single_request(client: httpx.AsyncClient, url: str, idx: int) -> tuple[bool, float]:
    payload = {
        "session_id": f"load-{idx % 30}",
        "message": f"病例测试请求 {idx}",
        "use_server_history": False,
    }
    start = time.perf_counter()
    try:
        response = await client.post(url, json=payload)
        ok = response.status_code == 200
    except Exception:
        ok = False
    cost = time.perf_counter() - start
    return ok, cost


async def run_test(base_url: str, total: int, concurrency: int) -> None:
    url = f"{base_url.rstrip('/')}/api/chat"
    sem = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(15)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async def wrapped(idx: int) -> tuple[bool, float]:
            async with sem:
                return await _single_request(client, url, idx)

        start = time.perf_counter()
        results = await asyncio.gather(*(wrapped(i) for i in range(total)))
        duration = time.perf_counter() - start

    success = sum(1 for ok, _ in results if ok)
    failed = total - success
    avg_ms = (sum(cost for _, cost in results) / total) * 1000 if total else 0
    rps = total / duration if duration > 0 else 0

    print(f"target={url}")
    print(f"total={total}, concurrency={concurrency}")
    print(f"success={success}, failed={failed}")
    print(f"avg_latency_ms={avg_ms:.2f}")
    print(f"rps={rps:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple load test for /api/chat")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--total", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=100)
    args = parser.parse_args()

    asyncio.run(run_test(args.base_url, args.total, args.concurrency))


if __name__ == "__main__":
    main()
