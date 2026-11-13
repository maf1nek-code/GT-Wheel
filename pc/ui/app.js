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
  { k: 'spotter', t: 'Spotter', d: 'Auto obok ciebie – skrajne diody po jego stronie. ACC i Le Mans Ultimate.', ico: 'i-spotter', opcja: 'spotter' },
  { k: 'brak_gry', t: 'Gra wyłączona', d: 'Gdy gra nie działa albo jest w menu.', ico: 'i-moon', opcja: 'tryb' },
];
const SIM_STANU = { spotter: 'spotter', zmiana_biegu: 'jazda', pit_limiter: 'pit', flaga_zolta: 'zolta', flaga_niebieska: 'niebieska', brak_gry: 'brak_gry' };
const KROTKO_PIT = { caly: 'Cały pasek', naprzemiennie: 'Co druga', polowki: 'Połówki' };
const KROTKO_TRYB = { wylaczone: 'Zgaszone', staly: 'Stały', oddech: 'Oddech', skaner: 'Skaner' };
const NAZWY_SIM = { gra: 'Gra na żywo', jazda: 'Jazda', pit: 'Pit limiter', zolta: 'Flaga żółta', niebieska: 'Flaga niebieska', brak_gry: 'Gra wyłączona' };

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

  // pasek stanu pod kierownicą
  const ov = $('#wheelOverlay');
  const polaczono = st.stan === 'polaczono';
  ov.classList.toggle('hide', polaczono);
  $('#wheelWrap').classList.toggle('off', !polaczono);
  renderEkran();
  if (S.przyp.wl) renderPrzypisywanie();
  renderFw();
  renderProgram();
  if (!polaczono) {
    const ikona = $('#ovIcon');
    const tytuly = {
      szukam: 'Szukam kierownicy…', brak: 'Nie znaleziono kierownicy', zajety: 'Port jest zajęty',
      utracono: 'Utracono połączenie', rozlaczono: 'Kierownica rozłączona',
    };
    $('#ovTitle').textContent = tytuly[st.stan] || st.tekst;
    ov.dataset.stan = st.stan;
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
// Miejsca na rysunku kierownicy (współrzędne w układzie 1205 × 700, jak zdjęcie).
const MIEJSCA = [
  { id: 'l_zolty', nazwa: 'żółty, lewy górny', x: 165, y: 128, r: 30, kolor: '#f2c014', jasny: true },
  { id: 'l_czarny', nazwa: 'czarny, lewy górny', x: 243, y: 142, r: 26, kolor: '#24262a' },
  { id: 'l_czerwony', nazwa: 'czerwony, lewa kolumna', x: 330, y: 372, r: 29, kolor: '#e0352b' },
  { id: 'l_bialy', nazwa: 'biały, lewa kolumna', x: 330, y: 456, r: 29, kolor: '#ececec', jasny: true },
  { id: 'l_zielony', nazwa: 'zielony, lewa kolumna', x: 330, y: 540, r: 29, kolor: '#2e9e44' },
  { id: 'p_czarny', nazwa: 'czarny, prawy górny', x: 962, y: 142, r: 26, kolor: '#24262a' },
  { id: 'p_niebieski', nazwa: 'niebieski, prawy górny', x: 1040, y: 128, r: 30, kolor: '#2f6fd6' },
  { id: 'p_czerwony', nazwa: 'czerwony, prawa kolumna', x: 875, y: 372, r: 29, kolor: '#e0352b' },
  { id: 'p_bialy', nazwa: 'biały, prawa kolumna', x: 875, y: 456, r: 29, kolor: '#ececec', jasny: true },
  { id: 'p_pomaranczowy', nazwa: 'pomarańczowy, prawa kolumna', x: 875, y: 540, r: 29, kolor: '#f06a1c' },
  { id: 'pok_l', nazwa: 'lewe pokrętło', x: 470, y: 524, r: 33, pokretlo: true },
  { id: 'pok_s', nazwa: 'środkowe pokrętło', x: 602, y: 524, r: 33, pokretlo: true },
  { id: 'pok_p', nazwa: 'prawe pokrętło', x: 735, y: 524, r: 33, pokretlo: true },
];
// Zgadnięte z README: lewa strona płytki = 1–5 i 11, prawa = 6–10 i 12.
const UKLAD_DOMYSLNY = {
  l_zolty: 1, l_czarny: 2, l_czerwony: 3, l_bialy: 4, l_zielony: 5,
  p_czarny: 6, p_niebieski: 7, p_czerwony: 8, p_bialy: 9, p_pomaranczowy: 10, pok_l: 11, pok_p: 12,
};
S.uklad = { ...UKLAD_DOMYSLNY };
S.przyp = { wl: false, miejsce: null };
S.ostatni = null;
S.ostrzezone = new Set();

const miejsceNumeru = (n) => MIEJSCA.find((m) => S.uklad[m.id] === n) || null;

const LEWY_UCHWYT = 'M150 44 C200 34 290 34 322 52 C340 64 340 90 338 120 L336 205 C335 232 318 240 296 240 '
  + 'L268 242 C246 244 240 258 240 280 L240 322 C240 346 256 356 280 358 L292 360 L292 588 '
  + 'C262 594 232 600 214 612 C200 650 180 684 140 690 C100 694 66 670 54 620 C36 540 34 420 46 300 '
  + 'C54 220 80 150 118 100 C128 70 136 52 150 44 Z';

function sruba(x, y, r = 11) {
  return `<g transform="translate(${x} ${y})"><circle class="k-screw" r="${r}"/><path class="k-screw-hex" d="M${-r * 0.45} 0 L${-r * 0.22} ${-r * 0.39} L${r * 0.22} ${-r * 0.39} L${r * 0.45} 0 L${r * 0.22} ${r * 0.39} L${-r * 0.22} ${r * 0.39} Z"/></g>`;
}

function budujKolo() {
  const svg = $('#wheel');
  const miejsca = MIEJSCA.map((m) => {
    const czapka = m.pokretlo
      ? `<circle class="k-knurl" r="${m.r}"/><circle r="${m.r - 8}" fill="url(#knobGrad)"/><circle r="${m.r - 8}" fill="url(#capShine)" opacity=".35"/>`
      : `<circle class="ws-cap" r="${m.r}" fill="${m.kolor}"/><circle r="${m.r}" fill="url(#capShine)"/>`;
    return `<g class="ws${m.pokretlo ? ' knob' : ''}" data-id="${m.id}" transform="translate(${m.x} ${m.y})"><title></title>
      <circle class="ws-halo" r="${m.r + 14}"/>
      <circle class="k-bezel" r="${m.r + 7}"/>
      <circle class="ws-sel" r="${m.r + 13}"/>
      <g class="ws-in">${czapka}<text class="ws-num${m.jasny ? ' ciemny' : ''}"></text></g>
      <g transform="translate(${(m.r * 0.74).toFixed(1)} ${(-m.r * 0.74).toFixed(1)})"><g class="ws-check"><circle r="10"/><path d="M-4.4 0.3 L-1.3 3.4 L4.4 -2.8"/></g></g>
    </g>`;
  }).join('');

  const sruby = [[330, 182], [875, 182], [536, 556], [669, 556], [96, 330], [80, 520], [120, 642], [1109, 330], [1125, 520], [1085, 642]]
    .map(([x, y]) => sruba(x, y, x < 200 || x > 1000 ? 9 : 11)).join('');

  svg.innerHTML = `
    <defs>
      <pattern id="carbon" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="14" height="14" fill="#141619"/><rect width="7" height="7" fill="#1f2226"/><rect x="7" y="7" width="7" height="7" fill="#1f2226"/>
      </pattern>
      <linearGradient id="carbonShine" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#fff" stop-opacity=".10"/><stop offset=".38" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity=".04"/>
      </linearGradient>
      <pattern id="druk" width="8" height="4" patternUnits="userSpaceOnUse">
        <rect width="8" height="4" fill="#131315"/><rect width="8" height="1.2" fill="#1a1a1d"/>
      </pattern>
      <linearGradient id="gripShade" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#000" stop-opacity=".55"/><stop offset=".45" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".15"/>
      </linearGradient>
      <radialGradient id="capShine" cx=".36" cy=".3" r=".78">
        <stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset=".42" stop-color="#fff" stop-opacity=".07"/><stop offset="1" stop-color="#000" stop-opacity=".32"/>
      </radialGradient>
      <radialGradient id="knobGrad" cx=".4" cy=".35" r=".8"><stop offset="0" stop-color="#3a3d42"/><stop offset="1" stop-color="#111214"/></radialGradient>
      <linearGradient id="screenGlass" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".07"/><stop offset=".35" stop-color="#fff" stop-opacity="0"/></linearGradient>
      <filter id="halo" x="-1" y="-1" width="3" height="3"><feGaussianBlur stdDeviation="9"/></filter>
      <filter id="ledGlow" x="-2" y="-2" width="5" height="5"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <filter id="cien" x="-.1" y="-.1" width="1.2" height="1.3"><feDropShadow dx="0" dy="14" stdDeviation="16" flood-color="#000" flood-opacity=".65"/></filter>
      <path id="uchwyt" d="${LEWY_UCHWYT}"/>
    </defs>
    <g id="kBody">
      <g filter="url(#cien)">
        <rect class="k-plate" x="278" y="46" width="649" height="556" rx="44"/>
        <use href="#uchwyt" class="k-grip"/>
        <use href="#uchwyt" class="k-grip" transform="matrix(-1 0 0 1 1205 0)"/>
      </g>
      <rect class="k-plate-shine" x="278" y="46" width="649" height="556" rx="44"/>
      <use href="#uchwyt" class="k-grip-shade"/>
      <use href="#uchwyt" class="k-grip-shade" transform="matrix(-1 0 0 1 1205 0)"/>
      <rect class="k-pod" x="288" y="326" width="84" height="256" rx="22"/>
      <rect class="k-pod" x="833" y="326" width="84" height="256" rx="22"/>
      <rect class="k-bar" x="356" y="80" width="493" height="68" rx="18"/>
      ${sruba(381, 114, 10)}${sruba(824, 114, 10)}
      <g id="wLeds"></g>
      ${sruby}
    </g>
    <g id="kScreen">
      <rect class="k-screen-frame" x="456" y="184" width="293" height="212" rx="14"/>
      <rect class="k-screen" x="466" y="194" width="273" height="166" rx="4"/>
      <text class="scr-l" x="474" y="214" style="font-size:13px;fill:#fff">KGT</text>
      <rect x="505" y="203" width="226" height="14" fill="#262626"/>
      <rect id="scrBar" x="505" y="203" width="0" height="14" fill="#f2c014"/>
      <rect class="scr-box" x="472" y="224" width="66" height="30"/><text class="scr-l" x="476" y="233">PORT</text><text class="scr-v" id="scrPort" x="505" y="249">—</text>
      <rect class="scr-box" x="472" y="258" width="66" height="30"/><text class="scr-l" x="476" y="267">FIRMWARE</text><text class="scr-v" id="scrFw" x="505" y="283">—</text>
      <rect class="scr-box big" x="543" y="224" width="80" height="64"/><text class="scr-l" x="548" y="233">PRZYCISK</text><text class="scr-big" id="scrBig" x="583" y="266">–</text>
      <rect class="scr-box" x="628" y="224" width="105" height="30"/><text class="scr-l" x="632" y="233">SPRAWDZONE</text><text class="scr-v" id="scrOk" x="680" y="249">0/12</text>
      <rect class="scr-box" x="628" y="258" width="105" height="30"/><text class="scr-l" x="632" y="267">PIN</text><text class="scr-v" id="scrPin" x="680" y="283">—</text>
      <rect class="scr-box" x="472" y="293" width="62" height="32"/><text class="scr-l" x="476" y="302">DIODY</text><text class="scr-v" id="scrLed" x="503" y="319">—</text>
      <rect class="scr-box" x="537" y="293" width="62" height="32"/><text class="scr-l" x="541" y="302">PRZYCISKI</text><text class="scr-v" id="scrN" x="568" y="319">12</text>
      <rect class="scr-box" x="602" y="293" width="62" height="32"/><text class="scr-l" x="606" y="302">CZAS</text><text class="scr-v" id="scrTime" x="633" y="319">—</text>
      <rect class="scr-box" x="667" y="293" width="66" height="32"/><text class="scr-l" x="671" y="302">STAN</text><text class="scr-v" id="scrState" x="700" y="319">—</text>
      <text class="scr-msg" id="scrMsg" x="602.5" y="346">SZUKAM KIEROWNICY…</text>
      <rect x="466" y="194" width="273" height="166" rx="4" fill="url(#screenGlass)" pointer-events="none"/>
      <text class="k-logo" x="602.5" y="383">KIEROWNICA <tspan>GT</tspan></text>
    </g>
    <g id="kSpots">${miejsca}</g>`;
  svg._ledN = -1;
  renderKolo();
}

function malujKolo(hex) {
  const g = document.getElementById('wLeds');
  if (!g) return;
  const n = hex.length / 6;
  const svg = $('#wheel');
  if (svg._ledN !== n) {
    const krok = 412 / n;
    const r = Math.max(2.2, Math.min(9, krok * 0.34));
    let html = '';
    for (let i = 0; i < n; i++) html += `<circle class="w-led" cx="${(397 + krok * (i + 0.5)).toFixed(2)}" cy="114" r="${r.toFixed(2)}"/>`;
    g.innerHTML = html;
    g._leds = [...g.children];
    svg._ledN = n;
  }
  g._leds.forEach((c, i) => {
    const kol = hex.substr(i * 6, 6);
    if (c._c === kol) return;
    c._c = kol;
    if (kol === '000000') { c.setAttribute('fill', '#1a1d21'); c.classList.remove('on'); }
    else { c.setAttribute('fill', '#' + kol); c.classList.add('on'); }
  });
}

function renderKolo() {
  const svg = $('#wheel');
  if (!svg.querySelector('#kSpots')) return;
  svg.classList.toggle('przypisywanie', S.przyp.wl);
  MIEJSCA.forEach((m) => {
    const g = svg.querySelector(`.ws[data-id="${m.id}"]`);
    const n = S.uklad[m.id];
    const b = n ? S.btns[n - 1] : null;
    const stan = b ? (b.wc && b.podejrz ? 'warn' : b.wc ? 'press' : '') : '';
    g.classList.toggle('press', stan === 'press');
    g.classList.toggle('warn', stan === 'warn');
    g.classList.toggle('ok', !!(b && b.ok));
    g.classList.toggle('pusty', !n);
    g.classList.toggle('wybrane', S.przyp.wl && S.przyp.miejsce === m.id);
    g.querySelector('.ws-num').textContent = n || '';
    g.querySelector('title').textContent = n
      ? `Przycisk ${n} – ${m.nazwa}${b ? ` · pin ${b.pin} · wciśnięć: ${b.licz}` : ''}`
      : `${m.nazwa[0].toUpperCase() + m.nazwa.slice(1)} – bez przypisanego przycisku`;
  });
  renderEkran();
}

function ustawTekst(id, t) { const el = document.getElementById(id); if (el && el.textContent !== t) el.textContent = t; }

function renderEkran() {
  if (!document.getElementById('scrBar')) return;
  const st = S.status;
  const pol = st && st.stan === 'polaczono';
  const info = pol ? st.info : null;
  const n = S.btns.length;
  const ok = S.btns.filter((b) => b.ok).length;
  const bar = document.getElementById('scrBar');
  bar.setAttribute('width', String(n ? (226 * ok) / n : 0));
  bar.setAttribute('fill', n && ok === n ? '#22c55e' : '#f2c014');
  ustawTekst('scrPort', pol ? String(st.port).replace(/^\/dev\//, '') : '—');
  ustawTekst('scrFw', info ? info.wersja : '—');
  ustawTekst('scrOk', `${ok}/${n}`);
  ustawTekst('scrN', String(n));
  ustawTekst('scrLed', info ? (info.max_diod ? String(S.u ? S.u.liczba_diod : '—') : 'BRAK') : '—');
  const o = S.ostatni;
  ustawTekst('scrBig', o ? String(o.n) : '–');
  ustawTekst('scrPin', o && o.pin && o.pin !== '?' ? o.pin : '—');
  ustawTekst('scrTime', o && o.czas != null ? `${o.czas.toFixed(2).replace('.', ',')}s` : '—');
  ustawTekst('scrState', o ? (o.wl ? 'WCIŚN.' : 'PUSZCZ.') : '—');
  let msg;
  if (!pol) msg = (KROTKI_STATUS[st ? st.stan : 'szukam'] || 'Brak połączenia').toUpperCase();
  else if (S.przyp.wl) msg = S.przyp.miejsce ? 'PRZYPISYWANIE: WCIŚNIJ PRZYCISK' : 'PRZYPISYWANIE: WYBIERZ MIEJSCE';
  else if (n && ok === n) msg = 'WSZYSTKIE PRZYCISKI DZIAŁAJĄ ✓';
  else msg = `WCIŚNIJ KOLEJNY PRZYCISK · ZOSTAŁO ${n - ok}`;
  ustawTekst('scrMsg', msg);
  const big = document.getElementById('scrBig');
  big.classList.toggle('on', !!(o && o.wl));
}

function przygotujPrzyciski(n, zachowaj) {
  const stare = S.btns;
  const takie = zachowaj && stare.length === n;
  S.nBtn = n;
  S.btns = Array.from({ length: n }, (_, i) => {
    const b = takie ? stare[i] : null;
    return { n: i + 1, pin: S.piny[i + 1] || (b && b.pin) || '?', wc: false, licz: b ? b.licz : 0, ok: b ? b.ok : false, podejrz: false, od: 0 };
  });
  if (!$('#wheel #kSpots')) budujKolo();
  budujListe();
  renderPrzyciski();
}

function budujListe() {
  $('#btnList').innerHTML = S.btns.map((b) => `
    <div class="bl-row" data-n="${b.n}">
      <span class="bl-num">${b.n}</span>
      <span class="bl-info"><span class="bl-pin"></span><small class="bl-loc"></small></span>
      <span class="chip"></span><span class="bl-count"></span>
    </div>`).join('');
  $('#ringTotal').textContent = S.nBtn;
}

function renderWiersz(b) {
  const stan = b.wc && b.podejrz ? 'warn' : b.wc ? 'press' : b.ok ? 'ok' : '';
  const row = $(`#btnList .bl-row[data-n="${b.n}"]`);
  if (!row) return;
  row.className = `bl-row ${stan}${b.ok ? ' ok' : ''}`;
  row.querySelector('.bl-pin').textContent = b.pin;
  const m = miejsceNumeru(b.n);
  const loc = row.querySelector('.bl-loc');
  loc.textContent = m ? m.nazwa : 'brak miejsca na rysunku';
  loc.classList.toggle('brak', !m);
  const chip = row.querySelector('.chip');
  chip.className = 'chip ' + stan;
  chip.textContent = stan === 'warn' ? 'od startu?' : stan === 'press' ? 'wciśnięty' : b.ok ? '✓ działa' : 'nie sprawdzony';
  row.querySelector('.bl-count').textContent = b.licz ? `×${b.licz}` : '';
}

function renderPostep() {
  const n = S.btns.length;
  const ok = S.btns.filter((b) => b.ok).length;
  $('#ringCount').textContent = ok;
  const obwod = 2 * Math.PI * 27;
  $('#ringFg').style.strokeDashoffset = String(obwod * (1 - (n ? ok / n : 0)));
  $('#allOk').hidden = !(n && ok === n);
}

function renderPrzyciski() { S.btns.forEach(renderWiersz); renderKolo(); renderPostep(); }

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
  if (b.wc === wl) { renderWiersz(b); return; }
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
      S.ostatni = { n, pin: b.pin, wl: true, czas: null };
      wpis(`<span class="l-on"><span class="lnum">Przycisk ${n}</span></span> wciśnięty ${pinTxt}${nowy ? ' <span class="chip ok">nowy ✓</span>' : ''}`);
      if (S.przyp.wl && S.przyp.miejsce) przypisz(S.przyp.miejsce, n);
      else if (!miejsceNumeru(n) && !S.ostrzezone.has(n)) {
        S.ostrzezone.add(n);
        toast(`Przycisk ${n} nie ma miejsca na rysunku – kliknij „Przypisz przyciski”.`, 'info', 4500);
      }
    }
  } else if (b.podejrz) {
    b.podejrz = false;
    wpis(`<span class="lnum">Przycisk ${n}</span> puszczony – wygląda dobrze. ${pinTxt}`);
  } else {
    const czas = (performance.now() - b.od) / 1000;
    if (S.ostatni && S.ostatni.n === n) Object.assign(S.ostatni, { wl: false, czas });
    wpis(`<span class="lnum">Przycisk ${n}</span> puszczony ${pinTxt}<span class="ldur">${czas.toFixed(2).replace('.', ',')} s</span>`);
  }
  renderWiersz(b);
  renderKolo();
  renderPostep();
}

