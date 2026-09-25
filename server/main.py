"""crawler-dojo —— 本地爬虫靶场。

同一份数据，六级递增的防护。契约（levels.json）是唯一事实来源，
通过 GET /__dojo/contract 暴露给爬虫侧。

用法
----
    python -m server.main                    # 全开（L1–L5）
    python -m server.main --level none       # 只跑 L0，裸爬畅通
    python -m server.main --level L0,L1      # 只开 UA 黑名单
    python -m server.main --level all --port 9000

换等级需要重启进程 —— 级别在启动时装配进防护链，不做热切换。
这是刻意的：靶场要可复现，不要在"到底哪一级在生效"上产生歧义。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from .guards import GUARDS, DojoState
from .guards.base import article_page, load_articles, render_items, render_page

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "levels.json"


def die(msg: str) -> None:
    sys.stderr.write(f"\n[dojo] 错误：{msg}\n")
    raise SystemExit(2)


def load_contract() -> dict:
    if not CONTRACT_PATH.exists():
        die(f"找不到契约文件 {CONTRACT_PATH}")
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def resolve_levels(contract: dict, spec: str) -> list[dict]:
    """把 --level 的写法解析成"实际生效的等级列表"。

    只返回**带 guard 的**等级 —— L0 是"无防护"基线，它没有守卫，
    这正好对应契约里 guard 为 null。
    """
    levels = contract["levels"]
    spec = (spec or "all").strip()

    if spec in ("all", "*"):
        return [lv for lv in levels if lv.get("guard")]
    if spec.lower() in ("none", "l0", ""):
        return []

    wanted = {s.strip().upper() for s in spec.split(",") if s.strip()}
    known = {lv["id"] for lv in levels}
    unknown = wanted - known
    if unknown:
        die(f"未知等级 {sorted(unknown)}；可选：{sorted(known)}，或 all / none")
    return [lv for lv in levels if lv["id"] in wanted and lv.get("guard")]


def create_app(level_spec: str = "all", *, secret: str | None = None) -> FastAPI:
    """按 level_spec 装配一个靶场实例。

    做成工厂函数而不是模块级单例，是为了让 self-test 能在同一个进程里
    分别装配"只开 L1""只开 L3"…… 逐个断言，互不干扰。
    """
    contract = load_contract()
    active = resolve_levels(contract, level_spec)
    guards = [GUARDS[lv["guard"]](lv) for lv in active]

    if secret is None:
        l5 = next((lv for lv in contract["levels"] if lv["id"] == "L5"), {})
        secret = (l5.get("config") or {}).get("dev_secret", "dojo-dev-secret")
    state = DojoState(secret=secret)

    whitelist_token = contract["whitelist"]["contains"].lower()

    app = FastAPI(
        title="crawler-dojo",
        description="本地爬虫靶场。契约见 /__dojo/contract。",
        docs_url=None,
        redoc_url=None,
    )
    app.state.dojo = state
    app.state.level_spec = level_spec

    @app.middleware("http")
    async def dojo_chain(request: Request, call_next):
        path = request.url.path

        # 契约与健康检查永远不被拦。
        # 否则爬虫没法知道"被拦是设计如此还是目标挂了" —— 这是自证性的前提。
        if path.startswith("/__dojo/"):
            return await call_next(request)

        ua = (request.headers.get("user-agent") or "").lower()
        if whitelist_token in ua:
            resp = await call_next(request)
            resp.headers["X-Dojo-Allow"] = "whitelist"
            return resp

        for guard in guards:
            hit = await guard.check(request, state)
            if hit is None:
                continue
            # 契约信号头在这里统一补 —— guard 只管内容，不管信号，
            # 这样契约里声明的 header/value 不可能和实现对不上。
            signal = guard.cfg.get("signal") or {}
            if signal.get("header"):
                hit.headers[signal["header"]] = str(signal.get("value", ""))
            hit.headers["X-Dojo-Level"] = guard.level
            hit.headers["Cache-Control"] = "no-store"
            return hit

        return await call_next(request)

    # ------------------------------------------------------------------ 契约

    @app.get("/__dojo/contract")
    def contract_route():
        doc = dict(contract)
        doc["runtime"] = {
            "level_spec": level_spec,
            "active_levels": [lv["id"] for lv in active],
            "chain": [g.level for g in guards],
            "note": "active_levels 为空表示当前是 L0 基线，裸爬畅通。",
        }
        return JSONResponse(doc)

    @app.get("/__dojo/health")
    def health():
        return {"ok": True, "active_levels": [lv["id"] for lv in active]}

    # ------------------------------------------------------------------ 内容

    @app.get("/", response_class=HTMLResponse)
    def index():
        arts = load_articles()
        return render_page("list.html", COUNT=str(len(arts)), ITEMS=render_items(arts))

    @app.get("/api/articles")
    def api_list():
        return JSONResponse(load_articles())

    @app.get("/posts/{slug}.html", response_class=HTMLResponse)
    def detail(slug: str):
        for a in load_articles():
            if a["slug"] == slug:
                return article_page(a)
        return PlainTextResponse("404 Not Found\n", status_code=404)

    @app.get("/static/dojo-data.js")
    def js_payload():
        """L4 的数据源。

        它是一个普通的、可以直接下载的文本文件 —— 这是本级的正解之一。
        真正的难点在下一档：数据由代码算出来，任何一个文件里都找不到它。
        本靶场刻意不做到那一步 —— 那已经是"要不要执行人家的代码"，
        会盖过这一级想讲的东西。
        """
        arts = load_articles()
        body = json.dumps(arts, ensure_ascii=False, indent=2)
        return Response(
            "// crawler-dojo · L4 载荷。列表页的条目由它构建。\n"
            f"window.DOJO_ARTICLES = {body};\n",
            media_type="application/javascript; charset=utf-8",
        )

    return app


# 便于 `uvicorn server.main:app --port 8000` 直接起（默认全开）
app = create_app("all")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="crawler-dojo",
        description="本地爬虫靶场：同一份数据，六级递增的防护。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="等级示例：none / L0 / L1 / L0,L1,L2 / all",
    )
    parser.add_argument("--level", default="all", help="生效的防护等级（默认 all）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1，只对本机开放）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    args = parser.parse_args(argv)

    contract = load_contract()
    active = resolve_levels(contract, args.level)
    chain = [lv["id"] for lv in active]

    base = f"http://{args.host}:{args.port}"
    print(f"crawler-dojo · 契约 v{contract['version']}")
    print(f"  生效等级  : {', '.join(chain) if chain else 'L0（无防护，裸爬畅通）'}")
    print(f"  白名单    : User-Agent 含 '{contract['whitelist']['contains']}' 的请求跳过全部防护")
    print(f"  契约端点  : {base}/__dojo/contract")
    print(f"  列表页    : {base}/")
    if "L2" in chain:
        print("  ⚠ L2 已开启：你和爬虫是同一个 IP，浏览器连续刷新也会被限流 —— 这是刻意的教学点。")
    if "L5" in chain:
        print("  ⚠ L5 已开启：密钥公开在契约里，但请求必须带时效签名，否则一律 403。")
    print()

    uvicorn.run(create_app(args.level), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
