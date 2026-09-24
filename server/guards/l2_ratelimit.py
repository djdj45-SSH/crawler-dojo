"""L2 · 滑动窗口限流

用最朴素的滑动窗口（list 当队列），不引第三方库 ——
读者应该能一眼看懂计数是怎么算的。

这一级最值得讲的不是算法，是**误伤**
---------------------------------------
本机跑靶场时，爬虫和你自己的浏览器是同一个 IP。所以 L2 一开，
你自己刷新页面也会被挡。这不是 bug，是限流的真实困境：

  · 按 IP 限流 → 同一 NAT 后的正常用户互相拖累
  · 按 UA 限流 → 换一个 UA 就绕过
  · 不设限流 → 被单个源压垮

真实站点用的从来不是单一维度。而白名单正是缓解误伤的第一手段 ——
本靶场让白名单绕过全部防护，就是为了让这个取舍看得见。
"""

from __future__ import annotations

import time

from fastapi import Request
from fastapi.responses import Response

from .base import DojoState, Guard


class RateLimitGuard(Guard):
    level = "L2"

    async def check(self, request: Request, state: DojoState) -> Response | None:
        limit = int(self.config.get("requests", 5))
        window = float(self.config.get("window_seconds", 10))

        client = request.client
        ip = client.host if client else "unknown"
        now = time.monotonic()

        bucket = state.windows.setdefault(ip, [])

        # 丢掉滑出窗口的记录
        cutoff = now - window
        while bucket and bucket[0] <= cutoff:
            bucket.pop(0)

        if len(bucket) >= limit:
            # Retry-After 是这一级的核心教学点：它把"该等多久"明确告诉客户端。
            # 无视它的爬虫会一直在窗口边缘撞墙，而懂得退避的重试一次就过。
            retry_after = max(1, int(window - (now - bucket[0])) + 1)
            resp = self.block(
                "bot_429.html",
                status=429,
                REASON=f"{window:g} 秒内已请求 {len(bucket)} 次，上限 {limit} 次",
                HINT=(
                    "读 <code>Retry-After</code> 响应头并退避重试，不要原地重试。"
                    f"本次建议等待 {retry_after} 秒。"
                ),
                RETRY=str(retry_after),
            )
            resp.headers["Retry-After"] = str(retry_after)
            return resp

        bucket.append(now)
        return None