function stanPrzyciskow(bity) {
  [...bity].forEach((ch, i) => { if (ch === '0' || ch === '1') zmianaPrzycisku(i + 1, ch === '1', '', true); });
  S.pierwszyStan = false;
}

/* ------------------------------------------------- przypisywanie miejsc */
function renderPrzypisywanie() {
  const p = S.przyp;
  $('#assignBar').hidden = !p.wl;
  const btn = $('#btnAssign');
  btn.setAttribute('aria-pressed', String(p.wl));
  btn.classList.toggle('primary', p.wl);
  const pol = S.status && S.status.stan === 'polaczono';
  const m = p.miejsce ? MIEJSCA.find((x) => x.id === p.miejsce) : null;
  const txt = $('#abText');
  if (!pol) txt.innerHTML = 'Podłącz kierownicę – przypisywanie działa po wciśnięciu prawdziwego przycisku.';
  else if (m) txt.innerHTML = `Wciśnij na kierownicy przycisk <b>${esc(m.nazwa)}</b>${S.uklad[m.id] ? ` (teraz: ${S.uklad[m.id]})` : ''}. Możesz też kliknąć inne miejsce na rysunku.`;
  else txt.innerHTML = 'Kliknij miejsce na rysunku, a potem wciśnij ten przycisk na kierownicy.';
  $('#abClear').disabled = !m || !S.uklad[m.id];
  renderKolo();
  S.btns.forEach(renderWiersz);
}

