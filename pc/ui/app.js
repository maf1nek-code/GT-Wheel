/* =====================================================================
   Kierownica GT – konfigurator (interfejs)
   Program w Pythonie (konfigurator.py) obsługuje kierownicę i liczy
   efekty LED; ta strona tylko je pokazuje i zmienia ustawienia.
   ===================================================================== */
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtNum = (v) => (Number.isInteger(v) ? String(v) : String(Math.round(v * 10) / 10)).replace('.', ',');
const teraz = () => new Date().toLocaleTimeString('pl-PL', { hour12: false });

const S = {
  u: null, opts: null, status: null,
  sim: { stan: 'jazda', obroty: 0.8, auto: true, wysylaj: true },
  niezapisane: false, profil: null, profile: [], plik: '',
  wzor: null, sel: new Set(), anchor: null, drag: null,
  presety: {}, gradient: ['#00FF00', '#FFDC00', '#FF0000'],
  tab: 'przyciski',
  btns: [], nBtn: 12, pierwszyStan: true, polId: -1, piny: {},
  rpmDrag: false, thrDrag: null,
};

const PALETA = [
  ['#FF0000', 'czerwony'], ['#FF5A00', 'pomarańczowy'], ['#FFC000', 'bursztynowy'], ['#FFFF00', 'żółty'],
  ['#00FF00', 'zielony'], ['#00FFB0', 'miętowy'], ['#00C8FF', 'błękitny'], ['#0040FF', 'niebieski'],
  ['#8000FF', 'fioletowy'], ['#FF00C8', 'różowy'], ['#FFFFFF', 'biały'], ['#000000', 'zgaszona'],
];

const STANY = [
  { k: 'zmiana_biegu', t: 'Zmiana biegu', d: 'Cały pasek miga, gdy obroty przekroczą próg.', ico: 'i-gear', opcja: 'prog' },
  { k: 'pit_limiter', t: 'Pit limiter', d: 'Ogranicznik prędkości w alei serwisowej.', ico: 'i-pit', opcja: 'wzor' },
  { k: 'flaga_zolta', t: 'Flaga żółta', d: 'Zagrożenie na torze – zwolnij.', ico: 'i-flag', kl: 'c-yellow', opcja: 'flagi' },
  { k: 'flaga_niebieska', t: 'Flaga niebieska', d: 'Szybszy kierowca chce cię wyprzedzić.', ico: 'i-flag', kl: 'c-blue', opcja: 'flagi' },
  { k: 'brak_gry', t: 'Gra wyłączona', d: 'Gdy gra nie działa albo jest w menu.', ico: 'i-moon', opcja: 'tryb' },
];
const SIM_STANU = { zmiana_biegu: 'jazda', pit_limiter: 'pit', flaga_zolta: 'zolta', flaga_niebieska: 'niebieska', brak_gry: 'brak_gry' };
const KROTKO_PIT = { caly: 'Cały pasek', naprzemiennie: 'Co druga', polowki: 'Połówki' };
const KROTKO_TRYB = { wylaczone: 'Zgaszone', staly: 'Stały', oddech: 'Oddech', skaner: 'Skaner' };
const NAZWY_SIM = { jazda: 'Jazda', pit: 'Pit limiter', zolta: 'Flaga żółta', niebieska: 'Flaga niebieska', brak_gry: 'Gra wyłączona' };

/* ------------------------------------------------------------ narzędzia */
function getPath(o, path) { return path.split('.').reduce((a, k) => (a == null ? a : a[k]), o); }
function setPath(o, path, v) {
  const k = path.split('.'); const last = k.pop();
  k.reduce((a, x) => a[x], o)[last] = v;
}
function stabilny(o) {
  if (Array.isArray(o)) return '[' + o.map(stabilny).join(',') + ']';
  if (o && typeof o === 'object') return '{' + Object.keys(o).sort().map((k) => JSON.stringify(k) + ':' + stabilny(o[k])).join(',') + '}';
  return JSON.stringify(o);
}
function hexNaRgb(h) { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }

async function api(sciezka, cialo = {}) {
  try {
    const r = await fetch(sciezka, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cialo) });
    let d;
    try { d = await r.json(); } catch { d = { ok: false, blad: `Błąd ${r.status}` }; }
    if (!d.ok) { toast(d.blad || 'Nieznany błąd', 'err', 4500); return null; }
    return d;
  } catch {
    toast('Brak połączenia z programem konfiguratora.', 'err', 4500);
    return null;
  }
}

function toast(tekst, typ = 'ok', ms = 3000) {
  const ikona = { ok: 'i-check', err: 'i-warn', info: 'i-eye' }[typ] || 'i-check';
  const el = document.createElement('div');
  el.className = `toast ${typ}`;
  el.innerHTML = `<svg><use href="#${ikona}"/></svg><span></span>`;
  el.querySelector('span').textContent = tekst;
  const box = $('#toasts');
  box.append(el);
  // warstwa nad oknami dialogowymi (inaczej komunikat chowa się pod tłem okna)
  try { if (box.matches(':popover-open')) box.hidePopover(); box.showPopover(); } catch { /* starsza przeglądarka */ }
  while (box.children.length > 4) box.firstElementChild.remove();
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 220); }, ms);
}

function potwierdz(tytul, tekst, ok = 'OK', niebezpieczne = false) {
  return new Promise((res) => {
    const d = $('#dlgConfirm'), okb = $('#cfOk'), anuluj = $('#cfCancel');
    $('#cfTitle').textContent = tytul;
    $('#cfText').textContent = tekst;
    okb.textContent = ok;
    okb.className = 'btn ' + (niebezpieczne ? 'danger' : 'primary');
    let zrobione = false;
    const koniec = (v) => {
      if (zrobione) return; zrobione = true;
      okb.onclick = anuluj.onclick = d.onclose = null;
      if (d.open) d.close();
      res(v);
    };
    okb.onclick = () => koniec(true);
    anuluj.onclick = () => koniec(false);
    d.onclose = () => koniec(false);
    d.showModal();
    okb.focus();
  });
}

/* ================================================================ PASKI */
function kolumny(n, max) { return n <= max ? n : Math.ceil(n / Math.ceil(n / max)); }

function budujPasek(el, n, max) {
  el.innerHTML = '';
  el.style.setProperty('--cols', kolumny(n, max));
  const leds = [];
  for (let i = 0; i < n; i++) {
    const d = document.createElement('div');
    d.className = 'led';
    d.dataset.i = i;
    el.append(d);
    leds.push(d);
  }
  el._leds = leds; el._n = n;
}

function malujPasek(el, hex, max) {
  const n = hex.length / 6;
  if (el._n !== n) budujPasek(el, n, max);
  const leds = el._leds;
  for (let i = 0; i < n; i++) {
    const c = hex.substr(i * 6, 6);
    const d = leds[i];
    if (d._c === c) continue;
    d._c = c;
    if (c === '000000') { d.classList.remove('on'); d.style.removeProperty('--c'); }
    else { d.classList.add('on'); d.style.setProperty('--c', '#' + c); }
  }
}

/* ============================================================== ZAKŁADKI */
function pokazZakladke(nazwa) {
  S.tab = nazwa;
  $$('.tab-btn').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === nazwa)));
  $$('.tab').forEach((t) => { t.hidden = t.id !== `tab-${nazwa}`; });
  try { localStorage.setItem('kgt-tab', nazwa); } catch { /* bez pamięci */ }
}

