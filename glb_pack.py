"""GLB aus KiCad fuer das Web verkleinern, ohne fremde Werkzeuge (nur numpy).

  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" glb_pack.py ein.glb aus.glb

Was passiert:
  1. Alle Teile werden mit ihrer Lage in eine gemeinsame Geometrie gerechnet und je Material zusammengefasst
     (KiCad schreibt mehrere tausend Einzelteile; allein deren Beschreibung belegt oft ein Drittel der Datei).
  2. Gleiche Eckpunkte werden zusammengelegt, entartete Dreiecke entfernt.
  3. Koordinaten werden als 16-Bit-Zahlen gespeichert (Raster ca. 2 um bei 130 mm), Normalen als 8 Bit
     (glTF-Erweiterung KHR_mesh_quantization; three.js / model-viewer lesen das ohne Zusatz-Decoder).
Sichtbar aendert sich nichts. Einzelteile sind danach nicht mehr getrennt anwaehlbar (fuer Blender die
Originale aus 010_Module/_3D nehmen).
"""
import json
import os
import struct
import subprocess
import sys

import numpy as np

CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _read(path):
    b = open(path, "rb").read()
    jl = struct.unpack_from("<I", b, 12)[0]
    j = json.loads(b[20:20 + jl])
    off = 20 + jl
    bl = struct.unpack_from("<I", b, off)[0]
    return j, memoryview(b)[off + 8:off + 8 + bl]


def _acc(j, bin_, i):
    a = j["accessors"][i]
    bv = j["bufferViews"][a["bufferView"]]
    dt, n = np.dtype(CT[a["componentType"]]), NC[a["type"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or dt.itemsize * n
    if stride == dt.itemsize * n:
        arr = np.frombuffer(bin_, dt, a["count"] * n, start).reshape(a["count"], n)
    else:
        raw = np.frombuffer(bin_, np.uint8, stride * (a["count"] - 1) + dt.itemsize * n, start)
        idx = (np.arange(a["count"])[:, None] * stride + np.arange(dt.itemsize * n)[None, :]).ravel()
        arr = raw[idx].view(dt).reshape(a["count"], n)
    if a.get("normalized"):
        arr = arr.astype(np.float32) / np.iinfo(dt).max
    return arr


def _local(n):
    if "matrix" in n:
        return np.array(n["matrix"], np.float64).reshape(4, 4).T
    m = np.eye(4)
    if "scale" in n:
        m = np.diag(list(n["scale"]) + [1.0]) @ m
    if "rotation" in n:
        x, y, z, w = n["rotation"]
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
                      [0, 0, 0, 1]])
        m = r @ m
    if "translation" in n:
        t = np.eye(4)
        t[:3, 3] = n["translation"]
        m = t @ m
    return m


def web_materials(mats):
    """Materialien fuer den 3D-Viewer: Loetstoppmaske deckend schwarz-matt, Platinenkante dunkel, Bauteile nicht
    spiegelnd. KiCad schreibt die Maske halbtransparent (wirkt grau) und laesst bei Bauteilfarben die Angaben weg;
    glTF nimmt dann 'Metall' an."""
    for m in mats:
        p = m.setdefault("pbrMetallicRoughness", {})
        c = p.get("baseColorFactor", [1, 1, 1, 1])
        if m.get("alphaMode") == "BLEND" and max(c[:3]) < 0.15:          # Loetstoppmaske
            m.pop("alphaMode", None)
            p.update(baseColorFactor=[0.006, 0.006, 0.007, 1.0], metallicFactor=0.0, roughnessFactor=0.92)
        elif "metallicFactor" not in p and "roughnessFactor" not in p:    # Bauteile aus STEP-Modellen
            gray = max(c[:3]) - min(c[:3]) < 0.04 and 0.12 < c[0] < 0.5   # Metallteile: Buchsen, Muttern, Pins
            p.update(metallicFactor=0.85 if gray else 0.0, roughnessFactor=0.38 if gray else 0.6)
        elif p.get("metallicFactor") == 0.0 and abs(p.get("roughnessFactor", 0) - 0.8) < 0.01 and c[1] > c[2] > 0.2:
            p.update(baseColorFactor=[0.012, 0.012, 0.013, 1.0], roughnessFactor=0.9)   # Platinenkoerper (Kante)
    return mats


