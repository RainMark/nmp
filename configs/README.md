# Clash 配置

适用于 Mihomo / Clash Verge Rev。国内域名直连，其他 TCP 默认通过 NMP；Windows Codex、OpenAI、ChatGPT、Auth0 和 GFW 列表优先代理。

## 使用

1. 在 NMP 中填写服务器地址和 token，设置端口为 `1234`，保存并启动。
2. 在 Clash Verge Rev「订阅」中导入以下链接，然后选中该配置：

   ```text
   https://raw.githubusercontent.com/RainMark/nmp/master/configs/clash.yaml
   ```

   此链接在 PR 合并后可用。合并前可下载当前分支的 [clash.yaml](clash.yaml) 本地导入。

3. 使用「规则」模式，开启「系统代理」。需要接管不遵循系统代理的应用时，再开启「TUN / 虚拟网卡模式」；两者可以同时开启。
4. 在「连接」页面确认代理连接经过 `NMP-Proxy → NMP-SOCKS5`。

首次导入和规则下载需要能访问 GitHub，可使用已有代理或下载文件后本地导入。每次使用先启动 NMP，再启动 Clash；规则列表每 24 小时自动更新。

## 常用设置

- **应用手动设置代理：** HTTP / SOCKS5 地址为 `127.0.0.1:7897`。Clash 客户端覆盖过端口时，以界面显示为准。
- **修改 NMP 端口：** 同时修改配置中 `NMP-SOCKS5` 节点的 `port`。
- **开启 TUN：** 保留 NMP 进程直连规则；重命名 NMP 后需同步修改对应规则，避免代理循环。
- **DNS：** 国外解析通过 NMP 转发 DoH，国内解析使用国内 DNS；系统代理不会接管所有应用的 DNS。
- **UDP：** NMP 不支持 UDP 转发，国外 UDP 会被拒绝；依赖 UDP 的游戏或语音应用可能无法使用。

本配置不包含 NMP 服务器地址或 token。Windows Codex 使用非标准安装目录时需调整进程路径规则；macOS 用户主要依靠域名分流。