/* ============================================================ POŁĄCZENIE */
const KROTKI_STATUS = {
  szukam: 'Szukam kierownicy…', brak: 'Nie znaleziono kierownicy', zajety: 'Port zajęty',
  utracono: 'Utracono połączenie', rozlaczono: 'Rozłączono',
};

function renderStatus() {
  const st = S.status; if (!st) return;
  const pill = $('#connPill');
  pill.dataset.conn = st.stan;
  const info = st.info;
  $('#connText').textContent = st.stan === 'polaczono' && info
    ? `${st.port} · firmware ${info.wersja}` : (KROTKI_STATUS[st.stan] || st.tekst);
  $('#popStatus').textContent = st.tekst;
  const dl = $('#popInfo');
  dl.innerHTML = st.stan === 'polaczono' && info ? `
    <dt>Port</dt><dd>${esc(st.port)}</dd>
    <dt>Firmware</dt><dd>${esc(info.wersja)}</dd>
    <dt>Przyciski</dt><dd>${info.przyciski}</dd>
    <dt>Pasek LED</dt><dd>${info.max_diod ? `do ${info.max_diod} diod` : 'brak obsługi (stary firmware)'}</dd>` : '';
  $('#btnDisconnect').disabled = !st.chce;

  // nakładka na kierownicy
  const ov = $('#wheelOverlay');
  const polaczono = st.stan === 'polaczono';
  ov.classList.toggle('hide', polaczono);
  if (!polaczono) {
    const ikona = $('#ovIcon');
    const tytuly = {
      szukam: 'Szukam kierownicy…', brak: 'Nie znaleziono kierownicy', zajety: 'Port jest zajęty',
      utracono: 'Utracono połączenie', rozlaczono: 'Kierownica rozłączona',
    };
    $('#ovTitle').textContent = tytuly[st.stan] || st.tekst;
    $('#ovText').textContent = st.stan === 'szukam' ? 'Podłącz kierownicę kablem USB.'
      : st.stan === 'rozlaczono' ? 'Kliknij „Połącz”, aby wrócić do testu.'
      : st.tekst + (st.stan !== 'zajety' ? ' Szukam dalej…' : ' Próbuję ponownie co 2 s.');
    $('#ovConnect').hidden = st.stan !== 'rozlaczono';
    if (st.stan === 'szukam' || st.stan === 'brak' || st.stan === 'utracono') {
      ikona.className = 'ov-icon';
      if (!ikona.querySelector('.spinner')) ikona.innerHTML = '<div class="spinner"></div>';
    } else {
      ikona.className = 'ov-icon ' + (st.stan === 'zajety' ? 'err' : 'idle');
      ikona.innerHTML = `<svg><use href="#${st.stan === 'zajety' ? 'i-warn' : 'i-plug'}"/></svg>`;
    }
  }
}

function ustawStatus(st) {
  const bylo = S.status;
  S.status = st;
  if (st.stan === 'polaczono' && st.id !== S.polId) {
    S.polId = st.id;
    przygotujPrzyciski(st.info ? st.info.przyciski : 12, true);
    S.pierwszyStan = true;
    wpis(`<span class="l-info">Połączono z kierownicą (${esc(st.port)}).</span>`);
  } else if (st.stan !== 'polaczono' && bylo && bylo.stan === 'polaczono') {
    S.btns.forEach((b) => { b.wc = false; b.podejrz = false; });
    renderPrzyciski();
    wpis(`<span class="l-info">${esc(KROTKI_STATUS[st.stan] || st.tekst)}</span>`);
  }
  renderStatus();
}

async function otworzPopover() {
  const pop = $('#connPop');
  pop.hidden = false;
  $('#connPill').setAttribute('aria-expanded', 'true');
  const sel = $('#portSelect');
  try {
    const r = await fetch('/api/porty');
    const d = await r.json();
    const wybrany = S.status ? S.status.port_wybrany : null;
    const porty = d.porty || [];
    sel.innerHTML = '<option value="">Automatycznie</option>' + porty.map((p) =>
      `<option value="${esc(p.port)}">${esc(p.port)}${p.opis ? ' – ' + esc(p.opis) : ''}</option>`).join('');
    if (wybrany && !porty.some((p) => p.port === wybrany)) sel.insertAdjacentHTML('beforeend', `<option value="${esc(wybrany)}">${esc(wybrany)}</option>`);
    sel.value = wybrany || '';
  } catch { /* zostaw stare */ }
}
function zamknijPopover() {
  $('#connPop').hidden = true;
  $('#connPill').setAttribute('aria-expanded', 'false');
}

/* ======================================================= TEST PRZYCISKÓW */
const UKLAD_12 = {
  1: [222, 205], 2: [262, 205], 3: [222, 255], 4: [262, 255], 5: [222, 305], 11: [262, 305],
  6: [378, 205], 7: [418, 205], 8: [378, 255], 9: [418, 255], 10: [378, 305], 12: [418, 305],
};

function pozycjaPrzycisku(n) {
  if (UKLAD_12[n]) return UKLAD_12[n];
  const i = n - 13;
  if (i < 6) return [230 + i * 36, 343];
  return null;
}

function budujKolo() {
  const svg = $('#wheel');
  const n = S.nBtn;
  let przyciski = '';
  for (let i = 1; i <= n; i++) {
    const p = pozycjaPrzycisku(i);
    if (!p) continue;
    przyciski += `<g class="wb" data-n="${i}" transform="translate(${p[0]} ${p[1]})"><title>Przycisk ${i}</title>
      <g class="wb-in"><circle class="wb-glow" r="22"/><circle class="wb-ring" r="20.5"/><circle class="wb-body" r="17"/><text class="wb-num">${i}</text></g>
      <g transform="translate(14 -14)"><g class="wb-check"><circle r="7.5"/><path d="M-3.4 0.2 L-1 2.6 L3.4 -2.2"/></g></g></g>`;
  }
  svg.innerHTML = `
    <defs>
      <linearGradient id="rimGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#434c58"/><stop offset=".45" stop-color="#2a3039"/><stop offset="1" stop-color="#1a1e24"/></linearGradient>
      <pattern id="grip" width="6" height="6" patternUnits="userSpaceOnUse"><circle cx="3" cy="3" r=".9" fill="#3d4651"/></pattern>
      <pattern id="carbon" width="8" height="8" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="#14181d"/><rect width="4" height="4" fill="#1a1f26"/><rect x="4" y="4" width="4" height="4" fill="#1a1f26"/></pattern>
      <linearGradient id="plateShine" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".07"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>
      <radialGradient id="btnGrad" cx=".4" cy=".35" r=".8"><stop offset="0" stop-color="#3b434d"/><stop offset="1" stop-color="#1b2027"/></radialGradient>
      <filter id="btnGlow" x="-1" y="-1" width="3" height="3"><feGaussianBlur stdDeviation="7"/></filter>
      <filter id="ledGlow" x="-2" y="-2" width="5" height="5"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    <path class="w-spoke" d="M126 262 L194 246 L194 318 L136 326 Z"/>
    <path class="w-spoke" d="M514 262 L446 246 L446 318 L504 326 Z"/>
    <path class="w-spoke" d="M290 366 H350 L358 404 H282 Z"/>
    <path class="w-rim-edge" d="M120 300 C104 168 190 70 320 70 C450 70 536 168 520 300 C512 362 480 402 430 404 L210 404 C160 402 128 362 120 300 Z"/>
    <path class="w-rim" d="M120 300 C104 168 190 70 320 70 C450 70 536 168 520 300 C512 362 480 402 430 404 L210 404 C160 402 128 362 120 300 Z"/>
    <path class="w-rim-grip" d="M120 300 C104 168 190 70 320 70 C450 70 536 168 520 300"/>
    <path class="w-rim-hl" d="M101 250 C104 146 198 50 320 50 C442 50 536 146 539 250"/>
    <rect class="w-mark" x="312" y="46" width="16" height="48" rx="3"/>
    <rect class="w-plate" x="190" y="130" width="260" height="240" rx="38"/>
    <rect class="w-plate-hl" x="190" y="130" width="260" height="240" rx="38"/>
    <rect class="w-bar" x="210" y="143" width="220" height="26" rx="13"/>
    <g id="wLeds"></g>
    <rect class="w-display" x="290" y="226" width="60" height="58" rx="9"/>
    <text class="w-gt" x="320" y="258" text-anchor="middle">GT</text>
    <text class="w-sub" x="320" y="275" text-anchor="middle">KGT</text>
    ${przyciski}`;
  svg._ledN = -1;
}

