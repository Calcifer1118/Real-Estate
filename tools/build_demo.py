"""Builds the Team HML demo (demo/index.html) from a saved copy of the live PHirst site.

Usage: python3 tools/build_demo.py <saved live page.html>
Keeps only the projects whose photos the demo has (Gen Tri Impressions, Editions Batulao), rebrands it for
Team HML, turns off tracking, adds the booking form with time, the auto-cycling calculator, a 3D terrain map
that works offline (demo/tiles), and the hooks the proposal's phone frame uses.
"""
import sys, re, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(sys.argv[1]).read().split('\n')
mlcss = open(os.environ.get('MAPLIBRE_CSS', '/tmp/claude-0/ml/package/dist/maplibre-gl.css')).read()

def idx(pred, start=0):
    for i in range(start, len(src)):
        if pred(src[i]): return i
    raise SystemExit('marker not found')
# projects: keep the first two entries (Gen Tri, Batulao); drop the rest and the shared-turnover table
naic = idx(lambda l: l.strip() == 'id: "naic", slug: "naic",')
assert src[naic-1].strip() == '}, {'
cut_to = idx(lambda l: l.startswith("// Team RDO's own area"), naic)
lines = src[:naic-1] + ['}', '];'] + src[cut_to:]
s = '\n'.join(lines)

def rep(a, b, n=1):
    global s
    c = s.count(a)
    assert c == n, (a[:90], c)
    s = s.replace(a, b)

# document shell: the artifact viewer supplies its own
for t in ['<!doctype html>\n', '<html lang="en">\n', '<head>\n', '</head>\n', '<body>\n', '</body>\n', '</html>']:
    rep(t, '')
s = re.sub(r'<base href="/">\n|<link rel="canonical"[^\n]*\n|<meta (property|name)="(og|twitter):[^\n]*\n', '', s)
rep('<title>PHirst Homes in Cavite & Batangas</title>', '<title>Team HML PHirst Homes</title>\n<meta name="claude:viewport-fit-sides" content="cover">')
rep('.wrap{max-width:1100px;margin:0 auto;padding-inline:20px}', '.wrap{max-width:1100px;margin:0 auto;padding-left:max(20px,env(safe-area-inset-left,0px));padding-right:max(20px,env(safe-area-inset-right,0px))}')

TROPHY = '<svg viewBox="0 0 120 120" aria-hidden="true"><path d="M36 34h-12v6c0 12 7 19 16 21M84 34h12v6c0 12-7 19-16 21" fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round"/><path d="M34 22h52v18c0 19-12 32-26 32S34 59 34 40z" fill="#E0693F"/><rect x="54" y="72" width="12" height="12" fill="#E0693F"/><rect x="40" y="84" width="40" height="9" rx="3" fill="currentColor"/><rect x="32" y="95" width="56" height="10" rx="3" fill="currentColor"/></svg>'
rep('<div class="avatar teammark"><img src="assets/team-rdo-mark.png" alt="Team RDO"></div>', '<div class="avatar">' + TROPHY + '</div>')
rep('<img class="footlogo" src="assets/team-rdo-logo.png" alt="Team RDO" width="104" height="90"><b>Authorized PHirst Park Homes Seller · <span id="footTeam">PHirst Park Homes - Team RDO</span></b>',
    '<span class="footmark">' + TROPHY + '<b>Team HML</b></span><b>Authorized PHirst Park Homes Seller · <span id="footTeam">Team HML</span></b>')
rep('<span><a href="/privacy">Privacy notice</a> · <a href="/data-deletion">Delete my data</a></span>', '<span>Privacy notice · Delete my data</span>')
rep('<p>We use Meta (Facebook) cookies to measure our ads. <a href="/privacy">Privacy notice</a></p>', '<p>We use Meta (Facebook) cookies to measure our ads.</p>')
# no tracking from the demo
rep('<script>window.EVENTS_ENDPOINT="/api/event";window.META_PIXEL_ID="";</script>', '<script>window.EVENTS_ENDPOINT="";window.META_PIXEL_ID="";</script>')
rep('<script src="pages.js"></script>\n', '')
rep('const SELLER = Object.assign({ name:"PHirst Cavite Batangas", team:"PHirst Park Homes - Team RDO",',
    'const SELLER = Object.assign({ name:"Team HML", team:"Team HML · Authorized PHirst Seller",')
