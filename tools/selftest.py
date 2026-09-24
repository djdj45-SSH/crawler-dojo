#!/usr/bin/env python
"""crawler-dojo 自检：逐级断言"防护行为"与"契约"一致。

为什么必须有这个脚本
--------------------
靶场是"守"的一侧。它对不对，直接决定爬虫练习得出的结论可不可信 ——
改了 guard 忘了改契约、或者反过来，读者会跑出一个错误的通过矩阵，
而他会以为是自己的代码写错了。

这个脚本就是那道闸门：契约、实现、行为三者必须同时自洽。

跑法
----
    python tools/selftest.py

退出码 0 = 全部通过。CI 里可以直接挂。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from server.guards import GUARDS  # noqa: E402
from server.main import create_app, load_contract  # noqa: E402

BARE_UA = "python-requests/2.31.0"
GOOD_UA = "DojoBot/1.0 (+https://blog.djdj45.top/about.html)"


class Harness:
    def __init__(self) -> None:
        self.passed = 0
        self.failures: list[tuple[str, str]] = []

    def ok(self, cond: bool, label: str, detail: str = "") -> bool:
        if cond:
            self.passed += 1
            print(f"  \u2713 {label}")
        else:
            self.failures.append((label, detail))
            print(f"  \u2717 {label}")
            if detail:
                print(f"      {detail}")
        return cond

    def eq(self, got, want, label: str) -> bool:
        return self.ok(got == want, label, f"期望 {want!r}，实际 {got!r}")

    def section(self, title: str) -> None:
        print(f"\n{title}")

    def report(self) -> int:
        print("\n" + "\u2500" * 58)
        if self.failures:
            print(f"失败 {len(self.failures)} 项，通过 {self.passed} 项：")
            for label, detail in self.failures:
                print(f"  \u2717 {label}")
                if detail:
                    print(f"      {detail}")
            return 1
        print(f"全部通过（{self.passed} 项断言）")
        return 0


def client_for(spec: str) -> TestClient:
    return TestClient(create_app(spec))


def main() -> int:
    h = Harness()
    contract = load_contract()
    levels = {lv["id"]: lv for lv in contract["levels"]}

    # ---------------------------------------------------------- 数据自洽
    h.section("⓪ 数据自洽")

    data_path = ROOT / "server" / "data" / "articles.json"
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
        h.ok(isinstance(raw, list) and raw, f"articles.json 可解析，{len(raw)} 条")
        required = {"slug", "title", "published_at", "tags", "body", "word_count", "summary"}
        missing = [a.get("slug", "?") for a in raw if not required <= set(a)]
        h.ok(not missing, "每条记录字段齐全", f"缺字段：{missing}")
        dupes = {a["slug"] for a in raw}
        h.eq(len(dupes), len(raw), "slug 不重复")
        h.ok(
            not any("honeypot" in a["slug"] for a in raw),
            "真数据里不含 honeypot 条目（蜜罐是运行时生成的）",
        )
    except json.JSONDecodeError as exc:
        h.ok(False, "articles.json 是合法 JSON", str(exc))

    # ---------------------------------------------------------- 契约自洽
    h.section("② 契约自洽")

    h.ok(contract.get("version") == 1, "契约 version = 1")
    h.ok(
        "contains" in (contract.get("whitelist") or {}),
        "whitelist.contains 存在（白名单是 L1–L5 的唯一出口）",
    )

    for want in ["L0", "L1", "L2", "L3", "L4", "L5"]:
        h.ok(want in levels, f"契约里有 {want}")

    h.ok(levels["L0"].get("guard") is None, "L0 的 guard 为 null（基线，没有守卫）")

    for lv in contract["levels"]:
        g = lv.get("guard")
        if g is None:
            continue
        h.ok(g in GUARDS, f"{lv['id']} 的 guard '{g}' 在注册表里")
        sig = lv.get("signal") or {}
        h.ok(
            bool(sig.get("header")) and sig.get("value") is not None,
            f"{lv['id']} 声明了 signal.header / signal.value",
        )

    # ---------------------------------------------------------- L0 基线
    h.section("② L0 基线：裸爬必须畅通")

    with client_for("none") as c:
        r = c.get("/api/articles", headers={"User-Agent": BARE_UA})
        h.eq(r.status_code, 200, "默认 UA 拿到 200")
        data = r.json()
        h.ok(isinstance(data, list) and len(data) > 0, f"拿到 {len(data)} 条真数据")
        h.ok(
            all("dojo-honeypot" not in a["slug"] for a in data),
            "真数据里没有蜜罐条目",
        )
        h.ok("X-Dojo-Block" not in r.headers, "L0 不产生拦截信号头")

    # ---------------------------------------------------------- L1
    h.section("③ L1 UA 黑名单")

    with client_for("L1") as c:
        r = c.get("/api/articles", headers={"User-Agent": BARE_UA})
        h.eq(r.status_code, levels["L1"]["expect_status"], "默认 UA 被 403")
        h.eq(r.headers.get("X-Dojo-Block"), "ua", "信号头 X-Dojo-Block: ua")
        h.eq(r.headers.get("X-Dojo-Level"), "L1", "X-Dojo-Level: L1")

        r = c.get("/api/articles", headers={"User-Agent": ""})
        h.eq(r.status_code, 403, "没有 UA 也会被挡（比带库 UA 更可疑）")

        r = c.get("/api/articles", headers={"User-Agent": GOOD_UA})
        h.eq(r.status_code, 200, "白名单 UA 放行")
        h.eq(r.headers.get("X-Dojo-Allow"), "whitelist", "白名单信号头 X-Dojo-Allow")

    # ---------------------------------------------------------- L2
    h.section("④ L2 频率限制")

    with client_for("L2") as c:
        limit = levels["L2"]["config"]["requests"]
        codes = []
        for _ in range(limit + 1):
            codes.append(c.get("/api/articles", headers={"User-Agent": BARE_UA}).status_code)
        h.ok(
            codes[:limit] == [200] * limit,
            f"前 {limit} 次都是 200",
            f"实际 {codes}",
        )
        h.eq(codes[-1], levels["L2"]["expect_status"], f"第 {limit + 1} 次被 429")

        r = c.get("/api/articles", headers={"User-Agent": BARE_UA})
        h.ok("Retry-After" in r.headers, "429 带 Retry-After（退避重试的依据）")
        h.eq(r.headers.get("X-Dojo-Block"), "ratelimit", "信号头 X-Dojo-Block: ratelimit")

        # 白名单绕过限流 —— 这是"声明身份的好处"这一课的直接证据
        r = c.get("/api/articles", headers={"User-Agent": GOOD_UA})
        h.eq(r.status_code, 200, "白名单 UA 不受限流影响")

    # ---------------------------------------------------------- L3
    h.section("⑤ L3 蜜罐：四种破绽必须都能被机械检出")

    with client_for("L3") as c:
        r = c.get("/api/articles", headers={"User-Agent": BARE_UA})
        h.eq(r.status_code, 200, "蜜罐返回 200（不是错误，是陷阱）")
        h.eq(r.headers.get("X-Dojo-Signal"), "honeypot", "信号头 X-Dojo-Signal: honeypot")
        fakes = r.json()
        h.ok(len(fakes) > 0, f"拿到 {len(fakes)} 条记录")

        today = time.strftime("%Y-%m-%d")

        # F1 未来日期
        future = [f for f in fakes if f["published_at"] > today]
        h.ok(len(future) == len(fakes), f"F1 未来日期：{len(future)}/{len(fakes)} 条晚于今天")

        # F2 正文重复
        hashes = {hashlib.sha1(f["body"].encode()).hexdigest() for f in fakes}
        h.eq(len(hashes), 1, "F2 正文重复：所有条目正文的 sha1 只有一个值")

        # F3 死链
        r = c.get(fakes[0]["url"], headers={"User-Agent": BARE_UA})
        h.eq(r.status_code, 404, "F3 死链：假条目的 url 确实 404")

        # F4 数字矛盾
        ratio = fakes[0]["word_count"] / max(1, len(fakes[0]["body"]))
        h.ok(ratio > 3, f"F4 数字矛盾：word_count 是实际长度的 {ratio:.1f} 倍")

        # 白名单拿到的是真数据，不是蜜罐
        r = c.get("/api/articles", headers={"User-Agent": GOOD_UA})
        real = r.json()
        h.ok(
            all("dojo-honeypot" not in a["slug"] for a in real),
            "白名单拿到真数据（蜜罐只喂给未声明身份的客户端）",
        )

    # ---------------------------------------------------------- L4
    h.section("⑥ L4 空壳：HTML 里不能有数据")

    with client_for("L4") as c:
        r = c.get("/", headers={"User-Agent": BARE_UA})
        h.eq(r.status_code, 200, "列表页返回 200")
        h.eq(r.headers.get("X-Dojo-Signal"), "js-shell", "信号头 X-Dojo-Signal: js-shell")
        html = r.text
        h.ok(
            f'data-shell="{levels["L4"]["config"]["shell_marker"]}"' in html,
            "空壳标记存在",
        )

        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")
            items = soup.select("#dojo-list li")
            h.eq(len(items), 0, "用 BeautifulSoup 解析：列表条目数为 0（数据确实不在 HTML 里）")
        except ImportError:
            h.ok("dojo-list" in html, "（未装 bs4，退化为字符串检查）空壳容器存在")

        r = c.get("/api/articles", headers={"User-Agent": BARE_UA})
        h.eq(r.status_code, 404, "JSON 接口被关闭 —— 逼你去找真正的数据源")

        r = c.get(levels["L4"]["config"]["payload"], headers={"User-Agent": BARE_UA})
        h.eq(r.status_code, 200, "载荷文件可取（这是本级的正解之一）")
        h.ok("DOJO_ARTICLES" in r.text, "载荷里有 DOJO_ARTICLES")

    # ---------------------------------------------------------- L5
    h.section("⑦ L5 时效签名")

    cfg = levels["L5"]["config"]
    secret = cfg["dev_secret"]

    def sign(path: str, ts: int) -> str:
        msg = cfg["message"].format(path=path, ts=ts)
        return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

    with client_for("L5") as c:
        path = "/api/articles"

        r = c.get(path, headers={"User-Agent": BARE_UA})
        h.eq(r.status_code, 403, "没有签名 → 403")
        h.eq(r.headers.get("X-Dojo-Block"), "signature", "信号头 X-Dojo-Block: signature")

        ts = int(time.time())
        r = c.get(
            path,
            headers={"User-Agent": BARE_UA, cfg["ts_header"]: str(ts), cfg["token_header"]: "0" * 64},
        )
        h.eq(r.status_code, 403, "签名错误 → 403")

        r = c.get(
            path,
            headers={
                "User-Agent": BARE_UA,
                cfg["ts_header"]: str(ts),
                cfg["token_header"]: sign(path, ts),
            },
        )
        h.eq(r.status_code, 200, "签名正确且在时间窗内 → 200")

        # 签名绑路径：拿 /api/articles 的签名去请求 / 应当失败
        r = c.get(
            "/",
            headers={
                "User-Agent": BARE_UA,
                cfg["ts_header"]: str(ts),
                cfg["token_header"]: sign(path, ts),
            },
        )
        h.eq(r.status_code, 403, "签名绑定路径：跨路径复用同一签名 → 403")

        # 过期签名
        old = ts - cfg["window_seconds"] * 3
        r = c.get(
            path,
            headers={
                "User-Agent": BARE_UA,
                cfg["ts_header"]: str(old),
                cfg["token_header"]: sign(path, old),
            },
        )
        h.eq(r.status_code, 403, "过期签名 → 403（时间窗挡住的正是重放）")

    # ---------------------------------------------------------- 契约端点
    h.section("⑧ 契约端点在任何等级下都必须可达")

    for spec in ["none", "L1", "L3", "L5", "all"]:
        with client_for(spec) as c:
            r = c.get("/__dojo/contract", headers={"User-Agent": BARE_UA})
            h.eq(r.status_code, 200, f"--level {spec} 下 /__dojo/contract 可达")

    with client_for("all") as c:
        doc = c.get("/__dojo/contract").json()
        h.eq(
            doc["runtime"]["active_levels"],
            ["L1", "L2", "L3", "L4", "L5"],
            "all 的生效等级是 L1–L5（L0 是基线，不在链上）",
        )
        h.ok("flaws" in json.dumps(doc), "契约里带上了 L3 的破绽清单")

    return h.report()


if __name__ == "__main__":
    raise SystemExit(main())
