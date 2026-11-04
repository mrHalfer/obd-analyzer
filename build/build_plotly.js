(function() {
    if (window === window.parent) return;
    var _t = null, _hasMap = null, _pending = null, _menu = null;
    // Зонд при старте — к первому ПКМ _hasMap уже будет известен.
    window.parent.postMessage({type: 'obd_map_probe'}, '*');
    function mkMenu() {
        var m = document.createElement('div');
        m.style.cssText = 'position:fixed;z-index:9999;background:#fff;border:1px solid #ccc;'
            + 'border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,.18);display:none;overflow:hidden;';
        var b = document.createElement('div');
        b.textContent = '🔎 GPS';
        b.style.cssText = 'padding:8px 16px;cursor:pointer;font-size:13px;white-space:nowrap;'
            + 'font-family:sans-serif;color:#1a237e;';
        b.onmouseenter = function() { this.style.background = '#e8eaf6'; };
        b.onmouseleave = function() { this.style.background = ''; };
        b.onclick = function() {
            hide();
            if (_t) window.parent.postMessage({type: 'obd_show_map', time: _t}, '*');
        };
        m.appendChild(b);
        document.body.appendChild(m);
        return m;
    }
    function show(x, y) {
        if (!_menu) _menu = mkMenu();
        _menu.style.left = x + 'px';
        _menu.style.top  = y + 'px';
        _menu.style.display = '';
        var r = _menu.getBoundingClientRect();
        if (r.right  > window.innerWidth)  _menu.style.left = (window.innerWidth  - r.width  - 8) + 'px';
        if (r.bottom > window.innerHeight) _menu.style.top  = (window.innerHeight - r.height - 8) + 'px';
    }
    function hide() { if (_menu) _menu.style.display = 'none'; }
    window.addEventListener('message', function(e) {
        if (!e.data || e.data.type !== 'obd_map_reply') return;
        _hasMap = !!e.data.hasMap;
        if (_pending) { if (_hasMap) show(_pending[0], _pending[1]); _pending = null; }
    });
    // Повторно проверяем наличие графиков — Plotly инициализируется асинхронно.
    // Не вызываем clearInterval: новые графики могут появляться позже (lazy iframe).
    function _extractTime(pt) {
        // 3D-графики хранят время в customdata; 2D-таймлайн — в pt.x (datetime-строка).
        var cd = pt.customdata;
        var src = (cd != null && cd !== '') ? String(cd) : String(pt.x != null ? pt.x : '');
        var m = src.match(/(\d{2}:\d{2}:\d{2})/);
        return m ? m[1] : null;
    }
    setInterval(function() {
        document.querySelectorAll('.js-plotly-plot').forEach(function(p) {
            if (p._obdHover || typeof p.on !== 'function') return;
            p._obdHover = true;
            p.on('plotly_hover', function(d) { if (d.points && d.points[0] != null) _t = _extractTime(d.points[0]); });
            p.on('plotly_click', function(d) { if (d.points && d.points[0] != null) _t = _extractTime(d.points[0]); });
        });
    }, 500);
    document.addEventListener('contextmenu', function(e) {
        // В iframe всегда подавляем браузерное меню.
        e.preventDefault();
        if (!_t) return;  // нет точки под курсором — ничего не показываем
        if (_hasMap === null) {
            // Зонд ещё не вернулся — сохраняем позицию и повторяем.
            _pending = [e.clientX, e.clientY];
            window.parent.postMessage({type: 'obd_map_probe'}, '*');
        } else if (_hasMap) {
            show(e.clientX, e.clientY);
        }
    });
    document.addEventListener('click', hide);
    document.addEventListener('scroll', hide);
    document.addEventListener('keydown', function(e) { if (e.key === 'Escape') hide(); });
})();
