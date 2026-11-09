
import path from 'node:path';
import { execFileSync } from 'node:child_process';
const root = 'C:/Users/jiahuanl/.codex/worktrees/style-preview-independent-review/MimirQ/web';
const base = '86a57dbf702ec9e4667e017da47e93ee41d23d5b';
const files = [
  'web/components/chunk-preview/context.tsx',
  'web/components/chunk-preview/components/workbench/sidebar-client.tsx',
];
const sources = new Map(files.map(file => [path.resolve(root, '..', file).replaceAll('\\', '/'), execFileSync('git', ['show', base + ':' + file], {cwd: path.resolve(root, '..'), encoding:'utf8', maxBuffer:16*1024*1024})]));
export default {
  root,
  resolve: { alias: { '@': root } },
  plugins: [{name:'independent-review-frozen-baseline',enforce:'pre', load(id) { return sources.get(id.split('?')[0].replaceAll('\\', '/')); }}],
  test: {environment:'node', include:['components/chunk-preview/context.independent-review.behavior.test.tsx'], testTimeout:15000},
};
