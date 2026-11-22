// Filter im Modulraster
(function () {
  var chips = document.querySelectorAll('.chip');
  var cards = document.querySelectorAll('.grid .card');
  chips.forEach(function (c) {
    c.addEventListener('click', function () {
      chips.forEach(function (x) { x.classList.toggle('on', x === c); });
      var f = c.dataset.f.split(':');
      cards.forEach(function (card) {
        card.hidden = !(f[0] === '*' || card.dataset[f[0]] === f[1]);
      });
    });
  });
})();

// 3D-Viewer erst nach Klick laden (model-viewer, Web Component)
(function () {
  var MV = 'https://cdn.jsdelivr.net/npm/@google/model-viewer@4.0.0/dist/model-viewer.min.js';
  var MESHOPT = 'https://cdn.jsdelivr.net/npm/meshoptimizer@0.22.0/meshopt_decoder.js';
  document.querySelectorAll('.viewer').forEach(function (box) {
    var btn = box.querySelector('button');
    if (!btn) return;
    btn.addEventListener('click', function () {
      btn.disabled = true;
      if (!customElements.get('model-viewer')) {
        var s = document.createElement('script');
        s.type = 'module';
        s.src = MV;
        document.head.appendChild(s);
      }
      var mv = document.createElement('model-viewer');
      // Die Modelle sind mit gltfpack komprimiert (EXT_meshopt_compression); der Viewer braucht dafuer den
      // Decoder, und zwar bevor er die Datei laedt. Deshalb src erst danach setzen.
      customElements.whenDefined('model-viewer').then(function () {
        customElements.get('model-viewer').meshoptDecoderLocation = MESHOPT;
        mv.setAttribute('src', box.dataset.src);
      });
      mv.setAttribute('camera-controls', '');
      mv.setAttribute('touch-action', 'pan-y');
      mv.setAttribute('camera-orbit', '25deg 55deg 75%');
      mv.setAttribute('min-camera-orbit', 'auto auto 20%');
      mv.setAttribute('shadow-intensity', '0.6');
      mv.setAttribute('exposure', '1');
      mv.setAttribute('tone-mapping', 'neutral');
      mv.setAttribute('interaction-prompt', 'none');
      box.insertBefore(mv, btn);
      btn.remove();
      mv.addEventListener('load', function () { animateLeds(mv); });
    });
  });
})();

// LEDs im 3D-Modell pulsieren lassen (Materialien 'LED:<Referenz>' aus glb_pack.py)
function animateLeds(mv) {
  var run = mv._ledRun = (mv._ledRun || 0) + 1;   // nach einem Modellwechsel endet die alte Schleife
  var leds = (mv.model ? mv.model.materials : []).filter(function (m) { return m.name.indexOf('LED:') === 0; });
  if (!leds.length) return;
  var base = leds.map(function (m) {
    var c = m.pbrMetallicRoughness.baseColorFactor, mx = Math.max(c[0], c[1], c[2]) || 1;
    return [c[0] / mx, c[1] / mx, c[2] / mx];
  });
  var still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function frame(t) {
    if (!mv.isConnected || mv._ledRun !== run) return;
    leds.forEach(function (m, i) {
      var k = still ? 0.8 : Math.pow(0.5 + 0.5 * Math.sin(t / 1000 * (2 * Math.PI) / (1.7 + i * 0.37) + i * 1.9), 2);
      m.setEmissiveFactor([base[i][0] * k, base[i][1] * k, base[i][2] * k]);
      if (m.setEmissiveStrength) m.setEmissiveStrength(1 + 3 * k);
    });
    if (!still) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

// Umschalter Fertigmodul / Bausatz / weitere Ausfuehrung: tauscht das Schraegbild und das 3D-Modell (bzw. die Beschriftung des Ladeknopfs)
(function () {
  var segs = document.querySelectorAll('.variants .seg');
  if (!segs.length) return;
  var img = document.querySelector('.view3d img[data-kit]');
  var box = document.querySelector('.viewer');
  function cap(v) { return v.charAt(0).toUpperCase() + v.slice(1); }
  segs.forEach(function (seg) {
    seg.addEventListener('click', function () {
      var v = seg.dataset.v;
      segs.forEach(function (x) {
        x.classList.toggle('on', x === seg);
        x.setAttribute('aria-pressed', x === seg ? 'true' : 'false');
      });
      if (img) {
        img.removeAttribute('width');
        img.removeAttribute('height');
        img.src = img.dataset[v];
        img.alt = img.dataset['alt' + cap(v)];
      }
      if (box && box.dataset[v]) {
        box.dataset.src = box.dataset[v];
        var mv = box.querySelector('model-viewer');
        var btn = box.querySelector('button');
        if (mv && mv.getAttribute('src')) mv.setAttribute('src', box.dataset.src);
        if (btn) btn.textContent = box.dataset['label' + cap(v)];
      }
    });
  });
})();
