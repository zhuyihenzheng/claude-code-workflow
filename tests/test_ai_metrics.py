import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'templates/project/scripts'))
import ai_metrics  # noqa: E402


def pr(number, merged, branch='claude/x', author='dev', reviews=(), commits=()):
    return {'number': number, 'title': f'PR {number}', 'author': {'login': author}, 'headRefName': branch,
            'createdAt': '2026-01-01T00:00:00Z', 'mergedAt': merged,
            'reviews': [{'author': {'login': who}, 'state': state, 'submittedAt': at} for who, state, at in reviews],
            'commits': [{'committedDate': at, 'messageBody': body} for at, body in commits]}


PRS = [
    # January: one PR reworked twice after a change request, one that passed first time.
    pr(1, '2026-01-10T00:00:00Z', reviews=[('lead', 'CHANGES_REQUESTED', '2026-01-05T00:00:00Z'),
                                           ('lead', 'APPROVED', '2026-01-08T00:00:00Z')],
       commits=[('2026-01-04T00:00:00Z', ''), ('2026-01-06T00:00:00Z', ''), ('2026-01-07T00:00:00Z', '')]),
    pr(2, '2026-01-20T00:00:00Z', reviews=[('lead', 'APPROVED', '2026-01-19T00:00:00Z')],
       commits=[('2026-01-18T00:00:00Z', '')]),
    # February: passes first time; the author's own review and a self-reply do not count.
    pr(3, '2026-02-03T00:00:00Z', branch='feature/y', reviews=[('dev', 'COMMENTED', '2026-02-01T00:00:00Z'),
                                                               ('lead', 'APPROVED', '2026-02-02T00:00:00Z')],
       commits=[('2026-02-01T12:00:00Z', 'Fix\n\nCo-Authored-By: Claude <noreply@anthropic.com>')]),
    # A person's PR without AI involvement, and an unmerged one.
    pr(4, '2026-02-05T00:00:00Z', branch='feature/z', reviews=[('lead', 'CHANGES_REQUESTED', '2026-02-04T00:00:00Z')],
       commits=[('2026-02-04T12:00:00Z', '')]),
    pr(5, None),
]


class AiMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.input = self.dir / 'prs.json'
        self.input.write_text(json.dumps(PRS), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def run_metrics(self, *args, root=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = ai_metrics.main(['--input', str(self.input), '--root', str(root or self.dir), *args])
        return code, out.getvalue()

    def test_monthly_rework_of_ai_pull_requests(self):
        code, out = self.run_metrics('--json')
        self.assertEqual(code, 0, out)
        rows = {r['month']: r for r in json.loads(out)}
        self.assertEqual(rows['2026-01'], {'month': '2026-01', 'prs': 2, 'first_pass_rate': 0.5, 'rework_per_pr': 1.0,
                                           'changes_requested_per_pr': 0.5, 'rules_added': 0, 'knowledge_commits': 0})
        self.assertEqual((rows['2026-02']['prs'], rows['2026-02']['first_pass_rate']), (1, 1.0))
        code, out = self.run_metrics('--json', '--all')
        self.assertEqual(json.loads(out)[1]['prs'], 2)
        code, out = self.run_metrics('--since', '2026-02-01')
        self.assertIn('| 2026-02 | 1 | 100% | 0 | 0 | 0 | 0 |', out)
        self.assertNotIn('2026-01', out)

    def test_bad_input_is_an_error(self):
        self.input.write_text('{"not": "a list"}', encoding='utf-8')
        code, out = self.run_metrics()
        self.assertEqual(code, 2)
        self.assertIn('集計できません', out)

    @unittest.skipUnless(shutil.which('git'), 'git not installed')
    def test_rules_and_knowledge_updates_are_counted_from_git(self):
        repo = self.dir / 'repo'
        (repo / 'config/guard').mkdir(parents=True)
        (repo / 'docs/knowledge').mkdir(parents=True)
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.com'}

        def commit(date, files):
            for rel, text in files.items():
                (repo / rel).write_text(text, encoding='utf-8')
            subprocess.run(['git', '-C', str(repo), 'add', '-A'], check=True, env=env)
            subprocess.run(['git', '-C', str(repo), 'commit', '-q', '-m', 'c'], check=True,
                           env={**env, 'GIT_AUTHOR_DATE': date, 'GIT_COMMITTER_DATE': date})

        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        rules = lambda *ids: json.dumps({'rules': [{'id': i} for i in ids]}, indent=2)  # noqa: E731
        commit('2026-01-02T00:00:00', {'config/guard/rules.json': rules('a', 'b')})
        commit('2026-02-02T00:00:00', {'config/guard/rules.json': rules('a', 'b', 'c'), 'docs/knowledge/codemap.md': '# x\n'})
        # Re-indenting existing rules does not add them again.
        commit('2026-02-03T00:00:00', {'config/guard/rules.json': json.dumps({'rules': [{'id': i} for i in 'abc']}, indent=4)})
        code, out = self.run_metrics('--json', root=repo)
        rows = {r['month']: r for r in json.loads(out)}
        self.assertEqual((rows['2026-01']['rules_added'], rows['2026-02']['rules_added']), (2, 1))
        self.assertEqual(rows['2026-02']['knowledge_commits'], 1)


if __name__ == '__main__':
    unittest.main()