function zapiszUklad() { return api('/api/uklad', { miejsca: S.uklad }); }

async function przypisz(id, n) {
  Object.keys(S.uklad).forEach((k) => { if (S.uklad[k] === n) delete S.uklad[k]; });
  S.uklad[id] = n;
  S.ostrzezone.delete(n);
  const m = MIEJSCA.find((x) => x.id === id);
  toast(`Przycisk ${n} → ${m.nazwa}`, 'ok', 2200);
  const i = MIEJSCA.findIndex((x) => x.id === id);
  S.przyp.miejsce = i >= 0 && i < MIEJSCA.length - 1 ? MIEJSCA[i + 1].id : null;
  renderPrzypisywanie();
  await zapiszUklad();
}

function przelaczPrzypisywanie(wl) {
  S.przyp.wl = wl;
  S.przyp.miejsce = wl ? MIEJSCA[0].id : null;
  renderPrzypisywanie();
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
    } else if (st.opcja === 'spotter') {
      opcja = `<div class="st-row stack"><span>Diody z każdej strony</span><span class="mini-stepper">
        <span class="stepper"><button class="step" data-step="-1" aria-label="Mniej">−</button><input type="number" data-bind="${p}.diody" data-type="int" min="1" max="${o.max_diod / 2}" aria-label="Diody spottera"><button class="step" data-step="1" aria-label="Więcej">+</button></span></span></div>
        <label class="st-swap" title="Włącz, jeśli w grze auto z lewej zapala diody po prawej stronie"><span class="switch"><input type="checkbox" data-bind="${p}.zamien_strony" data-type="bool" aria-label="Zamień strony spottera"><span class="slider"></span></span><span>Zamień lewą i prawą stronę</span></label>`;
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
  renderEkran();
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
    if (m.gra) renderGra(m.gra);
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
  if (S.gra) renderGra(S.gra);
  $('#simRpm').disabled = !rpmAktywne;
  auto.disabled = !rpmAktywne;
}

