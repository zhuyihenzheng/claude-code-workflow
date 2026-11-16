"""MCP handshake against the pinned npm servers: initialize, then tools/list.

Needs network access to the npm registry, so it only runs when MCP_SERVERS_REQUIRED=1
(set in CI). It proves the pinned versions start and still accept the template's
arguments; it does not drive a browser or a real database.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
NPX = shutil.which('npx')


def server(path, name):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))['mcpServers'][name]


def list_tools(command, args, timeout=180):
    errors = tempfile.TemporaryFile()
    process = subprocess.Popen([shutil.which(command) or command, *args], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=errors, text=True, encoding='utf-8')
    timer = threading.Timer(timeout, process.kill)
    timer.start()

    def call(message, reply_id=None):
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()
        while reply_id is not None:
            line = process.stdout.readline()
            if not line:
                errors.seek(0)
                raise AssertionError('MCP server closed the connection or timed out; stderr:\n'
                                     + errors.read().decode('utf-8', 'replace')[-2000:])
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if reply.get('id') == reply_id:
                return reply['result']

    try:
        call({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'template-test', 'version': '0'}}}, 1)
        call({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return {tool['name'] for tool in call({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, 2)['tools']}
    finally:
        timer.cancel()
        process.kill()
        process.wait()
        for stream in (process.stdin, process.stdout, errors):
            stream.close()


@unittest.skipUnless(os.environ.get('MCP_SERVERS_REQUIRED') == '1', 'set MCP_SERVERS_REQUIRED=1 to run (needs npm registry)')
class McpServerTests(unittest.TestCase):
    def test_playwright_starts_with_template_arguments(self):
        config = server('templates/project/.mcp.json', 'playwright')
        tools = list_tools(config['command'], config['args'])
        self.assertTrue({'browser_navigate', 'browser_click', 'browser_take_screenshot'} <= tools, sorted(tools))

    def test_dbhub_starts_with_a_dsn_argument(self):
        config = server('templates/mcp.optional.json', 'dbhub')
        args = [arg.replace('${DATABASE_URL}', 'sqlite:///:memory:') for arg in config['args']]
        self.assertIn('--dsn', args)
        self.assertIn('execute_sql', list_tools(config['command'], args))


if __name__ == '__main__':
    unittest.main()
