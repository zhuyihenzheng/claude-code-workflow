import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('install', ROOT / 'scripts/install.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)
PROJECT = ROOT / 'templates/project'


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = install.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


class InstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='target project ')
        self.addCleanup(temp.cleanup)
        self.target = Path(temp.name)
        (self.target / 'pom.xml').write_text('<project/>', encoding='utf-8')
        (self.target / 'mvnw').write_text('#!/bin/sh\n', encoding='utf-8')

    def kinds(self):
        return {a.rel: a.kind for a in install.plan_project(self.target)}

    def test_dry_run_writes_nothing(self):
        code, out, _ = run('project', self.target)
        self.assertEqual(code, 0)
        self.assertIn('Dry run only', out)
        self.assertFalse((self.target / 'CLAUDE.md').exists())
        self.assertFalse((self.target / '.claude').exists())

    def test_apply_into_empty_project_copies_every_template_byte_for_byte(self):
        run('project', self.target, '--apply')
        for rel, source in install.template_files(PROJECT):
            with self.subTest(rel=rel):
                self.assertEqual((self.target / rel).read_bytes(), source.read_bytes())
        self.assertNotIn('hooks', json.loads((self.target / '.claude/settings.json').read_text(encoding='utf-8')))
        self.assertTrue(set(self.kinds().values()) == {'skip'})

    def test_existing_settings_are_merged_not_overwritten(self):
        settings = self.target / '.claude/settings.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps({
            'model': 'sonnet',
            'hooks': {'Stop': []},
            'permissions': {'allow': ['Bash(npm test)', 'Bash(./mvnw *)'], 'defaultMode': 'default'},
        }), encoding='utf-8')
        action = {a.rel: a for a in install.plan_project(self.target)}['.claude/settings.json']
        self.assertEqual(action.kind, 'merge')
        self.assertIn('broad rule', action.note)
        run('project', self.target, '--apply')
        merged = json.loads(settings.read_text(encoding='utf-8'))
        template = json.loads((PROJECT / '.claude/settings.json').read_text(encoding='utf-8'))
        self.assertEqual(merged['model'], 'sonnet')
        self.assertEqual(merged['hooks'], {'Stop': []})
        self.assertEqual(merged['permissions']['defaultMode'], 'default')
        self.assertEqual(merged['permissions']['allow'][:2], ['Bash(npm test)', 'Bash(./mvnw *)'])
        for key in ('allow', 'deny', 'ask'):
            for rule in template['permissions'][key]:
                self.assertEqual(merged['permissions'][key].count(rule), 1)
        self.assertEqual(self.kinds()['.claude/settings.json'], 'skip')

    def test_existing_mcp_server_wins(self):
        (self.target / '.mcp.json').write_text(json.dumps({'mcpServers': {
            'playwright': {'command': 'npx', 'args': ['-y', '@playwright/mcp@0.0.1']},
            'other': {'type': 'http', 'url': 'https://example.invalid/mcp'},
        }}), encoding='utf-8')
        action = {a.rel: a for a in install.plan_project(self.target)}['.mcp.json']
        self.assertIn("'playwright' differs", action.note)
        servers = json.loads(action.content)['mcpServers']
        self.assertEqual(servers['playwright']['args'][1], '@playwright/mcp@0.0.1')
        self.assertIn('other', servers)
        self.assertIn('context7', servers)

    def test_invalid_json_is_a_conflict_and_left_untouched(self):
        (self.target / '.mcp.json').write_text('{ broken', encoding='utf-8')
        run('project', self.target, '--apply')
        self.assertEqual((self.target / '.mcp.json').read_text(encoding='utf-8'), '{ broken')
        self.assertEqual(self.kinds()['.mcp.json'], 'conflict')

    def test_line_files_append_only_missing_rules_and_keep_crlf(self):
        (self.target / '.gitignore').write_bytes(b'target/\r\n.env\r\n')
        run('project', self.target, '--apply')
        text = (self.target / '.gitignore').read_bytes().decode('utf-8')
        self.assertTrue(text.startswith('target/\r\n.env\r\n'))
        self.assertEqual(text.count('.env\r\n'), 1)
        self.assertIn('!.env.example\r\n', text)
        self.assertNotIn('\n', text.replace('\r\n', ''))
        self.assertEqual(self.kinds()['.gitignore'], 'skip')

    def test_differing_plain_file_is_conflict_and_preserved(self):
        (self.target / 'CLAUDE.md').write_text('# mine\n', encoding='utf-8')
        code, out, _ = run('project', self.target, '--apply')
        self.assertEqual(code, 0)
        self.assertEqual((self.target / 'CLAUDE.md').read_text(encoding='utf-8'), '# mine\n')
        self.assertRegex(out, r'conflict\s+CLAUDE\.md')

    def test_warns_without_maven_and_refuses_template_repo(self):
        (self.target / 'pom.xml').unlink()
        (self.target / 'mvnw').unlink()
        _, _, err = run('project', self.target)
        self.assertIn('no pom.xml', err)
        self.assertIn('no Maven Wrapper', err)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            install.main(['project', str(ROOT)])

    def test_user_skills_install_into_claude_dir(self):
        claude = self.target / 'home/.claude'
        run('user', '--claude-dir', claude, '--apply')
        for skill in ('diagnosing-bugs', 'grilling', 'writing-for-agents'):
            self.assertTrue((claude / 'skills' / skill / 'SKILL.md').is_file())
            self.assertTrue((claude / 'skills' / skill / 'LICENSE').is_file())
        self.assertFalse((claude / 'skills/LICENSE-mattpocock-skills').exists())
        self.assertEqual({a.kind for a in install.plan_user(claude)}, {'skip'})


if __name__ == '__main__':
    unittest.main()