function malujKolo(hex) {
  const g = document.getElementById('wLeds');
  if (!g) return;
  const n = hex.length / 6;
  const svg = $('#wheel');
  if (svg._ledN !== n) {
    const krok = 204 / n;
    const r = Math.max(1.6, Math.min(7, krok * 0.38));
    let html = '';
    for (let i = 0; i < n; i++) html += `<circle class="w-led" cx="${(218 + krok * (i + 0.5)).toFixed(2)}" cy="156" r="${r.toFixed(2)}"/>`;
    g.innerHTML = html;
    g._leds = [...g.children];
    svg._ledN = n;
  }
  g._leds.forEach((c, i) => {
    const kol = hex.substr(i * 6, 6);
    if (c._c === kol) return;
    c._c = kol;
    if (kol === '000000') { c.setAttribute('fill', '#1d232a'); c.classList.remove('on'); }
    else { c.setAttribute('fill', '#' + kol); c.classList.add('on'); }
  });
}

function przygotujPrzyciski(n, zachowaj) {
  const stare = S.btns;
  const takie = zachowaj && stare.length === n;
  S.nBtn = n;
  S.btns = Array.from({ length: n }, (_, i) => {
    const b = takie ? stare[i] : null;
    return { n: i + 1, pin: S.piny[i + 1] || (b && b.pin) || '?', wc: false, licz: b ? b.licz : 0, ok: b ? b.ok : false, podejrz: false, od: 0 };
  });
  budujKolo();
  budujListe();
  renderPrzyciski();
}

function budujListe() {
  $('#btnList').innerHTML = S.btns.map((b) => `
    <div class="bl-row" data-n="${b.n}">
      <span class="bl-num">${b.n}</span><span class="bl-pin"></span><span class="chip"></span><span class="bl-count"></span>
    </div>`).join('');
  $('#ringTotal').textContent = S.nBtn;
}

function renderPrzycisk(b) {
  const stan = b.wc && b.podejrz ? 'warn' : b.wc ? 'press' : b.ok ? 'ok' : '';
  const g = $(`#wheel .wb[data-n="${b.n}"]`);
  if (g) {
    g.classList.toggle('press', stan === 'press');
    g.classList.toggle('warn', stan === 'warn');
    g.classList.toggle('ok', b.ok);
    g.querySelector('title').textContent = `Przycisk ${b.n} · pin ${b.pin} · wciśnięć: ${b.licz}`;
  }
  const row = $(`#btnList .bl-row[data-n="${b.n}"]`);
  if (row) {
    row.className = `bl-row ${stan}${b.ok ? ' ok' : ''}`;
    row.querySelector('.bl-pin').textContent = b.pin;
    const chip = row.querySelector('.chip');
    chip.className = 'chip ' + (stan || '');
    chip.textContent = stan === 'warn' ? 'od startu?' : stan === 'press' ? 'wciśnięty' : b.ok ? '✓ działa' : 'nie sprawdzony';
    row.querySelector('.bl-count').textContent = b.licz ? `×${b.licz}` : '';
  }
}

function renderPostep() {
  const n = S.btns.length;
  const ok = S.btns.filter((b) => b.ok).length;
  $('#ringCount').textContent = ok;
  const obwod = 2 * Math.PI * 27;
  $('#ringFg').style.strokeDashoffset = String(obwod * (1 - (n ? ok / n : 0)));
  $('#allOk').hidden = !(n && ok === n);
}

function renderPrzyciski() { S.btns.forEach(renderPrzycisk); renderPostep(); }

function wpis(html) {
  const log = $('#log');
  const pusty = log.querySelector('.log-empty');
  if (pusty) pusty.remove();
  const li = document.createElement('li');
  li.innerHTML = `<time>${teraz()}</time>${html}`;
  log.prepend(li);
  while (log.children.length > 150) log.lastElementChild.remove();
}

function zmianaPrzycisku(n, wl, pin, sync) {
  const b = S.btns[n - 1];
  if (!b) return;
  if (pin) b.pin = pin;
  if (b.wc === wl) { renderPrzycisk(b); return; }
  b.wc = wl;
  const pinTxt = b.pin !== '?' ? `<span class="lpin">${esc(b.pin)}</span>` : '';
  if (wl) {
    b.od = performance.now();
    if (sync && S.pierwszyStan) {
      b.podejrz = true;
      wpis(`<span class="l-warn"><span class="lnum">Przycisk ${n}</span> jest wciśnięty od startu – jeśli go nie trzymasz, pin może zwierać do GND.</span>`);
    } else {
      b.licz += 1;
      const nowy = !b.ok;
      b.ok = true;
      wpis(`<span class="l-on"><span class="lnum">Przycisk ${n}</span></span> wciśnięty ${pinTxt}${nowy ? ' <span class="chip ok">nowy ✓</span>' : ''}`);
    }
  } else if (b.podejrz) {
    b.podejrz = false;
    wpis(`<span class="lnum">Przycisk ${n}</span> puszczony – wygląda dobrze. ${pinTxt}`);
  } else {
    const czas = (performance.now() - b.od) / 1000;
    wpis(`<span class="lnum">Przycisk ${n}</span> puszczony ${pinTxt}<span class="ldur">${czas.toFixed(2).replace('.', ',')} s</span>`);
  }
  renderPrzycisk(b);
  renderPostep();
}

function stanPrzyciskow(bity) {
  [...bity].forEach((ch, i) => { if (ch === '0' || ch === '1') zmianaPrzycisku(i + 1, ch === '1', '', true); });
  S.pierwszyStan = false;
}

