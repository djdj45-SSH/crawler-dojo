"""L4 · 数据不在 HTML 里

列表页返回一个空壳，正文由一段脚本在浏览器里现拼。用 BeautifulSoup 解析
会得到零条记录 —— 页面上只有 "Loading…"。

但这一级真正想教的不是"上浏览器"
------------------------------------
而是**先看看有没有更省事的入口**。

HTML 里没有数据，不代表数据拿不到。真实世界里数据通常还有一个来源：
  · 一个没有写在文档里的 JSON 接口
  · 一个前端的 JS 载荷（就是本级的做法）
  · 打包产物里的一个常量对象

上浏览器渲染是**最后手段**：慢几十倍、依赖浏览器、容易在 CI 里挂。
它的正确位置是"确认没有别的路之后"。

本级的正解顺序：
  1. 读 <script src> 指向的文件 → /static/dojo-data.js 里有完整数据；
  2. 找不到再上 Playwright（见 crawler-labs 的 lab07）。

对照案例见第 6 章：游戏站 blockwild-game 的数据藏在 src/sim/*.js 深处，
连一个规整的载荷文件都没有 —— 那才是"必须上浏览器"的处境。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

from .base import DojoState, Guard


class JsShellGuard(Guard):
    level = "L4"

    async def check(self, request: Request, state: DojoState) -> Response | None:
        path = request.url.path
        payload = self.config.get("payload", "/static/dojo-data.js")

        # JSON 接口也一并关掉 —— 否则"HTML 没数据"就成了假问题，
        # 读者会直接绕过 HTML 去调接口，学不到任何东西。
        if path == "/api/articles":
            return Response(
                '{\n  "error": "not_found",\n'
                '  "note": "此模式下不提供 JSON 接口。数据只在页面运行时请求一次。"\n}\n',
                status_code=404,
                media_type="application/json; charset=utf-8",
            )

        if path == "/" or path.startswith("/posts/"):
            return self.block(
                "shell.html",
                status=200,
                PAYLOAD=payload,
                SHELL_MARKER=self.config.get("shell_marker", "dojo-shell"),
            )

        return None
