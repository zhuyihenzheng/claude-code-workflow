import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.claude/skills/workflow-retro/scripts/session_metrics.py'
spec = importlib.util.spec_from_file_location('session_metrics', SCRIPT)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)

SECRET = 'customer-name-must-not-leak'


def prompt(text, **extra):
    return {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': text}, **extra}


def tool(name, **args):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'text', 'text': SECRET}, {'type': 'tool_use', 'id': 't', 'name': name, 'input': args}]}}


def result(error=False, **extra):
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 't', 'is_error': error, 'content': SECRET}]}, **extra}


def bash(command):
    return tool('Bash', command=command)


def edit(path):
    return tool('Edit', file_path=path, old_string=SECRET, new_string=SECRET)


class SessionMetricsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def session(self, name, *entries):
        path = self.dir / f'{name}.jsonl'
        path.write_text('\n'.join(json.dumps(e, ensure_ascii=False) for e in entries) + '\nnot json\n', encoding='utf-8')
        return path

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = metrics.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_edit_followed_by_the_required_check_is_verified(self):
        m = metrics.analyse(self.session(
            'aaaaaaaa-1', prompt(SECRET), edit('/p/src/main/java/a/OrderService.java'), result(),
            bash('cd /p && ./mvnw -Dtest=OrderServiceTest test'), result(),
            edit('/p/src/main/webapp/WEB-INF/jsp/orders/new.jsp'), result(),
            bash('node scripts/htmx-check.mjs --url http://localhost:8080/x --click "#a" --expect "#b"'), result()))
        self.assertEqual(m['outcome'], 'verified')
        self.assertEqual((m['edits']['backend'], m['edits']['view'], m['maven_tests'], m['browser_checks']), (1, 1, 1, 1))
        self.assertEqual(m['prompts'], 1)

    def test_edit_after_the_last_check_is_unverified(self):
        m = metrics.analyse(self.session(
            'bbbbbbbb-1', bash('./mvnw test'), result(), edit('/p/src/main/java/a/A.java'), result(),
            bash('./mvnw -q compile'), result()))
        self.assertTrue(m['backend_unverified'], 'compile is not a test run')
        self.assertEqual(m['outcome'], 'unverified')
        self.assertEqual(m['maven_compiles'], 1)

    def test_view_edit_needs_a_browser_check_and_test_edit_needs_maven(self):
        view = metrics.analyse(self.session(
            'cccccccc-1', edit('/p/src/main/webapp/a.jsp'), result(), bash('./mvnw verify'), result()))
        self.assertTrue(view['view_unverified'])
        self.assertFalse(view['backend_unverified'])
        mcp = metrics.analyse(self.session(
            'cccccccc-2', edit('/p/src/main/webapp/a.jsp'), result(), tool('mcp__playwright__browser_navigate', url='x'), result()))
        self.assertEqual(mcp['outcome'], 'verified')
        test_only = metrics.analyse(self.session('cccccccc-3', edit('/p/src/test/java/a/ATest.java'), result()))
        self.assertEqual(test_only['outcome'], 'unverified')

    def test_failed_or_skipped_checks_do_not_verify(self):
        failed = metrics.analyse(self.session(
            'c1c1c1c1-1', edit('/p/src/main/java/A.java'), result(), bash('./mvnw test'), result(error=True)))
        self.assertEqual((failed['outcome'], failed['maven_tests'], failed['maven_test_failures']), ('unverified', 1, 1))
        fixed = metrics.analyse(self.session(
            'c1c1c1c1-2', edit('/p/src/main/java/A.java'), result(), bash('./mvnw test'), result(error=True),
            bash('./mvnw test'), result()))
        self.assertEqual(fixed['outcome'], 'verified')
        skipped = metrics.analyse(self.session(
            'c1c1c1c1-3', edit('/p/src/main/java/A.java'), result(), bash('./mvnw -DskipTests package'), result(),
            bash('mvnw.cmd verify -Dmaven.test.skip=true'), result()))
        self.assertEqual((skipped['outcome'], skipped['maven_tests'], skipped['maven_compiles']), ('unverified', 0, 2))
        browser = metrics.analyse(self.session(
            'c1c1c1c1-4', edit('/p/src/main/webapp/a.jsp'), result(), bash('node scripts/htmx-check.mjs --url x'), result(error=True)))
        self.assertEqual((browser['outcome'], browser['browser_check_failures']), ('unverified', 1))
        unfinished = metrics.analyse(self.session('c1c1c1c1-5', edit('/p/src/main/java/A.java'), result(), bash('./mvnw test')))
        self.assertEqual(unfinished['outcome'], 'unverified', 'a check without a result did not finish')

    def test_file_kinds_decide_the_required_check(self):
        kinds = {'/p/src/main/resources/mapper/OrderMapper.xml': 'backend', '/p/src/main/resources/application.yml': 'backend',
                 '/p/src/main/resources/db/migration/V2__a.sql': 'migration', '/p/src/main/resources/templates/a.html': 'view',
                 '/p/src/main/resources/static/js/app.js': 'view', 'src/main/webapp/WEB-INF/jsp/a.jsp': 'view',
                 'C:\\p\\src\\test\\java\\ATest.java': 'test', '/p/README.md': 'other', '/p/scripts/tool.py': 'other',
                 '/p/pom.xml': 'other'}
        for path, kind in kinds.items():
            with self.subTest(path=path):
                self.assertEqual(metrics.edit_kind(path), kind)

    def test_checks_run_by_a_subagent_count(self):
        main = self.session(
            'c2c2c2c2-1', {**edit('/p/src/main/java/A.java'), 'timestamp': '2026-01-01T00:00:01Z'},
            {**tool('Agent', subagent_type='verifier'), 'timestamp': '2026-01-01T00:00:02Z'},
            {**result(), 'timestamp': '2026-01-01T00:00:09Z'})
        self.assertEqual(metrics.analyse(main)['outcome'], 'unverified')
        subagents = main.parent / main.stem / 'subagents'
        subagents.mkdir(parents=True)
        (subagents / 'agent-1.jsonl').write_text('\n'.join(json.dumps(e) for e in (
            {**prompt(SECRET), 'isSidechain': True, 'timestamp': '2026-01-01T00:00:03Z'},
            {**bash('./mvnw verify'), 'isSidechain': True, 'timestamp': '2026-01-01T00:00:04Z'},
            {**result(), 'isSidechain': True, 'timestamp': '2026-01-01T00:00:05Z'})), encoding='utf-8')
        m = metrics.analyse(main)
        self.assertEqual((m['outcome'], m['maven_tests'], m['prompts']), ('verified', 1, 0))
        self.assertIn(('agent-1:2', 'maven-test'), m['events'])

    def test_friction_and_rule_signals(self):
        m = metrics.analyse(self.session(
            'dddddddd-1', prompt('first'), bash('mvn test'), result(error=True),
            bash('git commit -m x'), result(toolDenialKind='permission-rule'),
            tool('Read', file_path='/p/specs/Design.XLSX'), result(permissionDecision={'decision': 'reject', 'reasonType': 'rule'}),
            tool('Skill', skill='spring-endpoint'), result(), tool('Agent', subagent_type='code-reviewer', prompt=SECRET), result(),
            {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '[Request interrupted by user]'}]}},
            prompt('<system-reminder>not a human turn</system-reminder>', origin={'kind': 'task-notification'}),
            {'type': 'user', 'isMeta': True, 'message': {'role': 'user', 'content': 'meta'}},
            {'type': 'system', 'subtype': 'compact_boundary'}, {'type': 'cost-state', 'totalCostUSD': 1.234}))
        self.assertEqual((m['prompts'], m['interrupts'], m['tool_errors'], m['system_mvn']), (1, 1, 1, 1))
        self.assertEqual(dict(m['denials']), {'permission-rule': 1, 'rule': 1})
        self.assertEqual((m['commits'], m['spec_xlsx_reads'], m['compactions'], m['cost_usd']), (1, 1, 1, 1.23))
        self.assertEqual((dict(m['skills']), dict(m['agents'])), ({'spring-endpoint': 1}, {'code-reviewer': 1}))
        self.assertEqual(m['outcome'], 'no-code-edit')

    def test_prompt_detection_without_origin_metadata(self):
        m = metrics.analyse(self.session(
            'eeeeeeee-1', {'type': 'user', 'message': {'role': 'user', 'content': 'please fix it'}},
            {'type': 'user', 'message': {'role': 'user', 'content': '<command-name>/clear</command-name>'}},
            bash('ls'), result()))
        self.assertEqual(m['prompts'], 1)

    def test_command_heads_carry_no_arguments_paths_or_heredoc_bodies(self):
        m = metrics.analyse(self.session(
            'ffffffff-1', bash(f'FOO=1 /usr/local/bin/gh pr view 12 && grep -rn "{SECRET}" /Users/someone/{SECRET}\n'
                               f'python3 - <<EOF\nimport {SECRET}\n}}\nEOF'), result()))
        self.assertEqual(dict(m['commands']), {'gh pr': 1, 'grep': 1, 'python3': 1})
        self.assertEqual(metrics.command_head('./mvnw test -Dx=1'), './mvnw test')
        self.assertEqual(metrics.command_head(f'./{SECRET}/run.sh {SECRET}'), 'run.sh')
        self.assertEqual(metrics.command_head(f'echo {SECRET}'), 'echo')

    def test_output_never_contains_transcript_text(self):
        self.session('gggggggg-1', prompt(SECRET), edit(f'/p/src/main/java/{SECRET}.java'), result(),
                     bash(f'./mvnw -Dtest={SECRET} test && echo {SECRET} && ./{SECRET}/run.sh && ../{SECRET}/x'), result(),
                     tool('Skill', skill='spring-endpoint'), result(), tool('Skill', skill=f'x {SECRET}'), result(),
                     tool('Agent', subagent_type=f'{SECRET} y'), result(toolDenialKind=f'{SECRET} z'))
        for flags in ((), ('--json',)):
            code, out, _ = self.run_cli('--transcripts', self.dir, *flags)
            self.assertEqual(code, 0)
            self.assertNotIn(SECRET, out)
            self.assertIn('gggggggg', out)
        self.assertEqual(json.loads(out)['summary']['verified_pct'], 100)

    def test_summary_rates_and_project_lookup(self):
        project = self.dir / 'my project'
        project.mkdir()
        encoded = metrics.transcript_dir(project, self.dir / 'claude')
        self.assertRegex(encoded.name, r'^[A-Za-z0-9-]+$')
        encoded.mkdir(parents=True)
        self.dir = encoded
        self.session('11111111-1', edit('/p/src/main/java/A.java'), result(), bash('./mvnw test'), result())
        self.session('22222222-1', edit('/p/src/main/java/A.java'), result())
        self.session('33333333-1', prompt('question'), bash('ls'), result())
        self.session('44444444-1')
        code, out, _ = self.run_cli('--project', project, '--claude-dir', encoded.parents[1], '--json')
        self.assertEqual(code, 0)
        summary = json.loads(out)['summary']
        self.assertEqual((summary['sessions'], summary['sessions_with_code_edits']), (3, 2))
        self.assertEqual((summary['verified_pct'], summary['backend_verified_pct'], summary['view_verified_pct']), (50, 50, None))

    def test_timeline_lists_ordered_events_with_line_numbers(self):
        path = self.session('hhhhhhhh-1', prompt(SECRET), edit('/p/src/main/java/A.java'), result(),
                            edit('/p/src/main/java/B.java'), result(), bash('./mvnw test'), result(error=True),
                            edit('/p/src/main/webapp/a.jsp'), result())
        code, out, _ = self.run_cli('--transcripts', self.dir, '--timeline', 'hhhhhhhh')
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET, out)
        lines = out.splitlines()
        self.assertEqual(lines[0], f'hhhhhhhh  unverified  {path}')
        self.assertEqual([line.split(None, 2)[2] for line in lines[1:]],
                         ['prompt', 'edit:backend ×2', 'maven-test', 'maven-test-failed', 'edit:view'])
        self.assertEqual(lines[2].split()[:2], ['line', '2'])
        self.assertEqual(self.run_cli('--transcripts', self.dir, '--timeline', 'zzzz')[0], 2)

    def test_wrapper_called_through_a_path_counts_and_system_mvn_is_flagged(self):
        for command in ('./pi/mvnw -q -f pi/pom.xml -pl :demo -am -Dtest=ATest test', 'cd x && ../mvnw verify',
                        '.\\mvnw.cmd test', 'sub\\mvnw.cmd -B verify'):
            with self.subTest(command=command):
                m = metrics.analyse(self.session('c3c3c3c3-1', edit('/p/src/main/java/A.java'), result(), bash(command), result()))
                self.assertEqual((m['outcome'], m['system_mvn']), ('verified', 0))
        m = metrics.analyse(self.session('c3c3c3c3-2', bash('mvn -q test'), result(), bash('echo mvnw-is-not-run test'), result()))
        self.assertEqual((m['system_mvn'], m['maven_tests']), (1, 1))

    def test_excerpt_prints_a_truncated_local_only_view(self):
        self.session('iiiiiiii-1', prompt('q'), bash('./mvnw test ' + 'x' * 400), result(error=True), edit('/p/A.java'), result())
        code, out, _ = self.run_cli('--transcripts', self.dir, '--excerpt', 'iiiiiiii', 2, 3)
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertIn('LOCAL ONLY', lines[0])
        self.assertTrue(any(line.lstrip().startswith('2 a Bash: ./mvnw test x') and line.endswith('…') for line in lines), out)
        self.assertTrue(any(' u ERROR: ' in line for line in lines))
        self.assertFalse(any('A.java' in line for line in lines), 'line 4 is outside the range')
        self.assertTrue(all(len(line) < 260 for line in lines))
        self.assertEqual(self.run_cli('--transcripts', self.dir, '--excerpt', 'nomatch', 1, 2)[0], 2)

    def test_missing_or_empty_sources_exit_2(self):
        self.assertEqual(self.run_cli('--transcripts', self.dir / 'missing')[0], 2)
        self.assertEqual(self.run_cli('--transcripts', self.dir)[0], 2)


if __name__ == '__main__':
    unittest.main()
