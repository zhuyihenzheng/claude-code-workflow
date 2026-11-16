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


def rule_matches(pattern, command):
    """Bash permission rule matching as documented at code.claude.com/docs/en/permissions:
    the rule matches the whole command, '*' stands for any text, and a single trailing
    ' *' also matches the bare command."""
    regex = '.*'.join(re.escape(part) for part in pattern.split('*'))
    if re.fullmatch(regex, command):
        return True
    return pattern.count('*') == 1 and pattern.endswith(' *') and command == pattern[:-2]


class TemplateTests(unittest.TestCase):
    def test_installed_files_have_no_chinese_simplified_characters(self):
        # Everything the installer copies into a (Japanese) target project, scripts included.
        # Use simplified forms absent from normal Japanese; shared kanji such as
        # 面, 行, 写, 数, 要, 内 and 容 must remain valid in Japanese templates.
        simplified_only = set('们这么个进还时说对过门问题应该实现设计测试检查运页开发编译错误关闭删读认证输据库处选择务环变权规间仅块单规则镜')
        installed = [path for path in PROJECT.rglob('*') if path.is_file() and '__pycache__' not in path.parts]
        self.assertGreater(len(installed), 15)
        for path in installed:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                found = sorted(simplified_only.intersection(path.read_text(encoding='utf-8')))
                self.assertFalse(found, f'Chinese simplified characters remain: {"".join(found)}')

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

    def test_force_push_deny_rules_cover_common_spellings(self):
        # rule_matches() follows the documented Bash rule semantics; it is not Claude Code's
        # permission engine, so this guards the rule text, not the product's behaviour.
        deny = json.loads((PROJECT / '.claude/settings.json').read_text(encoding='utf-8'))['permissions']['deny']
        rules = [rule[5:-1] for rule in deny if rule.startswith('Bash(git push')]

        def denied(command):
            return any(rule_matches(rule, command) for rule in rules)

        for command in ('git push --force', 'git push --force origin main', 'git push -f', 'git push -f origin main',
                        'git push origin main --force', 'git push origin --force main',
                        'git push origin main -f', 'git push origin -f main'):
            with self.subTest(command=command):
                self.assertTrue(denied(command))
        for command in ('git push', 'git push origin main', 'git push -u origin feature/x',
                        'git push --force-with-lease', 'git push origin feature/x --force-with-lease',
                        'git push origin fix-form', 'git push --follow-tags'):
            with self.subTest(command=command):
                self.assertFalse(denied(command))

    def test_company_edition_hardening(self):
        settings = json.loads((PROJECT / '.claude/settings.json').read_text(encoding='utf-8'))
        self.assertIs(settings['disableClaudeAiConnectors'], True)
        self.assertIs(settings['enableArtifact'], False)
        self.assertEqual(settings['permissions']['disableBypassPermissionsMode'], 'disable')
        # curl stays usable: the agent polls the local service before a browser check, and an allow
        # rule cannot carve an exception out of a deny. Egress is limited by the managed sandbox instead.
        self.assertFalse([rule for rule in settings['permissions']['deny'] if 'curl' in rule or 'wget' in rule])
        self.assertNotIn('enabledPlugins', settings)
        self.assertNotIn('extraKnownMarketplaces', settings)
        # No file in the repository asks a team to enable third-party plugins or marketplaces.
        for path in (ROOT / 'templates').rglob('*.json'):
            if path.name == 'managed-settings.example.json':
                continue
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('enabledPlugins', text, path)
            self.assertNotIn('extraKnownMarketplaces', text, path)
        managed = json.loads((ROOT / 'templates/managed-settings.example.json').read_text(encoding='utf-8'))
        self.assertIs(managed['allowManagedMcpServersOnly'], True)
        guard = managed['pluginConfigs']['cc-plugin-sec-default@builtin']['options']
        self.assertIs(guard['allowManagedModsOnly'], True)
        self.assertNotIn('allowManagedModsOnly', managed, 'it is an option of the built-in guard, not a top-level key')
        # The allowlist names the exact command the template starts, so the two cannot drift apart.
        playwright = json.loads((PROJECT / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']['playwright']
        self.assertEqual(managed['allowedMcpServers'], [{'serverCommand': [playwright['command'], *playwright['args']]}])
        self.assertIs(managed['sandbox']['network']['allowManagedDomainsOnly'], True)
        self.assertEqual(managed['strictKnownMarketplaces'], [])
        self.assertIs(managed['sandbox']['allowUnsandboxedCommands'], False)
        self.assertNotIn('xxxxxxxx', json.dumps(managed))

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
        self.assertIn('BASE のファイルのみ', prompt)
        self.assertIn('diff の追加側のハンク範囲', prompt)
        self.assertIn('「レビュー未完了」と報告', prompt)
        self.assertIn('--max-budget-usd', job['steps'][-1]['with']['claude_args'])

    def test_active_mcp_needs_no_secrets_and_versions_are_pinned(self):
        active = json.loads((PROJECT / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']
        self.assertNotIn('${', json.dumps(active))
        # Company edition: nothing in the default set talks to a remote MCP service.
        self.assertEqual(set(active), {'playwright'})
        for server in active.values():
            self.assertNotIn('url', server)
            self.assertNotEqual(server.get('type'), 'http')
        optional = json.loads((ROOT / 'templates/mcp.optional.json').read_text(encoding='utf-8'))['mcpServers']
        self.assertEqual(set(optional), {'context7', 'dbhub', 'github'})
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
        self.assertEqual(data['on']['push']['branches'], ['main', 'company'])
        self.assertEqual(set(data['jobs']['validate']['strategy']['matrix']['os']),
                         {'ubuntu-latest', 'macos-latest', 'windows-latest'})

    def test_user_skills_have_matching_frontmatter_and_license(self):
        skills = ROOT / 'templates/user/skills'
        self.assertTrue((skills / 'LICENSE-mattpocock-skills').is_file())
        expected = {'diagnosing-bugs', 'grilling', 'writing-for-agents'}
        self.assertEqual({p.name for p in skills.iterdir() if p.is_dir()}, expected)
        for skill in sorted(expected):
            with self.subTest(skill=skill):
                text = (skills / skill / 'SKILL.md').read_text(encoding='utf-8')
                self.assertTrue(text.startswith('---\n'))
                self.assertIn(f'\nname: {skill}\n', text.split('\n---', 2)[0] + '\n')

    def test_claude_md_stays_under_line_budget(self):
        lines = (PROJECT / 'CLAUDE.md').read_text(encoding='utf-8').splitlines()
        self.assertLess(len(lines), 200)

    def test_project_agents_skills_and_rules_have_frontmatter(self):
        def frontmatter(path):
            text = path.read_text(encoding='utf-8')
            self.assertTrue(text.startswith('---\n'), path)
            return yaml.safe_load(text.split('\n---', 2)[0][4:])

        for path in (PROJECT / '.claude/agents').glob('*.md'):
            with self.subTest(path=path.name):
                meta = frontmatter(path)
                self.assertEqual(meta['name'], path.stem)
                self.assertTrue(meta['description'])
                self.assertNotIn('Bash', meta.get('tools', ''))
        for path in (PROJECT / '.claude/skills').glob('*/SKILL.md'):
            with self.subTest(path=path.parent.name):
                meta = frontmatter(path)
                self.assertEqual(meta['name'], path.parent.name)
                self.assertTrue(meta['description'])
        for path in (PROJECT / '.claude/rules').glob('*.md'):
            with self.subTest(path=path.name):
                self.assertTrue(frontmatter(path)['paths'])

    def test_no_personal_absolute_paths(self):
        for path in markdown_files(ROOT):
            with self.subTest(path=path):
                self.assertNotRegex(path.read_text(encoding='utf-8'), r'/Users/[A-Za-z]|[A-Za-z]:\\Users\\[A-Za-z]')

if __name__ == '__main__':
    unittest.main()
