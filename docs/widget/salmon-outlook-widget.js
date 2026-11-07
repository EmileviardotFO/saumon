// Salmon Outlook — widget d'écran d'accueil pour Scriptable (iPhone / iPad)
//
// Installation : dans Scriptable, "+" puis coller ce script, le nommer "Salmon Outlook".
// Sur l'écran d'accueil : appui long > Modifier > "+" > Scriptable, choisir la taille,
// puis appui long sur le widget > Modifier le widget > Script : "Salmon Outlook".
//
// Choisir ce qui s'affiche : champ "Paramètre" du widget (appui long > Modifier le widget).
// Plusieurs blocs séparés par "+" ; filtre de bassin après ":" ; exemples :
//   news                  dernières actualités, tous bassins (par défaut)
//   news:NO,CL            dernières actualités Norvège et Chili
//   news:FEED             aliments et matières premières
//   top                   "This week in five" (les sujets à plus fort impact de la semaine)
//   chile                 estimation de la récolte chilienne (wellboats)
//   top+news:CL           les deux, l'un sous l'autre
// Codes de bassin : NO CL GB FO IS CA AU IE NZ US global FEED
//
// Un appui sur une ligne ouvre l'article (la première source gratuite) ; un appui ailleurs ouvre le dashboard.

const BASE = 'https://emileviardotfo.github.io/saumon/';
const DASH = BASE + 'docs/production.html';
const C = { bg: new Color('#0b1620'), card: new Color('#102231'), ink: new Color('#e7eef2'), muted: new Color('#8fa4b0'),
            accent: new Color('#4fc3f7'), up: new Color('#81c784'), down: new Color('#ffb74d') };
const BASIN = { NO: 'Norway', CL: 'Chile', GB: 'Scotland', FO: 'Faroes', IS: 'Iceland', CA: 'Canada', AU: 'Australia',
                IE: 'Ireland', NZ: 'New Zealand', US: 'USA', global: 'Global', FEED: 'Feed' };
const ACCESS = { free: 0, '?': 1, metered: 2, pay: 3 };

async function getJSON(name) {
  const fm = FileManager.local(), path = fm.joinPath(fm.cacheDirectory(), 'so-' + name);
  try {
    const r = new Request(BASE + 'data/' + name); r.timeoutInterval = 20;
    const j = await r.loadJSON(); fm.writeString(path, JSON.stringify(j)); return j;
  } catch (e) {   // hors ligne : derniere version gardee en cache
    return fm.fileExists(path) ? JSON.parse(fm.readString(path)) : null;
  }
}

function parse(param) {
  const p = (param || 'news').trim() || 'news';
  return p.split('+').map(x => { const [k, f] = x.trim().split(':'); return { k: k.toLowerCase(), f: f ? f.split(',').map(s => s.trim()) : null }; });
}

function day(d) {   // "4 Nov"
  if (!d) return '';
  const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return (+d.slice(8, 10)) + ' ' + m[+d.slice(5, 7) - 1];
}

function bestLink(s) {
  const a = (s.arts || []).slice().sort((x, y) => (ACCESS[x.access] ?? 1) - (ACCESS[y.access] ?? 1) || (x.date < y.date ? 1 : -1))[0];
  return a ? a.url : DASH;
}

function header(w, txt, sub) {
  const h = w.addStack(); h.centerAlignContent();
  const t = h.addText(txt.toUpperCase()); t.font = Font.boldSystemFont(11); t.textColor = C.accent;
  h.addSpacer();
  if (sub) { const s = h.addText(sub); s.font = Font.systemFont(10); s.textColor = C.muted; }
  w.addSpacer(4);
}

function storyRow(w, s, small) {
  const row = w.addStack(); row.layoutVertically(); row.url = bestLink(s);
  const meta = row.addText(`${BASIN[s.basin] || s.basin}${s.who && s.who !== 'Sector' ? ' · ' + s.who : ''} · ${day(s.last)}`);
  meta.font = Font.mediumSystemFont(9.5); meta.textColor = C.muted; meta.lineLimit = 1;
  const t = row.addText(s.title || ''); t.font = Font.semiboldSystemFont(small ? 12 : 13); t.textColor = C.ink; t.lineLimit = small ? 3 : 2;
  w.addSpacer(small ? 4 : 6);
}

async function build() {
  const fam = config.widgetFamily || 'large';
  const room = { small: 2, medium: 3, large: 7, extraLarge: 9 }[fam] || 7, small = fam === 'small';
  const blocks = parse(args.widgetParameter);
  const w = new ListWidget(); w.backgroundColor = C.bg; w.url = DASH; w.setPadding(12, 14, 12, 14);
  w.refreshAfterDate = new Date(Date.now() + 60 * 60 * 1000);   // iOS rafraichit au plus a peu pres toutes les heures
  let left = room;
  const ST = blocks.some(b => b.k === 'news' || b.k === 'top') ? await getJSON('stories.json') : null;
  for (const b of blocks) {
    if (left <= 0) break;
    if ((b.k === 'news' || b.k === 'top') && ST) {
      let S = ST.stories || [];
      if (b.f) S = S.filter(s => b.f.includes(s.basin));
      if (b.k === 'top') {
        S = (ST.top || []).map(t => (ST.stories || [])[t.i]).filter(Boolean);
        header(w, 'This week in five', '');
      } else {
        S = S.slice().sort((x, y) => (x.last < y.last ? 1 : x.last > y.last ? -1 : 0) || (+x.priority || 9) - (+y.priority || 9));
        header(w, b.f ? b.f.map(f => BASIN[f] || f).join(' · ') : 'Latest salmon news', small ? '' : 'to ' + day((ST.meta || {}).news_generated));
      }
      const n = Math.min(left, b.k === 'top' ? Math.min(5, left) : left, S.length);
      S.slice(0, n).forEach(s => storyRow(w, s, small));
      if (!n) { const t = w.addText('Nothing this week.'); t.font = Font.systemFont(12); t.textColor = C.muted; }
      left -= Math.max(1, n) + 1;
    } else if (b.k === 'chile') {
      const J = await getJSON('chile_wellboats.json');
      header(w, 'Chile · wellboat watch', '');
      if (!J) continue;
      const E = J.ll_estimate || {}, O = J.ll_official || {}, k = Object.keys(E).sort().pop();
      if (k) {
        const ly = (+k.slice(0, 4) - 1) + k.slice(4), d = O[ly] ? Math.round(100 * (E[k] / O[ly] - 1)) : null;
        const t = w.addText(`${day(k + '-01').split(' ')[1]} ${k.slice(0, 4)}: ≈ ${Math.round(E[k] / 1000)} kt`); t.font = Font.boldSystemFont(small ? 18 : 20); t.textColor = C.ink;
        if (d !== null) { const s = w.addText(`${d > 0 ? '+' : ''}${d} % vs a year earlier · Los Lagos plants`); s.font = Font.systemFont(11); s.textColor = d >= 0 ? C.up : C.down; }
      }
      w.addSpacer(6); left -= 1;
    }
  }
  w.addSpacer();
  const f = w.addText('Salmon Outlook · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })); f.font = Font.systemFont(9); f.textColor = C.muted;
  return w;
}

const widget = await build();
if (config.runsInWidget) Script.setWidget(widget); else await widget.presentLarge();
Script.complete();