/* ============================================================ DIODY LED */
function budujStany() {
  const o = S.opts;
  $('#states').innerHTML = STANY.map((st) => {
    const p = `stany.${st.k}`;
    const przelacznik = st.k === 'brak_gry' ? '' :
      `<span class="switch" title="Włącz / wyłącz"><input type="checkbox" data-bind="${p}.wlaczony" data-type="bool" aria-label="${st.t} – włączony"><span class="slider"></span></span>`;
    const miganie = st.k === 'brak_gry' ? '' : `
      <div class="st-row"><span>Miganie</span>
        <div class="range-row"><input type="range" data-bind="${p}.miganie_hz" data-type="float" min="0" max="20" step="0.5" aria-label="${st.t} – miganie"><output data-out="hz:${p}.miganie_hz"></output></div>
      </div>`;
    let opcja = '';
    if (st.opcja === 'prog') {
      opcja = `<div class="st-row"><span>Próg</span><span>od <b data-out="pct:${p}.prog"></b> obrotów <small class="muted">(zmień w progach wyżej)</small></span></div>`;
    } else if (st.opcja === 'wzor') {
      opcja = `<div class="st-row stack"><span>Wzór</span><div class="seg st-seg" data-bind="${p}.wzor">${Object.keys(o.wzory_pit).map((k) =>
        `<button data-v="${k}" title="${esc(o.wzory_pit[k])}">${KROTKO_PIT[k] || esc(o.wzory_pit[k])}</button>`).join('')}</div></div>`;
    } else if (st.opcja === 'flagi') {
      opcja = `<div class="st-row"><span>Obszar</span><span class="mini-stepper">
        <span class="stepper"><button class="step" data-step="-1" aria-label="Mniej">−</button><input type="number" data-bind="stany.flagi_diody_skrajne" data-type="int" min="0" max="${o.max_diod / 2}" aria-label="Diody skrajne"><button class="step" data-step="1" aria-label="Więcej">+</button></span>
        <span data-out="flagi"></span></span></div>`;
    } else if (st.opcja === 'tryb') {
      opcja = `<div class="st-row stack"><span>Efekt</span><div class="seg st-seg" data-bind="${p}.tryb">${Object.keys(o.tryby).map((k) =>
        `<button data-v="${k}" title="${esc(o.tryby[k])}">${KROTKO_TRYB[k] || esc(o.tryby[k])}</button>`).join('')}</div></div>`;
    }
    return `
      <div class="card state" data-state="${st.k}">
        <div class="st-head">
          <div class="st-icon"><svg class="${st.kl || ''}"><use href="#${st.ico}"/></svg></div>
          <div class="st-title"><h4>${st.t}</h4><p>${st.d}</p></div>
          ${przelacznik}
        </div>
        <div class="st-strip-wrap"><div class="strip st-strip" data-mini="${st.k}"></div></div>
        <div class="st-row"><span>Kolor</span>
          <span class="st-color"><label class="color-btn"><input type="color" data-bind="${p}.kolor" data-type="color" aria-label="${st.t} – kolor"><span class="swatch" data-sw="${p}.kolor"></span><span data-hex="${p}.kolor"></span></label></span>
        </div>
        ${miganie}
        ${opcja}
        <div class="st-foot"><button class="btn ghost sm" data-pokaz="${st.k}"><svg><use href="#i-eye"/></svg>Pokaż w podglądzie</button></div>
      </div>`;
  }).join('');
  S.mini = {};
  $$('[data-mini]').forEach((el) => { S.mini[el.dataset.mini] = el; });
}

function budujStale() {
  // paleta
  $('#palette').innerHTML = PALETA.map(([k, n]) =>
    `<button style="--sw:${k}" data-kolor="${k}" title="${n}" aria-label="${n}"></button>`).join('');
  // ikonki kierunku (7 diod)
  const wzory = {
    lewo_prawo: { 0: 'l1', 1: 'l2' }, prawo_lewo: { 6: 'l1', 5: 'l2' },
    od_srodka: { 3: 'l1', 2: 'l2', 4: 'l2' }, do_srodka: { 0: 'l1', 6: 'l1', 1: 'l2', 5: 'l2' },
  };
  $$('.dir-ico').forEach((el) => {
    const w = wzory[el.dataset.dir];
    el.innerHTML = Array.from({ length: 7 }, (_, i) => `<i class="${w[i] || ''}"></i>`).join('');
  });
  renderGradient();
}

function renderGradient() {
  $('#gradStops').innerHTML = S.gradient.map((k, i) => {
    const opis = ['pierwsza dioda', 'środek', 'ostatnia dioda'][i];
    return `<label class="grad-stop" style="--sw:${k}" title="Kolor: ${opis}"><input type="color" value="${k.toLowerCase()}" data-grad="${i}" aria-label="Gradient – ${opis}"></label>`;
  }).join('');
  $('#gradPreview').style.background = `linear-gradient(90deg, ${S.gradient.join(', ')})`;
}

/* --------------------------------------------------- formularz ustawień */
function ustawZakres(el) {
  const min = +el.min || 0, max = +el.max || 100;
  el.style.setProperty('--p', `${((+el.value - min) / (max - min)) * 100}%`);
}

function renderForm() {
  if (!S.u) return;
  const aktywny = document.activeElement;
  $$('[data-bind]').forEach((el) => {
    const v = getPath(S.u, el.dataset.bind);
    if (el.classList.contains('seg')) {
      $$('button[data-v]', el).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === v)));
      return;
    }
    if (el.type === 'checkbox') el.checked = !!v;
    else if (el.type === 'color') { if (el !== aktywny) el.value = String(v).toLowerCase(); }
    else if (el !== aktywny) el.value = Number.isInteger(v) ? String(v) : String(Math.round(v * 10) / 10);
    if (el.type === 'range') ustawZakres(el);
  });
  $$('[data-sw]').forEach((e) => e.style.setProperty('--sw', getPath(S.u, e.dataset.sw)));
  $$('[data-hex]').forEach((e) => { e.textContent = getPath(S.u, e.dataset.hex); });
  $$('[data-out]').forEach((e) => {
    const [typ, sciezka] = e.dataset.out.split(':');
    if (typ === 'hz') { const v = getPath(S.u, sciezka); e.textContent = v > 0 ? `${fmtNum(v)} Hz` : 'ciągle'; }
    else if (typ === 'pct') e.textContent = `${fmtNum(getPath(S.u, sciezka))}%`;
    else if (typ === 'flagi') {
      const v = S.u.stany.flagi_diody_skrajne;
      e.textContent = v === 0 || 2 * v >= S.u.liczba_diod ? 'cały pasek' : `${v === 1 ? 'dioda' : v < 5 ? 'diody' : 'diod'} z każdej strony`;
    }
  });
  $('#outJasnosc').textContent = `${S.u.jasnosc}%`;
  $$('.state').forEach((c) => {
    const k = c.dataset.state;
    if (k !== 'brak_gry') c.classList.toggle('off', !S.u.stany[k].wlaczony);
  });
  renderEdytor();
  renderProgi();
  renderZasilanie();
  renderPresetyAktywne();
  renderZapis();
}

function zmiana() {
  S.lokalnie = (S.lokalnie || 0) + 1;
  renderForm();
  clearTimeout(S.timer);
  S.timer = setTimeout(wyslijUstawienia, 70);
}

async function wyslijUstawienia() {
  clearTimeout(S.timer);
  S.timer = null;
  const nr = S.lokalnie;
  const d = await api('/api/ustawienia', { ustawienia: S.u });
  if (!d) return;
  S.niezapisane = d.niezapisane;
  if (nr === S.lokalnie && stabilny(d.ustawienia) !== stabilny(S.u)) {
    S.u = d.ustawienia;   // program poprawił wartości (np. zakresy)
    renderForm();
  } else {
    renderZapis();
  }
}

async function dokonczWysylanie() {
  if (S.timer) await wyslijUstawienia();
}

function ustawPole(sciezka, v) {
  if (getPath(S.u, sciezka) === v) return;
  setPath(S.u, sciezka, v);
  if (sciezka === 'liczba_diod') przeskaluj(v);
  if (sciezka === 'liczba_diod' || sciezka === 'kierunek') odswiezPresety();
  zmiana();
}

function przeskaluj(n) {
  // rozciąga ostatnio ustawiony wzór kolorów na nową liczbę diod
  const w = S.wzor && S.wzor.length ? S.wzor : S.u.kolory;
  S.u.kolory = Array.from({ length: n }, (_, i) => (n === 1 || w.length === 1 ? w[0] : w[Math.round((i * (w.length - 1)) / (n - 1))]));
  S.sel = new Set([...S.sel].filter((i) => i < n));
  if (S.anchor != null && S.anchor >= n) S.anchor = null;
}

