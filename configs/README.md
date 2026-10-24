# Clash / Mihomo 在线配置

此配置基于实际使用并验证过的 NMP 本地订阅整理。适用于 Mihomo / Clash Verge Rev，NMP 监听 `127.0.0.1:1234`，Clash mixed-port 为 `7897`。

## 导入

1. 安装 NMP，填写自己的服务器地址和 token，保存并启动，端口设为 `1234`。
2. 此配置合并到 master 后，在 Clash Verge Rev「订阅」中导入并选中：

   ```text
   https://raw.githubusercontent.com/RainMark/nmp/master/configs/clash.yaml
   ```

3. 选择规则模式，打开系统代理；在连接页面确认目标连接经过 `NMP-Proxy → NMP-SOCKS5`。

订阅只配置 Clash，不包含 NMP 服务地址或 token，也不会替你安装或启动 NMP。首次下载需要能访问 GitHub Raw，可通过已有代理导入，或下载 YAML 本地导入。规则列表首次加载需要 NMP 已启动；以后每 24 小时更新。Clash 客户端的端口、DNS、TUN 覆写设置可能优先于订阅，请检查运行时配置。

## 行为与边界

应用 → Clash → 本机 NMP SOCKS5 → NMP 服务端 → 目标网站。

规则按顺序匹配：

1. 回环、私网 IPv4、NMP 进程直连，防止代理循环。
2. Windows Codex 安装目录内的程序、OpenAI / ChatGPT / Auth0 域名和 GFW 列表优先代理。
3. `.cn` 和国内域名列表直连。
4. 其余 TCP 默认代理；其余 UDP 拒绝，因为 NMP 不支持 UDP 转发。

这属于域名列表分流，不是按服务器地理位置分流。只有公网 IP、没有域名信息的连接默认代理；私网优先直连。国内直连规则允许 UDP，国外 QUIC 通常回退 TCP，依赖 UDP 的应用不保证可用。

国外 DNS 使用 `https://1.1.1.1/dns-query#NMP-SOCKS5`，即 DoH 的 TCP 连接通过 NMP，国内域名使用国内 DNS。域名可直接通过 SOCKS5 交给 NMP 服务端；已经被应用解析成 IP 的请求无法凭空恢复域名。系统代理也不接管所有应用的 DNS。因此默认配置不承诺“所有 DNS 均远端解析”。参见 [Mihomo DNS 文档](https://wiki.metacubex.one/config/dns/)。

保留 fake-IP 和可选 TUN 设置，默认关闭 TUN；系统代理适合遵循系统代理设置的应用。其他程序需单独设置代理，或自行启用 TUN 后检查路由和 DNS。不要把 fake-IP 段加入私网直连规则。不要把 NMP 重命名后直接启用 TUN：先相应修改 NMP 的进程直连规则。

配置没有用户名、固定系统盘符、私密凭据或绝对规则文件路径。Windows Codex 进程匹配覆盖商店安装目录及常见用户安装目录；特殊安装路径需补充规则。macOS 的 NMP 进程直连已列出，但 macOS Codex 进程强制代理和 TUN 未实测；跨平台域名分流不依赖这些 Windows 路径规则。旧 Clash 内核不在兼容范围内。

## 为什么保留这些配置

- DNS、代理节点、代理组、规则源、分流顺序及 UDP 子规则沿用已验证的配置，仅将 JSON 表达改为 YAML。
- 两条 Codex 路径正则改为任意盘符及用户名；额外增加 macOS NMP 进程直连规则。
- 保留一个有明确名字的代理组，方便界面查看连接；没有增加测速、自动切换或备用直连，以免悄悄绕过代理。
- GFW 规则虽然不是默认代理所必需，但保留它可满足显式列表需求，并在国内列表重叠时优先代理。
- 保留 OpenAI / Auth0 的显式规则及 DNS 策略，避免国内列表更新改变这些域名的行为。

规则引用 [Loyalsoldier/clash-rules](https://github.com/Loyalsoldier/clash-rules) 的 `gfw.txt` 与 `direct.txt`，未复制规则数据到本仓库。第三方列表变化会影响分流结果。

## 验证记录

2026-10-24，Windows / Mihomo v1.19.31：

- 配置通过内核 `-t` 检查。以同一 YAML 启动独立实例，仅修改混合端口并添加本机测试控制接口，没有修改正在使用的 Clash。
- 从空缓存通过 NMP 下载规则：GFW 4,434 条，国内 110,235 条（数量会随上游更新）。
- 百度、gov.cn 返回 200，日志分别匹配国内列表及 `.cn` 直连。
- Google 返回 204，Auth0 和 Cloudflare 返回 200，日志分别匹配 GFW、Auth0 和默认代理。
- ChatGPT 匹配代理规则，curl 返回站点 HTTP 403；不视为网页登录验证通过。
- DNS 查询 example.com 成功，日志确认 DoH 连接到 `1.1.1.1:443` 使用 NMP-SOCKS5。

此记录不代表测试过所有域名、未来规则更新或所有客户端；也未将当前 Codex 会话切换到测试端口。
