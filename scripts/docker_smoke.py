"""Exercise an actual disposable container. No live rooms or credentials needed."""
import argparse
import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def request(base, path, data=None):
    req = urllib.request.Request(base + path,
                                 data=None if data is None else json.dumps(data).encode(),
                                 headers={'Content-Type': 'application/json'},
                                 method='GET' if data is None else 'PATCH')
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.read()


def wait_ready(base):
    for _ in range(90):
        try:
            return json.loads(request(base, '/api/v1/app/info'))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(1)
    raise RuntimeError('Container API did not become ready')


def smoke(image, version, platform):
    name = 'blrec-smoke-' + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='blrec-smoke-') as directory:
        root = Path(directory)
        for folder in ('cfg', 'log', 'rec'):
            (root / folder).mkdir()
        args = ['run', '-d', '--name', name, '--platform', platform,
                '-p', '127.0.0.1::2233']
        for folder in ('cfg', 'log', 'rec'):
            args.extend(['-v', f'{root / folder}:/{folder}'])
        try:
            docker(*args, image)
            def endpoint():
                port = docker('port', name, '2233/tcp').splitlines()[0]
                return 'http://' + port
            base = endpoint()
            assert wait_ready(base)['version'] == version
            assert b'<html' in request(base, '/').lower()
            assert 'ffmpeg version' in docker('exec', name, 'ffmpeg', '-version')
            docker('exec', name, 'python', '-m', 'pip', 'check')
            assert version in docker('exec', name, 'blrec', '--version')
            # This fixture changes only a harmless recording preference.
            request(base, '/api/v1/settings', {'danmaku': {'recordGiftSend': False}})
            saved = root / 'cfg/settings.toml'
            assert saved.exists() and saved.stat().st_size > 0
            docker('restart', '--time', '15', name)
            base = endpoint()
            assert wait_ready(base)['version'] == version
            settings = json.loads(request(base, '/api/v1/settings'))
            assert settings['danmaku']['recordGiftSend'] is False
            print(f'{platform}: API, webpage, version, FFmpeg, settings persistence OK')
        finally:
            # Only this script's uniquely named test container is removed.
            subprocess.run(['docker', 'logs', '--tail', '60', name], check=False)
            subprocess.run(['docker', 'rm', '-f', name], check=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('image')
    parser.add_argument('version')
    parser.add_argument('--platform', required=True)
    args = parser.parse_args()
    smoke(args.image, args.version, args.platform)