function renderZasilanie() {
  const u = S.u;
  const prad = (kolory) => kolory.reduce((s, k) => { const [r, g, b] = hexNaRgb(k); return s + ((r + g + b) / 255) * 20; }, 0);
  const n = u.liczba_diod;
  const kandydaci = [prad(u.kolory)];
  ['zmiana_biegu', 'pit_limiter', 'flaga_zolta', 'flaga_niebieska'].forEach((k) => { if (u.stany[k].wlaczony) kandydaci.push(prad(Array(n).fill(u.stany[k].kolor))); });
  if (u.stany.brak_gry.tryb !== 'wylaczone') kandydaci.push(prad(Array(n).fill(u.stany.brak_gry.kolor)));
  const ma = Math.round((Math.max(...kandydaci) * u.jasnosc) / 100);
  const el = $('#powerNote');
  const zaDuzo = ma > 400;
  el.className = 'note' + (zaDuzo ? ' warn' : '');
  el.innerHTML = zaDuzo
    ? `<svg><use href="#i-warn"/></svg><span>Pasek może pobierać do <b>${ma} mA</b> – za dużo przy zasilaniu z USB. Zmniejsz jasność albo użyj osobnego zasilacza 5 V.</span>`
    : `<svg><use href="#i-plug"/></svg><span>Maksymalny pobór paska: <b>≈ ${ma} mA</b> – zasilanie z USB wystarczy.</span>`;
}

/* ------------------------------------------------------- edytor kolorów */
function renderEdytor() {
  const ed = $('#editor');
  const n = S.u.liczba_diod;
  if (ed._n !== n) {
    budujPasek(ed, n, 20);
    ed._leds.forEach((d, i) => { d.dataset.n = i + 1; });
  }
  ed._leds.forEach((d, i) => {
    const k = S.u.kolory[i];
    if (k === '#000000') { d.classList.remove('on'); d.style.removeProperty('--c'); }
    else { d.classList.add('on'); d.style.setProperty('--c', k); }
    d.classList.toggle('sel', S.sel.has(i));
    d.title = `Dioda ${i + 1}: ${k}`;
  });
  const ile = S.sel.size;
  $('#selInfo').textContent = ile ? `Zaznaczono: ${ile} ${ile === 1 ? 'dioda' : ile % 10 >= 2 && ile % 10 <= 4 && (ile % 100 < 10 || ile % 100 >= 20) ? 'diody' : 'diod'} · Shift = zakres, Ctrl = pojedyncze` : 'Kliknij lub przeciągnij po diodach, aby je zaznaczyć';
  const wrap = $('#selColorWrap');
  const input = $('#selColor');
  input.disabled = !ile;
  wrap.classList.toggle('disabled', !ile);
  wrap.title = ile ? 'Kolor zaznaczonych diod' : 'Najpierw zaznacz diody';
  const pierwsza = ile ? S.u.kolory[Math.min(...S.sel)] : '#444444';
  $('#selSwatch').style.setProperty('--sw', pierwsza);
  if (document.activeElement !== input) input.value = pierwsza.toLowerCase();
  $$('#palette button').forEach((b) => { b.disabled = !ile; });
}

function indeksDiody(el) {
  const d = el && el.closest ? el.closest('#editor .led') : null;
  return d ? +d.dataset.i : null;
}
function zakres(a, b) { const s = new Set(); for (let i = Math.min(a, b); i <= Math.max(a, b); i++) s.add(i); return s; }

function ustawKoloryZaznaczonych(kolor) {
  if (!S.sel.size) { toast('Najpierw zaznacz diody na pasku.', 'info'); return; }
  S.sel.forEach((i) => { S.u.kolory[i] = kolor; });
  S.wzor = [...S.u.kolory];
  zmiana();
}

function ustawWszystkieKolory(kolory) {
  S.u.kolory = kolory.slice();
  S.wzor = [...S.u.kolory];
  S.sel.clear();
  zmiana();
}

/* --------------------------------------------------------------- presety */
function odswiezPresety() {
  clearTimeout(S.presetTimer);
  S.presetTimer = setTimeout(async () => {
    const d = await api('/api/presety', { n: S.u.liczba_diod, kierunek: S.u.kierunek });
    if (!d) return;
    S.presety = d.presety;
    renderPresety();
  }, 120);
}

function renderPresety() {
  const o = S.opts.presety;
  $('#presets').innerHTML = Object.keys(S.presety).map((k) => {
    const [tytul, opis] = String(o[k] || k).split(': ');
    const kropki = S.presety[k].map((c) => `<i style="--c:${c}"></i>`).join('');
    return `<button class="preset" data-preset="${k}"><b>${esc(tytul[0].toUpperCase() + tytul.slice(1))}</b><small>${esc(opis || '')}</small><span class="mini-static">${kropki}</span></button>`;
  }).join('');
  renderPresetyAktywne();
}

function renderPresetyAktywne() {
  const akt = stabilny(S.u.kolory);
  $$('.preset').forEach((b) => b.classList.toggle('active', stabilny(S.presety[b.dataset.preset] || []) === akt));
}

/* ----------------------------------------------------------------- progi */
const PROGI = {
  start: () => S.u.obroty.start, pelne: () => S.u.obroty.pelne, prog: () => S.u.stany.zmiana_biegu.prog,
};

function ustawProg(k, v) {
  v = Math.round(clamp(v, 0, 100));
  const o = S.u.obroty;
  if (k === 'start') { o.start = v; if (o.pelne < v) o.pelne = v; }
  else if (k === 'pelne') { o.pelne = v; if (o.start > v) o.start = v; }
  else S.u.stany.zmiana_biegu.prog = v;
  zmiana();
}

function renderProgi() {
  const st = S.u.obroty.start, pe = S.u.obroty.pelne, pr = S.u.stany.zmiana_biegu.prog;
  const thr = $('#thr');
  $$('.thr-h', thr).forEach((h) => {
    const v = PROGI[h.dataset.k]();
    h.style.left = `${v}%`;
    h.querySelector('.tip').textContent = `${fmtNum(v)}%`;
    h.setAttribute('aria-valuenow', v);
    h.setAttribute('aria-valuemin', 0);
    h.setAttribute('aria-valuemax', 100);
  });
  const zona = $('#thrZone');
  zona.style.left = `${st}%`;
  zona.style.width = `${Math.max(0.6, pe - st)}%`;
  const sz = $('#thrShiftZone');
  sz.style.left = `${pr}%`;
  sz.style.opacity = S.u.stany.zmiana_biegu.wlaczony ? '1' : '.25';
  $('.h-shift').style.opacity = S.u.stany.zmiana_biegu.wlaczony ? '1' : '.45';
  // znaczniki na suwaku obrotów w podglądzie
  $('#rpmMarks').innerHTML = `<i style="left:${st}%;background:var(--c-start)"></i><i style="left:${pe}%;background:var(--c-full)"></i>${S.u.stany.zmiana_biegu.wlaczony ? `<i style="left:${pr}%;background:var(--c-shift)"></i>` : ''}`;
}

function procentZ(e) {
  const r = $('#thrTrack').getBoundingClientRect();
  return clamp(((e.clientX - r.left) / r.width) * 100, 0, 100);
}

