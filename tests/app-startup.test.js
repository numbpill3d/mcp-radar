import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const index = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('the page keeps the dynamic results mount point and prerender markers', () => {
  assert.match(index, /id="results"/);
  assert.match(index, /<!-- prerender:start -->/);
  assert.match(index, /<!-- prerender:end -->/);
  assert.match(index, /<label class="field">\s*<span>sort<\/span>\s*<select id="sort">/);
});

function makeElement(id = '') {
  return {
    id,
    value: id === 'sort' ? 'stars' : '',
    textContent: '',
    innerHTML: '',
    children: [],
    attributes: {},
    appendChild(child) { this.children.push(child); return child; },
    addEventListener() {},
    setAttribute(name, value) { this.attributes[name] = value; },
  };
}

test('the directory starts and renders its server count without an error', async () => {
  const ids = new Map(
    ['category', 'q', 'tag', 'sort', 'results', 'status', 'generatedAt']
      .map((id) => [id, makeElement(id)]),
  );
  const document = {
    createElement: (tag) => makeElement(tag),
    getElementById: (id) => ids.get(id),
    querySelector: () => null,
  };
  const server = {
    name: 'example/server',
    description: 'example mcp server',
    category: 'testing',
    tags: ['example'],
    stars: 1,
    url: 'https://github.com/example/server',
  };
  const context = {
    clearTimeout,
    console,
    document,
    fetch: async () => ({ ok: true, json: async () => ({ servers: [server] }) }),
    setTimeout,
    window: { location: { href: 'https://example.test/' } },
  };

  vm.runInNewContext(fs.readFileSync(new URL('../app.js', import.meta.url), 'utf8'), context);
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ids.get('status').textContent, '1 / 1 servers');
  assert.equal(ids.get('results').children.length, 1);
});