function renderGra(g) {
  S.gra = g;
  const box = $('#gameInfo');
  const stan = g.aktywna ? 'jazda' : g.gra ? (/format/i.test(g.opis) ? 'blad' : 'menu') : 'brak';
  if (box.dataset.stan !== stan) box.dataset.stan = stan;
  ustawTekst('giTitle', g.gra ? g.nazwa : 'Nie wykryto gry');
  ustawTekst('giText', g.gra ? g.opis : `${g.opis} Uruchom grę i wyjedź na tor – diody pokażą obroty.`);
  const zJazdy = g.aktywna;
  ustawTekst('giRpm', zJazdy ? `${g.rpm.toLocaleString('pl-PL')} / ${g.max_rpm ? g.max_rpm.toLocaleString('pl-PL') : '?'}` : '—');
  ustawTekst('giGear', zJazdy && g.bieg != null ? ({ '-1': 'R', 0: 'N' }[g.bieg] || String(g.bieg)) : '—');
  const pit = $('#giPit');
  ustawTekst('giPit', zJazdy ? (g.pit_limiter ? 'TAK' : 'nie') : '—');
  pit.className = zJazdy && g.pit_limiter ? 'tak' : '';
  const fl = $('#giFlag');
  ustawTekst('giFlag', zJazdy ? ({ zolta: 'żółta', niebieska: 'niebieska' }[g.flaga] || 'brak') : '—');
  fl.className = zJazdy && g.flaga ? g.flaga : '';
  const sp = $('#giSpot');
  let spTxt = '—', spKl = '';
  if (zJazdy && !g.spotter) { spTxt = 'brak w tej grze'; spKl = 'brak'; }
  else if (zJazdy) {
    let l = g.auto_lewo, p = g.auto_prawo;
    if (S.u && S.u.stany.spotter.zamien_strony) [l, p] = [p, l];
    spTxt = l && p ? '◀ obie ▶' : l ? '◀ z lewej' : p ? 'z prawej ▶' : 'wolne';
    spKl = l || p ? 'spot' : '';
  }
  ustawTekst('giSpot', spTxt);
  sp.className = spKl;
  $('#giUse').hidden = !(g.aktywna && S.sim.stan !== 'gra');
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

/* ============================================================= USTAWIENIA */
function renderProgram() {
  const p = S.program;
  if (!p) return;
  const u = p.ustawienia;
  const auto = $('#pAutostart');
  auto.checked = p.autostart;
  auto.disabled = !p.autostart_dostepny;
  $('#pBrakAutostartu').hidden = p.autostart_dostepny;
  $('#pBrakTacki').hidden = p.tacka || !p.autostart_dostepny;
  $$('input[data-prog]').forEach((el) => { el.checked = !!u[el.dataset.prog]; });
  const ks = $('#pKontroler');
  if (!ks.children.length) {
    const krotko = { auto: 'Automatycznie', vjoy: 'vJoy', xbox: 'Pad Xbox 360', brak: 'Wyłączony' };
    ks.innerHTML = Object.keys(p.kontrolery).map((k) => `<button data-v="${k}" title="${esc(p.kontrolery[k])}">${krotko[k] || esc(k)}</button>`).join('');
    $('#pVjoy').innerHTML = Array.from({ length: 16 }, (_, i) => `<option value="${i + 1}">${i + 1}</option>`).join('');
  }
  $$('.seg[data-prog]').forEach((seg) => {
    $$('button[data-v]', seg).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === u[seg.dataset.prog])));
  });
  $('#pVjoy').value = String(u.vjoy_id);
  $('#pVjoyRow').hidden = !(u.kontroler === 'auto' || u.kontroler === 'vjoy');
  const ksStan = $('#pKontrolerStan');
  if (p.kontroler_blad) {
    ksStan.className = 'note warn';
    ksStan.innerHTML = `<svg><use href="#i-warn"/></svg><span>${esc(p.kontroler_blad)}</span>`;
  } else {
    ksStan.className = 'note' + (u.kontroler === 'brak' ? '' : ' ok');
    ksStan.innerHTML = `<svg><use href="#i-${u.kontroler === 'brak' ? 'eye' : 'check'}"/></svg><span>${u.kontroler === 'brak'
      ? 'Przyciski nie są przekazywane do gier (działa tylko test w konfiguratorze).'
      : `Aktywny: ${esc(p.kontroler_opis)}.`}</span>`;
  }
  ustawTekst('pWersja', p.wersja);
  ustawTekst('pFolder', p.folder);
  const fw = S.status && S.status.stan === 'polaczono' && S.status.info ? S.status.info.wersja : 'kierownica niepodłączona';
  ustawTekst('pFirmware', fw);
}

