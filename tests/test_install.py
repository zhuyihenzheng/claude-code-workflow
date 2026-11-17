import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
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

    def kinds(self, **options):
        return {a.rel: a.kind for a in install.plan_project(self.target, **options)}

    def test_dry_run_writes_nothing(self):
        code, out, _ = run('project', self.target)
        self.assertEqual(code, 0)
        self.assertIn('Dry run only', out)
        self.assertFalse((self.target / 'CLAUDE.md').exists())
        self.assertFalse((self.target / '.claude').exists())

    def test_apply_into_empty_project_copies_every_template_byte_for_byte(self):
        run('project', self.target, '--apply', '--with-workflows', '--with-screen-tests')
        for rel, source in install.template_files(PROJECT):
            with self.subTest(rel=rel):
                self.assertEqual((self.target / rel).read_bytes(), source.read_bytes())
        self.assertNotIn('hooks', json.loads((self.target / '.claude/settings.json').read_text(encoding='utf-8')))
        self.assertEqual(set(self.kinds().values()), {'skip'})

    def test_workflows_are_installed_only_on_request(self):
        workflows = self.target / '.github/workflows'
        code, out, _ = run('project', self.target, '--apply')
        self.assertEqual(code, 0)
        self.assertFalse(workflows.exists())
        self.assertRegex(out, r'optional\s+\.github/workflows/claude\.yml\s+\(.*--with-workflows')
        self.assertEqual(len([line for line in out.splitlines() if line.startswith('optional') and '--with-workflows' in line]), 3)
        self.assertEqual({k for rel, k in self.kinds().items() if rel.startswith('.github/workflows/')}, {'optional'})
        self.assertEqual(set(self.kinds().values()), {'skip', 'optional'})
        run('project', self.target, '--apply', '--with-workflows')
        self.assertTrue((workflows / 'claude.yml').is_file())
        # Once present, a workflow is compared like any other file, with or without the flag.
        self.assertEqual(self.kinds()['.github/workflows/claude.yml'], 'skip')
        (workflows / 'claude.yml').write_text('name: mine\n', encoding='utf-8')
        self.assertEqual(self.kinds()['.github/workflows/claude.yml'], 'conflict')

    def test_installed_sync_rules_reports_target_in_sync(self):
        run('project', self.target, '--apply')
        result = subprocess.run([sys.executable, 'scripts/sync_rules.py', '--check'],
                                cwd=self.target, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_screen_tests_are_installed_only_on_request(self):
        code, out, _ = run('project', self.target, '--apply')
        self.assertEqual(code, 0)
        self.assertFalse((self.target / 'screen-tests').exists())
        self.assertRegex(out, r'optional\s+screen-tests/package\.json\s+\(.*--with-screen-tests')
        run('project', self.target, '--apply', '--with-screen-tests')
        package = json.loads((self.target / 'screen-tests/package.json').read_text(encoding='utf-8'))
        # The framework is pinned to a full commit SHA, never to a branch or a version range.
        self.assertRegex(package['devDependencies']['midscene-poc'], r'^github:zhuyihenzheng/midscene-poc#[0-9a-f]{40}$')
        self.assertTrue((self.target / 'screen-tests/.gitignore').is_file())
        self.assertFalse((self.target / '.github/workflows').exists(), 'the two options are independent')

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
        self.assertEqual(merged['permissions']['disableBypassPermissionsMode'], 'disable')
        self.assertIs(merged['disableClaudeAiConnectors'], True)
        self.assertIs(merged['enableArtifact'], False)
        self.assertEqual(merged['permissions']['allow'][:2], ['Bash(npm test)', 'Bash(./mvnw *)'])
        for key in ('allow', 'deny', 'ask'):
            for rule in template['permissions'][key]:
                self.assertEqual(merged['permissions'][key].count(rule), 1)
        self.assertEqual(self.kinds()['.claude/settings.json'], 'skip')

    def test_existing_hardening_values_win_and_are_reported(self):
        settings = self.target / '.claude/settings.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps({'enableArtifact': True, 'permissions': {'disableBypassPermissionsMode': 'allow'}}),
                            encoding='utf-8')
        action = {a.rel: a for a in install.plan_project(self.target)}['.claude/settings.json']
        merged = json.loads(action.content)
        self.assertIs(merged['enableArtifact'], True)
        self.assertEqual(merged['permissions']['disableBypassPermissionsMode'], 'allow')
        self.assertIs(merged['disableClaudeAiConnectors'], True)
        self.assertIn("'enableArtifact' differs from template; kept existing", action.note)
        self.assertIn('"permissions.disableBypassPermissionsMode" differs', action.note)

    def test_existing_mcp_server_wins(self):
        mcp = self.target / '.mcp.json'
        mcp.write_text(json.dumps({'mcpServers': {
            'playwright': {'command': 'npx', 'args': ['-y', '@playwright/mcp@0.0.1']},
            'other': {'type': 'http', 'url': 'https://example.invalid/mcp'},
        }}), encoding='utf-8')
        action = {a.rel: a for a in install.plan_project(self.target)}['.mcp.json']
        # Nothing to add: the only template server already exists, in the project's own version.
        self.assertEqual(action.kind, 'skip')
        self.assertIn("'playwright' differs", action.note)
        mcp.write_text(json.dumps({'mcpServers': {'other': {'type': 'http', 'url': 'https://example.invalid/mcp'}}}),
                       encoding='utf-8')
        action = {a.rel: a for a in install.plan_project(self.target)}['.mcp.json']
        self.assertEqual(action.kind, 'merge')
        self.assertEqual(set(json.loads(action.content)['mcpServers']), {'other', 'playwright'})

    def test_invalid_json_is_a_conflict_and_left_untouched(self):
        (self.target / '.mcp.json').write_text('{ broken', encoding='utf-8')
        run('project', self.target, '--apply')
        self.assertEqual((self.target / '.mcp.json').read_text(encoding='utf-8'), '{ broken')
        self.assertEqual(self.kinds()['.mcp.json'], 'conflict')

    def test_gitignore_adds_only_missing_rules_before_existing_ones_and_keeps_crlf(self):
        (self.target / '.gitignore').write_bytes(b'target/\r\n.env\r\n')
        run('project', self.target, '--apply')
        text = (self.target / '.gitignore').read_bytes().decode('utf-8')
        self.assertTrue(text.endswith('target/\r\n.env\r\n'))
        self.assertEqual(text.count('.env\r\n'), 1)
        self.assertIn('!.env.example\r\n', text)
        self.assertNotIn('\n', text.replace('\r\n', ''))
        self.assertEqual(self.kinds()['.gitignore'], 'skip')

    def test_gitignore_merge_keeps_existing_negations_effective(self):
        # Appending the template's ".env.*" after "!.env.example" would ignore the file again.
        (self.target / '.gitignore').write_text('.env*\n!.env.example\n', encoding='utf-8')
        (self.target / '.env.example').write_text('KEY=\n', encoding='utf-8')
        run('project', self.target, '--apply')
        lines = (self.target / '.gitignore').read_text(encoding='utf-8').splitlines()
        self.assertEqual(lines[-2:], ['.env*', '!.env.example'])
        self.assertLess(lines.index('.env.*'), lines.index('.env*'))
        git = shutil.which('git')
        if git:
            subprocess.run([git, 'init', '-q', str(self.target)], check=True, capture_output=True)
            ignored = subprocess.run([git, 'check-ignore', '-q', '.env.example'], cwd=self.target)
            self.assertEqual(ignored.returncode, 1, '.env.example must stay tracked')
            ignored = subprocess.run([git, 'check-ignore', '-q', '.env.local'], cwd=self.target)
            self.assertEqual(ignored.returncode, 0)

    def test_gitignore_merge_keeps_a_leading_bom_first(self):
        (self.target / '.gitignore').write_bytes(b'\xef\xbb\xbftarget/\n')
        run('project', self.target, '--apply')
        data = (self.target / '.gitignore').read_bytes()
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(data.count(b'\xef\xbb\xbf'), 1)

    def test_gitattributes_appends_so_specific_rules_override_a_generic_one(self):
        (self.target / '.gitattributes').write_text('* text=auto eol=crlf\n', encoding='utf-8')
        run('project', self.target, '--apply')
        lines = (self.target / '.gitattributes').read_text(encoding='utf-8').splitlines()
        self.assertEqual(lines[0], '* text=auto eol=crlf')
        self.assertIn('mvnw text eol=lf', lines[1:])

    def test_differing_plain_file_is_conflict_and_preserved(self):
        (self.target / 'CLAUDE.md').write_text('# mine\n', encoding='utf-8')
        code, out, _ = run('project', self.target, '--apply')
        self.assertEqual(code, 0)
        self.assertEqual((self.target / 'CLAUDE.md').read_text(encoding='utf-8'), '# mine\n')
        self.assertRegex(out, r'conflict\s+CLAUDE\.md')

    def test_claude_md_without_agents_import_is_flagged(self):
        (self.target / 'CLAUDE.md').write_text('# mine\n', encoding='utf-8')
        note = {a.rel: a for a in install.plan_project(self.target)}['CLAUDE.md'].note
        self.assertIn('@AGENTS.md', note)
        (self.target / 'CLAUDE.md').write_text('@AGENTS.md\n# mine\n', encoding='utf-8')
        note = {a.rel: a for a in install.plan_project(self.target)}['CLAUDE.md'].note
        self.assertNotIn('lacks', note)

    def test_gitattributes_same_pattern_override_is_noted(self):
        (self.target / '.gitattributes').write_text('mvnw text eol=crlf\n', encoding='utf-8')
        action = {a.rel: a for a in install.plan_project(self.target)}['.gitattributes']
        self.assertEqual(action.kind, 'merge')
        self.assertIn("'mvnw' is overridden", action.note)

    def test_non_string_rules_and_legacy_broad_syntax(self):
        settings = self.target / '.claude/settings.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps({'permissions': {'allow': [{'tool': 'Bash'}]}}), encoding='utf-8')
        self.assertEqual(self.kinds()['.claude/settings.json'], 'conflict')
        settings.write_text(json.dumps({'permissions': {'allow': ['Bash(./mvnw:*)']}}), encoding='utf-8')
        note = {a.rel: a for a in install.plan_project(self.target)}['.claude/settings.json'].note
        self.assertIn('broad rule', note)

    @unittest.skipIf(os.name == 'nt', 'symlinks need privileges on Windows')
    def test_symlinked_destination_is_not_written_through(self):
        shared = self.target / 'shared-ignore'
        shared.write_text('x\n', encoding='utf-8')
        (self.target / '.gitignore').symlink_to(shared)
        run('project', self.target, '--apply')
        self.assertEqual(shared.read_text(encoding='utf-8'), 'x\n')
        self.assertEqual(self.kinds()['.gitignore'], 'conflict')

    @unittest.skipIf(os.name == 'nt', 'symlinks need privileges on Windows')
    def test_dangling_symlink_is_a_conflict_and_nothing_is_created_behind_it(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        # One link whose parent exists (a file could be created there) and one whose parent does not.
        (self.target / 'AGENTS.md').symlink_to(Path(outside.name) / 'leak.md')
        (self.target / 'CLAUDE.md').symlink_to(Path(outside.name) / 'missing-dir/CLAUDE.md')
        code, out, _ = run('project', self.target, '--apply')
        self.assertEqual(code, 0)
        self.assertEqual(os.listdir(outside.name), [])
        self.assertRegex(out, r'conflict\s+AGENTS\.md\s+\(destination is a symlink')
        self.assertRegex(out, r'conflict\s+CLAUDE\.md\s+\(destination is a symlink')
        # The rest of the plan is still applied.
        self.assertTrue((self.target / 'scripts/sync_rules.py').is_file())

    def test_unwritable_destination_is_reported_and_the_rest_is_applied(self):
        # ".claude" is a file, so nothing can be created below it.
        (self.target / '.claude').write_text('not a directory\n', encoding='utf-8')
        code, out, _ = run('project', self.target, '--apply')
        self.assertEqual(code, 1)
        self.assertRegex(out, r'error\s+\.claude/settings\.json\s+\(not written: ')
        self.assertIn('could not be written', out)
        self.assertEqual((self.target / '.claude').read_text(encoding='utf-8'), 'not a directory\n')
        self.assertTrue((self.target / 'AGENTS.md').is_file())
        self.assertTrue((self.target / 'scripts/sync_rules.py').is_file())

    def test_diff_option_prints_conflict_differences(self):
        (self.target / 'CLAUDE.md').write_text('# mine\n', encoding='utf-8')
        _, out, _ = run('project', self.target)
        self.assertIn('--diff prints the differences', out)
        self.assertNotIn('--- CLAUDE.md (existing)', out)
        _, out, _ = run('project', self.target, '--diff')
        self.assertIn('--- CLAUDE.md (existing)', out)
        self.assertIn('+++ CLAUDE.md (template)', out)
        self.assertIn('-# mine', out)
        self.assertIn('+@AGENTS.md', out)
        self.assertEqual((self.target / 'CLAUDE.md').read_text(encoding='utf-8'), '# mine\n')

    def test_warns_without_maven_and_refuses_template_repo(self):
        (self.target / 'pom.xml').unlink()
        (self.target / 'mvnw').unlink()
        _, _, err = run('project', self.target)
        self.assertIn('no pom.xml', err)
        self.assertIn('no Maven Wrapper', err)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            install.main(['project', str(ROOT)])

    def doctor(self):
        return {message: level for level, message in install.doctor(self.target)}

    def test_doctor_fails_on_a_fresh_install_until_placeholders_are_filled(self):
        run('project', self.target, '--apply')
        code, out, _ = run('doctor', self.target)
        self.assertEqual(code, 1)
        self.assertRegex(out, r'fail\s+AGENTS\.md: \d+ TODO placeholder')
        self.assertRegex(out, r'warn\s+\.claude/skills/spring-endpoint/SKILL\.md')
        self.assertRegex(out, r'ok\s+CLAUDE\.md imports @AGENTS\.md')
        self.assertRegex(out, r'ok\s+\.github/instructions/ matches')
        for path in (self.target / 'AGENTS.md', self.target / '.claude/skills/spring-endpoint/SKILL.md'):
            path.write_text(path.read_text(encoding='utf-8').replace('<!-- TODO', '<!-- done'), encoding='utf-8')
        code, out, _ = run('doctor', self.target)
        self.assertEqual(code, 0, out)
        self.assertIn('fail: 0', out)
        # The only warnings left are the remote MCP services the template enables by default, if any.
        remote = {name for name, server in json.loads((PROJECT / '.mcp.json').read_text(encoding='utf-8'))['mcpServers'].items()
                  if server.get('url')}
        warnings = [line for line in out.splitlines() if line.startswith('warn ')]
        self.assertEqual(len(warnings), len(remote), warnings)
        for name in remote:
            self.assertTrue(any(f"'{name}' is a remote service" in line for line in warnings), warnings)

    def test_doctor_reports_drift_and_risky_configuration(self):
        run('project', self.target, '--apply')
        (self.target / 'CLAUDE.md').write_text('# mine\n', encoding='utf-8')
        rule = self.target / '.claude/rules/jsp.md'
        rule.write_text(rule.read_text(encoding='utf-8') + '\n- 追加ルール\n', encoding='utf-8')
        (self.target / '.claude/settings.json').write_text(json.dumps(
            {'permissions': {'allow': ['Bash(./mvnw *)']}, 'hooks': {'Stop': [{'hooks': []}]}}), encoding='utf-8')
        (self.target / '.mcp.json').write_text(json.dumps({'mcpServers': {
            'docs': {'type': 'http', 'url': 'https://example.invalid/mcp'},
            'loose': {'command': 'npx', 'args': ['-y', 'some-mcp@latest']},
            'pinned': {'command': 'npx', 'args': ['-y', '@scope/some-mcp@1.2.3']}}}), encoding='utf-8')
        found = self.doctor()
        levels = {level: [m for m, lv in found.items() if lv == level] for level in ('warn', 'fail')}
        self.assertTrue(any('without @AGENTS.md' in m for m in levels['fail']))
        self.assertTrue(any('out of sync' in m for m in levels['fail']))
        self.assertTrue(any('broad Maven allow' in m for m in levels['warn']))
        self.assertTrue(any('no Read deny rule for .env' in m for m in levels['warn']))
        self.assertTrue(any('hooks are registered' in m for m in levels['warn']))
        self.assertTrue(any("'docs' is a remote service" in m for m in levels['warn']))
        self.assertTrue(any("'loose' is started with npx without a pinned version" in m for m in levels['warn']))
        self.assertFalse(any("'pinned'" in m for m in found))

    def test_doctor_flags_tracked_local_files_and_writes_nothing(self):
        git = shutil.which('git')
        if not git:
            self.skipTest('git not available')
        run('project', self.target, '--apply')
        (self.target / '.env').write_text('SECRET=x\n', encoding='utf-8')
        (self.target / '.env.example').write_text('SECRET=\n', encoding='utf-8')
        subprocess.run([git, 'init', '-q', str(self.target)], check=True, capture_output=True)
        subprocess.run([git, '-C', str(self.target), 'add', '-f', '.env', '.env.example'], check=True, capture_output=True)
        before = {p: p.read_bytes() for p in self.target.rglob('*') if p.is_file() and '.git' not in p.parts}
        found = self.doctor()
        self.assertEqual(found["tracked by git but must stay local: ['.env']"], 'fail')
        self.assertEqual(before, {p: p.read_bytes() for p in self.target.rglob('*') if p.is_file() and '.git' not in p.parts})
        self.assertEqual(install.doctor(self.target / 'scripts')[0][0], 'fail', 'a directory without AGENTS.md')

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
