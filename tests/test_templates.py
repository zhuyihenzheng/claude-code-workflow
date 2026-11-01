import json
import os
from pathlib import Path
import re
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'templates/project'


def markdown_files(root):
    excluded = {'.git', '.venv', 'venv', 'node_modules', '__pycache__'}
    for directory, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in excluded]
        for name in files:
            if name.endswith('.md'):
                yield Path(directory) / name


def workflow(name):
    # BaseLoader preserves GitHub's YAML 1.2 key "on" (SafeLoader uses YAML 1.1).
    return yaml.load((PROJECT / '.github/workflows' / name).read_text(encoding='utf-8'), Loader=yaml.BaseLoader)


class TemplateTests(unittest.TestCase):
    def test_json_templates_parse(self):
        for path in (ROOT / 'templates').rglob('*.json'):
            with self.subTest(path=path):
                self.assertIsInstance(json.loads(path.read_text(encoding='utf-8')), dict)

    def test_no_hooks_enabled_and_reference_script_exists(self):
        config = json.loads((PROJECT / '.claude/settings.json').read_text(encoding='utf-8'))
        self.assertNotIn('hooks', config)
        self.assertTrue((PROJECT / '.claude/hooks/verify-stop.py').is_file())

    def test_maven_allow_rules_cover_windows_and_posix(self):
        allowed = json.loads((PROJECT / '.claude/settings.json').read_text(encoding='utf-8'))['permissions']['allow']
        for tool, wrapper in (('Bash', './mvnw'), ('Bash', 'mvnw.cmd'),
                              ('Bash', './mvnw.cmd'), ('PowerShell', '.\\mvnw.cmd')):
            with self.subTest(tool=tool, wrapper=wrapper):
                for args in ('-q compile', '-B -q compile', 'test', 'verify'):
                    self.assertIn(f'{tool}({wrapper} {args})', allowed)
                self.assertNotIn(f'{tool}({wrapper} *)', allowed)

    def test_wrapper_line_endings_are_explicit(self):
        attributes = PROJECT / '.gitattributes'
        self.assertTrue(attributes.is_file())
        rules = attributes.read_text(encoding='utf-8').splitlines()
        for rule in ('mvnw text eol=lf', '*.cmd text eol=crlf', '*.sh text eol=lf'):
            self.assertIn(rule, rules)

    def test_migrations_are_not_blanket_denied(self):
        config = json.loads((PROJECT / '.claude/settings.json').read_text(encoding='utf-8'))['permissions']
        self.assertNotIn('Bash(./mvnw *)', config['allow'])
        self.assertFalse(any('db/migration' in x for x in config['deny']))
        self.assertIn('Edit(/src/main/resources/db/migration/**)', config['ask'])
        self.assertIn('Read(/**/.env)', config['deny'])
        self.assertIn('Bash(./mvnw -B -q compile)', config['allow'])
        for tool in ('Read', 'Edit'):
            self.assertIn(tool + '(/**/.env.*)', config['deny'])
            self.assertNotIn(tool + '(/.env)', config['deny'])
            self.assertNotIn(tool + '(/.env.*)', config['deny'])

    def test_mentions_are_separate_from_pr_automation(self):
        data = workflow('claude.yml')
        self.assertNotIn('pull_request', data['on'])
        job = data['jobs']['claude']
        for event in data['on']:
            self.assertIn("github.event_name == '" + event + "'", job['if'])
        self.assertIn('github.event.issue.title', job['if'])
        self.assertEqual(job['permissions']['id-token'], 'write')
        self.assertIn('--max-turns', job['steps'][-1]['with']['claude_args'])
        self.assertIn('--max-budget-usd', job['steps'][-1]['with']['claude_args'])
        self.assertTrue(job['timeout-minutes'])
        self.assertEqual(job['permissions']['actions'], 'read')
        self.assertEqual(job['steps'][-1]['with']['additional_permissions'].strip(), 'actions: read')

    def test_opt_in_review_has_prompt_and_excludes_forks_and_drafts(self):
        data = workflow('claude-review.yml.example')
        self.assertIn('pull_request', data['on'])
        self.assertNotIn('pull_request_target', data['on'])
        job = data['jobs']['review']
        self.assertIn('head.repo.full_name == github.repository', job['if'])
        self.assertIn('draft == false', job['if'])
        self.assertIn('base.sha', job['steps'][0]['with']['ref'])
        self.assertEqual(job['permissions']['contents'], 'read')
        self.assertNotIn('id-token', job['permissions'])
        self.assertTrue(all(value == 'read' for value in job['permissions'].values()))
        action = job['steps'][-1]
        self.assertEqual(action['with']['github_token'], '${{ github.token }}')
        self.assertEqual(action['env']['GH_TOKEN'], '${{ github.token }}')
        preflight = job['steps'][1]
        self.assertEqual(preflight['env']['GH_TOKEN'], '${{ github.token }}')
        self.assertIn('gh pr diff', preflight['run'])
        self.assertIn('gh pr view', preflight['run'])
        self.assertNotIn('continue-on-error', preflight)
        prompt = action['with']['prompt']
        self.assertIn('BASE files only', prompt)
        self.assertIn("diff's added-side hunk ranges", prompt)
        self.assertIn('report review incomplete', prompt)
        self.assertIn('--max-budget-usd', job['steps'][-1]['with']['claude_args'])

    def test_active_mcp_needs_no_secrets_and_versions_are_pinned(self):
        active = json.loads((PROJECT / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']
        self.assertNotIn('${', json.dumps(active))
        self.assertNotIn('dbhub', active)
        self.assertNotIn('github', active)
        for path in (ROOT / 'templates').rglob('*mcp*.json'):
            servers = json.loads(path.read_text(encoding='utf-8'))['mcpServers']
            for server in servers.values():
                if server.get('command') == 'npx':
                    package = server['args'][1]
                    self.assertRegex(package, r'@\d+\.\d+\.\d+$')

    def test_relative_markdown_links_exist(self):
        for path in markdown_files(ROOT):
            for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^\s)]+)\)', path.read_text(encoding='utf-8')):
                if ':' in target or target.startswith('#'):
                    continue
                target = target.split('#')[0]
                with self.subTest(file=str(path.relative_to(ROOT)), target=target):
                    self.assertTrue((path.parent / target).exists())

    def test_link_scan_prunes_dependencies_but_keeps_project_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('docs/guide.md', 'README.md', '.git/internal.md', '.venv/pkg/readme.md',
                         'nested/node_modules/pkg/readme.md', 'venv/readme.md', '__pycache__/readme.md'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('[broken dependency link](missing.md)', encoding='utf-8')
            self.assertEqual({p.relative_to(root).as_posix() for p in markdown_files(root)}, {'docs/guide.md', 'README.md'})

    def test_validation_runs_on_pr_and_main_push_only(self):
        data = yaml.load((ROOT / '.github/workflows/validate.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
        self.assertIn('pull_request', data['on'])
        self.assertEqual(data['on']['push']['branches'], ['main'])
        self.assertEqual(set(data['jobs']['validate']['strategy']['matrix']['os']),
                         {'ubuntu-latest', 'macos-latest', 'windows-latest'})

    def test_user_skills_have_matching_frontmatter_and_license(self):
        skills = ROOT / 'templates/user/skills'
        self.assertTrue((skills / 'LICENSE-mattpocock-skills').is_file())
        for skill in ('diagnosing-bugs', 'grilling', 'writing-for-agents', 'handoff', 'retro'):
            with self.subTest(skill=skill):
                text = (skills / skill / 'SKILL.md').read_text(encoding='utf-8')
                self.assertTrue(text.startswith('---\n'))
                self.assertIn(f'\nname: {skill}\n', text.split('\n---', 2)[0] + '\n')

    def test_no_personal_absolute_paths(self):
        for path in markdown_files(ROOT):
            with self.subTest(path=path):
                self.assertNotRegex(path.read_text(encoding='utf-8'), r'/Users/[A-Za-z]|[A-Za-z]:\\Users\\[A-Za-z]')

if __name__ == '__main__':
    unittest.main()
