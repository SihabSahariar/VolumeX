// VolumeX site: nav state, scroll reveals, the in-browser boost demo, the screen tour, the manual TOC.
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pdf = new URLSearchParams(location.search).has("pdf");  // print view used to make the PDF manual
  if (pdf) document.documentElement.classList.add("pdf");

  // Nav gets a background once you scroll.
  const nav = document.getElementById("nav");
  const onScroll = () => nav && !nav.hasAttribute("data-solid") && nav.classList.toggle("scrolled", scrollY > 12);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // Reveal sections as they enter the viewport.
  const targets = document.querySelectorAll(".stage, .try-grid, .how-grid article, .tile, .tour figure, .facts, .start-steps li, .credit-list, .mark");
  if ("IntersectionObserver" in window && !reduce && !pdf) {
    targets.forEach((el) => el.classList.add("reveal"));
    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    }), { rootMargin: "0px 0px -10% 0px" });
    targets.forEach((el) => io.observe(el));
  }

  // Tour: tabs swap the screenshot.
  const tabs = [...document.querySelectorAll(".tabs [role=tab]")];
  const tourImg = document.getElementById("tour-img");
  if (tourImg) {
    const view = document.getElementById("tour-view");
    const caption = document.getElementById("tour-caption");
    const label = document.getElementById("tour-label");
    const select = (tab) => {
      tabs.forEach((t) => { t.setAttribute("aria-selected", String(t === tab)); t.tabIndex = t === tab ? 0 : -1; });
      const next = new Image();
      next.onload = () => {
        tourImg.src = next.src;
        tourImg.alt = `${tab.textContent} screen`;
        view.classList.toggle("narrow", tab.hasAttribute("data-narrow"));
        tourImg.style.opacity = 1;
      };
      tourImg.style.opacity = 0;
      next.src = tab.dataset.src;
      caption.textContent = tab.dataset.caption;
      label.textContent = `VolumeX · ${tab.textContent}`;
    };
    tabs.forEach((tab, i) => {
      tab.tabIndex = i === 0 ? 0 : -1;
      tab.addEventListener("click", () => select(tab));
      tab.addEventListener("keydown", (e) => {
        const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
        if (!step) return;
        const next = tabs[(i + step + tabs.length) % tabs.length];
        next.focus();
        select(next);
      });
    });
  }

  // Manual: highlight the section in view; open every answer when printing.
  const links = [...document.querySelectorAll(".toc a")];
  const secs = links.map((a) => document.querySelector(a.getAttribute("href"))).filter(Boolean);
  if ("IntersectionObserver" in window && secs.length) {
    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (e.isIntersecting) links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${e.target.id}`));
    }), { rootMargin: "-25% 0px -65% 0px" });
    secs.forEach((s) => io.observe(s));
  }
  const openAll = () => document.querySelectorAll("details").forEach((d) => { d.open = true; });
  addEventListener("beforeprint", openAll);
  if (pdf) openAll();

  // --------------------------------------------------------------- the boost demo
  const demo = document.getElementById("demo");
  if (demo) boostDemo(demo);

  function boostDemo(root) {
    const playBtn = document.getElementById("demo-play");
    const gainEl = document.getElementById("demo-gain");
    const valueEl = document.getElementById("demo-value");
    const dbEl = document.getElementById("demo-db");
    const meterEl = document.getElementById("demo-meter");
    const guardEl = document.getElementById("demo-guard");
    const hint = document.getElementById("demo-hint");

    const BPM = 96, BEAT = 60 / BPM, BAR = BEAT * 4;
    const CHORDS = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]];  // Am F C G
    const BASS = [45, 41, 36, 43];
    const ARP = [0, 1, 2, 1, 0, 2, 1, 2];
    const hz = (m) => 440 * 2 ** ((m - 69) / 12);

    let ctx = null, music, boost, analyser, guard, clip, noise, timer = 0, nextBar = 0, bar = 0, playing = false;
    let hintState = "", peakHold = 0;
    const buf = new Float32Array(1024);

    const paint = () => {
      const v = +gainEl.value, end = v / 3, knee = 100 / 3;
      const rest = "rgba(255,255,255,.1)";
      gainEl.style.setProperty("--track", v <= 100
        ? `linear-gradient(90deg, #22D3EE 0%, #C084FC ${end}%, ${rest} ${end}%)`
        : `linear-gradient(90deg, #22D3EE 0%, #C084FC ${knee}%, #FBBF24 ${knee}%, #FB7185 ${(knee + end) / 2}%, #E879F9 ${end}%, ${rest} ${end}%)`);
      gainEl.style.setProperty("--thumb", v > 100 ? "#FB7185" : "#818CF8");
      valueEl.textContent = `${v}%`;
      const db = 20 * Math.log10(v / 100);
      dbEl.textContent = v === 0 ? "−∞ dB" : Math.abs(db) < 0.05 ? "0 dB" : `${db > 0 ? "+" : "−"}${Math.abs(db).toFixed(1)} dB`;
      root.classList.toggle("boosted", v > 100);
      if (boost) boost.gain.setTargetAtTime(v / 100, ctx.currentTime, 0.03);
    };

    const say = (state, text) => {
      if (state === hintState) return;
      hintState = state;
      hint.className = `hint ${state}`;
      hint.textContent = text;
    };

    const wire = () => {
      boost.disconnect();
      boost.connect(analyser);
      boost.connect(guardEl.checked ? guard : clip);
    };

    const build = () => {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      music = ctx.createGain();
      music.gain.value = 0.4;  // mastered quietly, like many videos
      boost = ctx.createGain();
      boost.gain.value = gainEl.value / 100;
      analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      guard = ctx.createDynamicsCompressor();  // the "Distortion Guard": a fast, hard limiter
      guard.threshold.value = -1.5;
      guard.knee.value = 0;
      guard.ratio.value = 20;
      guard.attack.value = 0.002;
      guard.release.value = 0.1;
      clip = ctx.createWaveShaper();  // full scale: anything past ±1 is clipped, like a real output
      const curve = new Float32Array(2049);
      for (let i = 0; i < curve.length; i++) curve[i] = (i / (curve.length - 1)) * 2 - 1;
      clip.curve = curve;
      const out = ctx.createGain();
      out.gain.value = 0.6;  // keep the whole demo at a sensible loudness
      music.connect(boost);
      guard.connect(clip);
      clip.connect(out).connect(ctx.destination);
      wire();
      noise = ctx.createBuffer(1, ctx.sampleRate * 0.3, ctx.sampleRate);
      const data = noise.getChannelData(0);
      for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    };

    const tone = (t, freq, dur, type, peak, attack = 0.005) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = type;
      o.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.linearRampToValueAtTime(peak, t + attack);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g).connect(music);
      o.start(t);
      o.stop(t + dur + 0.05);
    };

    const kick = (t) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.setValueAtTime(140, t);
      o.frequency.exponentialRampToValueAtTime(42, t + 0.16);
      g.gain.setValueAtTime(0.75, t);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.34);
      o.connect(g).connect(music);
      o.start(t);
      o.stop(t + 0.4);
    };

    const hit = (t, freq, gain, dur) => {
      const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
      s.buffer = noise;
      f.type = freq > 5000 ? "highpass" : "bandpass";
      f.frequency.value = freq;
      g.gain.setValueAtTime(gain, t);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      s.connect(f).connect(g).connect(music);
      s.start(t);
      s.stop(t + dur + 0.02);
    };

    const scheduleBar = (i, t) => {
      const chord = CHORDS[i % 4];
      chord.forEach((m) => { tone(t, hz(m), BAR, "sawtooth", 0.035, 0.25); tone(t, hz(m) * 1.004, BAR, "triangle", 0.05, 0.25); });
      ARP.forEach((k, n) => tone(t + n * BEAT / 2, hz(chord[k] + 12), 0.3, "triangle", 0.14));
      tone(t, hz(BASS[i % 4]), BEAT * 1.8, "sine", 0.32, 0.01);
      tone(t + 2 * BEAT, hz(BASS[i % 4]), BEAT * 1.8, "sine", 0.28, 0.01);
      kick(t);
      kick(t + 2 * BEAT);
      hit(t + BEAT, 1800, 0.35, 0.14);
      hit(t + 3 * BEAT, 1800, 0.35, 0.14);
      for (let b = 0; b < 4; b++) hit(t + b * BEAT + BEAT / 2, 7500, 0.12, 0.05);
    };

    const tick = () => {
      while (nextBar < ctx.currentTime + 0.4) { scheduleBar(bar++, nextBar); nextBar += BAR; }
    };

    const meter = () => {
      if (!playing) { meterEl.style.width = "0%"; return; }
      analyser.getFloatTimeDomainData(buf);
      let peak = 0;
      for (let i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i]));
      peakHold = Math.max(peak, peakHold * 0.94);
      meterEl.style.width = `${Math.min(100, (guardEl.checked ? Math.min(peakHold, 1) : peakHold) / 1.333 * 100)}%`;
      const v = +gainEl.value;
      if (peakHold > 1 && guardEl.checked) say("guard", "Distortion Guard is catching the peaks - still clean.");
      else if (peakHold > 1) say("clip", "Clipping! That crackle is what the guard prevents.");
      else say("clean", v > 100 ? "Boosted - and clean." : "Playing at normal volume.");
      requestAnimationFrame(meter);
    };

    const setPlaying = (on) => {
      playing = on;
      playBtn.innerHTML = `<svg><use href="#i-${on ? "pause" : "play"}"/></svg>`;
      playBtn.setAttribute("aria-label", on ? "Pause the demo" : "Play the demo");
    };

    playBtn.addEventListener("click", async () => {
      if (!ctx) build();
      if (playing) {
        clearInterval(timer);
        await ctx.suspend();
        setPlaying(false);
        say("", "Paused.");
        return;
      }
      await ctx.resume();
      if (nextBar < ctx.currentTime) nextBar = ctx.currentTime + 0.08;
      tick();
      timer = setInterval(tick, 100);
      setPlaying(true);
      requestAnimationFrame(meter);
    });
    gainEl.addEventListener("input", paint);
    gainEl.addEventListener("dblclick", () => { gainEl.value = 100; paint(); });
    guardEl.addEventListener("change", () => { if (ctx) wire(); hintState = ""; });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && playing) playBtn.click();
    });
    paint();
  }
})();
