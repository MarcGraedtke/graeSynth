"""graeSynth-Website erzeugen (statisch, Deutsch + Englisch) -> 050_Marketing/Website/dist

  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" 050_Marketing\\Website\\build_site.py            # alles
  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" 050_Marketing\\Website\\build_site.py --no-images  # nur HTML/Daten

Quellen:
  content/modules.json           Texte je Modul (de/en), von Hand gepflegt
  content/site.json              Seitentexte (de/en)
  assets/                        site.css, site.js (werden nach dist/assets kopiert)
  010_Module/_3D                 zusammengebaute Modelle aus render3d.py (vorher laufen lassen)
  KiCad-Dateien                  Breite (HP), Buchsen, Regler, Schalter

Bilder werden nur neu gerendert, wenn das zusammengebaute Modell neuer ist. dist/data/modules.json enthaelt
alle Daten in einer Datei (fuer den spaeteren Umstieg auf Next.js).
"""
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
MODS = os.path.join(ROOT, "010_Module")
D3 = os.path.join(MODS, "_3D")
TMP = os.path.join(D3, "_tmp")
DIST = os.path.join(HERE, "dist")
CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
LANGS = ("de", "en")
NOINDEX = True        # Vorschau: noch nicht in Suchmaschinen
HP_MM = 5.08
sys.path.insert(0, os.path.join(MODS, "_kicad_tools"))
sys.path.insert(0, HERE)

FAM = {"A": "analog", "P": "passive", "D": "digital"}


def esc(s):
    return html.escape(str(s), quote=True)


def slug(m):
    s = re.sub(r"[^a-z0-9]+", "-", m["name"]["en"].lower()).strip("-")
    return "%s-%s" % (m["id"].lower(), s)


def sort_key(m):
    return ("APD".index(m["id"][0]), int(m["id"][1:]))


