"""L3 · 蜜罐数据

前三级的失败都是"被挡住"——看得见，会报错，爬虫知道要处理。
这一级的失败是**看不见的**：状态码 200、结构完全正确、字段一个不少，
但每一个值都是假的。裸爬的脚本会安安静静地把垃圾写进数据库，
而且第二天看报表才发现数字不对劲。

四种破绽（都是机械可判的，契约 levels[L3].flaws 里也列了）
------------------------------------------------------------
  F1 未来日期   published_at 晚于当前日期
  F2 正文重复   8 条记录的 body 完全相同（比对 sha1 一行就能发现）
  F3 死链       url 指向的 /posts/dojo-honeypot-*.html 实际不存在
  F4 数字矛盾   word_count 是正文实际长度的 5 倍

真实的蜜罐不会留这么明显的破绽。这里刻意做浅，是为了让校验方法可教：
先把四种校验方法（时间范围 / 重复率 / 链接可达性 / 字段自洽）各写一遍，
再换成真站点时你只是把阈值调紧，方法本身不用改。

为什么只拦列表端点，不拦详情页
--------------------------------
因为 F3 要成立 —— 死链必须是真死的。如果详情页也返回假内容，
那"链接可达性"这条校验就永远发现不了问题。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from fastapi import Request
from fastapi.responses import Response

from .base import DojoState, Guard, render_items, render_page

# 所有假条目共用同一段正文 —— 这就是 F2
_SHARED_BODY = (
    "本机在恒温箱内完成了一轮标定，参考电压偏移 0.4%，重复三次的离散度小于 0.1%。"
    "详细步骤见附录，结论是这批传感器可以直接入库。"
)

_TITLES = [
    "DOJO-1 参考电压二次标定记录",
    "湿度通道零点漂移复核",
    "长期记录的存储分区调整",
    "串口重传机制的压力测试",
    "上位机解析脚本的边界用例",
    "低温段读数的异常复核",
    "传感器批次一致性抽检",
    "电源模块纹波对读数的影响",
]


def fake_records(count: int, today: date | None = None) -> list[dict]:
    """确定性生成假记录 —— 同一台机器每次跑出来完全一样，便于写断言。"""
    today = today or date.today()
    body_len = len(_SHARED_BODY)
    records = []
    for i in range(count):
        slug = f"dojo-honeypot-{i + 1:02d}"
        records.append(
            {
                "slug": slug,
                # F1：未来日期 —— 站点不可能有"明天发布"的文章
                "published_at": (today + timedelta(days=9 + i)).isoformat(),
                "title": _TITLES[i % len(_TITLES)],
                "tags": ["calibration", "baseline"],
                "summary": "标定与复核记录。",
                # F2：所有条目正文逐字节相同
                "body": _SHARED_BODY,
                "body_sha1": hashlib.sha1(_SHARED_BODY.encode("utf-8")).hexdigest(),
                # F4：声称的字数是实际的 5 倍
                "word_count": body_len * 5,
                # F3：详情页并不存在
                "url": f"/posts/{slug}.html",
            }
        )
    return records


class HoneypotGuard(Guard):
    level = "L3"

    async def check(self, request: Request, state: DojoState) -> Response | None:
        path = request.url.path
        records = fake_records(int(self.config.get("fake_count", 8)))

        if path == "/api/articles":
            return Response(
                json.dumps(records, ensure_ascii=False, indent=2),
                status_code=200,
                media_type="application/json; charset=utf-8",
            )

        if path == "/":
            html = render_page(
                "list.html",
                COUNT=str(len(records)),
                ITEMS=render_items(records),
            )
            return Response(html, status_code=200, media_type="text/html; charset=utf-8")

        return None
