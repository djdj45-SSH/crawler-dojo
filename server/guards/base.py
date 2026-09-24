"""防护基类与共享工具。

设计要点
--------
每个 guard 只回答一个问题：**这次请求该不该被拦？**

    return None        → 放行，交给下一级
    return Response    → 拦截（内容由 guard 决定）

为什么响应头不在这里设
----------------------
levels.json 里已经声明了 signal.header / signal.value。如果每个 guard 各写一遍，
迟早和契约漂移。所以 guard 只管**响应内容**，main.py 统一补**契约信号头** ——
爬虫侧断言的是契约里那个头，两边不可能对不上。
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from fastapi import Request
from fastapi.responses import Response

HERE = pathlib.Path(__file__).resolve().parent
PAGES = HERE.parent / "pages"
DATA = HERE.parent / "data"

# 只匹配"形状像占位符"的东西：{{全大写字母和下划线}}
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")


class DojoState:
    """进程内共享状态。

    靶场是单进程的，用内存就够 —— 不引入 Redis 是刻意的：
    读者 clone 下来就能跑，不该为了一个练习去装中间件。
    """

    def __init__(self, secret: str) -> None:
        self.secret = secret
        # 限流窗口：{ip: [单调时间戳, ...]}
        self.windows: dict[str, list[float]] = {}

    def reset(self) -> None:
        self.windows.clear()


def load_articles() -> list[dict[str, Any]]:
    return json.loads((DATA / "articles.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 共享视图
#
# 真列表页和蜜罐列表页共用这两个函数。这不是为了省事 —— 是蜜罐的本质：
# 它必须和真页面长得一模一样，否则一眼就露馅了。
# 真假的分界只在"喂给视图的数据从哪来"。
# --------------------------------------------------------------------------

def render_items(articles: list[dict[str, Any]]) -> str:
    """渲染列表条目片段。"""
    rows = []
    for a in articles:
        tags = "".join(f'<span class="tag">{t}</span>' for t in a.get("tags", []))
        rows.append(
            f'    <li>\n'
            f'      <a href="/posts/{a["slug"]}.html">{a["title"]}</a>\n'
            f'      <div class="meta">{a["published_at"]} · {a.get("word_count", "?")} 字</div>\n'
            f'      <div class="tags">{tags}</div>\n'
            f'      <p class="summary">{a.get("summary", "")}</p>\n'
            f'    </li>'
        )
    return "\n".join(rows)


def article_page(article: dict[str, Any]) -> str:
    """渲染单篇文章页。"""
    return render_page(
        "article.html",
        TITLE=article["title"],
        DATE=article["published_at"],
        SLUG=article["slug"],
        BODY="".join(f"<p>{para}</p>" for para in article["body"].split("\n\n")),
        WORDS=str(article.get("word_count", "")),
        TAGS="".join(f'<span class="tag">{t}</span>' for t in article.get("tags", [])),
    )


def render_page(name: str, **tokens: str) -> str:
    """读 pages/ 下的模板并做占位符替换。

    两重防呆（踩过一次，代价是整站 500）：
      1. 传入的每个 key，模板里必须**真的存在**占位符 —— 拼错了名字要立刻报错，
         否则你会得到一个安静地缺了内容的页面。
      2. 替换后不得**残留**形状像占位符的东西。

    第 2 条的匹配要用 `{{大写字母和下划线}}` 这种严格形状，
    不能简单地用 `"{{" in line and "}}" in line` ——
    注释里写一句 `双花括号占位符` 的说明就会被误判成残留，
    而误判发生在请求处理路径上，表现是 500，排查起来非常绕。
    """
    raw = (PAGES / name).read_text(encoding="utf-8")
    html = raw

    for key, value in tokens.items():
        token = "{{" + key + "}}"
        if token not in raw:
            raise RuntimeError(f"{name} 里找不到占位符 {token}（检查 key 拼写）")
        html = html.replace(token, value)

    leftover = PLACEHOLDER_RE.search(html)
    if leftover:
        raise RuntimeError(f"{name} 渲染后仍残留占位符 {leftover.group(0)}")
    return html


class Guard:
    """所有防护的基类。子类只需实现 check()。"""

    level: str = ""

    def __init__(self, level_cfg: dict[str, Any]) -> None:
        self.cfg = level_cfg

    @property
    def name(self) -> str:
        return self.cfg.get("name", self.level)

    @property
    def config(self) -> dict[str, Any]:
        return self.cfg.get("config") or {}

    def block(self, filename: str, status: int, **tokens: str) -> Response:
        """构造一个拦截响应。信号头由 main.py 补，这里不管。"""
        text = render_page(
            filename,
            LEVEL=self.level,
            NAME=self.name,
            **tokens,
        )
        return Response(text, status_code=status, media_type="text/html; charset=utf-8")

    async def check(self, request: Request, state: DojoState) -> Response | None:
        raise NotImplementedError
