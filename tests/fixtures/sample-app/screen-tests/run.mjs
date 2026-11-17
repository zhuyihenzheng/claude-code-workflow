// 実行：node run.mjs --engine playwright [--only 01-order] [--build-only]
import { runTests } from 'midscene-poc/core/runner.mjs';
import site from './site.mjs';
import { SUITES } from './cases.mjs';

await runTests({ ...site, suites: SUITES });
