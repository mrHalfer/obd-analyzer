(function() {
  var mapEl = document.getElementById('obd-map');
  if (!mapEl) return;

  var d = window._OBD_MAP_DATA;
  var colorSchemes = d.colorSchemes;
  var popupFields = d.popupFields;
  var geojsonData = d.geojsonData;
  var bboxCoords = d.bboxCoords;
  var dtcIncrease = d.dtcIncrease;
  var map, geoLayer;

  function interpolateColor(val, stops) {
    if (val <= stops[0][0]) return stops[0][1];
    if (val >= stops[stops.length-1][0]) return stops[stops.length-1][1];
    for (var i = 0; i < stops.length - 1; i++) {
      var s1 = stops[i][0], c1 = stops[i][1];
      var s2 = stops[i+1][0], c2 = stops[i+1][1];
      if (val >= s1 && val <= s2) {
        var t = (val - s1) / (s2 - s1);
        var r1 = parseInt(c1.slice(1,3),16), g1 = parseInt(c1.slice(3,5),16), b1 = parseInt(c1.slice(5,7),16);
        var r2 = parseInt(c2.slice(1,3),16), g2 = parseInt(c2.slice(3,5),16), b2 = parseInt(c2.slice(5,7),16);
        var r = Math.round(r1+(r2-r1)*t), g = Math.round(g1+(g2-g1)*t), b = Math.round(b1+(b2-b1)*t);
        return '#'+(r<16?'0':'')+r.toString(16)+(g<16?'0':'')+g.toString(16)+(b<16?'0':'')+b.toString(16);
      }
    }
    return stops[stops.length-1][1];
  }

  function buildLegend(scheme) {
    var stops = scheme.stops;
    var html = '';
    for (var i = 0; i < stops.length; i++) {
      html += '<span style="display:inline-flex;align-items:center;margin-right:10px;">' +
        '<span style="width:18px;height:4px;background:' + stops[i][1] + ';display:inline-block;margin-right:4px;border-radius:2px;"></span>' +
        stops[i][0] + '+</span>';
    }
    return html;
  }

  function applyColorScheme(key) {
    var scheme = colorSchemes[key];
    if (!scheme || !geoLayer) return;

    // Обновляем легенду
    var legendEl = document.getElementById('map-legend');
    if (legendEl) legendEl.innerHTML = buildLegend(scheme);

    // Перекрашиваем отрезки (только LineString, не точки)
    geoLayer.eachLayer(function(layer) {
      if (layer.feature.geometry.type !== 'LineString') return;
      var val = layer.feature.properties[key + '_mean'] || 0;
      layer.setStyle({ color: interpolateColor(val, scheme.stops), weight: 4, opacity: 0.85 });
    });
  }

  function initMap() {
    if (typeof L === 'undefined') {
      setTimeout(initMap, 100);
      return;
    }

    map = L.map('obd-map');
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19
    }).addTo(map);

    map.fitBounds(bboxCoords);

    // Ч/б переключатель подложки (по умолчанию ч/б)
    var bwOn = true;
    var bwBtn = document.getElementById('map-bw-toggle');
    var tilePane = mapEl.querySelector('.leaflet-tile-pane');
    function updateBw() {
      if (tilePane) tilePane.style.filter = bwOn ? 'grayscale(1)' : 'none';
      if (bwBtn) { bwBtn.textContent = bwOn ? '\u25C9' : '\u25CB'; bwBtn.style.opacity = bwOn ? '0.5' : '0.85'; }
    }
    updateBw();
    if (bwBtn) {
      bwBtn.addEventListener('click', function() {
        bwOn = !bwOn;
        updateBw();
      });
    }

    var select = document.getElementById('map-color-select');
    var currentKey = select ? select.value : Object.keys(colorSchemes)[0];

    var highlightedLayer = null;

    function resetHighlight() {
      if (highlightedLayer) {
        highlightedLayer.setStyle({ weight: 4 });
        highlightedLayer = null;
      }
    }

    geoLayer = L.geoJSON(geojsonData, {
      style: function(feature) {
        if (feature.geometry.type !== 'LineString') return {};
        var val = feature.properties[currentKey + '_mean'] || 0;
        return { color: interpolateColor(val, colorSchemes[currentKey].stops), weight: 4, opacity: 0.85 };
      },
      pointToLayer: function(feature, latlng) {
        if (feature.properties.event_type === 'stall') {
          return L.circleMarker(latlng, {
            radius: 9,
            fillColor: '#F44336',
            color: '#B71C1C',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.85,
          });
        }
        if (feature.properties.event_type === 'dtc_increase') {
          return L.circleMarker(latlng, {
            radius: 9,
            fillColor: '#FF9800',
            color: '#E65100',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.85,
          });
        }
        return L.circleMarker(latlng, { radius: 6 });
      },
      onEachFeature: function(feature, layer) {
        // Всплывающая подсказка для точек заглоха
        if (feature.geometry.type === 'Point' && feature.properties.event_type === 'stall') {
          var p = feature.properties;
          var timeRow = p.time ? '<b>' + popupFields['TIME'] + ':</b> ' + p.time + '<br>' : '';
          var rpmRow  = (p.rpm !== undefined && p.rpm !== null) ? '<b>RPM:</b> ' + p.rpm + '<br>' : '';
          layer.bindPopup(
            '<div style="text-align:center;font-weight:bold;color:#c62828;border-bottom:1px solid #ffcdd2;'
            + 'padding-bottom:4px;margin-bottom:5px;">\u26A0 ' + dtcIncrease.stall_title + '</div>'
            + timeRow + rpmRow
          );
          return;
        }
        // Всплывающая подсказка для точек увеличения ошибок DTC
        if (feature.geometry.type === 'Point' && feature.properties.event_type === 'dtc_increase') {
          var p = feature.properties;
          var timeRow = p.time ? '<b>' + popupFields['TIME'] + ':</b> ' + p.time + '<br>' : '';
          var countRow = (p.error_count !== undefined && p.error_count !== null)
            ? '<b>' + dtcIncrease.count_label + ':</b> ' + p.error_count + '<br>' : '';
          var deltaRow = (p.delta !== undefined && p.delta !== null && p.delta > 0)
            ? '<b>' + dtcIncrease.delta_label + ':</b> +' + p.delta + '<br>' : '';
          layer.bindPopup(
            '<div style="text-align:center;font-weight:bold;color:#e65100;border-bottom:1px solid #ffe0b2;'
            + 'padding-bottom:4px;margin-bottom:5px;">\u26A0 ' + dtcIncrease.title + '</div>'
            + timeRow + countRow + deltaRow
          );
          return;
        }
        // Подсказка для отрезков маршрута
        var p = feature.properties;
        var header = '';
        var rows = '';
        for (var key in popupFields) {
          var line = null;
          if (key === 'TIME') {
            var tf = p['TIME_first'], tl = p['TIME_last'];
            if (tf !== undefined && tf !== null) {
              var t1 = String(tf).split('.')[0];
              var t2 = (tl !== undefined && tl !== null) ? String(tl).split('.')[0] : null;
              header = '<div style="font-size:1.05em;font-weight:bold;text-align:center;color:#1565c0;border-bottom:1px solid #bbdefb;padding-bottom:4px;margin-bottom:6px;">'
                + t1 + (t2 && t2 !== t1 ? ' \u2014 ' + t2 : '') + '</div>';
            }
          } else if (key === 'SPEED') {
            var sf = p['SPEED_first'], sl = p['SPEED_last'];
            if (sf !== undefined && sf !== null) {
              var arrow = (sl !== undefined && sl !== null)
                ? (sl > sf ? ' \u2191' : sl < sf ? ' \u2193' : ' \u2192') : '';
              line = '<b>' + popupFields[key] + ':</b> '
                + sf + (sl !== undefined && sl !== null ? ' \u2192 ' + sl : '')
                + arrow + ' \u043a\u043c/\u0447';
            }
          } else {
            var mean = p[key + '_mean'];
            if (mean !== undefined && mean !== null) {
              var min = p[key + '_min'], max = p[key + '_max'];
              line = '<b>' + popupFields[key] + ':</b> ' + mean;
              if (min !== undefined && max !== undefined && min !== max) {
                line += ' (' + min + ' .. ' + max + ')';
              }
            }
          }
          if (line) rows += line + '<br>';
        }
        if (header || rows) layer.bindPopup(header + rows);
        layer.on('click', function() {
          resetHighlight();
          this.setStyle({ weight: 10 });
          this.bringToFront();
          highlightedLayer = this;
        });
      }
    }).addTo(map);

    map.on('popupclose', function() { resetHighlight(); });

    // Легенда для начальной схемы
    applyColorScheme(currentKey);

    // Маркеры начала и конца (только по LineString-отрезкам)
    var coords = [];
    geojsonData.features.forEach(function(f) {
      if (f.geometry.type !== 'LineString') return;
      f.geometry.coordinates.forEach(function(c) { coords.push(c); });
    });
    if (coords.length >= 2) {
      var first = coords[0], last = coords[coords.length - 1];
      L.marker([first[1], first[0]], {
        icon: L.divIcon({className:'',html:'<div style="background:#4CAF50;color:#fff;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:14px;box-shadow:0 2px 4px rgba(0,0,0,0.3);">A</div>',iconSize:[24,24],iconAnchor:[12,12]})
      }).addTo(map).bindPopup(d.routeStart);
      L.marker([last[1], last[0]], {
        icon: L.divIcon({className:'',html:'<div style="background:#F44336;color:#fff;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:14px;box-shadow:0 2px 4px rgba(0,0,0,0.3);">B</div>',iconSize:[24,24],iconAnchor:[12,12]})
      }).addTo(map).bindPopup(d.routeEnd);
    }

    // Обработчик смены параметра раскраски
    if (select) {
      select.addEventListener('change', function() {
        applyColorScheme(this.value);
      });
    }

    // Поиск отрезка по времени
    function timeStrToSec(s) {
      if (!s) return null;
      s = String(s).split('.')[0];
      var p = s.split(':');
      if (p.length < 3) return null;
      return +p[0] * 3600 + +p[1] * 60 + +p[2];
    }

    function findByTime() {
      var inp = document.getElementById('map-time-input');
      if (!inp || !geoLayer) return;
      var tSec = timeStrToSec(inp.value);
      if (tSec === null) return;
      var found = null;
      geoLayer.eachLayer(function(layer) {
        if (found) return;
        var p = layer.feature.properties;
        var t1 = timeStrToSec(p['TIME_first']);
        var t2 = timeStrToSec(p['TIME_last']);
        if (t1 === null) return;
        if (t2 === null) t2 = t1;
        if (tSec >= t1 && tSec <= t2) found = layer;
      });
      if (found) {
        resetHighlight();
        found.setStyle({ weight: 10 });
        found.bringToFront();
        highlightedLayer = found;
        map.panTo(found.getBounds().getCenter());
        found.openPopup();
        inp.style.borderColor = '';
      } else {
        inp.style.borderColor = '#e53935';
        setTimeout(function() { inp.style.borderColor = ''; }, 800);
      }
    }

    var timeBtn = document.getElementById('map-time-go');
    if (timeBtn) timeBtn.addEventListener('click', findByTime);
    var timeInp = document.getElementById('map-time-input');
    if (timeInp) timeInp.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') findByTime();
    });

    // Навигация из Plotly-графика: время сохранено до инициализации карты
    if (window._OBD_PENDING_MAP_TIME) {
      var pendInp = document.getElementById('map-time-input');
      if (pendInp) {
        pendInp.value = window._OBD_PENDING_MAP_TIME;
        window._OBD_PENDING_MAP_TIME = null;
        findByTime();
      }
    }
  }

  var mapInited = false;
  function tryInit() {
    if (mapInited) return;
    mapInited = true;
    initMap();
  }

  // Инициализируем карту только когда вкладка "Карта" активна (иначе Leaflet неверно считает размер)
  var tabInput = document.getElementById('tab-map');
  if (tabInput) {
    tabInput.addEventListener('change', function() {
      if (this.checked) setTimeout(tryInit, 50);
    });
  }

  // Если вкладка уже активна при загрузке
  if (tabInput && tabInput.checked) setTimeout(tryInit, 100);
})();