async function zmienProgram(zmiany, komunikat) {
  const d = await api('/api/program', { zmiany });
  if (d) {
    S.program = d.program;
    if (komunikat) toast(komunikat, 'ok', 2600);
  }
  renderProgram();    // przy błędzie cofa przełącznik do faktycznego stanu
}

/* ===================================================== AKTUALIZACJA FIRMWARE */
const wersjaT = (v) => (String(v || '').match(/\d+/g) || []).slice(0, 4).map(Number);
function nowszaWersja(a, b) {
  const x = wersjaT(a), y = wersjaT(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (x[i] || 0) - (y[i] || 0);
    if (d) return d > 0;
  }
  return false;
}
const FW_TRWA = ['pobieranie', 'wgrywanie', 'restart'];

function renderFw() {
  const fw = S.fw || { stan: 'bezczynny' };
  const pol = S.status && S.status.stan === 'polaczono' && S.status.info;
  const obecna = pol ? S.status.info.wersja : null;
  const naj = S.fwNajnowsza;
  const trwa = FW_TRWA.includes(fw.stan);
  const jestNowsza = !!(pol && naj && nowszaWersja(naj.wersja, obecna));

  $('#fwBanner').hidden = !jestNowsza || trwa || fw.stan === 'gotowe';
  ustawTekst('fwbNew', naj ? naj.wersja : '');
  ustawTekst('fwbOld', obecna || '');
  $('#fwBadge').hidden = !jestNowsza;
  $('#connPill').classList.toggle('fw-new', jestNowsza);

  ustawTekst('fwCurrent', obecna || (trwa ? '…' : '—'));
  const latest = $('#fwLatest');
  ustawTekst('fwLatest', naj ? naj.wersja : '—');
  latest.className = jestNowsza ? 'nowa' : '';
  ustawTekst('fwLatestNote', S.fwSprawdzam ? 'sprawdzam…' : S.fwBlad ? S.fwBlad
    : naj ? `wydana ${naj.data}` : 'brak wydań na GitHubie');

  const prog = $('#fwProgress');
  prog.hidden = fw.stan === 'bezczynny';
  prog.className = 'fw-progress ' + fw.stan;
  ustawTekst('fwStage', fw.tekst || '');
  ustawTekst('fwPct', trwa && fw.procent != null ? `${fw.procent}%` : '');
  $('#fwBar').style.width = `${fw.stan === 'gotowe' || fw.stan === 'blad' ? 100 : fw.procent || 0}%`;
  const logEl = $('#fwLog');
  const logTxt = (fw.log || []).join('\n');
  if (logEl.textContent !== logTxt) { logEl.textContent = logTxt; logEl.scrollTop = logEl.scrollHeight; }
  if (fw.stan === 'blad') $('.fw-details').open = true;

  const go = $('#fwGo');
  go.disabled = trwa || !pol || !naj;
  ustawTekst('fwGoText', trwa ? 'Trwa aktualizacja…' : !naj ? 'Aktualizuj' : jestNowsza ? `Aktualizuj do ${naj.wersja}` : `Wgraj ponownie ${naj.wersja}`);
  go.className = 'btn ' + (jestNowsza ? 'primary' : '');
  go.title = !pol ? 'Najpierw podłącz kierownicę' : '';
  $('#fwFromFile').disabled = trwa || !pol;
  $('#fwCheck').disabled = trwa || S.fwSprawdzam;
  $('#fwClose').disabled = trwa;
}

