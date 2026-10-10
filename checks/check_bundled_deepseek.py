"""Run the actual service with no installed Python/Git on PATH and no personal accounts."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def check(executable):
    executable = Path(executable).resolve()
    with tempfile.TemporaryDirectory(prefix='flandre-bundled-service-') as directory:
        root = Path(directory)
        key = secrets.token_urlsafe(32)
        env = dict(os.environ, DB_PATH=str(root/'deeperseeker.db'), HOST='127.0.0.1',
            DEEPSEEKER_API_KEY=key, DEEPSEEKER_ADMIN_USER='notebook', DEEPSEEKER_ADMIN_PASSWORD=key,
            PATH=str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'))
        env.pop('PYTHONPATH', None)
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        checked = subprocess.run([str(executable), '--self-check'], cwd=root, env=env,
            capture_output=True, text=True, timeout=45, creationflags=flags)
        assert checked.returncode == 0 and 'PASS:' in checked.stdout, checked.stdout + checked.stderr
        assert (executable.parent/'_internal/LICENSE').is_file()
        assert not any(p.suffix in ('.db','.sqlite3') for p in executable.parent.rglob('*') if p.is_file())
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0))
            env['PORT'] = str(probe.getsockname()[1])
        base = 'http://127.0.0.1:' + env['PORT']
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with (root/'service.log').open('wb') as log:
            process = subprocess.Popen([str(executable)], cwd=root, env=env, creationflags=flags,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            try:
                for _ in range(150):
                    assert process.poll() is None, 'Bundled service stopped during startup'
                    try:
                        request = urllib.request.Request(base+'/v1/models', headers={'Authorization':'Bearer '+key})
                        with opener.open(request,timeout=2) as reply:
                            models = json.load(reply)
                        break
                    except OSError:
                        time.sleep(.2)
                else:
                    raise AssertionError('Bundled service did not become ready')
                assert any(m['id']=='v4.1flash' for m in models['data'])
                try:
                    opener.open(base+'/v1/models',timeout=2)
                except urllib.error.HTTPError as error:
                    assert error.code in (401,403)
                else:
                    raise AssertionError('Unauthenticated access must be rejected')
                with opener.open(base+'/login',timeout=2) as reply:
                    assert b'<form' in reply.read()
                with opener.open(base+'/static/style.css',timeout=2) as reply:
                    assert reply.read()
                request = urllib.request.Request(base+'/health',headers={'Authorization':'Bearer '+key})
                try:
                    opener.open(request,timeout=2)
                except urllib.error.HTTPError as error:
                    assert error.code == 503 and json.load(error)['active_tokens'] == 0
                else:
                    raise AssertionError('Fresh service must not contain accounts')
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    print('PASS: standalone EXE, tokenizer/WASM, dashboard, authentication, empty account store and shutdown')


if __name__ == '__main__':
    check(sys.argv[1])