rep('<header class="bar">', '<div class="demo"><b>Demo for Team HML</b> · a preview of your site before launch. Prices are from the latest PHirst list.</div>\n<header class="bar">')

# section ids the phone's chapter buttons jump to
rep('''    <section class="block">
      <div class="head rv"><span class="eyebrow">Location</span>''', '''    <section class="block" id="location">
      <div class="head rv"><span class="eyebrow">Location</span>''')
rep('''    <section class="block">
      <div class="head rv"><span class="eyebrow">Turned over with</span>''', '''    <section class="block" id="finished">
      <div class="head rv"><span class="eyebrow">Turned over with</span>''')
rep('''    <section class="block">
      <div class="head rv"><span class="eyebrow">Inside the community</span>''', '''    <section class="block" id="amenities">
      <div class="head rv"><span class="eyebrow">Inside the community</span>''')
rep('''  return `<section class="block">
      <div class="head rv"><span class="eyebrow">Total contract price</span>''', '''  return `<section class="block" id="tcp">
      <div class="head rv"><span class="eyebrow">Total contract price</span>''')
# the booking form lives inside the project's "Come see your future home" card (one booking block, not two)
rep('''    <section class="cta rv">
      <span class="glow"></span>
      <span class="eyebrow" style="color:#F4B08F">Free tripping''', '''    <section class="cta rv" id="book">
      <span class="glow"></span>
      <span class="eyebrow" style="color:#F4B08F">Free tripping''')
rep('<div class="btns"><a class="btn" href="${msg("book",P)}" target="_blank" rel="noopener">Schedule a free tripping ${arrow}</a><a class="btn ghost" href="${msg("ask",P)}" target="_blank" rel="noopener">More questions? Message us</a></div>',
    '<div class="book in-cta">${bookForm(P)}</div>\n      <div class="btns"><a class="btn ghost" href="${msg("ask",P)}" target="_blank" rel="noopener">More questions? Message us</a></div>')
# header and sticky "Book" buttons jump to the form on project pages
rep('$("#msgBtn").href=msg("book",CUR,MODELS[id]?id:null); $("#stickyBtn").href=msg("book",CUR,MODELS[id]?id:null);', 'bookLinks(P, MODELS[id]?id:null);')
# 3D map with bundled terrain
rep('const USE3D = /(^|\\.)workers\\.dev$|^localhost$|^127\\.0\\.0\\.1$/.test(location.hostname);',
    '// Terrain tiles ship with the page (tiles/dem), so the 3D map works anywhere the MapLibre script loads.\nconst USE3D = true;')
rep('    const css=document.createElement("link"); css.rel="stylesheet"; css.href=`https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/${ML_VER}/maplibre-gl.css`; document.head.appendChild(css);\n', '')
a = s.index('function style3d(){'); b = s.index('function map3dHTML(P){')
s = s[:a] + open(os.path.join(ROOT, 'tools', 'map3d_offline.js')).read() + s[b:]
rep('    map.on("load",()=>{\n', '    map.on("load",()=>{\n      addVectors(map,P);\n')
# calculator cycles until tapped; booking form wiring
rep('  wireBody(P.comps[0]);\n', '  wireBody(P.comps[0]);\n  autoCycle();\n')
rep('wireAmen(P); wireSeg(P); wireCalc(P);', 'wireAmen(P); wireSeg(P); wireCalc(P); wireBook();')
rep('$("#sellerName").textContent=SELLER.name;', open(os.path.join(ROOT, 'tools', 'demo_extras.js')).read() + '\n$("#sellerName").textContent=SELLER.name;')
# styles
rep('</style>\n\n<style>\n:root{padding-top', open(os.path.join(ROOT, 'tools', 'demo_extras.css')).read() + '\n/* MapLibre GL 5.6.0 stylesheet (BSD-3-Clause) */\n' + mlcss + '\n</style>\n\n<style>\n:root{padding-top')
open(os.path.join(ROOT, 'demo', 'index.html'), 'w').write(s.strip() + '\n')
print('ok', len(s))
