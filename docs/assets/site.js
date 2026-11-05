/* TrueStretch site: scroll reveals, parallax, progress, menu, FAQ, lightbox, release info. No libraries. */
(function () {
  "use strict";
  window.TS_READY = true;

  var doc = document, html = doc.documentElement;
  var $ = function (s, r) { return (r || doc).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || doc).querySelectorAll(s)); };
  var motion = html.classList.contains("motion");
  var reduceMq = window.matchMedia ? matchMedia("(prefers-reduced-motion: reduce)") : null;

  /* ---------- masked lines: index each line for the stagger ---------- */
  $$("[data-r=lines]").forEach(function (h) {
    $$(".ln", h).forEach(function (ln, i) { ln.style.setProperty("--i", i); });
  });

  /* ---------- CTA glitch: two aria-hidden clones of the red face ---------- */
  $$(".btn-red").forEach(function (b) {
    var face = $(".face", b);
    if (!face) return;
    ["s1", "s2"].forEach(function (c) {
      var s = face.cloneNode(true);
      s.classList.add("slice", c);
      s.setAttribute("aria-hidden", "true");
      b.appendChild(s);
    });
  });

  /* ---------- count-up ---------- */
  function fmt(v, pad) { var s = String(Math.round(v)); while (s.length < pad) s = "0" + s; return s; }
  function countUp(el, to) {
    var pad = +el.getAttribute("data-pad") || 0;
    if (!motion) { el.textContent = fmt(to, pad); return; }
    var t0 = performance.now(), dur = 1100;
    el.textContent = fmt(0, pad);
    (function step(t) {
      var p = Math.min(1, (t - t0) / dur), e = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
      el.textContent = fmt(to * e, pad);
      if (p < 1) requestAnimationFrame(step);
    })(t0);
  }

  /* ---------- reveal ---------- */
  function waitImg(img, cb) {
    if (!img || (img.complete && img.naturalWidth)) return cb();
    var done = false, fin = function () { if (!done) { done = true; cb(); } };
    img.addEventListener("load", fin, { once: true });
    img.addEventListener("error", fin, { once: true });
    setTimeout(fin, 1500);
  }
  function reveal(el) {
    if (el._rv) return;
    el._rv = true;
    var go = function () {
      el.classList.add("in");
      $$("[data-count]", el).forEach(function (c) { countUp(c, parseFloat(c.getAttribute("data-count"))); });
    };
    if (el.classList.contains("frame")) waitImg($("img", el), go); else go();
  }

  var targets = $$("[data-r]");
  var heroTargets = $$(".hero [data-r]");
  var scrollTargets = targets.filter(function (el) { return heroTargets.indexOf(el) < 0; });

  var io = null, pending = [];
  function revealBatch(hits) {
    hits.sort(function (a, b) { return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1; });
    hits.forEach(function (el, k) {
      if (io) io.unobserve(el);
      if (!el.style.getPropertyValue("--i") && el.getAttribute("data-r") !== "lines") el.style.setProperty("--i", Math.min(k, 6));
      reveal(el);
    });
  }
  /* safety net for fast jumps / throttled observers: reveal anything whose top is above the fold line */
  function sweep() {
    if (!pending.length) return;
    var lim = window.innerHeight * 0.9, hits = [];
    pending = pending.filter(function (el) {
      if (el._rv) return false;
      if (el.getBoundingClientRect().top < lim) { hits.push(el); return false; }
      return true;
    });
    if (hits.length) revealBatch(hits);
  }

  if (!motion) {
    targets.forEach(function (el) { el.classList.add("in"); });
  } else {
    io = new IntersectionObserver(function (entries) {
      revealBatch(entries.filter(function (e) { return e.isIntersecting; }).map(function (e) { return e.target; }));
    }, { rootMargin: "0px 0px -10% 0px", threshold: 0 });
    scrollTargets.forEach(function (el) { io.observe(el); });
    pending = scrollTargets.slice();

    /* hero entrance: sequenced via inline --dl, starts once fonts are in (or 700ms) */
    var fontsReady = doc.fonts && doc.fonts.ready ? doc.fonts.ready : Promise.resolve();
    Promise.race([fontsReady, new Promise(function (r) { setTimeout(r, 700); })]).then(function () {
      requestAnimationFrame(function () { heroTargets.forEach(reveal); });
    });
  }

  /* ---------- scroll: progress bar + parallax on giant outline type ---------- */
  var bar = $(".progress");
  var px = $$("[data-px]").map(function (el) {
    return { el: el, host: el.parentElement, f: parseFloat(el.getAttribute("data-px")) || 0, x: el.getAttribute("data-axis") === "x", vis: false };
  });
  if (motion && "IntersectionObserver" in window) {
    var pio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { px.forEach(function (p) { if (p.host === e.target) p.vis = e.isIntersecting; }); });
      schedule();
    }, { rootMargin: "100px 0px" });
    px.forEach(function (p) { pio.observe(p.host); });
  }
  var ticking = false, lastSweep = 0, sweepTimer = 0;
  function frame() {
    ticking = false;
    if (motion && pending.length) {
      var now = performance.now();
      if (now - lastSweep > 160) { lastSweep = now; sweep(); }
      clearTimeout(sweepTimer); sweepTimer = setTimeout(sweep, 220);
    }
    var vh = window.innerHeight, max = html.scrollHeight - vh;
    var p = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
    if (!motion) return void (bar.style.transform = "scaleX(" + p + ")");
    /* read all, then write all */
    var reads = px.map(function (o) {
      if (!o.vis) return null;
      var r = o.host.getBoundingClientRect();
      return (r.top + r.height / 2 - vh / 2) * o.f;
    });
    bar.style.transform = "scaleX(" + p + ")";
    px.forEach(function (o, i) {
      if (reads[i] === null) return;
      var v = reads[i].toFixed(1);
      o.el.style.transform = o.x ? "translate3d(" + v + "px,0,0)" : "translate3d(0," + v + "px,0)";
    });
  }
  function schedule() { if (!ticking) { ticking = true; requestAnimationFrame(frame); } }
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule, { passive: true });
  schedule();

  /* ---------- nav: highlight current section ---------- */
  var navLinks = $$(".nav-links a[href^='#']");
  if ("IntersectionObserver" in window && navLinks.length) {
    var sio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        navLinks.forEach(function (a) { a.classList.toggle("on", a.getAttribute("href") === "#" + e.target.id); });
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    navLinks.forEach(function (a) { var s = $(a.getAttribute("href")); if (s) sio.observe(s); });
    ["#top", ".final"].forEach(function (s) { var el = $(s); if (el) sio.observe(el); }); /* no link: clears highlight */
  }

  /* ---------- mobile menu ---------- */
  var burger = $(".burger"), menu = $("#menu");
  function setMenu(open, refocus) {
    html.classList.toggle("menu-open", open);
    burger.setAttribute("aria-expanded", String(open));
    burger.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    if (open) menu.removeAttribute("inert"); else menu.setAttribute("inert", "");
    if (open) { var first = $("a", menu); if (first) first.focus({ preventScroll: true }); }
    else if (refocus) burger.focus({ preventScroll: true });
  }
  if (burger && menu) {
    burger.addEventListener("click", function () { setMenu(!html.classList.contains("menu-open"), true); });
    $$("a", menu).forEach(function (a) { a.addEventListener("click", function () { setMenu(false, false); }); });
    doc.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && html.classList.contains("menu-open")) setMenu(false, true);
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth >= 1100 && html.classList.contains("menu-open")) setMenu(false, false);
    }, { passive: true });
  }

  /* ---------- FAQ accordion ---------- */
  $$(".qa").forEach(function (qa) {
    var q = $(".q", qa);
    q.setAttribute("aria-expanded", "false");
    q.addEventListener("click", function () {
      var open = !qa.classList.contains("open");
      qa.classList.toggle("open", open);
      q.setAttribute("aria-expanded", String(open));
    });
  });

  /* ---------- lightbox ---------- */
  var lb = $("#lb");
  var items = $$(".g-item");
  if (lb && items.length && typeof lb.showModal === "function") {
    var img = $("#lb-img"), cap = $("#lb-cap"), cnt = $("#lb-count"), fig = $("#lb-fig");
    var cur = 0, opener = null, closing = false;
    var pad2 = function (n) { return (n < 10 ? "0" : "") + n; };
    var show = function (i) {
      cur = (i + items.length) % items.length;
      var it = items[cur], thumb = $("img", it);
      img.src = it.getAttribute("data-full");
      img.alt = thumb ? thumb.alt : "";
      var t = $(".g-t b", it);
      cap.textContent = t ? t.textContent : "";
      cnt.textContent = pad2(cur + 1) + " / " + pad2(items.length);
      if (motion) { fig.classList.remove("swap"); void fig.offsetWidth; fig.classList.add("swap"); }
    };
    var close = function () {
      if (!lb.open || closing) return;
      var done = function () {
        closing = false; lb.classList.remove("closing"); lb.close();
        html.classList.remove("lb-open");
        if (opener) opener.focus({ preventScroll: true });
      };
      if (motion && !(reduceMq && reduceMq.matches)) {
        closing = true; lb.classList.add("closing");
        lb.addEventListener("animationend", function h(e) { if (e.target === lb) { lb.removeEventListener("animationend", h); done(); } });
        setTimeout(function () { if (closing) done(); }, 600);
      } else done();
    };
    items.forEach(function (it, i) {
      it.addEventListener("click", function () {
        if (closing || lb.open) return;
        opener = it; show(i);
        html.classList.add("lb-open");
        lb.showModal();
        $("#lb-x").focus({ preventScroll: true });
      });
    });
    $("#lb-x").addEventListener("click", close);
    $("#lb-prev").addEventListener("click", function () { show(cur - 1); });
    $("#lb-next").addEventListener("click", function () { show(cur + 1); });
    $("#lb-stage").addEventListener("click", function (e) { if (e.target === e.currentTarget) close(); });
    lb.addEventListener("cancel", function (e) { e.preventDefault(); close(); });
    lb.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight") { e.preventDefault(); show(cur + 1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); show(cur - 1); }
    });
  }

  /* ---------- release info from GitHub ---------- */
  if (window.fetch) {
    fetch("https://api.github.com/repos/candyqueenjr/TrueStretch/releases")
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (releases) {
        var latest = releases.filter(function (r) { return !r.prerelease && !r.draft; })[0];
        if (!latest) return;
        var exe = latest.assets.filter(function (a) { return a.name === "TrueStretch.exe"; })[0];
        $("#ver").textContent = "// Version " + latest.tag_name.replace(/^v/, "") + " · Free · Windows 10 & 11";
        if (exe) $("#size").textContent = Math.round(exe.size / 1048576) + " MB";
        var total = releases.reduce(function (n, r) {
          return n + r.assets.filter(function (a) { return a.name === "TrueStretch.exe"; })
            .reduce(function (m, a) { return m + a.download_count; }, 0);
        }, 0);
        if (total >= 10) $("#dls").textContent = total.toLocaleString() + " downloads";
      })
      .catch(function () {});
  }
})();
