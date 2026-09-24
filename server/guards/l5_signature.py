"""L5 · 时效签名

服务端要求每个请求带一个 HMAC 签名，签名内容包含**请求路径**和**时间戳**。
两个效果：

  · 签名绑定路径 → 抄一个签名不能拿去请求别的页面
  · 签名绑定时间 → 过期作废，重放无效

这一级拦得住的是"离线抄数据"：先把所有 URL 列出来，之后再慢慢抓。
有了时间窗，那份 URL 清单在 30 秒后就全部作废。

关于密钥是公开的
----------------
靶场把 dev_secret 直接写在契约里。这是有意的：
**这里教的是"签名为什么拦得住"，不是"怎么拿到密钥"。**
真实站点的密钥你永远拿不到，所以这一课的价值不在于能不能过，
而在于让你理解请求链路上到底被校验了什么 —— 之后你写自己的接口时，
才知道签名该怎么设计。

换言之：这是给"守"的一课，伪装成"攻"。
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Request
from fastapi.responses import Response

from .base import DojoState, Guard


class SignatureGuard(Guard):
    level = "L5"

    async def check(self, request: Request, state: DojoState) -> Response | None:
        cfg = self.config
        ts_header = cfg.get("ts_header", "X-Dojo-Ts")
        token_header = cfg.get("token_header", "X-Dojo-Token")
        window = int(cfg.get("window_seconds", 30))

        ts_raw = request.headers.get(ts_header)
        token = request.headers.get(token_header)

        if not ts_raw or not token:
            return self._reject(f"缺少 <code>{ts_header}</code> 或 <code>{token_header}</code> 请求头")

        try:
            ts = int(ts_raw)
        except ValueError:
            return self._reject(f"<code>{ts_header}</code> 不是整数：{ts_raw}")

        now = int(time.time())
        drift = now - ts
        if abs(drift) > window:
            return self._reject(
                f"时间戳超出 {window} 秒窗口（偏差 {drift} 秒）。"
                "签名绑定时间，过期即作废 —— 这正是它拦得住重放的原因。"
            )

        message = cfg["message"].format(path=request.url.path, ts=ts)
        expected = hmac.new(
            state.secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected, token):
            return self._reject(
                "签名不匹配。注意签名内容包含**请求路径**，"
                "换一个路径就得重新签 —— 抄一个签名不能跨页面复用。"
            )

        return None

    def _reject(self, reason: str) -> Response:
        return self.block(
            "bot_403.html",
            status=403,
            REASON=reason,
            HINT=(
                "签名算法与时间窗在 <code>/__dojo/contract</code> 的 levels[L5].config 里，"
                "密钥也是公开的 —— 这一级要理解的是链路，不是保密。"
            ),
        )
