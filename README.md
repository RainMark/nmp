## Project Nmp

### Setup

```bash
$ git clone https://git.oxfs.io/nmp/nmp.git
$ cd nmp
$ python3.8 -m venv .env
$ source .env/bin/activate
$ python setup.py develop
```

### Get Started

- Start Nmp Server

```bash
$ nmp --server nmp --port 10010
[2021-11-09 02:16:15,702] [   INFO] [main.py -- start_nmp_server():62] start nmp server: (127.0.0.1:10010)
[2021-11-09 02:16:15,703] [   INFO] [server.py -- start_server():56] ### Token: f353f0ab21e2d93c ###
```

- Caddy2 Config

```bash
nmp.example.io {
  ### Token: f353f0ab21e2d93c ###
  handle /f353f0ab21e2d93c/* {
    reverse_proxy 127.0.0.1:10010 {
      header_up -Origin
    }
  }
  reverse_proxy https://www.baidu.com {
    header_up -Origin
  }

  # tls {
  #   dns cloudflare your_api_token
  # }
}
```

- Start Local Sockv5 Server

```bash
$ nmp --server sockv5 --endpoint wss://nmp.example.io --port 1234 --token f353f0ab21e2d93c
[2021-11-09 15:20:58,781] [   INFO] [main.py -- start_sockv5_server():68] start sockv5 server: (127.0.0.1:1234)
```

- Test

```bash
all_proxy='socks5h://127.0.0.1:1234' curl https://www.google.com
```

### Desktop Client

The desktop client exposes a local SOCKS5 proxy on `127.0.0.1`. It can be used
directly by a browser or as a local SOCKS5 outbound in Mihomo / Clash Verge
Rev. System proxy and routing rules remain outside NMP.

The same Tkinter GUI is packaged for Windows x64 and macOS arm64. It edits and
saves the endpoint, token and local port, starts or stops the proxy, copies its
address, and displays live and rotating file logs.

Download the matching artifact from the `Desktop clients` GitHub Actions
workflow:

- `NMP-windows-x64` contains `NMP.exe`.
- `NMP-macos-arm64` contains `NMP-macos-arm64.zip`; unzip it and move
  `NMP.app` to Applications.

Configuration and logs are stored in the platform user directories:

- Windows: `%APPDATA%\NMP\client.toml` and
  `%LOCALAPPDATA%\NMP\logs\nmp-client.log`.
- macOS: `~/Library/Application Support/NMP/client.toml` and
  `~/Library/Logs/NMP/nmp-client.log`.

CI builds are unsigned development artifacts. Distribution without Windows
SmartScreen or macOS Gatekeeper warnings requires platform code signing; macOS
distribution also requires Apple notarization.

Run the source tests locally with:

```bash
python -m pip install -e . pytest
python -m pytest -q
```