async function sprawdzFw() {
  S.fwSprawdzam = true; renderFw();
  const d = await api('/api/fw/sprawdz');
  S.fwSprawdzam = false;
  if (d) { S.fwNajnowsza = d.najnowsza; S.fwBlad = d.blad; }
  renderFw();
}

function otworzFw() {
  zamknijPopover();
  renderFw();
  $('#dlgFw').showModal();
  if (!S.fwNajnowsza && !S.fwSprawdzam) sprawdzFw();
}

async function wgrajPlikFw(plik) {
  if (!plik) return;
  if (plik.size > 8 * 1024 * 1024) { toast('Plik jest za duży jak na firmware.', 'err'); return; }
  try {
    const r = await fetch('/api/fw/plik', {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream', 'X-Nazwa-Pliku': encodeURIComponent(plik.name) },
      body: plik,
    });
    const d = await r.json().catch(() => ({ ok: false, blad: `Błąd ${r.status}` }));
    if (!d.ok) toast(d.blad || 'Nie udało się wgrać pliku.', 'err', 6000);
  } catch {
    toast('Brak połączenia z programem konfiguratora.', 'err');
  }
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
      S.uklad = m.uklad ? { ...m.uklad } : { ...UKLAD_DOMYSLNY };
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
      S.fw = m.fw; S.fwNajnowsza = m.fw_najnowsza; S.fwBlad = m.fw_blad;
      S.program = m.program;
      renderProgram();
      renderFw();
      if (m.blad) toast(`${m.blad} Wczytano ustawienia domyślne.`, 'err', 7000);
      break;
    }
    case 'status': ustawStatus(m.status); break;
    case 'przycisk': zmianaPrzycisku(m.n, m.wl, m.pin, false); break;
    case 'stan': stanPrzyciskow(m.bity); break;
    case 'piny':
      S.piny = m.piny;
      S.btns.forEach((b) => { if (m.piny[b.n]) { b.pin = m.piny[b.n]; renderWiersz(b); } });
      renderKolo();
      break;
    case 'klatka': naKlatke(m); break;
    case 'fw': {
      const bylo = S.fw ? S.fw.stan : null;
      S.fw = m.fw;
      renderFw();
      if (m.fw.stan !== bylo && m.fw.stan === 'gotowe') toast(m.fw.tekst, 'ok', 6000);
      if (m.fw.stan !== bylo && m.fw.stan === 'blad') toast('Aktualizacja nie powiodła się.', 'err', 5000);
      break;
    }
    case 'program': S.program = m.program; renderProgram(); break;
    case 'fw_najnowsza': S.fwNajnowsza = m.najnowsza; S.fwBlad = m.blad; renderFw(); break;
    case 'uklad':
      S.uklad = m.uklad ? { ...m.uklad } : { ...UKLAD_DOMYSLNY };
      renderPrzypisywanie();
      break;
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
  // ustawienia programu
  $('#pAutostart').addEventListener('change', (e) => zmienProgram({ autostart: e.target.checked },
    e.target.checked ? 'Program będzie startował razem z Windows (w tle, przy zegarze).' : 'Wyłączono autostart.'));
  $$('input[data-prog]').forEach((el) => el.addEventListener('change', () => zmienProgram({ [el.dataset.prog]: el.checked })));
  $('#tab-ustawienia').addEventListener('click', (e) => {
    const b = e.target.closest('.seg[data-prog] button[data-v]');
    if (!b || !S.program) return;
    const klucz = b.closest('.seg').dataset.prog;
    if (S.program.ustawienia[klucz] !== b.dataset.v) zmienProgram({ [klucz]: b.dataset.v });
  });
  $('#pVjoy').addEventListener('change', (e) => zmienProgram({ vjoy_id: +e.target.value }));
  $('#pFolderBtn').addEventListener('click', () => api('/api/folder'));
  $('#pFwBtn').addEventListener('click', otworzFw);
  $('#pZakoncz').addEventListener('click', async () => {
    if (!(await potwierdz('Zakończyć program?', 'Kierownica przestanie działać w grach (przyciski i diody) do następnego uruchomienia.', 'Zakończ', true))) return;
    if (await api('/api/zakoncz')) {
      S.zakonczony = true;
      $('#offline h3').textContent = 'Program zakończony';
      $('#offline p').innerHTML = 'Możesz zamknąć to okno. Aby uruchomić ponownie, kliknij <b>Konfigurator_GT.bat</b>.';
    }
  });

  // aktualizacja firmware
  $('#btnFw').addEventListener('click', otworzFw);
  $('#fwbOpen').addEventListener('click', otworzFw);
  $('#fwClose').addEventListener('click', () => $('#dlgFw').close());
  $('#dlgFw').addEventListener('cancel', (e) => { if (S.fw && FW_TRWA.includes(S.fw.stan)) e.preventDefault(); });
  $('#fwCheck').addEventListener('click', sprawdzFw);
  $('#fwGo').addEventListener('click', async () => {
    const naj = S.fwNajnowsza;
    if (!naj) return;
    const obecna = S.status && S.status.info ? S.status.info.wersja : '?';
    if (!nowszaWersja(naj.wersja, obecna)
        && !(await potwierdz('Wgrać ponownie?', `W kierownicy jest już wersja ${obecna}. Wgrać ją jeszcze raz?`, 'Wgraj'))) return;
    await api('/api/fw/aktualizuj');
  });
  $('#fwFromFile').addEventListener('click', () => $('#fwFile').click());
  $('#fwFile').addEventListener('change', (e) => { const f = e.target.files[0]; e.target.value = ''; wgrajPlikFw(f); });

  // przypisywanie przycisków do miejsc na rysunku
  $('#btnAssign').addEventListener('click', () => przelaczPrzypisywanie(!S.przyp.wl));
  $('#abDone').addEventListener('click', () => { przelaczPrzypisywanie(false); toast('Zapisano układ przycisków.'); });
  $('#abClear').addEventListener('click', async () => {
    const id = S.przyp.miejsce;
    if (!id || !S.uklad[id]) return;
    delete S.uklad[id];
    renderPrzypisywanie();
    await zapiszUklad();
  });
  $('#abReset').addEventListener('click', async () => {
    if (await potwierdz('Przywrócić układ domyślny?', 'Przypisania przycisków do miejsc na rysunku wrócą do ustawień początkowych.', 'Przywróć')) {
      if (await api('/api/uklad', { domyslny: true })) toast('Przywrócono domyślny układ przycisków.', 'info');
    }
  });
  $('#wheel').addEventListener('click', (e) => {
    const g = e.target.closest('.ws');
    if (!g) return;
    if (!S.przyp.wl) return;
    S.przyp.miejsce = g.dataset.id;
    renderPrzypisywanie();
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
  $('#giUse').addEventListener('click', () => { S.sim.stan = 'gra'; renderSim(); wyslijSim({ stan: 'gra' }); });
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
    if (e.key === 'Escape') {
      zamknijPopover();
      if (S.przyp.wl && !document.querySelector('dialog[open]')) przelaczPrzypisywanie(false);
    }
  });

  window.addEventListener('beforeunload', (e) => {
    if (S.niezapisane || (S.fw && FW_TRWA.includes(S.fw.stan))) { e.preventDefault(); e.returnValue = ''; }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && klatka) naKlatke(klatka); });
}

/* ================================================================ START */
(function start() {
  let tab = 'przyciski';
  try { tab = localStorage.getItem('kgt-tab') || tab; } catch { /* bez pamięci */ }
  pokazZakladke(['ledy', 'ustawienia'].includes(tab) ? tab : 'przyciski');
  przygotujPrzyciski(12, false);
  podepnij();
  polaczZdarzenia();
})();
