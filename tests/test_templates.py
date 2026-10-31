import json
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'templates/project'


def workflow(name):
    # BaseLoader preserves GitHub's YAML 1.2 key "on" (SafeLoader uses YAML 1.1).
    return yaml.load((PROJECT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


class TemplateTests(unittest.TestCase):
    def test_json_templates_parse(self):
        for path in (ROOT / 'templates').rglob('*.json'):
            with self.subTest(path=path):
                self.assertIsInstance(json.loads(path.read_text()), dict)

    def test_hook_configuration_has_no_fake_events_and_script_exists(self):
        config = json.loads((PROJECT / '.claude/settings.json').read_text())
        self.assertEqual(set(config['hooks']), {'Stop'})
        handler = config['hooks']['Stop'][0]['hooks'][0]
        self.assertIn('"$CLAUDE_PROJECT_DIR/.claude/hooks/verify-stop.py"', handler['command'])
        self.assertGreater(handler['timeout'], 90)
        self.assertTrue((PROJECT / '.claude/hooks/verify-stop.py').is_file())

    def test_migrations_are_not_blanket_denied(self):
        config = json.loads((PROJECT / '.claude/settings.json').read_text())['permissions']
        self.assertNotIn('Bash(./mvnw *)', config['allow'])
        self.assertFalse(any('db/migration' in x for x in config['deny']))
        self.assertIn('Edit(/src/main/resources/db/migration/**)', config['ask'])
        self.assertIn('Read(/**/.env)', config['deny'])

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

    def test_opt_in_review_has_prompt_and_excludes_forks_and_drafts(self):
        data = workflow('claude-review.yml.example')
        self.assertIn('pull_request', data['on'])
        self.assertNotIn('pull_request_target', data['on'])
        job = data['jobs']['review']
        self.assertIn('head.repo.full_name == github.repository', job['if'])
        self.assertIn('draft == false', job['if'])
        self.assertIn('base.sha', job['steps'][0]['with']['ref'])
        self.assertEqual(job['permissions']['contents'], 'read')
        self.assertEqual(job['permissions']['id-token'], 'write')
        self.assertTrue(job['steps'][-1]['with']['prompt'])
        self.assertIn('--max-budget-usd', job['steps'][-1]['with']['claude_args'])

    def test_active_mcp_needs_no_secrets_and_versions_are_pinned(self):
        active = json.loads((PROJECT / '.mcp.json').read_text())['mcpServers']
        self.assertNotIn('${', json.dumps(active))
        self.assertNotIn('dbhub', active)
        self.assertNotIn('github', active)
        for path in (ROOT / 'templates').rglob('*mcp*.json'):
            servers = json.loads(path.read_text())['mcpServers']
            for server in servers.values():
                if server.get('command') == 'npx':
                    package = server['args'][1]
                    self.assertRegex(package, r'@\d+\.\d+\.\d+$')

    def test_relative_markdown_links_exist(self):
        for path in ROOT.rglob('*.md'):
            for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^\s)]+)\)', path.read_text()):
                if ':' in target or target.startswith('#'):
                    continue
                target = target.split('#')[0]
                with self.subTest(file=str(path.relative_to(ROOT)), target=target):
                    self.assertTrue((path.parent / target).exists())


if __name__ == '__main__':
    unittest.main()