def pack(src, dst, web=False, leds=()):
    """leds: Knotennamen (Referenzen) der LEDs. Ihre farbige Linse bekommt je LED ein eigenes Material 'LED:<Ref>',
    damit die Website sie einzeln leuchten lassen kann."""
    j, bin_ = _read(src)
    groups = {}      # (Material, LED) -> ([pos], [nrm], [idx], Eckpunktzahl)
    leds = set(leds)
    mats = j.get("materials", [])

    def lens(mi):
        if mi is None or mi < 0 or mi >= len(mats):
            return False
        c = mats[mi].get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])[:3]
        return max(c) - min(c) > 0.2

    def walk(ni, world, led=None):
        n = j["nodes"][ni]
        w = world @ _local(n)
        if n.get("name") in leds:
            led = n["name"]
        if "mesh" in n:
            nm = np.linalg.inv(w[:3, :3]).T
            flip = np.linalg.det(w[:3, :3]) < 0
            for pr in j["meshes"][n["mesh"]]["primitives"]:
                if pr.get("mode", 4) != 4 or "POSITION" not in pr["attributes"]:
                    continue
                p = _acc(j, bin_, pr["attributes"]["POSITION"]).astype(np.float64)
                p = p @ w[:3, :3].T + w[:3, 3]
                ix = (_acc(j, bin_, pr["indices"]).ravel().astype(np.int64) if "indices" in pr
                      else np.arange(len(p), dtype=np.int64))
                ix = ix[:len(ix) // 3 * 3].reshape(-1, 3)
                if flip:
                    ix = ix[:, ::-1]
                if "NORMAL" in pr["attributes"]:
                    nr = _acc(j, bin_, pr["attributes"]["NORMAL"]).astype(np.float64) @ nm.T
                else:               # Flaechennormalen je Eckpunkt mitteln
                    fn = np.cross(p[ix[:, 1]] - p[ix[:, 0]], p[ix[:, 2]] - p[ix[:, 0]])
                    nr = np.zeros_like(p)
                    for k in range(3):
                        np.add.at(nr, ix[:, k], fn)
                ln = np.linalg.norm(nr, axis=1, keepdims=True)
                nr = nr / np.where(ln > 0, ln, 1)
                mi = pr.get("material", -1)
                g = groups.setdefault((mi, led if led and lens(mi) else ""), [[], [], [], 0])
                g[0].append(p)
                g[1].append(nr)
                g[2].append(ix + g[3])
                g[3] += len(p)
        for c in n.get("children", []):
            walk(c, w, led)

    for root in j["scenes"][j.get("scene", 0)]["nodes"]:
        walk(root, np.eye(4))
    if not groups:
        raise ValueError("keine Dreiecke gefunden")
    allp = np.concatenate([np.concatenate(g[0]) for g in groups.values()])
    lo, hi = allp.min(0), allp.max(0)
    scale = float((hi - lo).max()) / 65535.0 or 1.0
    out, views, accs, prims = bytearray(), [], [], []

    def add(data, target, stride=None):
        while len(out) % 4:
            out.append(0)
        v = {"buffer": 0, "byteOffset": len(out), "byteLength": len(data), "target": target}
        if stride:
            v["byteStride"] = stride
        out.extend(data)
        views.append(v)
        return len(views) - 1

    nv = nt = 0
    out_mats = [json.loads(json.dumps(m)) for m in mats]
    if web:
        web_materials(out_mats)
    for (mat, led), (ps, ns, ixs, _) in sorted(groups.items()):
        p = np.rint((np.concatenate(ps) - lo) / scale).astype(np.uint16)
        n = np.clip(np.rint(np.concatenate(ns) * 127), -127, 127).astype(np.int8)
        ix = np.concatenate(ixs)
        key = np.zeros(len(p), dtype=[("p", np.uint16, 3), ("n", np.int8, 3)])
        key["p"], key["n"] = p, n
        uniq, inv = np.unique(key, return_inverse=True)
        ix = inv.ravel()[ix]
        ix = ix[(ix[:, 0] != ix[:, 1]) & (ix[:, 1] != ix[:, 2]) & (ix[:, 0] != ix[:, 2])]
        if not len(ix):
            continue
        used, ix2 = np.unique(ix, return_inverse=True)      # unbenutzte Eckpunkte entfernen
        uniq, ix = uniq[used], ix2.reshape(-1, 3)
        pv = np.zeros((len(uniq), 4), np.uint16)
        pv[:, :3] = uniq["p"]
        nb = np.zeros((len(uniq), 4), np.int8)
        nb[:, :3] = uniq["n"]
        it = np.uint16 if len(uniq) <= 65535 else np.uint32
        a0 = len(accs)
        accs.append({"bufferView": add(pv.tobytes(), 34962, 8), "componentType": 5123, "count": len(uniq), "type": "VEC3",
                     "min": uniq["p"].min(0).tolist(), "max": uniq["p"].max(0).tolist()})
        accs.append({"bufferView": add(nb.tobytes(), 34962, 4), "componentType": 5120, "normalized": True,
                     "count": len(uniq), "type": "VEC3"})
        accs.append({"bufferView": add(ix.astype(it).tobytes(), 34963), "componentType": 5123 if it is np.uint16 else 5125,
                     "count": int(ix.size), "type": "SCALAR"})
        pr = {"attributes": {"POSITION": a0, "NORMAL": a0 + 1}, "indices": a0 + 2}
        if led:                                   # eigenes Material je LED, Leuchten setzt die Website
            lm = json.loads(json.dumps(out_mats[mat]))
            lm["name"] = "LED:" + led
            lm["emissiveFactor"] = [0.0, 0.0, 0.0]
            lm.setdefault("pbrMetallicRoughness", {}).update(metallicFactor=0.0, roughnessFactor=0.35)
            out_mats.append(lm)
            pr["material"] = len(out_mats) - 1
        elif mat >= 0:
            pr["material"] = mat
        prims.append(pr)
        nv += len(uniq)
        nt += len(ix)
    while len(out) % 4:
        out.append(0)
    g = {"asset": {"version": "2.0", "generator": "graeSynth glb_pack"}, "scene": 0, "scenes": [{"nodes": [0]}],
         "nodes": [{"mesh": 0, "translation": lo.tolist(), "scale": [scale] * 3}],
         "meshes": [{"primitives": prims}], "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(out)}],
         "extensionsUsed": ["KHR_mesh_quantization"], "extensionsRequired": ["KHR_mesh_quantization"]}
    if out_mats:
        g["materials"] = out_mats
    js = json.dumps(g, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(out)
    with open(dst, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(js), b"JSON"))
        f.write(js)
        f.write(struct.pack("<I4s", len(out), b"BIN\0"))
        f.write(out)
    return total, nv, nt


GLTFPACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tools", "gltfpack", "gltfpack.exe")


def squeeze(path):
    """Zweite Stufe: gltfpack (meshoptimizer, MIT) komprimiert die gepackte Datei mit EXT_meshopt_compression,
    etwa auf ein Viertel. Ohne gltfpack.exe oder bei einem Fehler bleibt die Datei, wie sie ist.
    -km haelt die benannten LED-Materialien getrennt, -vp 16 das 2-um-Raster (Druck liegt nur wenige um ueber der
    Maske). model-viewer laedt den Decoder dafuer selbst nach. Gibt die neue Groesse in Byte zurueck."""
    if not os.path.exists(GLTFPACK):
        return os.path.getsize(path)
    tmp = path + ".tmp.glb"
    try:
        r = subprocess.run([GLTFPACK, "-i", path, "-o", tmp, "-cc", "-km", "-vp", "16"],
                           capture_output=True, timeout=600)
        if r.returncode == 0 and os.path.exists(tmp) and 0 < os.path.getsize(tmp) < os.path.getsize(path):
            os.replace(tmp, path)
    except (OSError, subprocess.SubprocessError):
        pass
    if os.path.exists(tmp):
        os.remove(tmp)
    return os.path.getsize(path)


def is_squeezed(path):
    b = open(path, "rb").read(20)
    with open(path, "rb") as f:
        f.seek(20)
        return b"EXT_meshopt_compression" in f.read(struct.unpack_from("<I", b, 12)[0])


if __name__ == "__main__":
    size, nv, nt = pack(sys.argv[1], sys.argv[2], web="--web" in sys.argv)
    size = squeeze(sys.argv[2])
    print("%s: %.2f MB -> %.2f MB, %d Eckpunkte, %d Dreiecke" % (
        os.path.basename(sys.argv[1]), os.path.getsize(sys.argv[1]) / 1e6, size / 1e6, nv, nt))
