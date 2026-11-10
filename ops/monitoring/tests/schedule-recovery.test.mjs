// Exercise the production renderer, without loading the application or using a network.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const source = readFileSync(new URL('../../../static-site/app.js', import.meta.url), 'utf8');
const start = source.indexOf('function _renderScheduleStats(rows) {');
const end = source.indexOf('\nfunction _loadScheduleStats()', start);
assert.ok(start >= 0 && end > start);
function render(row) {
  const table = { innerHTML: '' };
  const context = vm.createContext({document: {querySelector: () => table}});
  vm.runInContext(source.slice(start, end), context);
  context._renderScheduleStats([row]);
  return table.innerHTML;
}
test('same completed overfit recovery keeps history without an outstanding warning', () => {
  const row = {task: 'overfit_monitor', last_exit: 0, r2_skip_count: 2, r2_skip_recovered: true};
  const html = render(row);
  assert.match(html, /R2已恢复（曾跳过 2 次）/);
  assert.doesNotMatch(html, /⚠️/);
  assert.equal(row.r2_skip_count, 2);
});
for (const [name, changes] of [
  ['failure', {last_exit: 75}], ['unfinished', {last_exit: null}],
  ['old producer', {r2_skip_recovered: undefined}], ['string flag', {r2_skip_recovered: 'true'}],
  ['other task', {task: 'fetch_news'}],
]) test(`${name} cannot borrow recovery evidence`, () => {
  const html = render({task: 'overfit_monitor', last_exit: 0, r2_skip_count: 1, r2_skip_recovered: true, ...changes});
  assert.match(html, /⚠️ R2跳过 1 次/);
  assert.doesNotMatch(html, /R2已恢复/);
});
test('a run without skips does not fabricate a recovery', () => {
  assert.doesNotMatch(render({task: 'overfit_monitor', last_exit: 0, r2_skip_count: 0, r2_skip_recovered: true}), /R2已恢复|⚠️/);
});
