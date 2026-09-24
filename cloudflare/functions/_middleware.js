/**
 * crawler-dojo · 上云版（Cloudflare Pages Function）
 * ---------------------------------------------------------------------------
 * 放置位置：functions/_middleware.js
 * 必须配套：同目录的 _routes.json（否则每个静态资源请求都会命中这里）
 *
 * 这是"同一套防护在真实边缘环境里"的实现之一，用来对照本地 FastAPI 版。
 * 完整的两种实现与代价对比见 cloudflare/README.md。
 *
 * ⚠️ 代价（这一版存在的意义就是让你看见它）
 *   本文件每执行一次 = 消耗 1 次 Workers / Pages Functions 请求配额。
 *   免费额度 10 万/天，且**与站点上的其他 Function（如留言板 /api）共用同一个池**。
 *   所以：必须在边缘先用限流挡一道（被 Block 的请求不会进到这里），
 *   并且**绝不要**把 Pages 项目设成 fail closed。
 *
 * 本地版没有这个问题 —— 本地没有配额。这也是为什么靶场主体跑 localhost：
 * 学习时不该被计量规则分心，理解了机制再去看代价。
 */

// 与契约（levels.json）的 whitelist 段一致：声明身份 + 留联系方式
const WHITELIST = ['dojobot'];

// 与契约的 L1.config.block 一致
const UA_BLOCK = [
  'python-requests', 'httpx', 'aiohttp', 'scrapy',
  'curl', 'wget', 'go-http-client', 'okhttp', 'java/',
  'node-fetch', 'axios', 'libwww-perl', 'python-urllib',
];

// 与契约的 L3 一致：蜜罐只喂给未声明身份的客户端
function honeypotResponse(reason, level, status) {
  const html = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>crawler-dojo · ${level}</title></head>
<body style="background:#0b0d10;color:#e8edf2;font-family:ui-monospace,Menlo,monospace;padding:40px;line-height:1.9">
<h1 style="font-size:18px">crawler-dojo · ${level}</h1>
<p style="color:#8b98a5">${reason}</p>
<p style="color:#8b98a5">这是上云版的对照实现。完整六级防护在本地靶场：
<code>python -m server.main</code>。</p>
</body></html>`;
  return new Response(html, {
    status,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      // 必须 no-store：否则 CDN 可能把"给爬虫的响应"缓存给真人
      'cache-control': 'no-store',
      'x-dojo-level': level,
      'x-robots-tag': 'noindex',
    },
  });
}

export async function onRequest(context) {
  const { request, next, env } = context;
  const url = new URL(request.url);
  const ua = (request.headers.get('user-agent') || '').toLowerCase();

  // 兜底：即使 _routes.json 配错了，也别让中间件包住留言板
  if (url.pathname.startsWith('/api/')) return next();
  if (url.pathname.startsWith('/__dojo/')) return next();

  // 白名单：跳过全部防护
  if (WHITELIST.some((k) => ua.includes(k))) {
    const res = await next();
    res.headers.set('x-dojo-allow', 'whitelist');
    return res;
  }

  // L1 · UA 黑名单
  const hit = UA_BLOCK.find((token) => ua.includes(token));
  if (hit) {
    const res = honeypotResponse(
      `L1 UA 黑名单命中：<code>${hit}</code>。声明身份的客户端会被放行。`,
      'L1',
      403,
    );
    res.headers.set('x-dojo-block', 'ua');
    return res;
  }

  // L2 / L3 / L4 / L5 在本地版里由 guards/ 实现。
  // 上云版刻意只保留 L1 —— 因为再往上每一层都要做状态管理（计数窗口、签名时间窗），
  // 而 Workers 免费版没有 KV（要额外绑定），会把示例撑得很复杂。
  // 「先看清代价，再决定要不要往上加」本身就是这一章的教学目标。

  return next();
}
