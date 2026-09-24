"""L1 · UA 黑名单

最粗的一层，也最容易被误当成"反爬"的全部。
它教的是两件事：
  1. 默认 UA 会主动暴露你的身份 —— python-requests 相当于敲门时自报家门；
  2. 被挡之后有两条路 —— 伪装成浏览器，或声明自己的爬虫。**后者才会被放行**。

第 2 点是这一级的重点。伪装是能过，但真实站点会继续针对你（换检测维度）；
声明身份才会进入白名单，从"对抗"变成"被接纳"。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

from .base import DojoState, Guard


class UaGuard(Guard):
    level = "L1"

    async def check(self, request: Request, state: DojoState) -> Response | None:
        ua = (request.headers.get("user-agent") or "").lower()
        if not ua:
            return self.block(
                "bot_403.html",
                status=403,
                REASON="请求里没有 User-Agent",
                HINT="连身份都不带，比带一个库的默认 UA 更容易被识别。",
            )

        blocked = [t for t in self.config.get("block", []) if t.lower() in ua]
        if not blocked:
            return None

        return self.block(
            "bot_403.html",
            status=403,
            REASON=f"User-Agent 命中黑名单：<code>{blocked[0]}</code>",
            HINT=(
                "改 UA 能过。但更好的做法是声明身份 —— "
                "请求头里带标识与联系方式的客户端会被白名单放行，"
                "规则见 <code>/__dojo/contract</code> 的 whitelist 段。"
            ),
        )
