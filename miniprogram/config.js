// The API origin the mini program talks to. Release: the FILED mainland domain whose relay proxies /api/auth/wechat/* to the word-Dance
// server (deploy/relay/README.md) — it must be listed under 开发 → 开发设置 → 服务器域名 → request 合法域名. Development: the server's
// WD_PUBLIC_URL with 「不校验合法域名」 ticked in DevTools (README.md).
module.exports = {
  apiBase: 'https://RELAY-DOMAIN',
};
