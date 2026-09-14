(function () {
  var NOTES = window.NOTES || [];
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function badge(n) {
    var id = n.source === 'idebate' ? 'idebate' : 'procon';
    var label = n.source === 'idebate' ? 'iDebate' : 'ProCon';
    return '<span class="badge ' + id + '">' + label + '</span>';
  }

  function initIndex() {
    var grid = document.getElementById('cards');
    if (!grid) return;
    var state = { src: 'all', cat: 'all', q: '' };
    var search = document.getElementById('search');
    var catRow = document.getElementById('cats');

    var counts = {};
    NOTES.forEach(function (n) { counts[n.category] = (counts[n.category] || 0) + 1; });
    var catNames = Object.keys(counts).sort();
    if (catRow) {
      catRow.innerHTML = '';
      var all = document.createElement('button');
      all.className = 'chip active'; all.dataset.cat = 'all'; all.textContent = '全部';
      catRow.appendChild(all);
      catNames.forEach(function (c) {
        var b = document.createElement('button');
        b.className = 'chip'; b.dataset.cat = c;
        b.textContent = c + ' · ' + counts[c];
        catRow.appendChild(b);
      });
    }

    function render() {
      var q = state.q.trim().toLowerCase();
      var html = '', shown = 0;
      NOTES.forEach(function (n) {
        if (state.src !== 'all' && n.source !== state.src) return;
        if (state.cat !== 'all' && n.category !== state.cat) return;
        if (q && (n.title + ' ' + n.category).toLowerCase().indexOf(q) < 0) return;
        shown++;
        html += '<article class="card">'
          + '<div class="card-top">' + badge(n) + '<span class="tag">' + esc(n.category) + '</span></div>'
          + '<a class="card-title" href="/topic/' + esc(n.slug) + '.html">' + esc(n.title) + '</a>'
          + '<div class="card-meta"><span class="card-cat">' + esc(n.category) + '</span><span class="card-date">' + esc(n.date) + '</span></div>'
          + '</article>';
      });
      grid.innerHTML = html || '<p class="empty">没有匹配的辩题</p>';
      var countEl = document.getElementById('count');
      if (countEl) countEl.textContent = shown;
    }

    if (search) search.addEventListener('input', function () { state.q = this.value; render(); });
    document.querySelectorAll('.src-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        document.querySelectorAll('.src-btn').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        state.src = b.dataset.src;
        render();
      });
    });
    if (catRow) catRow.addEventListener('click', function (e) {
      var chip = e.target.closest('.chip');
      if (!chip) return;
      document.querySelectorAll('.chip').forEach(function (x) { x.classList.remove('active'); });
      chip.classList.add('active');
      state.cat = chip.dataset.cat;
      render();
    });
    render();
  }

  function initSidebar() {
    var nav = document.getElementById('sidebarNav');
    if (!nav) return;
    var current = nav.getAttribute('data-current') || '';
    var search = document.getElementById('sideSearch');
    function render() {
      var q = (search ? search.value : '').trim().toLowerCase();
      var groups = {};
      NOTES.forEach(function (n) {
        if (q && (n.title + ' ' + n.category).toLowerCase().indexOf(q) < 0) return;
        (groups[n.category] = groups[n.category] || []).push(n);
      });
      var cats = Object.keys(groups).sort();
      var html = '';
      if (!cats.length) { nav.innerHTML = '<p class="empty">无匹配</p>'; return; }
      cats.forEach(function (cat) {
        html += '<div class="side-group">' + esc(cat) + '</div>';
        groups[cat].forEach(function (n) {
          html += '<a class="nav-link' + (n.slug === current ? ' active' : '') + '" href="/topic/' + esc(n.slug) + '.html">'
            + badge(n) + '<span>' + esc(n.title) + '</span></a>';
        });
      });
      nav.innerHTML = html;
    }
    if (search) search.addEventListener('input', render);
    render();
  }

  function initToggle() {
    var btn = document.getElementById('navToggle');
    var sb = document.getElementById('sidebar');
    var ov = document.getElementById('overlay');
    function close() { if (sb) sb.classList.remove('open'); document.body.classList.remove('nav-open'); }
    if (btn && sb) btn.addEventListener('click', function () {
      var open = sb.classList.toggle('open');
      document.body.classList.toggle('nav-open', open);
    });
    if (ov) ov.addEventListener('click', close);
    if (sb) sb.addEventListener('click', function (e) { if (e.target.closest('a')) close(); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initIndex();
    initSidebar();
    initToggle();
  });
})();
