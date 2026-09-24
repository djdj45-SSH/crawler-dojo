"""防护注册表。

名字（key）必须与 levels.json 里每一级的 `guard` 字段一致 ——
这是契约与实现之间的唯一接缝。

注意这里**没有 L0**
-------------------
L0 是"无防护"基线，它的 `guard` 在契约里是 `null`。
曾经想写一个 L0NoneGuard 让链条看起来整齐，但一个什么都不做的类只会让人
误以为它做了点什么 —— 空实现是比缺失实现更糟的文档。所以 L0 就是"没有守卫"。
"""

from __future__ import annotations

from typing import Type

from .base import DojoState, Guard, load_articles, render_page

from .l1_ua import UaGuard
from .l2_ratelimit import RateLimitGuard
from .l3_honeypot import HoneypotGuard
from .l4_jschallenge import JsShellGuard
from .l5_signature import SignatureGuard

GUARDS: dict[str, Type[Guard]] = {
    "ua": UaGuard,
    "ratelimit": RateLimitGuard,
    "honeypot": HoneypotGuard,
    "jschallenge": JsShellGuard,
    "signature": SignatureGuard,
}

__all__ = [
    "GUARDS",
    "Guard",
    "DojoState",
    "load_articles",
    "render_page",
    "UaGuard",
    "RateLimitGuard",
    "HoneypotGuard",
    "JsShellGuard",
    "SignatureGuard",
]
