# crawler-dojo —— 爬虫靶场

**同一份数据，六级递增的防护。** 用来练"爬虫遇到防护该怎么办"，以及反过来理解"防护到底拦住了什么"。

内容全部虚构（主题是一台叫 DOJO-1 的温湿度记录仪），所以你可以把防护开到满级，
不必担心碰到别人的站。**这是这个仓库存在的前提。**

配套的教学项目是 [**crawler-labs**](https://github.com/djdj45-SSH/crawler-labs) ——
那边是"攻"，这边是"守"。真实站点的对照案例：本项目的博客
[blog.djdj45.top](https://blog.djdj45.top) 用的就是同一套思路
（边缘重定向 + 静态 trap 页），配置见 `cloudflare/README.md`。

> 不加 shields.io 徽章是有意的：那个服务在国内经常加载不出来，会显示成裂图。
> 纯文本链接在任何网络下都能用。

---

## 快速开始

```bash
pip install -r requirements.txt

python -m server.main                 # 全开（L1–L5）
python -m server.main --level none    # 只跑 L0，裸爬畅通
python -m server.main --level L0,L1   # 只开 UA 黑名单
python -m server.main --port 9000     # 换端口
```

起来之后：

```bash
curl http://127.0.0.1:8000/__dojo/contract   # 契约（爬虫侧唯一的对接依据）
curl http://127.0.0.1:8000/api/articles      # 数据
curl -A "DojoBot/1.0" http://127.0.0.1:8000/ # 白名单放行
```

浏览器打开 <http://127.0.0.1:8000/> 也能看。

---

## 六级防护

| 级 | 手段 | 状态码 | 信号头 | 教什么 |
|---|---|---|---|---|
| **L0** | 无 | 200 | — | 先建立基线：确认能拿到数据 |
| **L1** | UA 黑名单 | 403 | `X-Dojo-Block: ua` | 默认 UA 会暴露身份；声明身份 vs 伪装 |
| **L2** | 滑动窗口限流 | 429 | `X-Dojo-Block: ratelimit` | 退避重试、`Retry-After`、**限流为什么会误伤** |
| **L3** | 蜜罐数据 | 200 | `X-Dojo-Signal: honeypot` | **数据校验** —— 爬到的东西是假的 |
| **L4** | 空壳 + JS 载荷 | 200 | `X-Dojo-Signal: js-shell` | HTML 里没有数据时，先找数据源再上浏览器 |
| **L5** | 时效签名 | 403 | `X-Dojo-Block: signature` | HMAC + 时间窗；签名为什么拦得住重放 |

每级的完整定义（预期状态码、信号头、教学点、配置）都在 **`levels.json`**。

### 三级里藏着三个反直觉的点

**L2：本机跑靶场，你和爬虫是同一个 IP。** 所以 L2 一开，你自己在浏览器里刷新也会被限流。
这不是 bug —— 这就是限流的真实困境，也是白名单存在的理由。

**L3：状态码是 200，不是错误。** 裸爬的脚本会安安静静地把垃圾写进数据库，
第二天看报表才发现数字不对。四种破绽（未来日期 / 正文重复 / 死链 / 数字矛盾）
都是机械可判的，`tools/selftest.py` 里逐个断言了。

**L4：数据在 `/static/dojo-data.js` 里，不在 HTML 里。** 正解有两条，但请按顺序试：
先读载荷文件，再考虑上浏览器。渲染是最后手段，不是第一手段 ——
那几十倍的耗时和 CI 里的不稳定，都是你自己写出来的。

---

## 契约：为什么规则不写在爬虫仓库里

爬虫侧（`crawler-labs`）启动时先请求 `GET /__dojo/contract`，再按契约跑。

如果把"第几级是什么、预期什么状态码"在两边各写一遍，**它们一定会漂移** ——
改了靶场忘了改爬虫，读者跑出来是错的，然后他会以为是自己的代码写错了。

抽成契约之后：

- 加一级防护 = 改 `levels.json` + 加一个 guard，**爬虫仓库一行都不用动**
- 契约本身也是一个教学点：服务端声明自己的规则，客户端去适配 —— 这是真实世界的对接方式
- `runtime.active_levels` 会告诉你当前实际生效的是哪几级，不必猜

契约端点 `/__dojo/*` **在任何等级下都不会被拦**。这是刻意留的：爬虫需要能区分
"被拦是设计如此"和"目标挂了"。

---

## 白名单

`User-Agent` 含 `dojobot` 的请求**跳过全部防护**，直接拿到真数据，并带上
`X-Dojo-Allow: whitelist` 响应头。

```bash
curl -A "DojoBot/1.0 (+https://blog.djdj45.top/about.html)" http://127.0.0.1:8000/api/articles
```

这是全项目的礼貌爬虫约定：**声明身份 + 留联系方式**。它同时让 L2 和 L3 的教学成立 ——
你能看到"守规矩的客户端"和"不声明的客户端"拿到的东西完全不同。

注意这里的取向：L1 教的是"改 UA 能过"，但**能过 ≠ 被接纳**。
伪装成浏览器你只是不再被这一条规则针对；声明身份才会进入白名单。

---

## 目录结构

```
crawler-dojo/
├── levels.json            契约：唯一事实来源（同时由 /__dojo/contract 暴露）
├── requirements.txt
├── server/
│   ├── main.py            FastAPI 入口，装配防护链
│   ├── guards/
│   │   ├── base.py        基类 + 共享视图（真页面和蜜罐页共用一套视图）
│   │   ├── l1_ua.py
│   │   ├── l2_ratelimit.py
│   │   ├── l3_honeypot.py
│   │   ├── l4_jschallenge.py
│   │   └── l5_signature.py
│   ├── data/articles.json 靶场内容（全虚构）
│   └── pages/             页面模板
├── tools/selftest.py      自检：66 项断言
└── cloudflare/            上云版（对照真实 Pages 环境）
```

**没有 `l0_none.py`。** L0 在契约里 `guard` 是 `null` —— 它是"无防护"基线。
写一个什么都不做的 guard 只会让人误以为它做了点什么，空实现比缺失实现更糟。

---

## 自检

```bash
python tools/selftest.py
```

逐级断言防护行为与契约一致，包括：L3 的四种破绽**都能被机械检出**、
L5 的签名确实绑定路径且时间窗生效、契约端点在所有等级下都可达。

改完 guard 或契约都跑一遍。这个脚本是"守"这一侧的可信度闸门 ——
靶场要是不准，读者练出来的结论就是错的。

---

## 上云版

`cloudflare/` 下是同一套防护在真实边缘环境里的两种实现，
以及它们**代价上的差别**（一个是零配额，一个会消耗 Pages Functions 的每日额度）。
见 [`cloudflare/README.md`](cloudflare/README.md)。

---

## 声明

- 靶场内容全部虚构，与任何真实站点无关
- 这里练的是"自己的站被爬时该怎么守"，以及"自己的爬虫该怎么守规矩"
- **L1–L5 都是演示用规则，不是绕过别人站点的教程。**
  L5 的密钥是公开的，因为这一课教的是机制，不是保密