# ---------------------------------------------------------------- Fakten aus KiCad
def facts(mods):
    """HP, Bedienteile und Bauformen je Modul aus den KiCad-Dateien; setzt m['_base'] (Name des zusammengebauten Modells)."""
    import pcbnew
    import render3d as r
    groups = {}
    for mod, pcb in r.boards():
        groups.setdefault(mod, []).append(pcb)
    for m in mods:
        allps = groups.get(m["folder"], [])
        ps = [p for p in allps if not r.variant_of(p)]       # Grundausfuehrung; Varianten (z. B. D2-RGB) unten
        ispan = lambda p: os.sep + "PCB_Panel" + os.sep in p
        pan = [p for p in ps if ispan(p)]
        tht = [p for p in ps if os.sep + "PCB_THT" + os.sep in p]
        smd = [p for p in ps if p not in pan and p not in tht]
        # 'default_variant' in modules.json (D2: RGB): diese Ausfuehrung ist das Fertigmodul der Seite,
        # die Grundausfuehrung wird zur Option 'mono'
        dv = m.get("default_variant")
        mono = []
        vps = [p for p in allps if dv and r.variant_of(p) == dv]
        if [p for p in vps if ispan(p)] and [p for p in vps if not ispan(p)]:
            mono, pan, smd = smd, [p for p in vps if ispan(p)], [p for p in vps if not ispan(p)]
        else:
            dv = None
        sel = smd or tht
        f = {"kit": bool(tht), "assembled": bool(smd), "panel": os.path.basename(pan[0])[:-10] if pan else None}
        m["_panel"] = pan[0] if pan else None
        if pan:
            e = pcbnew.LoadBoard(pan[0]).GetBoardEdgesBoundingBox()
            f["hp"] = round(e.GetWidth() / 1e6 / HP_MM)
            f["width_mm"] = round(e.GetWidth() / 1e6, 1)
        cnt = {"jacks": 0, "knobs": 0, "switches": 0}
        best = (-1, None)
        for p in sel:
            fp = r.front_parts(pcbnew.LoadBoard(p))
            if len(fp) > best[0]:
                best = (len(fp), p)
            for e, _, _ in fp:
                k = e[0]
                cnt["jacks" if k.startswith("PJ") else "knobs" if k in ("RD90", "EC11E", "SR2612F") else "switches"] += 1
        f.update(cnt)
        # LEDs: Lage im Frontbild (Anteil an Panelbreite/-hoehe), auf die naechste Panelbohrung gesetzt
        m["leds"], m["_ledrefs"] = [], []
        for p in sel:
            b = pcbnew.LoadBoard(p)
            lf = [fp for fp in b.GetFootprints() if fp.GetFPID().GetLibItemName().wx_str().startswith("LED_")]
            m["_ledrefs"] += [fp.GetReference() for fp in lf]
            if p != best[1] or not pan or not lf:
                continue
            pb = pcbnew.LoadBoard(pan[0])
            holes = r._holes(pb)
            n, dx, dy = r._align(r.front_parts(b), holes)
            e = pb.GetBoardEdgesBoundingBox()
            x0, y0, w, h = e.GetX() / 1e6, e.GetY() / 1e6, e.GetWidth() / 1e6, e.GetHeight() / 1e6
            for fp in lf:
                pads = list(fp.Pads())
                if not pads or n < 2:
                    continue
                x = sum(q.GetPosition().x for q in pads) / len(pads) / 1e6 + dx
                y = sum(q.GetPosition().y for q in pads) / len(pads) / 1e6 + dy
                hx, hy = min(holes, key=lambda q: (q[0] - x) ** 2 + (q[1] - y) ** 2)
                if (hx - x) ** 2 + (hy - y) ** 2 < 2.0 ** 2:
                    q = {"x": round((hx - x0) / w * 100, 2), "y": round((hy - y0) / h * 100, 2),
                         "d": round(3.6 / w * 100, 2)}
                    if fp.GetFPID().GetLibItemName().wx_str().startswith(r.LED5_FP):   # RGB: Farbe wie im Rendering
                        num = re.search(r"(\d+)$", fp.GetReference())
                        q["d"] = round(5.8 / w * 100, 2)
                        q["hue"] = ((int(num.group(1)) - 1) % 8) * 45 if num else 0
                    m["leds"].append(q)
            m["leds"].sort(key=lambda q: (q["y"], q["x"]))
        f["powered"] = not m["id"].startswith("P")
        m["facts"] = f
        m["_base"] = os.path.splitext(os.path.basename(best[1]))[0] + "_komplett" if best[1] else None
        # Bausatz (THT) als zweite Ansicht, wenn es daneben ein Fertigmodul gibt
        # und weitere Ausfuehrungen aus PCB_SMD_V<n>_<Kennung> (eigenes Panel), z. B. 'rgb'
        m["_vars"] = []

        def add_var(key, pcbs):
            vb = max(pcbs, key=lambda p: len(r.front_parts(pcbnew.LoadBoard(p))))
            leds = [fp.GetReference() for p in pcbs for fp in pcbnew.LoadBoard(p).GetFootprints()
                    if fp.GetFPID().GetLibItemName().wx_str().startswith("LED_")]
            m["_vars"].append({"key": key, "base": os.path.splitext(os.path.basename(vb))[0] + "_komplett", "leds": leds})

        if smd and tht:
            add_var("kit", tht)
        if mono:
            add_var("mono", mono)
        for tag in sorted({r.variant_of(p) for p in allps} - {None, dv}):
            vb = [p for p in allps if r.variant_of(p) == tag and os.sep + "PCB_Panel" + os.sep not in p]
            if vb and best[1]:
                add_var(tag.lower(), vb)


