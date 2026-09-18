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

### Windows x64 Client

The Windows client exposes a local SOCKS5 proxy and keeps routing and system
proxy integration outside NMP. It can be used directly by a browser or as a
local SOCKS5 outbound in Mihomo / Clash Verge Rev.

Copy `nmp-client.example.toml` to `%APPDATA%\NMP\client.toml` and update the
endpoint and token:

```toml
[client]
endpoint = "wss://nmp.example.com"
token = "replace-with-your-token"
host = "127.0.0.1"
port = 1234
pre_connect = false
```

Run the packaged executable without arguments to use that default config:

```powershell
.\nmp-client.exe
```

Command-line options override the TOML file:

```powershell
.\nmp-client.exe --config .\client.toml --port 1080
```

Development builds are produced by the `Windows x64` GitHub Actions workflow.
Each successful run uploads `nmp-client-windows-x64` containing the executable
and example configuration.

Run the source tests locally with:

```bash
python -m pip install -e . pytest
python -m pytest -q
```