function startProgu(e, k) {
  e.preventDefault();
  const el = e.currentTarget;
  el.setPointerCapture(e.pointerId);
  const st = S.u.obroty.start, pe = S.u.obroty.pelne;
  S.thrDrag = { k, el, niezdecydowany: (k === 'start' || k === 'pelne') && st === pe };
}

function ruchProgu(e) {
  const d = S.thrDrag; if (!d) return;
  const v = procentZ(e);
  if (d.niezdecydowany) {
    const obecna = S.u.obroty.start;
    if (Math.round(v) === obecna) return;
    d.k = v < obecna ? 'start' : 'pelne';
    d.niezdecydowany = false;
    $(`.thr-h[data-k="${d.k}"]`).focus();
  }
  ustawProg(d.k, v);
}

/* ------------------------------------------------------- podgląd / klatki */
let klatka = null, rafCzeka = false;
function naKlatke(m) {
  klatka = m;
  if (!rafCzeka) { rafCzeka = true; requestAnimationFrame(rysujKlatke); }
}

const OPIS_PASKA = {
  brak: ['kierownica niepołączona', ''], bez_led: ['firmware bez obsługi LED – wgraj wersję 1.1', 'bad'],
  wylaczony: ['wyłączone', ''], wysylam: ['na żywo', 'live'],
};

function rysujKlatke() {
  rafCzeka = false;
  const m = klatka;
  if (!m || document.hidden) return;
  if (S.tab === 'ledy') {
    malujPasek($('#heroStrip'), m.glowna, 30);
    for (const k in m.mini) if (S.mini && S.mini[k]) malujPasek(S.mini[k], m.mini[k], 24);
    const proc = m.obroty * 100;
    if (!S.rpmDrag) {
      const r = $('#simRpm');
      r.value = proc;
      ustawZakres(r);
      $('#rpmVal').textContent = Math.round(proc);
    }
    $('#thrRpm').style.left = `${proc}%`;
    const [tekst, kl] = OPIS_PASKA[m.pasek] || ['', ''];
    const ds = $('#deviceState');
    if (ds.textContent !== tekst) { ds.textContent = tekst; ds.className = kl; }
  } else {
    malujKolo(m.glowna);
  }
}

