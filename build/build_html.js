(function() {
    var urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('inline') !== 'true') {
        var warnings = document.querySelectorAll('.inline-warning');
        warnings.forEach(function(warning) {
            warning.style.display = 'none';
        });
    }
})();

function loadLazyIframe(iframe) {
    if (iframe.classList.contains('lazy-iframe') && !iframe.hasAttribute('srcdoc')) {
        var dataSrc = iframe.getAttribute('data-src');
        if (dataSrc) {
            iframe.setAttribute('srcdoc', dataSrc);
            iframe.removeAttribute('data-src');
            var chartWrap = iframe.closest('.chart-wrap');
            if (chartWrap) {
                var loader = chartWrap.querySelector('.chart-loading');
                if (loader) {
                    loader.style.display = 'none';
                }
            }
        }
    }
}

function loadVisibleIframes(panelId) {
    var panel = document.getElementById(panelId);
    if (!panel) return;
    panel.querySelectorAll('iframe.lazy-iframe').forEach(function(iframe) {
        var details = iframe.closest('details');
        if (!details || details.open) {
            loadLazyIframe(iframe);
        }
    });
}

function handleTabChange() {
    var checkedTab = document.querySelector('input[name="report-tab"]:checked');
    if (checkedTab) {
        var tabId = checkedTab.id;
        var panelId = 'panel-' + tabId.replace('tab-', '');
        setTimeout(function() { loadVisibleIframes(panelId); }, 50);
        var hash = tabId.replace('tab-', '');
        if (window.location.hash !== '#' + hash) {
            window.location.hash = hash;
        }
    }
}

document.querySelectorAll('input[name="report-tab"]').forEach(function(radio) {
    radio.addEventListener('change', handleTabChange);
});

document.addEventListener('toggle', function(e) {
    if (e.target.classList.contains('collapsible') && e.target.open) {
        var iframes = e.target.querySelectorAll('iframe.lazy-iframe');
        iframes.forEach(function(iframe) {
            loadLazyIframe(iframe);
        });
    }
}, true);

function setActiveTabFromHash() {
    var hash = window.location.hash.substring(1);
    if (hash) {
        var tabInput = document.getElementById('tab-' + hash);
        if (tabInput) {
            tabInput.checked = true;
            handleTabChange();
        }
    }
}

window.addEventListener('load', function() {
    setActiveTabFromHash();
    handleTabChange();
});

window.addEventListener('hashchange', function() {
    setActiveTabFromHash();
});

// Пагинация таблиц
function initPagination() {
    document.querySelectorAll('table[data-page-size]').forEach(function(table) {
        var pageSize = parseInt(table.getAttribute('data-page-size'));
        var tbody = table.querySelector('tbody');
        if (!tbody) return;
        var rows = Array.from(tbody.querySelectorAll('tr'));
        if (rows.length <= pageSize) return;
        var totalPages = Math.ceil(rows.length / pageSize);
        var paginationDiv = document.querySelector('.pagination[data-for="' + table.id + '"]');
        if (!paginationDiv) return;
        function showPage(page) {
            rows.forEach(function(row, i) {
                row.style.display = (i >= page * pageSize && i < (page + 1) * pageSize) ? '' : 'none';
            });
            renderControls(page);
        }
        function renderControls(current) {
            var html = '<button class="pg-prev"' + (current === 0 ? ' disabled' : '') + '>&laquo;</button>';
            var start = Math.max(0, current - 2);
            var end = Math.min(totalPages, start + 5);
            if (end - start < 5) start = Math.max(0, end - 5);
            for (var i = start; i < end; i++) {
                html += '<button class="pg-num' + (i === current ? ' active' : '') + '" data-page="' + i + '">' + (i + 1) + '</button>';
            }
            html += '<button class="pg-next"' + (current === totalPages - 1 ? ' disabled' : '') + '>&raquo;</button>';
            html += '<span class="page-info">' + (current + 1) + ' / ' + totalPages + '</span>';
            paginationDiv.innerHTML = html;
            paginationDiv.setAttribute('data-current', current);
        }
        paginationDiv.addEventListener('click', function(e) {
            var btn = e.target.closest('button');
            if (!btn || btn.disabled) return;
            var current = parseInt(paginationDiv.getAttribute('data-current'));
            if (btn.classList.contains('pg-prev')) showPage(current - 1);
            else if (btn.classList.contains('pg-next')) showPage(current + 1);
            else if (btn.classList.contains('pg-num')) showPage(parseInt(btn.getAttribute('data-page')));
        });
        showPage(0);
    });
}

window.addEventListener('load', function() { initPagination(); });

// === Навигация Plotly-график → Карта ===
// Принимает postMessage от iframe-графиков: зонд о наличии карты и запрос перехода.
// e.data.time — строка "HH:MM:SS", извлечённая из datetime-метки оси X.
(function() {
    var _hasMap = !!document.getElementById('tab-map');

    window.addEventListener('message', function(e) {
        if (!e.data || !e.source) return;
        if (e.data.type === 'obd_map_probe') {
            try { e.source.postMessage({type: 'obd_map_reply', hasMap: _hasMap}, '*'); } catch (_) {}
        } else if (e.data.type === 'obd_show_map' && _hasMap) {
            var timeStr = e.data.time || null;
            if (!timeStr) return;
            // Сохраняем время: initMap() заберёт его когда карта будет готова.
            window._OBD_PENDING_MAP_TIME = timeStr;
            var mapTab = document.getElementById('tab-map');
            mapTab.checked = true;
            mapTab.dispatchEvent(new Event('change'));
            // Fallback: если карта уже была инициализирована ранее,
            // tryInit() возвращается сразу и initMap() не вызывается —
            // применяем время напрямую через кнопку.
            setTimeout(function() {
                if (!window._OBD_PENDING_MAP_TIME) return; // уже обработано initMap()
                var inp = document.getElementById('map-time-input');
                if (!inp) return;
                inp.value = window._OBD_PENDING_MAP_TIME;
                window._OBD_PENDING_MAP_TIME = null;
                var btn = document.getElementById('map-time-go');
                if (btn) btn.click();
            }, 300);
        }
    });
})();