# ---------------------------------------------------------------- Bilder
def render(args, out, src):
    r = subprocess.run([CLI, "pcb", "render", *args, "-o", out, src], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0 and os.path.exists(out)


def crop_opaque(png, out, height=None, keep_soft=False):
    """Auf den deckenden Bereich zuschneiden (KiCad zeichnet einen halbtransparenten Schatten dahinter)."""
    from PIL import Image
    im = Image.open(png).convert("RGBA")
    a = im.getchannel("A").point(lambda v: 255 if v >= 250 else 0)
    box = a.getbbox()
    if not box:
        return None
    if not keep_soft:
        im.putalpha(a)
    im = im.crop(box)
    if height and im.height > height:
        im = im.resize((round(im.width * height / im.height), height), Image.LANCZOS)
    im.save(out, "WEBP", quality=88, method=6)
    return im.size


def images(mods, force=False):
    from render3d import MASK_BLACK
    for sub in ("img", "models"):
        os.makedirs(os.path.join(DIST, sub), exist_ok=True)
    scratch = os.path.join(TMP, "_web")
    os.makedirs(scratch, exist_ok=True)
    only = next((a[7:].upper().split(",") for a in sys.argv if a.startswith("--only=")), None)
    for m in mods:
        if only and m["id"] not in only:
            continue
        sid = m["id"].lower()
        src = os.path.join(TMP, m["_base"] + ".kicad_pcb") if m["_base"] else None
        glb = os.path.join(D3, m["folder"], m["_base"] + ".glb") if m["_base"] else None
        if not src or not os.path.exists(src):     # nur Panel (P8): Kopie mit deckender Maske
            if not m["_panel"]:
                print("  ohne Bild:", m["id"])
                continue
            src = os.path.join(scratch, sid + "_panel.kicad_pcb")
            txt = open(m["_panel"], encoding="utf-8").read()
            txt = re.sub(r'(\(type "(?:Top|Bottom) Solder Mask"\)\s*\(color )"Black"',
                         lambda mo: mo.group(1) + '"%s"' % MASK_BLACK, txt)
            open(src, "w", encoding="utf-8", newline="").write(txt)
            os.utime(src, (os.path.getmtime(m["_panel"]),) * 2)
            glb = None
        variants = [(src, glb, sid, m.get("_ledrefs", ()), True)]
        for v in m.get("_vars", []) if glb else []:   # Bausatz, RGB: nur Schraegbild und Modell
            variants.append((os.path.join(TMP, v["base"] + ".kicad_pcb"), os.path.join(D3, m["folder"], v["base"] + ".glb"),
                             "%s-%s" % (sid, v["key"]), v["leds"], False))
        for src, glb, vid, ledrefs, with_front in variants:
            if not os.path.exists(src):
                print("  ohne Ansicht:", vid, flush=True)
                continue
            front, persp = os.path.join(DIST, "img", vid + "-front.webp"), os.path.join(DIST, "img", vid + "-3d.webp")
            t = os.path.getmtime(src)
            todo = [(front, ("--side", "top", "--width", "1100", "--height", "2000"), 1500, False)] * with_front + [
                (persp, ("--perspective", "--rotate", "-50,0,25", "--zoom", "0.9", "--width", "2000", "--height", "1600"),
                 1200, True)]
            for out, args, h, soft in todo:
                if not force and os.path.exists(out) and os.path.getmtime(out) > t:
                    continue
                raw = os.path.join(scratch, os.path.basename(out)[:-5] + ".png")
                ok = False
                for _ in range(2):             # abgeschnittenes PNG (z. B. Laufwerk kurz voll): einmal wiederholen
                    if not render(("--use-board-stackup-colors", "--background", "transparent", "--quality", "high") + args,
                                  raw, src):
                        continue
                    try:
                        crop_opaque(raw, out, h, soft)
                        ok = True
                        break
                    except OSError:
                        pass
                if ok:
                    print("  Bild", os.path.basename(out), flush=True)
                else:
                    print("  FEHLER Bild", m["id"], os.path.basename(out), flush=True)
            if glb and os.path.exists(glb):
                dst = os.path.join(DIST, "models", vid + ".glb")
                if force or not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(glb):
                    try:                       # fuer das Web verkleinern (siehe glb_pack.py)
                        from glb_pack import pack, squeeze
                        pack(glb, dst, web=True, leds=ledrefs)
                        size = squeeze(dst)    # zweite Stufe mit gltfpack, falls vorhanden
                        print("  Modell %s.glb %.1f -> %.1f MB" % (vid, os.path.getsize(glb) / 1e6, size / 1e6), flush=True)
                    except Exception as ex:    # im Zweifel das Original ausliefern
                        print("  Modell %s unveraendert (%s)" % (vid, ex), flush=True)
                        shutil.copy2(glb, dst)


def _ver(path):
    """?v=<Stand der Datei>, damit Browser ein neu gebautes Bild oder Modell nicht aus dem Cache nehmen."""
    return "?v=%x" % int(os.path.getmtime(path))


def image_info(mods):
    from PIL import Image
    for m in mods:
        sid = m["id"].lower()
        m["img"] = {}
        for key, name in (("front", sid + "-front.webp"), ("view3d", sid + "-3d.webp")):
            p = os.path.join(DIST, "img", name)
            if os.path.exists(p):
                w, h = Image.open(p).size
                m["img"][key] = {"src": "img/" + name + _ver(p), "w": w, "h": h}
        g = os.path.join(DIST, "models", sid + ".glb")
        if os.path.exists(g):
            m["model"] = {"src": "models/" + sid + ".glb" + _ver(g), "mb": round(os.path.getsize(g) / 1e6, 1)}
        m["variants"] = []                     # weitere Ausfuehrungen mit Schraegbild und Modell
        for v in m.get("_vars", []):
            ip = os.path.join(DIST, "img", "%s-%s-3d.webp" % (sid, v["key"]))
            g = os.path.join(DIST, "models", "%s-%s.glb" % (sid, v["key"]))
            if os.path.exists(ip) and os.path.exists(g) and m.get("model"):
                w, h = Image.open(ip).size
                m["variants"].append({"key": v["key"], "img": {"src": "img/" + os.path.basename(ip) + _ver(ip), "w": w, "h": h},
                                      "model": {"src": "models/" + os.path.basename(g) + _ver(g),
                                                "mb": round(os.path.getsize(g) / 1e6, 1)}})


SCH_INDEX = os.path.join(MODS, "Schaltplaene_Website.md")
SCH_PART = ("Control", "Main", "Front", "Traeger", "RGB")   # Teilplan am Ende des Dateinamens


def schematics(mods):
    """Schaltplan-PDFs laut 010_Module/Schaltplaene_Website.md nach dist/schematics kopieren.
    m['schematics'] = [{kind: main|kit, part: ''|control|main|front|traeger|rgb, src, kb}]"""
    rows = {}
    for line in open(SCH_INDEX, encoding="utf-8") if os.path.exists(SCH_INDEX) else ():
        cells = line.split("|")
        if len(cells) < 4:
            continue
        for kind, cell in (("main", cells[2]), ("kit", cells[3])):
            for rel in re.findall(r"`([^`]+\.pdf)`", cell):
                rows.setdefault(rel.split("/")[0], []).append((kind, rel))
    od = os.path.join(DIST, "schematics")
    os.makedirs(od, exist_ok=True)
    keep = set()
    for m in mods:
        m["schematics"] = []
        for kind, rel in rows.get(m["folder"], []):
            src = os.path.join(MODS, *rel.split("/"))
            if not os.path.exists(src):
                print("  Schaltplan fehlt:", rel, flush=True)
                continue
            sch = src[:-len("_Schematic.pdf")] + ".kicad_sch"
            if os.path.exists(sch) and os.path.getmtime(sch) > os.path.getmtime(src) + 1:
                print("  Schaltplan-PDF aelter als der Plan:", rel, flush=True)
            name = os.path.basename(src)
            dst = os.path.join(od, name)
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                shutil.copy2(src, dst + ".neu")
                os.replace(dst + ".neu", dst)
            keep.add(name)
            last = name[:-len("_Schematic.pdf")].split("_")[-1]
            m["schematics"].append({"kind": kind, "part": last.lower() if last in SCH_PART else "",
                                    "src": "schematics/" + name + _ver(dst), "kb": int(round(os.path.getsize(dst) / 1000.0))})
    for f in os.listdir(od):                   # nicht mehr gelistete Plaene entfernen
        if f not in keep:
            os.remove(os.path.join(od, f))


DS_INDEX = os.path.join(MODS, "Datenblaetter.md")


def datasheets(mods):
    """Datenblatt-PDFs laut 010_Module/Datenblaetter.md (Spalten ID | Modul | Deutsch | Englisch) nach dist/datasheets
    kopieren. m['datasheet'] = {de: {src, kb}, en: {src, kb}}. Erzeugt werden sie mit _kicad_tools/datenblatt.py."""
    rows = {}
    for line in open(DS_INDEX, encoding="utf-8") if os.path.exists(DS_INDEX) else ():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 6:
            continue
        links = [re.findall(r"\]\(([^)]+\.pdf)\)", c) for c in cells[3:5]]
        if all(links):
            rows[cells[1]] = {"de": links[0][0], "en": links[1][0]}
    od = os.path.join(DIST, "datasheets")
    os.makedirs(od, exist_ok=True)
    keep = set()
    for m in mods:
        m.pop("datasheet", None)
        r = rows.get(m["id"])
        if not r:
            print("  ohne Datenblatt:", m["id"], flush=True)
            continue
        ds = {}
        for lang, rel in r.items():
            src = os.path.join(MODS, *rel.split("/"))
            if not os.path.exists(src):
                print("  Datenblatt fehlt:", rel, flush=True)
                continue
            js = os.path.join(os.path.dirname(src), "datenblatt.json")
            if os.path.exists(js) and os.path.getmtime(js) > os.path.getmtime(src) + 1:
                print("  Datenblatt-PDF aelter als datenblatt.json:", rel, flush=True)
            name = os.path.basename(src)
            dst = os.path.join(od, name)
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                shutil.copy2(src, dst + ".neu")
                os.replace(dst + ".neu", dst)
            keep.add(name)
            ds[lang] = {"src": "datasheets/" + name + _ver(dst), "kb": int(round(os.path.getsize(dst) / 1000.0))}
        if ds:
            m["datasheet"] = ds
    for f in os.listdir(od):                   # nicht mehr gelistete Datenblaetter entfernen
        if f not in keep:
            os.remove(os.path.join(od, f))


# ---------------------------------------------------------------- HTML
# Stand von site.css/site.js als ?v=..., damit Browser nach einer Aenderung nicht die alte Datei aus dem Cache nehmen
ASSET_VER = "%x" % int(max(os.path.getmtime(os.path.join(HERE, "assets", f)) for f in ("site.css", "site.js")))


def page(lang, T, title, desc, body, here, other, depth=1):
    up = "../" * depth
    nav = "".join('<a href="%s%s/index.html#%s">%s</a>' % (up, lang, a, esc(T["nav"][a])) for a in ("module", "system", "status"))
    ol = "en" if lang == "de" else "de"
    return """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><meta name="description" content="{desc}">
<link rel="alternate" hreflang="{ol}" href="{up}{ol}/{other}"><link rel="stylesheet" href="{up}assets/site.css?v={ver}">
</head><body>
<header class="top"><a class="logo" href="{up}{lang}/index.html"><span>grae</span>Synth</a>
<nav>{nav}</nav><a class="lang" href="{up}{ol}/{other}" hreflang="{ol}">{olname}</a></header>
<main>{body}</main>
<footer><p><span class="logo small"><span>grae</span>Synth</span> · {foot}</p>
<p><a href="{up}{lang}/impressum.html">{imp}</a> · <a href="{up}{lang}/datenschutz.html">{priv}</a></p></footer>
<script src="{up}assets/site.js?v={ver}" defer></script></body></html>
""".format(lang=lang, ol=ol, up=up, title=esc(title), desc=esc(desc), nav=nav, other=other, body=body,
           olname="English" if lang == "de" else "Deutsch", ver=ASSET_VER, foot=esc(T["foot"]), imp=esc(T["imprint"]), priv=esc(T["privacy"]))


def spec_rows(m, lang, T):
    f, S = m["facts"], T["spec"]
    rows = []
    if f.get("hp"):
        rows.append((S["width"], "%d %s · %s mm" % (f["hp"], T["hp"], ("%.1f" % f["width_mm"]).replace(".", "," if lang == "de" else "."))))
    rows.append((S["height"], "3 U · 128,5 mm" if lang == "de" else "3 U · 128.5 mm"))
    for k in ("jacks", "knobs", "switches"):
        if f.get(k):
            rows.append((S[k], str(f[k])))
    rows.append((S["power"], S["powered"] if f["powered"] else S["passive"]))
    forms = [S["assembled"]] * bool(f["assembled"]) + [S["kit"]] * bool(f["kit"])
    if forms:
        rows.append((S["form"], " · ".join(forms)))
    return rows


def front_html(m, lang, lazy=True):
    """Frontbild mit leuchtenden LED-Punkten darueber."""
    im = m["img"].get("front")
    if not im:
        return ""
    dots = "".join('<i%s style="left:%s%%;top:%s%%;width:%s%%;--i:%d%s"></i>' % (
        ' class="rgb"' if "hue" in q else "", q["x"], q["y"], q["d"], k, ";--h:%d" % q["hue"] if "hue" in q else "")
                   for k, q in enumerate(m.get("leds", [])))
    return '<span class="fp"><img %ssrc="../%s" width="%d" height="%d" alt="%s %s">%s</span>' % (
        'loading="lazy" ' if lazy else "", im["src"], im["w"], im["h"], esc(m["id"]), esc(m["name"][lang]), dots)


def card(m, lang, T):
    f = m["facts"]
    pic = front_html(m, lang)
    return ('<a class="card" href="%s.html" data-fam="%s" data-cat="%s"><div class="pic">%s</div>'
            '<div class="meta"><span class="id">%s</span><span class="hp">%s</span></div>'
            '<h3>%s</h3><p>%s</p></a>') % (
        slug(m), m["id"][0], m["cat"], pic, esc(m["id"]), "%d %s" % (f["hp"], T["hp"]) if f.get("hp") else "",
        esc(m["name"][lang]), esc(m["tag"][lang]))


def index_page(mods, lang, T):
    rack = "".join('<a href="%s.html" title="%s %s">%s</a>' % (
        slug(m), esc(m["id"]), esc(m["name"][lang]), front_html(m, lang, lazy=False)) for m in mods if m["img"].get("front"))
    chips = '<button class="chip on" data-f="*">%s</button>' % esc(T["all"])
    chips += "".join('<button class="chip" data-f="fam:%s">%s</button>' % (k, esc(T["fam"][k]["short"])) for k in "APD")
    chips += '<span class="sep"></span>'
    cats = [c for c in T["cat"] if any(m["cat"] == c for m in mods)]
    chips += "".join('<button class="chip" data-f="cat:%s">%s</button>' % (c, esc(T["cat"][c])) for c in cats)
    fams = "".join('<div class="fam"><span class="id">%s</span><h3>%s</h3><p>%s</p><p class="count">%d %s</p></div>' % (
        k, esc(T["fam"][k]["name"]), esc(T["fam"][k]["text"]), sum(m["id"][0] == k for m in mods), esc(T["modules"]))
        for k in "APD")
    points = "".join("<li><strong>%s</strong> %s</li>" % (esc(a), esc(b)) for a, b in T["system_points"])
    body = """
<section class="hero"><p class="kicker">{kicker}</p><h1>{h1}</h1><p class="lead">{lead}</p>
<p class="badge">{badge}</p></section>
<section class="rackwrap" aria-label="{racklabel}"><div class="rack">{rack}</div></section>
<section id="module"><h2>{h_mod}</h2><p class="sub">{sub_mod}</p>
<div class="chips">{chips}</div><div class="grid">{cards}</div></section>
<section id="system"><h2>{h_sys}</h2><p class="sub">{sub_sys}</p><div class="fams">{fams}</div>
<ul class="points">{points}</ul></section>
<section id="status"><h2>{h_stat}</h2><p class="sub">{stat}</p></section>
""".format(kicker=esc(T["kicker"]), h1=esc(T["h1"]), lead=esc(T["lead"]), badge=esc(T["badge"]), racklabel=esc(T["rack_label"]),
           rack=rack, h_mod=esc(T["h_modules"]), sub_mod=esc(T["sub_modules"]) % len(mods), chips=chips,
           cards="".join(card(m, lang, T) for m in mods), h_sys=esc(T["h_system"]), sub_sys=esc(T["sub_system"]),
           fams=fams, points=points, h_stat=esc(T["h_status"]), stat=esc(T["status"]))
    return page(lang, T, T["title"], T["lead"], body, "index.html", "index.html")


def module_page(m, mods, lang, T):
    i = mods.index(m)
    prev, nxt = mods[i - 1], mods[(i + 1) % len(mods)]
    front, v3 = m["img"].get("front"), m["img"].get("view3d")
    pic = front_html(m, lang, lazy=False)
    feats = "".join("<li>%s</li>" % esc(x) for x in m["feat"][lang])
    specs = "".join("<tr><th>%s</th><td>%s</td></tr>" % (esc(a), esc(b)) for a, b in spec_rows(m, lang, T))
    vs = m.get("variants", []) if v3 and m.get("model") else []

    def num(mb):
        return str(mb).replace(".", "," if lang == "de" else ".")

    def alt(key):
        return esc(T["alt3d" if key == "main" else "alt3d_" + key] % m["name"][lang])

    view = ""
    if v3:
        extra = ' data-main="../%s" data-alt-main="%s"' % (v3["src"], alt("main")) if vs else ""
        extra += "".join(' data-%s="../%s" data-alt-%s="%s"' % (v["key"], v["img"]["src"], v["key"], alt(v["key"])) for v in vs)
        view = '<figure class="view3d"><img loading="lazy" src="../%s" width="%d" height="%d" alt="%s"%s></figure>' % (
            v3["src"], v3["w"], v3["h"], alt("main"), extra)
    viewer = ""
    if m.get("model"):
        label = esc(T["btn3d"] % num(m["model"]["mb"]))
        extra = "".join(' data-%s="../%s" data-label-%s="%s"' % (
            v["key"], v["model"]["src"], v["key"], esc(T["btn3d"] % num(v["model"]["mb"]))) for v in vs)
        viewer = ('<div class="viewer" data-src="../%s" data-main="../%s" data-label-main="%s"%s>'
                  '<button class="btn" type="button">%s</button><p class="note">%s</p></div>') % (
                      m["model"]["src"], m["model"]["src"], label, extra, label, esc(T["note3d"]))
    switch = ""
    if vs:                                     # Umschalter Fertigmodul / Bausatz / ... fuer Schraegbild und 3D-Modell
        segs = '<button class="seg on" type="button" data-v="main" aria-pressed="true">%s</button>' % esc(T["variant_main"])
        segs += "".join('<button class="seg" type="button" data-v="%s" aria-pressed="false">%s</button>' % (
            v["key"], esc(T["variant_" + v["key"]])) for v in vs)
        switch = '<div class="variants" role="group" aria-label="%s">%s</div>' % (esc(T["variant_label"]), segs)
    ds = ""
    d = (m.get("datasheet") or {}).get(lang)
    if d:                                      # Datenblatt in der Sprache der Seite, unter der Spezifikationstabelle
        ds = ('<p class="ds"><a href="../%s" target="_blank" rel="noopener" type="application/pdf">'
              '<span class="doc">PDF</span><span>%s</span><span class="kb">%d kB</span></a></p>') % (
                  d["src"], esc(T["ds_link"]), d["kb"])
    sch = ""
    if m.get("schematics"):                    # Schaltplaene als PDF
        def sch_label(e):
            a = T["variant_main" if e["kind"] == "main" else "variant_kit"]
            dv = (m.get("default_variant") or "").lower()
            if dv and e["kind"] == "main":         # D2: RGB ist das Fertigmodul, der Plan ohne Zusatz die Option 'mono'
                return a if e["part"] == dv else T["variant_mono"]
            return a + (" · " + T["sch_part"][e["part"]] if e["part"] else "")
        items = "".join('<li><a href="../%s" target="_blank" rel="noopener" type="application/pdf">'
                        '<span class="doc">PDF</span><span>%s</span><span class="kb">%d kB</span></a></li>' % (
                            e["src"], esc(sch_label(e)), e["kb"]) for e in sorted(
                            m["schematics"], key=lambda e: sch_label(e) != T["variant_main"]))
        sch = '<section class="sch"><h2>%s</h2><p class="note">%s</p><ul>%s</ul></section>' % (
            esc(T["sch_title"]), esc(T["sch_note"]), items)
    body = """
<p class="crumb"><a href="index.html#module">{back}</a></p>
<article class="module"><div class="front">{pic}</div>
<div class="info"><p class="meta"><span class="id">{id}</span><span class="tagfam">{fam}</span></p>
<h1>{name}</h1><p class="lead">{tag}</p><p>{text}</p><ul class="feat">{feats}</ul>
<table class="specs">{specs}</table>{ds}<p class="badge">{badge}</p></div></article>
<section class="more">{switch}{view}{viewer}</section>{sch}
<nav class="pn"><a href="{pu}.html">← {pi} {pn}</a><a href="{nu}.html">{ni} {nn} →</a></nav>
""".format(back=esc(T["back"]), pic=pic, id=esc(m["id"]), fam=esc(T["fam"][m["id"][0]]["name"]), name=esc(m["name"][lang]),
           tag=esc(m["tag"][lang]), text=esc(m["text"][lang]), feats=feats, specs=specs, badge=esc(T["badge"]),
           view=view, viewer=viewer, switch=switch, sch=sch, ds=ds, pu=slug(prev), pi=esc(prev["id"]), pn=esc(prev["name"][lang]),
           nu=slug(nxt), ni=esc(nxt["id"]), nn=esc(nxt["name"][lang]))
    return page(lang, T, "%s %s – graeSynth" % (m["id"], m["name"][lang]), m["tag"][lang], body,
                slug(m) + ".html", slug(m) + ".html")


def legal_html(key, lang, L):
    """Text aus content/legal/<key>.<lang>.html; sonst der Platzhalter aus site.json.
    Der Abschnitt <!--cdn-->...<!--/cdn--> erscheint nur, solange site.js noch etwas von jsdelivr laedt."""
    f = os.path.join(HERE, "content", "legal", "%s.%s.html" % (key, lang))
    if not os.path.exists(f):
        return '<p class="todo">%s</p>' % esc(L["text"])
    txt = open(f, encoding="utf-8").read()
    cdn = "cdn.jsdelivr.net" in open(os.path.join(HERE, "assets", "site.js"), encoding="utf-8").read()
    txt = re.sub(r"<!--cdn-->(.*?)<!--/cdn-->", lambda mo: mo.group(1) if cdn else "", txt, flags=re.S)
    return txt


def main():
    mods = sorted(json.load(open(os.path.join(HERE, "content", "modules.json"), encoding="utf-8"))["modules"], key=sort_key)
    site = json.load(open(os.path.join(HERE, "content", "site.json"), encoding="utf-8"))
    os.makedirs(DIST, exist_ok=True)
    print("Fakten aus KiCad ...", flush=True)
    facts(mods)
    if "--no-images" not in sys.argv:
        print("Bilder ...", flush=True)
        images(mods, force="--force" in sys.argv)
    image_info(mods)
    schematics(mods)
    datasheets(mods)
    shutil.copytree(os.path.join(HERE, "assets"), os.path.join(DIST, "assets"), dirs_exist_ok=True)
    for lang in LANGS:
        T = site[lang]
        od = os.path.join(DIST, lang)
        os.makedirs(od, exist_ok=True)
        open(os.path.join(od, "index.html"), "w", encoding="utf-8").write(index_page(mods, lang, T))
        for m in mods:
            open(os.path.join(od, slug(m) + ".html"), "w", encoding="utf-8").write(module_page(m, mods, lang, T))
        for key in ("impressum", "datenschutz"):
            L = T["legal"][key]
            body = '<section class="legal"><h1>%s</h1>%s</section>' % (esc(L["title"]), legal_html(key, lang, L))
            open(os.path.join(od, key + ".html"), "w", encoding="utf-8").write(
                page(lang, T, L["title"] + " – graeSynth", L["title"], body, key + ".html", key + ".html"))
    open(os.path.join(DIST, "index.html"), "w", encoding="utf-8").write(
        '<!doctype html><html lang="de"><head><meta charset="utf-8"><title>graeSynth</title>'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="assets/site.css">'
        '<script>location.replace(((navigator.language||"de").toLowerCase().indexOf("de")===0?"de":"en")+"/index.html")</script>'
        '</head><body><main><p><a href="de/index.html">Deutsch</a> · <a href="en/index.html">English</a></p></main></body></html>\n')
    # Vorschau: Suchmaschinen fernhalten (zusammen mit X-Robots-Tag in der Caddyfile). Zum Freischalten NOINDEX = False.
    robots = "User-agent: *\nDisallow: /\n" if NOINDEX else "User-agent: *\nAllow: /\n"
    open(os.path.join(DIST, "robots.txt"), "w", encoding="utf-8", newline="\n").write(robots)
    os.makedirs(os.path.join(DIST, "data"), exist_ok=True)
    data = [{k: v for k, v in m.items() if not k.startswith("_")} | {"slug": slug(m)} for m in mods]
    json.dump({"modules": data}, open(os.path.join(DIST, "data", "modules.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("fertig: %d Module, %d Seiten -> %s" % (len(mods), len(LANGS) * (len(mods) + 3) + 1, DIST))


if __name__ == "__main__":
    main()
