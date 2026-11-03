from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'templates/project'
SCRIPT = ROOT / 'scripts/sync_rules.py'


def run_sync(*args, script=SCRIPT, cwd=ROOT):
    return subprocess.run([sys.executable, str(script), *map(str, args)], cwd=cwd,
                          capture_output=True, text=True, encoding='utf-8')


def split_rule(path):
    _, header, body = path.read_text(encoding='utf-8').split('---\n', 2)
    return yaml.safe_load(header), body


class CopilotTests(unittest.TestCase):
    def test_shared_rules_and_claude_import(self):
        agents = (PROJECT / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertLess(len(agents.splitlines()), 150)
        self.assertIn('## チーム共通ルール', agents.splitlines())
        self.assertIn('## 本システム固有情報', agents.splitlines())
        for heading in re.findall(r'^#+ .+$', agents, re.MULTILINE):
            self.assertNotRegex(heading, r'(?i)Claude|Copilot')
        claude = (PROJECT / 'CLAUDE.md').read_text(encoding='utf-8')
        self.assertEqual(claude.splitlines()[0], '@AGENTS.md')

    def test_copilot_entry_references_source(self):
        instructions = (PROJECT / '.github/copilot-instructions.md').read_text(encoding='utf-8')
        self.assertIn('AGENTS.md', instructions)

    def test_generated_globs_and_bodies_match_sources(self):
        sources = sorted((PROJECT / '.claude/rules').glob('*.md'))
        mirrors = PROJECT / '.github/instructions'
        self.assertEqual({p.name for p in mirrors.glob('*.instructions.md')},
                         {f'{p.stem}.instructions.md' for p in sources})
        for source in sources:
            with self.subTest(source=source.name):
                original, body = split_rule(source)
                generated, mirror_body = split_rule(mirrors / f'{source.stem}.instructions.md')
                self.assertEqual(generated['applyTo'].split(','), original['paths'])
                self.assertEqual(mirror_body, body)

    def test_check_default_root_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_sync('--check', cwd=directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_changed_source_fails_check_then_regenerates(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / '测试 project'
            shutil.copytree(PROJECT, project)
            # 脚本复制进业务仓库后，从该仓库显式传入根目录也能工作。
            script = project / 'scripts/sync_rules.py'
            script.parent.mkdir()
            shutil.copy2(SCRIPT, script)
            rule = project / '.claude/rules/htmx.md'
            rule.write_bytes(rule.read_bytes() + '\n- 新增规则：验证失败必须报告。\n'.encode('utf-8'))
            target = project / '.github/instructions/htmx.instructions.md'
            before = target.read_bytes()
            result = run_sync('.', '--check', script=script, cwd=project)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(target.read_bytes(), before, '--check must not write')
            result = run_sync('.', script=script, cwd=project)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = run_sync('.', '--check', script=script, cwd=project)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('新增规则', target.read_text(encoding='utf-8'))
            self.assertNotIn(b'\r', target.read_bytes())

    def test_missing_mirror_is_detected_and_created(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'
            shutil.copytree(PROJECT, project)
            target = project / '.github/instructions/jsp.instructions.md'
            target.unlink()
            self.assertEqual(run_sync(project, '--check').returncode, 1)
            self.assertFalse(target.exists())
            result = run_sync(project)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(target.is_file())

    def test_removed_rule_cleans_only_generated_mirror(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'
            shutil.copytree(PROJECT, project)
            (project / '.claude/rules/jsp.md').unlink()
            custom = project / '.github/instructions/custom.instructions.md'
            custom.write_text('---\napplyTo: "**/*.java"\n---\n项目自有规则\n', encoding='utf-8')
            self.assertEqual(run_sync(project, '--check').returncode, 1)
            target = project / '.github/instructions/jsp.instructions.md'
            self.assertTrue(target.exists())
            result = run_sync(project)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(target.exists())
            self.assertTrue(custom.is_file())
            self.assertEqual(run_sync(project, '--check').returncode, 0)

    def test_block_lists_and_crlf_input(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            rules = project / '.claude/rules'
            rules.mkdir(parents=True)
            text = '---\npaths:\n  - "src/**/*.java"\n  - \'src/**/*.jsp\'\n  - src/**/*.html\n---\n\n# 规则\n\n保留正文。\n'
            (rules / 'mixed.md').write_bytes(text.replace('\n', '\r\n').encode('utf-8'))
            result = run_sync(project)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            target = project / '.github/instructions/mixed.instructions.md'
            metadata, body = split_rule(target)
            self.assertEqual(metadata['applyTo'], 'src/**/*.java,src/**/*.jsp,src/**/*.html')
            self.assertEqual(body, '\n# 规则\n\n保留正文。\n')
            self.assertNotIn(b'\r', target.read_bytes())
            self.assertEqual(run_sync(project, '--check').returncode, 0)
            target.write_bytes(target.read_bytes().replace(b'\n', b'\r\n'))
            self.assertEqual(run_sync(project, '--check').returncode, 1)
            self.assertEqual(run_sync(project).returncode, 0)
            self.assertNotIn(b'\r', target.read_bytes())

    def test_invalid_source_fails_before_any_writes(self):
        for header in ('', '---\npaths: []\n---\n', '---\npaths:\n---\n'):
            with self.subTest(header=header), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                rules = project / '.claude/rules'
                rules.mkdir(parents=True)
                (rules / 'a-valid.md').write_text('---\npaths:\n  - "**/*.jsp"\n---\n规则\n', encoding='utf-8')
                (rules / 'z-invalid.md').write_text(header + '规则\n', encoding='utf-8')
                result = run_sync(project)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse((project / '.github/instructions').exists())

    def test_missing_project_fails_without_creating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'missing'
            result = run_sync(project, '--check')
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertFalse(project.exists())


if __name__ == '__main__':
    unittest.main()