function renderSim() {
  const s = S.sim;
  $$('#simState button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.v === s.stan)));
  const auto = $('#simAuto');
  auto.setAttribute('aria-pressed', String(s.auto));
  auto.title = s.auto ? 'Zatrzymaj automatyczną jazdę' : 'Automatyczna jazda (obroty rosną same)';
  auto.innerHTML = `<svg><use href="#${s.auto ? 'i-pause' : 'i-play'}"/></svg>`;
  $('#simSend').checked = s.wysylaj;
  const rpmAktywne = s.stan === 'jazda' || s.stan === 'zolta' || s.stan === 'niebieska';
  $('#simRpm').disabled = !rpmAktywne;
  auto.disabled = !rpmAktywne;
}

let simTimer = null, simDoWyslania = null;
function wyslijSim(zmiany) {
  simDoWyslania = Object.assign(simDoWyslania || {}, zmiany);
  if (simTimer) return;
  simTimer = setTimeout(async () => {
    const d = simDoWyslania; simDoWyslania = null; simTimer = null;
    const r = await api('/api/sim', d);
    if (r) { S.sim = r.sim; renderSim(); }
  }, 40);
}

/* -------------------------------------------------------------- zapis */
function renderZapis() {
  const bar = $('#savebar');
  bar.classList.toggle('dirty', S.niezapisane);
  $('#sbTitle').textContent = S.niezapisane ? 'Niezapisane zmiany' : 'Wszystko zapisane';
  $('#sbFile').textContent = (S.profil ? `Profil: ${S.profil} · ` : '') + S.plik;
  $('#sbFile').title = S.plik;
  $('#btnSave').disabled = !S.niezapisane;
  $('#btnRevert').disabled = !S.niezapisane;
  $('#tabDot').hidden = !S.niezapisane;
}

async function zapisz() {
  await dokonczWysylanie();
  const d = await api('/api/zapisz');
  if (d) toast(S.profil ? `Zapisano (także w profilu „${S.profil}”).` : 'Zapisano ustawienia diod.');
}

/* -------------------------------------------------------------- profile */
function renderProfile() {
  const box = $('#profileList');
  if (!S.profile.length) {
    box.innerHTML = '<div class="profile-empty">Nie masz jeszcze żadnych profili.<br>Wpisz nazwę poniżej i zapisz bieżące ustawienia.</div>';
    return;
  }
  box.innerHTML = S.profile.map((p) => {
    const kropki = (p.kolory || []).map((c) => `<i style="--c:${c}"></i>`).join('');
    const aktywny = p.nazwa === S.profil;
    return `<div class="profile${aktywny ? ' active' : ''}">
      <div class="profile-main"><b>${esc(p.nazwa)}${aktywny ? '<small>wczytany</small>' : ''}</b>
        ${p.blad ? '<small class="muted">uszkodzony plik</small>' : `<span class="mini-static">${kropki}</span>`}</div>
      <div class="profile-actions">
        <button class="btn sm" data-wczytaj="${esc(p.nazwa)}"${p.blad ? ' disabled' : ''}>Wczytaj</button>
        <button class="btn ghost sm danger" data-usun="${esc(p.nazwa)}" aria-label="Usuń profil ${esc(p.nazwa)}"><svg><use href="#i-x"/></svg></button>
      </div></div>`;
  }).join('');
}

/* ============================================================ ZDARZENIA */
function przyjmijUstawienia(m) {
  S.u = m.ustawienia;
  S.wzor = [...S.u.kolory];
  S.sel.clear(); S.anchor = null;
  if ('niezapisane' in m) S.niezapisane = m.niezapisane;
  if ('profil' in m) S.profil = m.profil;
  if (m.profile) S.profile = m.profile;
  S.lokalnie = (S.lokalnie || 0) + 1;   // odrzuć odpowiedzi na starsze zmiany
  renderForm();
  odswiezPresety();
  renderProfile();
}

function obsluz(m) {
  switch (m.t) {
    case 'witaj': {
      S.opts = m.opcje; S.plik = m.plik; S.sim = m.sim; S.piny = m.piny || {};
      if (!S.zbudowane) { budujStany(); budujStale(); S.zbudowane = true; }
      przyjmijUstawienia(m);
      renderSim();
      const st = m.status;
      if (st.stan === 'polaczono') {
        if (st.id !== S.polId) { S.status = null; ustawStatus(st); }
        else { S.status = st; renderStatus(); }
        if (m.bity) { S.pierwszyStan = true; stanPrzyciskow(m.bity); }
      } else {
        ustawStatus(st);
      }
      if (m.blad) toast(`${m.blad} Wczytano ustawienia domyślne.`, 'err', 7000);
      break;
    }
    case 'status': ustawStatus(m.status); break;
    case 'przycisk': zmianaPrzycisku(m.n, m.wl, m.pin, false); break;
    case 'stan': stanPrzyciskow(m.bity); break;
    case 'piny':
      S.piny = m.piny;
      S.btns.forEach((b) => { if (m.piny[b.n]) { b.pin = m.piny[b.n]; renderPrzycisk(b); } });
      break;
    case 'klatka': naKlatke(m); break;
    case 'sim': S.sim = m.sim; renderSim(); break;
    case 'niezapisane': S.niezapisane = m.niezapisane; renderZapis(); break;
    case 'ustawienia': przyjmijUstawienia(m); break;
    default: break;
  }
}

function polaczZdarzenia() {
  const es = new EventSource('/api/zdarzenia');
  let offlineTimer = null;
  es.onmessage = (e) => {
    let m;
    try { m = JSON.parse(e.data); } catch { return; }
    obsluz(m);
  };
  es.onopen = () => { clearTimeout(offlineTimer); offlineTimer = null; $('#offline').hidden = true; };
  es.onerror = () => {
    if (offlineTimer) return;
    offlineTimer = setTimeout(() => { offlineTimer = null; if (es.readyState !== EventSource.OPEN) $('#offline').hidden = false; }, 1500);
  };
}

function podepnij() {
  // zakładki
  $$('.tab-btn').forEach((b) => b.addEventListener('click', () => pokazZakladke(b.dataset.tab)));

  // połączenie
  $('#connPill').addEventListener('click', (e) => { e.stopPropagation(); if ($('#connPop').hidden) otworzPopover(); else zamknijPopover(); });
  $('#connPop').addEventListener('click', (e) => e.stopPropagation());
  document.addEventListener('click', () => zamknijPopover());
  $('#btnConnect').addEventListener('click', async () => {
    if (await api('/api/polacz', { port: $('#portSelect').value || null })) zamknijPopover();
  });
  $('#btnDisconnect').addEventListener('click', async () => { if (await api('/api/rozlacz')) zamknijPopover(); });
  $('#ovConnect').addEventListener('click', () => api('/api/polacz', { port: S.status ? S.status.port_wybrany : null }));

  // test przycisków
  $('#btnTestReset').addEventListener('click', () => {
    S.btns.forEach((b) => { b.licz = 0; b.ok = false; });
    renderPrzyciski();
    $('#log').innerHTML = '<li class="log-empty">Tu pojawi się każde wciśnięcie.</li>';
    toast('Test zaczęty od nowa.', 'info');
  });
  $('#btnLogClear').addEventListener('click', () => { $('#log').innerHTML = '<li class="log-empty">Tu pojawi się każde wciśnięcie.</li>'; });

  // pola z data-bind
  document.addEventListener('input', (e) => {
    const el = e.target;
    if (el.type === 'range') ustawZakres(el);
    if (!S.u || !el.dataset || !el.dataset.bind || el.classList.contains('seg')) return;
    let v;
    switch (el.dataset.type) {
      case 'bool': v = el.checked; break;
      case 'color': v = el.value.toUpperCase(); break;
      case 'int': v = parseInt(el.value, 10); if (!Number.isFinite(v) || v < +el.min || v > +el.max) return; break;
      case 'float': v = parseFloat(String(el.value).replace(',', '.')); if (!Number.isFinite(v) || v < +el.min || v > +el.max) return; break;
      default: v = el.value;
    }
    ustawPole(el.dataset.bind, v);
  });
  document.addEventListener('change', (e) => {
    const el = e.target;
    if (el.dataset && el.dataset.bind && el.type === 'number') { el.blur(); renderForm(); }
  });
  document.addEventListener('focusout', (e) => {
    if (e.target.dataset && e.target.dataset.bind && e.target.type === 'number') setTimeout(renderForm, 0);
  });
  document.addEventListener('click', (e) => {
    const b = e.target.closest('.seg[data-bind] button[data-v]');
    if (b && S.u) ustawPole(b.closest('.seg').dataset.bind, b.dataset.v);
    const step = e.target.closest('.step');
    if (step) {
      const inp = step.parentElement.querySelector('input');
      const nv = clamp((parseInt(inp.value, 10) || 0) + +step.dataset.step, +inp.min, +inp.max);
      inp.value = nv;
      inp.dispatchEvent(new Event('input', { bubbles: true }));
    }
    const pokaz = e.target.closest('[data-pokaz]');
    if (pokaz) {
      const k = pokaz.dataset.pokaz;
      wyslijSim(k === 'zmiana_biegu' ? { stan: 'jazda', obroty: 1 } : { stan: SIM_STANU[k] });
      toast(`Podgląd: ${STANY.find((s) => s.k === k).t}`, 'info', 1800);
    }
  });

  // edytor kolorów
  const ed = $('#editor');
  ed.addEventListener('pointerdown', (e) => {
    const i = indeksDiody(e.target);
    if (i == null) { if (!e.shiftKey && !e.ctrlKey && !e.metaKey) { S.sel.clear(); renderEdytor(); } return; }
    e.preventDefault();
    ed.focus({ preventScroll: true });
    ed.setPointerCapture(e.pointerId);
    if (e.shiftKey && S.anchor != null) {
      S.sel = zakres(S.anchor, i);
      S.drag = { baza: new Set() };
    } else if (e.ctrlKey || e.metaKey) {
      if (S.sel.has(i)) S.sel.delete(i); else S.sel.add(i);
      S.anchor = i;
      S.drag = { baza: new Set(S.sel) };
    } else {
      S.sel = new Set([i]);
      S.anchor = i;
      S.drag = { baza: new Set() };
    }
    renderEdytor();
  });
  ed.addEventListener('pointermove', (e) => {
    if (!S.drag) return;
    const i = indeksDiody(document.elementFromPoint(e.clientX, e.clientY));
    if (i == null || S.anchor == null) return;
    const s = zakres(S.anchor, i);
    S.drag.baza.forEach((x) => s.add(x));
    if (stabilny([...s].sort()) !== stabilny([...S.sel].sort())) { S.sel = s; renderEdytor(); }
  });
  const koniecZaznaczania = () => { S.drag = null; };
  ed.addEventListener('pointerup', koniecZaznaczania);
  ed.addEventListener('pointercancel', koniecZaznaczania);
  ed.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') { e.preventDefault(); S.sel = zakres(0, S.u.liczba_diod - 1); renderEdytor(); }
    if (e.key === 'Escape') { S.sel.clear(); renderEdytor(); }
  });
  $('#selColor').addEventListener('input', (e) => ustawKoloryZaznaczonych(e.target.value.toUpperCase()));
  $('#palette').addEventListener('click', (e) => { const b = e.target.closest('button[data-kolor]'); if (b) ustawKoloryZaznaczonych(b.dataset.kolor); });
  $('#selAll').addEventListener('click', () => { S.sel = zakres(0, S.u.liczba_diod - 1); S.anchor = 0; renderEdytor(); });
  $('#selNone').addEventListener('click', () => { S.sel.clear(); renderEdytor(); });
  $('#mirror').addEventListener('click', () => {
    const k = S.u.kolory, n = k.length;
    for (let i = 0; i < Math.floor(n / 2); i++) k[n - 1 - i] = k[i];
    S.wzor = [...k];
    zmiana();
    toast('Prawa połowa jest teraz lustrzanym odbiciem lewej.', 'info');
  });
  $('#presets').addEventListener('click', (e) => {
    const b = e.target.closest('[data-preset]');
    if (b && S.presety[b.dataset.preset]) ustawWszystkieKolory(S.presety[b.dataset.preset]);
  });
  $('#gradStops').addEventListener('input', (e) => {
    const i = e.target.dataset.grad;
    if (i == null) return;
    S.gradient[+i] = e.target.value.toUpperCase();
    e.target.parentElement.style.setProperty('--sw', S.gradient[+i]);
    $('#gradPreview').style.background = `linear-gradient(90deg, ${S.gradient.join(', ')})`;
  });
  $('#gradApply').addEventListener('click', async () => {
    const d = await api('/api/gradient', { n: S.u.liczba_diod, kierunek: S.u.kierunek, punkty: S.gradient });
    if (d) ustawWszystkieKolory(d.kolory);
  });

  // progi
  $$('.thr-h').forEach((h) => {
    h.addEventListener('pointerdown', (e) => startProgu(e, h.dataset.k));
    h.addEventListener('keydown', (e) => {
      const k = h.dataset.k;
      const v = PROGI[k]();
      const kroki = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -10, PageUp: 10 };
      if (e.key in kroki) { e.preventDefault(); ustawProg(k, v + kroki[e.key] * (e.shiftKey ? 5 : 1)); }
      else if (e.key === 'Home') { e.preventDefault(); ustawProg(k, 0); }
      else if (e.key === 'End') { e.preventDefault(); ustawProg(k, 100); }
    });
  });
  $('#thrTrack').addEventListener('pointerdown', (e) => {
    const v = procentZ(e);
    const kand = ['start', 'pelne', 'prog'].filter((k) => k !== 'prog' || S.u.stany.zmiana_biegu.wlaczony);
    const k = kand.reduce((a, b) => (Math.abs(PROGI[b]() - v) < Math.abs(PROGI[a]() - v) ? b : a));
    const h = $(`.thr-h[data-k="${k}"]`);
    ustawProg(k, v);
    h.focus();
    h.setPointerCapture(e.pointerId);
    S.thrDrag = { k, el: h, niezdecydowany: false };
    e.preventDefault();
  });
  document.addEventListener('pointermove', ruchProgu);
  const koniecProgu = () => { S.thrDrag = null; };
  document.addEventListener('pointerup', koniecProgu);
  document.addEventListener('pointercancel', koniecProgu);

  // symulacja
  $('#simState').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-v]');
    if (b) { S.sim.stan = b.dataset.v; renderSim(); wyslijSim({ stan: b.dataset.v }); }
  });
  $('#simAuto').addEventListener('click', () => { S.sim.auto = !S.sim.auto; renderSim(); wyslijSim({ auto: S.sim.auto }); });
  $('#simSend').addEventListener('change', (e) => wyslijSim({ wysylaj: e.target.checked }));
  const rpm = $('#simRpm');
  rpm.addEventListener('pointerdown', () => { S.rpmDrag = true; });
  rpm.addEventListener('input', () => {
    S.rpmDrag = true;
    $('#rpmVal').textContent = Math.round(+rpm.value);
    if (S.sim.auto) { S.sim.auto = false; renderSim(); }
    wyslijSim({ obroty: +rpm.value / 100 });
  });
  const puscRpm = () => { setTimeout(() => { S.rpmDrag = false; }, 150); };
  rpm.addEventListener('change', puscRpm);
  rpm.addEventListener('pointerup', puscRpm);
  rpm.addEventListener('blur', puscRpm);

  // zapis
  $('#btnSave').addEventListener('click', zapisz);
  $('#btnRevert').addEventListener('click', async () => {
    if (await potwierdz('Cofnąć zmiany?', 'Ustawienia wrócą do ostatnio zapisanych w pliku.', 'Cofnij zmiany')) {
      clearTimeout(S.timer); S.timer = null;
      if (await api('/api/cofnij')) toast('Przywrócono zapisane ustawienia.', 'info');
    }
  });
  $('#btnDefaults').addEventListener('click', async () => {
    if (await potwierdz('Przywrócić ustawienia domyślne?', 'Kolory, progi i efekty wrócą do ustawień fabrycznych. Plik zmieni się dopiero po kliknięciu „Zapisz”.', 'Przywróć')) {
      clearTimeout(S.timer); S.timer = null;
      if (await api('/api/domyslne')) toast('Przywrócono ustawienia domyślne – kliknij Zapisz, aby je zachować.', 'info', 4000);
    }
  });

  // profile
  const dlg = $('#dlgProfiles');
  $('#btnProfiles').addEventListener('click', () => { renderProfile(); dlg.showModal(); $('#profileName').focus(); });
  dlg.addEventListener('click', (e) => {
    if (e.target.closest('[data-close]')) { dlg.close(); return; }
    if (e.target === dlg) {
      const r = dlg.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dlg.close();
    }
  });
  $('#profileList').addEventListener('click', async (e) => {
    const w = e.target.closest('[data-wczytaj]');
    const u = e.target.closest('[data-usun]');
    if (w) {
      const nazwa = w.dataset.wczytaj;
      if (S.niezapisane && !(await potwierdz('Wczytać profil?', 'Masz niezapisane zmiany – zostaną zastąpione ustawieniami z profilu.', 'Wczytaj'))) return;
      clearTimeout(S.timer); S.timer = null;
      if (await api('/api/profile/wczytaj', { nazwa })) {
        dlg.close();
        toast(`Wczytano profil „${nazwa}”. Kliknij Zapisz, żeby używać go w grze.`, 'ok', 4500);
      }
    } else if (u) {
      const nazwa = u.dataset.usun;
      if (await potwierdz('Usunąć profil?', `Profil „${nazwa}” zostanie trwale usunięty.`, 'Usuń', true)) {
        if (await api('/api/profile/usun', { nazwa })) toast(`Usunięto profil „${nazwa}”.`, 'info');
      }
    }
  });
  $('#profileForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const inp = $('#profileName');
    const nazwa = inp.value.trim();
    if (!nazwa) { inp.focus(); toast('Wpisz nazwę profilu.', 'info'); return; }
    if (S.profile.some((p) => p.nazwa.toLowerCase() === nazwa.toLowerCase())
        && !(await potwierdz('Nadpisać profil?', `Profil „${nazwa}” już istnieje.`, 'Nadpisz'))) return;
    await dokonczWysylanie();
    const d = await api('/api/profile/zapisz', { nazwa });
    if (d) { inp.value = ''; toast(`Zapisano profil „${d.nazwa}”.`); }
  });
  $('#btnExport').addEventListener('click', async () => {
    await dokonczWysylanie();
    const blob = new Blob([JSON.stringify(S.u, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `kierownica-gt-led${S.profil ? '-' + S.profil.replace(/\s+/g, '-') : ''}.json`;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    toast('Wyeksportowano ustawienia do pliku.');
  });
  $('#btnImport').addEventListener('click', () => $('#importFile').click());
  $('#importFile').addEventListener('change', async (e) => {
    const plik = e.target.files[0];
    e.target.value = '';
    if (!plik) return;
    let dane;
    try { dane = JSON.parse(await plik.text()); } catch { toast('To nie jest poprawny plik JSON.', 'err', 4500); return; }
    if (!dane || typeof dane !== 'object' || Array.isArray(dane)) { toast('Plik nie zawiera ustawień diod.', 'err', 4500); return; }
    clearTimeout(S.timer); S.timer = null;
    if (await api('/api/ustawienia', { ustawienia: dane, rozglos: true })) {
      dlg.close();
      toast('Zaimportowano ustawienia – kliknij Zapisz, aby je zachować.', 'ok', 4500);
    }
  });

  // skróty klawiszowe
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      if (S.niezapisane || S.timer) zapisz();
      else toast('Wszystko jest już zapisane.', 'info', 1800);
    }
    if (e.key === 'Escape') zamknijPopover();
  });

  window.addEventListener('beforeunload', (e) => {
    if (S.niezapisane) { e.preventDefault(); e.returnValue = ''; }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && klatka) naKlatke(klatka); });
}

/* ================================================================ START */
(function start() {
  let tab = 'przyciski';
  try { tab = localStorage.getItem('kgt-tab') || tab; } catch { /* bez pamięci */ }
  pokazZakladke(tab === 'ledy' ? 'ledy' : 'przyciski');
  przygotujPrzyciski(12, false);
  podepnij();
  polaczZdarzenia();
})();
