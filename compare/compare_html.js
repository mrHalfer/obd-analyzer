// compare_html.js — minimal JS for comparison report
// Tab logic is CSS-only (radio inputs). This file handles dynamic behavior.

(function () {
  'use strict';

  // Restore last active tab from sessionStorage
  function restoreTab() {
    var saved = sessionStorage.getItem('cmp_active_tab');
    if (saved) {
      var el = document.getElementById(saved);
      if (el) { el.checked = true; }
    }
  }

  // Resize all visible Plotly charts (fixes 620px initial width in hidden tabs)
  function resizePlotlyCharts() {
    if (typeof Plotly === 'undefined') { return; }
    setTimeout(function () {
      document.querySelectorAll('.js-plotly-plot').forEach(function (div) {
        Plotly.Plots.resize(div);
      });
    }, 150);
  }

  // ---------------------------------------------------------------------------
  // Lazy chart initialization (JSON spec → Plotly.newPlot in parent DOM)
  // Used for both compare tab charts (.lazy-chart) and profile accordion charts
  // ---------------------------------------------------------------------------

  function initLazyChart(div) {
    if (!div || div.dataset.plotlyLoaded || typeof Plotly === 'undefined') { return; }
    var spec = document.getElementById(div.id + '-spec');
    if (!spec) { return; }
    try {
      var fig = JSON.parse(spec.textContent);
      Plotly.newPlot(div, fig.data, fig.layout, fig.config || {responsive: true});
      div.dataset.plotlyLoaded = '1';
      // Pin rendered height so legend clicks / relayout don't collapse the div
      var h = div.offsetHeight;
      if (h > 0) { div.style.height = h + 'px'; }
    } catch (e) {
      console.warn('Lazy chart init error:', e);
    }
  }

  // Init all lazy charts inside an element that are not inside a closed <details>
  function loadVisibleIframesIn(root) {
    if (!root) { return; }
    root.querySelectorAll('.lazy-chart').forEach(function (div) {
      var details = div.closest('details');
      if (!details || details.open) {
        initLazyChart(div);
      }
    });
  }

  // Get the currently visible tab panel element
  function getActivePanel() {
    var checked = document.querySelector('.tab-input:checked');
    if (!checked) { return null; }
    // panel id is derived from tab id: ctab-foo → cpanel-foo
    var panelId = checked.id.replace('ctab-', 'cpanel-');
    return document.getElementById(panelId);
  }

  // ---------------------------------------------------------------------------
  // Event bindings
  // ---------------------------------------------------------------------------

  // Save active tab on change; resize Plotly; load lazy iframes in new panel
  function bindTabSave() {
    var inputs = document.querySelectorAll('.tab-input');
    inputs.forEach(function (inp) {
      inp.addEventListener('change', function () {
        sessionStorage.setItem('cmp_active_tab', inp.id);
        resizePlotlyCharts();
        setTimeout(function () {
          loadVisibleIframesIn(getActivePanel());
        }, 60);
      });
    });
  }

  // Init lazy charts when an accordion item is opened
  function bindAccordionLazyLoad() {
    document.addEventListener('toggle', function (e) {
      var target = e.target;
      if (target.classList && target.classList.contains('accordion-item') && target.open) {
        target.querySelectorAll('.lazy-chart').forEach(initLazyChart);
      }
    }, true);
  }

  // Selector for table cells by scope and col index
  function _scopedCells(scope, col) {
    var base = '[data-tscope="' + scope + '"] .compare-table th[data-col="' + col + '"],'
             + '[data-tscope="' + scope + '"] .compare-table td[data-col="' + col + '"]';
    return document.querySelectorAll(base);
  }

  // Toggle column visibility when a trip badge is clicked
  function bindBadgeToggle() {
    document.querySelectorAll('.trip-badge[data-col]').forEach(function (badge) {
      badge.addEventListener('click', function () {
        var col   = badge.getAttribute('data-col');
        var scope = badge.getAttribute('data-scope');
        badge.classList.toggle('col-hidden');
        _scopedCells(scope, col).forEach(function (cell) {
          cell.classList.toggle('col-hidden');
        });
      });
    });
  }

  // Show/hide all columns at once
  function bindShowHideAll() {
    document.querySelectorAll('.btn-toggle-all').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var scope   = btn.getAttribute('data-scope');
        var badges  = Array.from(document.querySelectorAll('.trip-badge[data-scope="' + scope + '"]'));
        var hideNow = badges.some(function (b) { return !b.classList.contains('col-hidden'); });
        badges.forEach(function (badge) {
          var col = badge.getAttribute('data-col');
          if (hideNow) {
            badge.classList.add('col-hidden');
            _scopedCells(scope, col).forEach(function (c) { c.classList.add('col-hidden'); });
          } else {
            badge.classList.remove('col-hidden');
            _scopedCells(scope, col).forEach(function (c) { c.classList.remove('col-hidden'); });
          }
        });
        btn.textContent = hideNow ? btn.getAttribute('data-show') : btn.getAttribute('data-hide');
      });
    });
  }

  // Hide inline CSP warning unless ?inline=true is in the URL
  function applyInlineWarning() {
    var urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('inline') !== 'true') {
      document.querySelectorAll('.inline-warning').forEach(function (el) {
        el.style.display = 'none';
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    applyInlineWarning();
    restoreTab();
    bindTabSave();
    bindBadgeToggle();
    bindShowHideAll();
    bindAccordionLazyLoad();
    resizePlotlyCharts();
    // Init profile charts that are already visible on the initial active tab
    loadVisibleIframesIn(getActivePanel());
  });
})();
