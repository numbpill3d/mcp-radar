async function getJson(path) {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'html') node.innerHTML = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.appendChild(c);
  return node;
}

function fmtInt(n) {
  if (typeof n !== 'number') return '';
  return n.toLocaleString();
}

function norm(s) {
  return (s || '').toString().toLowerCase();
}

function uniq(arr) {
  return Array.from(new Set(arr)).filter(Boolean);
}

function buildCategoryOptions(servers) {
  const select = document.getElementById('category');
  const cats = uniq(servers.map(s => s.category)).sort();
  for (const c of cats) {
    select.appendChild(el('option', { value: c, text: c }));
  }
}

function renderSponsors(sponsors) {
  const wrap = document.getElementById('sponsors');
  wrap.innerHTML = '';

  if (!Array.isArray(sponsors) || sponsors.length === 0) {
    document.getElementById('sponsorsPanel').style.display = 'none';
    return;
  }

  for (const s of sponsors.slice(0, 3)) {
    const card = el('div', { class: 'card' }, [
      el('div', { class: 'title' }, [
        el('a', { href: s.url || '#', class: 'name', text: s.name || 'sponsor' }),
        el('span', { class: 'badge', text: s.tagline || 'sponsor' })
      ]),
      el('div', { class: 'fine', text: s.blurb || '' })
    ]);
    wrap.appendChild(card);
  }
}

function serverMatches(server, q, category, tag) {
  const text = [
    server.name,
    server.description,
    server.category,
    ...(server.tags || []),
  ].map(norm).join(' | ');

  if (q && !text.includes(q)) return false;
  if (category && norm(server.category) !== category) return false;
  if (tag) {
    const tags = (server.tags || []).map(norm);
    if (!tags.includes(tag) && !text.includes(tag)) return false;
  }
  return true;
}

function sortServers(servers, mode) {
  const s = [...servers];
  if (mode === 'name') {
    s.sort((a, b) => norm(a.name).localeCompare(norm(b.name)));
  } else if (mode === 'updated') {
    s.sort((a, b) => (b.last_updated || '').localeCompare(a.last_updated || ''));
  } else {
    s.sort((a, b) => (b.stars || -1) - (a.stars || -1));
  }
  return s;
}

function renderServers(servers) {
  const q = norm(document.getElementById('q').value).trim();
  const category = norm(document.getElementById('category').value).trim();
  const tag = norm(document.getElementById('tag').value).trim();
  const sort = document.getElementById('sort').value;

  const filtered = servers.filter(s => serverMatches(s, q, category, tag));
  const sorted = sortServers(filtered, sort);

  const results = document.getElementById('results');
  results.innerHTML = '';

  document.getElementById('status').textContent = `${sorted.length.toLocaleString()} / ${servers.length.toLocaleString()} servers`;

  for (const s of sorted) {
    const tags = (s.tags || []).slice(0, 12);

    const metaBits = [];
    if (s.category) metaBits.push({ k: 'category', v: s.category });
    if (typeof s.stars === 'number') metaBits.push({ k: 'stars', v: fmtInt(s.stars) });
    if (s.last_updated) metaBits.push({ k: 'updated', v: s.last_updated.slice(0, 10) });
    if (tags.length) metaBits.push({ k: 'tags', v: tags.join(', ') });

    const item = el('div', { class: 'item' }, [
      el('div', { class: 'top' }, [
        el('a', { class: 'name', href: s.url || '#', text: s.name || 'unknown' }),
        el('span', { class: 'badge', text: s.source || 'source' })
      ]),
      el('div', { class: 'desc', text: s.description || '' }),
      el('div', { class: 'meta2' }, metaBits.map(b => el('span', { class: 'badge', text: `${b.k}: ${b.v}` })))
    ]);

    results.appendChild(item);
  }
}

function setSeoUrls() {
  const url = window.location.href;
  const canonical = document.querySelector('link[rel="canonical"]');
  if (canonical) canonical.setAttribute('href', url);

  const ogUrl = document.querySelector('meta[property="og:url"]');
  if (ogUrl) ogUrl.setAttribute('content', url);
}

async function main() {
  setSeoUrls();

  const serversPayload = await getJson('./data/servers.json');
  const sponsors = await getJson('./data/sponsors.json').catch(() => []);

  const servers = Array.isArray(serversPayload) ? serversPayload : (serversPayload.servers || []);
  const generatedAt = serversPayload.generated_at || null;

  renderSponsors(sponsors);
  buildCategoryOptions(servers);

  const rerender = () => renderServers(servers);
  for (const id of ['q', 'category', 'tag', 'sort']) {
    document.getElementById(id).addEventListener('input', rerender);
    document.getElementById(id).addEventListener('change', rerender);
  }

  rerender();

  if (generatedAt) {
    document.getElementById('generatedAt').textContent = `generated: ${generatedAt}`;
  }
}

main().catch((e) => {
  console.error(e);
  document.getElementById('status').textContent = `error: ${e.message}`;
});
