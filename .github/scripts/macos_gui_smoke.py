import argparse
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix='nmp-gui-ci-') as directory:
        config_path = Path(directory) / 'client.toml'
        process = subprocess.Popen([
            str(args.executable.resolve()), '--config', str(config_path)
        ])
        try:
            time.sleep(5)
            if process.poll() is not None:
                raise RuntimeError(
                    f'packaged GUI exited early with code {process.returncode}')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    print('Packaged macOS GUI stayed running after launch.')


if __name__ == '__main__':
    main()
