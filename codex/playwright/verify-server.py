#!/usr/bin/env python3
"""Run real-extension regression checks without exposing the stored token."""
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import time

directory = Path(__file__).resolve().parent
configuration = plistlib.loads((Path.home() / 'Library/LaunchAgents/local.codex-playwright.plist').read_bytes())
environment = dict(os.environ, **configuration['EnvironmentVariables'])
node = configuration['ProgramArguments'][0]
with tempfile.TemporaryDirectory(prefix='playwright-regression-') as workspace:
    with tempfile.TemporaryFile(mode='w+') as log:
        server = subprocess.Popen([node, str(directory / 'server.mjs'), '--extension', '--background',
                                   '--profile-dir-name', 'Default', '--host', '127.0.0.1', '--port', '0'],
                                  env=environment, cwd=workspace, stdout=log, stderr=log)
        try:
            endpoint = None
            for _ in range(200):
                log.seek(0)
                match = re.search(r'Listening on (http://127\.0\.0\.1:[0-9]+)', log.read())
                if match:
                    endpoint = match.group(1) + '/mcp'
                    break
                if server.poll() is not None:
                    raise RuntimeError('Test server failed to start; inspect its configuration locally')
                time.sleep(.05)
            if endpoint is None:
                raise TimeoutError('Test server startup exceeded 10 seconds')
            scripts = sys.argv[1:] or ['verify.mjs']
            for script in scripts:
                subprocess.run([node, str(directory / script), endpoint], check=True, cwd=workspace, timeout=180)
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
