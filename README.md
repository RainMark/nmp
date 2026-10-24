# NMP

NMP forwards TCP traffic through a WebSocket server. The desktop client exposes
SOCKS5 and HTTP CONNECT on `127.0.0.1:1234`; UDP forwarding is not supported by
this local proxy.

1. [Deploy the server](#server): Linux / macOS with Python 3.11 and Caddy.
2. [Connect the desktop client](#desktop-client): Windows x64 or macOS Apple Silicon.
   A [command-line client](#command-line-client) is also available on Linux / macOS.
3. Import the [Clash configuration](configs/README.md) for system proxy and routing rules.

## Server

Run the following commands on your server with Python 3.11 installed.

### Install from source

```bash
git clone https://github.com/RainMark/nmp.git
cd nmp
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

### Start the server

```bash
nmp --server nmp --port 10010
```

The server listens on `127.0.0.1:10010`. On first startup, it securely generates
a random token and saves it to `~/.NMP_TOKEN`; later starts reuse that token.
Copy the token printed at startup into `YOUR_TOKEN` below and into your client.
Replace `nmp.example.io` with your domain throughout the examples.

Point your domain to the server and configure Caddy for HTTPS; keep the NMP
port on loopback.
The Caddy path rule restricts access to the token-bearing URL:

```caddyfile
nmp.example.io {
  handle /YOUR_TOKEN/* {
    reverse_proxy 127.0.0.1:10010 {
      header_up -Origin
    }
  }
  handle {
    respond 404
  }
}
```

## Desktop client

### Download and install

Download from [GitHub Releases](https://github.com/RainMark/nmp/releases/latest).
The current builds are not commercially signed.

**Windows x64** — run this in PowerShell from a permanent folder:

```powershell
Invoke-WebRequest -Uri "https://github.com/RainMark/nmp/releases/latest/download/NMP-windows-x64.exe" -OutFile ".\NMP-windows-x64.exe"
```

Double-click `NMP-windows-x64.exe`; no installer is required.

Defender exclusions: **Windows 安全中心 → 病毒和威胁防护 → 管理设置 → 排除项 →
添加或删除排除项 → 添加排除项 → 文件** (Windows Security → Virus & threat protection →
Manage settings → Exclusions → Add or remove exclusions → Add an exclusion → File).
If you have verified and trust the official download and choose to exclude it,
select only `NMP-windows-x64.exe`; exclusions reduce protection for that file.

**macOS arm64** — download [NMP-macos-arm64.zip](https://github.com/RainMark/nmp/releases/latest/download/NMP-macos-arm64.zip),
unzip it, and move `NMP.app` to Applications. If macOS reports that the app cannot
be checked or opened, run the following only for the official download:

```bash
xattr -dr com.apple.quarantine /Applications/NMP.app
```

### Connect

1. Enter your server address, such as `wss://nmp.example.io`, and its token.
2. Keep local port `1234`, or choose another unused port.
3. Click **保存配置**, then **启动代理**.
4. Set your application's SOCKS5 proxy to `127.0.0.1:1234`, or import the
   [Clash configuration](configs/README.md) for system proxy and routing rules.

Closing the window keeps NMP running in the tray. Use the tray menu to reopen
it or choose **退出 NMP** to quit. On Windows, enable **开机自启** to start the
saved proxy in the tray after login; manual launches still open the window.

To update, quit NMP from its tray menu, replace the executable or app, and reopen
it. Connection settings are stored separately. Keep the Windows executable at
the same path when **开机自启** is enabled; after moving it, switch the option
off and on from the new location.

### Configuration and logs

| Platform | Configuration | Log |
| --- | --- | --- |
| Windows | `%APPDATA%\NMP\client.toml` | `%LOCALAPPDATA%\NMP\logs\nmp-client.log` |
| macOS | `~/Library/Application Support/NMP/client.toml` | `~/Library/Logs/NMP/nmp-client.log` |

Use **打开日志目录** in the app to open the log folder.

## Command-line client

On Linux / macOS, follow [Install from source](#install-from-source) on the
client machine, then start the local proxy with your server address and token:

```bash
nmp --server sockv5 --endpoint wss://nmp.example.io --port 1234 --token YOUR_TOKEN
```

Test SOCKS5 with remote hostname resolution:

```bash
curl --proxy socks5h://127.0.0.1:1234 https://www.google.com
```

The same port also accepts HTTP CONNECT for HTTPS tunnels; it is not a full
plain-HTTP forward proxy. Use Clash's mixed port when an application needs both.

## Development

From the source checkout, install desktop dependencies and run the tests:

```bash
python -m pip install -e ".[desktop]" pytest
python -m pytest -q
```

Run the GUI from source with `python nmp_client_gui.py`. **开机自启** is available
in packaged Windows builds only.

Test binaries are available in the [Desktop clients CI artifacts](https://github.com/RainMark/nmp/actions/workflows/desktop-clients.yml).
Version tags publish CI-tested packages to GitHub Releases.
