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

NMP Desktop Client provides a local SOCKS5 proxy with a graphical interface.
It supports Windows x64 and Apple Silicon macOS (arm64).

#### Download and install

Download the newest version from the
[GitHub Releases page](https://github.com/RainMark/nmp/releases/latest):

- **Windows x64:** [Download NMP-windows-x64.exe](https://github.com/RainMark/nmp/releases/latest/download/NMP-windows-x64.exe),
  move it to a permanent folder, and double-click it to run. No installer is
  required.
- **macOS arm64:** [Download NMP-macos-arm64.zip](https://github.com/RainMark/nmp/releases/latest/download/NMP-macos-arm64.zip),
  unzip it, and drag `NMP.app` into the Applications folder.

The current builds are not commercially signed. Windows SmartScreen or macOS
Gatekeeper may therefore display a warning. Only continue when the file was
downloaded from the official NMP Releases page above.

If macOS reports that `NMP.app` cannot be checked or opened, first make sure it
has been moved to the Applications folder. Then remove the download quarantine
attribute in Terminal and open the app again:

```bash
xattr -dr com.apple.quarantine /Applications/NMP.app
```

Only run this command for `NMP.app` downloaded from the official Releases page.

#### Configure and use

1. Enter the NMP server WebSocket address, for example
   `wss://nmp.example.io`.
2. Enter the token printed when the NMP server starts.
3. Keep the default local port `1234`, or select another unused port.
4. Click **保存配置**, then **启动代理**.
5. Configure the browser or downstream proxy application to use SOCKS5 at
   `127.0.0.1:1234`.

The client can be used directly by a browser or as a local SOCKS5 outbound in
Mihomo / Clash Verge Rev. System proxy and routing rules remain outside NMP.
The app can start or stop the proxy, copy its address, and display live and
rotating file logs. Closing the window hides it to the system tray while the
proxy keeps running. Use the tray menu to show the window, start or stop the
proxy, or quit NMP completely.

Configuration and logs are stored in the platform user directories:

- Windows: `%APPDATA%\NMP\client.toml` and
  `%LOCALAPPDATA%\NMP\logs\nmp-client.log`.
- macOS: `~/Library/Application Support/NMP/client.toml` and
  `~/Library/Logs/NMP/nmp-client.log`.

Run the source tests locally with:

```bash
python -m pip install -e ".[desktop]" pytest
python -m pytest -q
```
