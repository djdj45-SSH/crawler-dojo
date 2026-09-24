"""crawler-dojo —— 本地爬虫靶场。

包结构：
    server/main.py           FastAPI 入口，装配防护链，提供契约端点
    server/guards/           六级防护的实现（L0 是"无守卫"）
    server/data/             靶场内容（全虚构）
    server/pages/            页面模板
    tools/selftest.py        自检：逐级断言防护行为
    cloudflare/              上云版（对照真实 Pages 环境）
"""

__version__ = "0.1.0"
