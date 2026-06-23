/* Midnight Radio — SSE Client */

(function () {
  "use strict";

  // ── DOM refs ──────────────────────────────────────────────────────
  const $ambilight = document.getElementById("ambilight");
  const $albumArtWrap = document.getElementById("album-art-wrap");
  const $albumArt = document.getElementById("album-art");
  const $albumPlaceholder = document.getElementById("album-placeholder");
  const $trackName = document.getElementById("track-name");
  const $trackArtist = document.getElementById("track-artist");
  const $onAir = document.getElementById("on-air");
  const $teleprompter = document.getElementById("teleprompter");
  const $monologueText = document.getElementById("monologue-text");
  const $micStatus = document.getElementById("mic-status");
  const $nextTrack = document.getElementById("next-track");
  const $djState = document.getElementById("dj-state");
  const $connection = document.getElementById("connection");
  const $eqSpectrum = document.getElementById("eq-spectrum");
  const eqBars = $eqSpectrum
    ? Array.prototype.slice.call($eqSpectrum.querySelectorAll(".eq-bar"))
    : [];
  const $spectrumCapture = document.getElementById("spectrum-capture");
  const $spectrumStatus = document.getElementById("spectrum-status");
  const $clock = document.getElementById("clock");
  const $stationIntro = document.getElementById("station-intro");
  const $tickerDj = document.getElementById("ticker-dj");
  const $tickerBreak = document.getElementById("ticker-break");
  const backdropLayers = $ambilight
    ? Array.prototype.slice.call($ambilight.querySelectorAll(".ambilight-layer"))
    : [];

  function ensureControlRoom() {
    if (document.getElementById("control-room")) return;

    var oldDrawer = document.getElementById("settings-drawer");
    var oldBody = oldDrawer ? oldDrawer.querySelector(".drawer-body") : null;
    var container = document.querySelector(".container");
    if (!oldBody || !container) return;

    var section = document.createElement("section");
    section.id = "control-room";
    section.className = "control-room reveal-section is-visible";
    section.setAttribute("aria-label", "Broadcast controls and hourly news links");

    var inner = document.createElement("div");
    inner.className = "control-room-inner";
    inner.innerHTML = [
      '<div class="control-room-heading">',
      '<span class="section-kicker">CONTROL ROOM</span>',
      '<h2>Broadcast Settings</h2>',
      '</div>',
      '<div class="control-room-grid">',
      '<div class="control-panel settings-panel"><div class="panel-title">Station Controls</div></div>',
      '<div class="control-panel news-panel">',
      '<div class="panel-title">Hourly News Links</div>',
      '<div id="news-meta" class="news-meta">Loading latest articles...</div>',
      '<div id="news-links" class="news-links" aria-live="polite"></div>',
      '<button id="news-refresh" class="news-refresh" type="button">Refresh Links</button>',
      '</div>',
      '</div>'
    ].join("");

    var settingsPanel = inner.querySelector(".settings-panel");
    Array.prototype.slice.call(oldBody.children).forEach(function (row) {
      row.classList.add("control-row");
      settingsPanel.appendChild(row);
    });

    section.appendChild(inner);
    container.insertAdjacentElement("afterend", section);
  }

  ensureControlRoom();

  // ── State ─────────────────────────────────────────────────────────
  let typewriterTimer = null;
  let boothResetTimer = null;
  let trackTransitionTimer = null;
  let introTimer = null;
  let currentTrackKey = "";
  let currentTrackTiming = null;
  let visualizerLevels = eqBars.map(function () { return 0.12; });
  let activeBackdropLayer = 0;
  let currentBackdropUrl = "";
  let audioContext = null;
  let analyser = null;
  let analyserData = null;
  let captureStream = null;
  let captureSource = null;

  // ── Studio Clock ─────────────────────────────────────────────────

  function startClock() {
    function tick() {
      var now = new Date();
      var h = String(now.getHours()).padStart(2, "0");
      var m = String(now.getMinutes()).padStart(2, "0");
      var s = String(now.getSeconds()).padStart(2, "0");
      $clock.textContent = h + ":" + m + ":" + s;
    }
    tick();
    setInterval(tick, 1000);
  }

  function formatClock(seconds) {
    if (seconds == null || !isFinite(seconds) || seconds < 0) return "--:--";
    var total = Math.max(0, Math.floor(seconds));
    var m = String(Math.floor(total / 60)).padStart(2, "0");
    var s = String(total % 60).padStart(2, "0");
    return m + ":" + s;
  }

  function updateTrackCountdown() {
    if (!currentTrackTiming) {
      if ($tickerBreak) $tickerBreak.textContent = "NEXT BREAK --:--";
      return;
    }

    var elapsedMs = Date.now() - currentTrackTiming.updatedAt;
    var progressMs = Math.min(
      currentTrackTiming.durationMs,
      currentTrackTiming.progressMs + elapsedMs
    );
    var remainingSec = Math.max(0, (currentTrackTiming.durationMs - progressMs) / 1000);

    if ($tickerBreak) $tickerBreak.textContent = "NEXT BREAK " + formatClock(remainingSec);
  }

  function startProgressLoop() {
    updateTrackCountdown();
    setInterval(updateTrackCountdown, 1000);
  }

  // ── SSE connection ────────────────────────────────────────────────

  function connect() {
    const es = new EventSource("/api/events");

    es.onopen = function () {
      $connection.textContent = "● connected";
      $connection.classList.remove("disconnected");
      $connection.classList.add("connected");
      // Fetch initial state on connect.
      fetchStatus();
    };

    es.addEventListener("state", function (e) {
      const data = JSON.parse(e.data);
      updateState(data.dj_state);
    });

    es.addEventListener("track", function (e) {
      const data = JSON.parse(e.data);
      updateTrack(data.current_track);
    });

    es.addEventListener("monologue", function (e) {
      const data = JSON.parse(e.data);
      showMonologue(data.text);
    });

    es.addEventListener("monologue_clear", function () {
      resetBooth();
    });

    es.addEventListener("next_track", function (e) {
      const data = JSON.parse(e.data);
      updateNextTrack(data.next_track);
    });

    es.onerror = function () {
      $connection.textContent = "● disconnected";
      $connection.classList.remove("connected");
      $connection.classList.add("disconnected");
      es.close();
      // Reconnect after 3 seconds.
      setTimeout(connect, 3000);
    };
  }

  // ── Fetch initial status via REST ─────────────────────────────────

  function fetchStatus() {
    fetch("/api/status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        updateState(data.dj_state);
        updateTrack(data.current_track);
        updateNextTrack(data.next_track);
      })
      .catch(function () { /* will retry via SSE reconnect */ });
  }

  // ── Update functions ──────────────────────────────────────────────

  function setVisualState(state) {
    const normalized = state || "IDLE";
    const speaking = normalized === "SPEAKING";
    const ducking = normalized === "DUCKING_IN" || normalized === "DUCKING_OUT";
    const live = speaking;

    document.body.classList.toggle("is-speaking", speaking);
    document.body.classList.toggle("is-ducking", ducking);
    document.body.classList.toggle("is-idle", !live);

    if (live) {
      $onAir.classList.add("on");
      $onAir.classList.remove("off");
      $albumArtWrap.classList.add("speaking");
    } else {
      $onAir.classList.remove("on");
      $onAir.classList.add("off");
      $albumArtWrap.classList.remove("speaking");
    }

    if ($tickerDj) $tickerDj.textContent = "AI DJ " + normalized.replace(/_/g, " ");
  }

  // ── Dynamic backdrop ─────────────────────────────────────────────

  function cssUrl(url) {
    return 'url("' + String(url).replace(/"/g, '\\"') + '")';
  }

  function updateBackdrop(albumArtUrl) {
    var nextUrl = albumArtUrl || "";
    console.log("Backdrop URL:", nextUrl);
    if (!$ambilight || !backdropLayers.length || nextUrl === currentBackdropUrl) return;

    currentBackdropUrl = nextUrl;
    var nextLayerIndex = activeBackdropLayer === 0 ? 1 : 0;
    var nextLayer = backdropLayers[nextLayerIndex];
    var previousLayer = backdropLayers[activeBackdropLayer];

    console.log("Applying to layer:", nextLayerIndex, "URL:", cssUrl(nextUrl));
    nextLayer.style.backgroundImage = nextUrl ? cssUrl(nextUrl) : "none";
    nextLayer.classList.add("active");
    previousLayer.classList.remove("active");
    activeBackdropLayer = nextLayerIndex;
    $ambilight.classList.toggle("has-backdrop", Boolean(nextUrl));
  }

  // ── Bottom visualizer ────────────────────────────────────────────

  function setSpectrumState(state, label) {
    if ($spectrumStatus) $spectrumStatus.textContent = label || "INPUT";
    if ($spectrumCapture) {
      $spectrumCapture.classList.remove("is-live", "is-pending", "is-error");
      if (state) $spectrumCapture.classList.add("is-" + state);
    }
    if ($eqSpectrum) {
      $eqSpectrum.classList.toggle("active", state === "live");
    }
  }

  function cleanupCapture() {
    if (captureSource) {
      try { captureSource.disconnect(); } catch (_) { /* already disconnected */ }
      captureSource = null;
    }

    if (captureStream) {
      captureStream.getTracks().forEach(function (track) { track.stop(); });
      captureStream = null;
    }

    analyser = null;
    analyserData = null;
  }

  async function requestSpectrumCapture() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      setSpectrumState("error", "N/A");
      return;
    }

    setSpectrumState("pending", "WAIT");

    try {
      var sharedStream = await navigator.mediaDevices.getDisplayMedia({
        audio: true,
        video: true
      });

      sharedStream.getVideoTracks().forEach(function (track) { track.stop(); });
      var audioTracks = sharedStream.getAudioTracks();

      if (!audioTracks.length) {
        sharedStream.getTracks().forEach(function (track) { track.stop(); });
        setSpectrumState("error", "NO AUDIO");
        return;
      }

      cleanupCapture();
      captureStream = new MediaStream(audioTracks);
      audioContext = audioContext || new (window.AudioContext || window.webkitAudioContext)();
      await audioContext.resume();

      analyser = audioContext.createAnalyser();
      analyser.fftSize = 1024;
      analyser.minDecibels = -92;
      analyser.maxDecibels = -18;
      analyser.smoothingTimeConstant = 0.86;
      analyserData = new Uint8Array(analyser.frequencyBinCount);
      captureSource = audioContext.createMediaStreamSource(captureStream);
      captureSource.connect(analyser);

      audioTracks.forEach(function (track) {
        track.addEventListener("ended", function () {
          cleanupCapture();
          setSpectrumState("", "INPUT");
        });
      });

      setSpectrumState("live", "LIVE");
    } catch (_) {
      cleanupCapture();
      setSpectrumState("error", "DENIED");
    }
  }

  let visualizerTime = 0;

  function getSimulatedBarLevel(index, timeOffset) {
    var bands = eqBars.length || 24;
    var t = visualizerTime * 0.001; // Convert to seconds
    
    // Create multiple overlapping sine waves for natural variation
    var sine1 = Math.sin((t + index * 0.15) * 1.2) * 0.35;
    var sine2 = Math.sin((t * 0.7 + index * 0.08) * 0.8) * 0.25;
    var sine3 = Math.sin((t * 1.3 + index * 0.22) * 1.5) * 0.20;
    
    // Add pseudo-random base pattern
    var seed = index * 7.1 + Math.sin(t * 0.3) * 5;
    var noise = Math.abs(Math.sin(seed) * Math.cos(seed * 1.3)) * 0.15;
    
    // Combine waves with bass boost for lower frequencies
    var bassBoost = Math.max(0, 1 - (index / bands) * 0.3);
    var combined = (sine1 + sine2 + sine3) * 0.5 + noise + bassBoost * 0.25;
    
    // Clamp to visible range
    var level = Math.max(0.08, Math.min(0.98, combined + 0.45));
    return level;
  }

  function updateVisualizer() {
    visualizerTime += 16; // Approximate 60fps frame time
    var isPlaying = document.body.classList.contains("is-speaking") || 
                   document.body.classList.contains("has-track");

    eqBars.forEach(function (bar, index) {
      var target = isPlaying ? getSimulatedBarLevel(index, visualizerTime) : 0.10;
      visualizerLevels[index] += (target - visualizerLevels[index]) * (isPlaying ? 0.18 : 0.08);
      bar.style.transform = "scaleY(" + visualizerLevels[index].toFixed(3) + ")";
      bar.style.opacity = isPlaying ? "0.95" : "0.32";
    });

    window.requestAnimationFrame(updateVisualizer);
  }

  function startVisualizer() {
    if ($spectrumCapture) {
      $spectrumCapture.addEventListener("click", requestSpectrumCapture);
    }

    setSpectrumState("", "INPUT");
    if (eqBars.length) window.requestAnimationFrame(updateVisualizer);
  }

  // ── Station boot intro ────────────────────────────────────────────

  function prefersReducedMotion() {
    return window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function finishStationIntro() {
    if (introTimer) {
      clearTimeout(introTimer);
      introTimer = null;
    }

    document.body.classList.remove("is-booting");
    document.body.classList.add("has-booted");

    if ($stationIntro) {
      $stationIntro.classList.add("finished");
      setTimeout(function () {
        $stationIntro.setAttribute("hidden", "hidden");
      }, prefersReducedMotion() ? 20 : 420);
    }
  }

  function runStationIntro() {
    if (!$stationIntro || prefersReducedMotion()) {
      finishStationIntro();
      return;
    }

    introTimer = setTimeout(finishStationIntro, 3900);
  }

  function getTrackKey(track) {
    if (!track) return "";
    return [
      track.name || "",
      track.artist || "",
      track.album_art_url || ""
    ].join("|");
  }

  function triggerTrackCrossfade() {
    if (trackTransitionTimer) {
      clearTimeout(trackTransitionTimer);
      trackTransitionTimer = null;
    }

    document.body.classList.remove("track-changing");
    // Force the animation to replay if Spotify sends rapid updates.
    void document.body.offsetWidth;
    document.body.classList.add("track-changing");

    trackTransitionTimer = setTimeout(function () {
      document.body.classList.remove("track-changing");
      trackTransitionTimer = null;
    }, 2200);
  }

  function updateState(state) {
    if (!state) return;
    $djState.textContent = state;
    setVisualState(state);

    // Reset DJ booth when back to IDLE.
    if (state === "IDLE") {
      // Stop the typewriter animation but keep the text readable for a moment,
      // then clear the booth after a short grace period.
      stopTypewriter();
      $micStatus.textContent = "● MIC MUTED";
      $micStatus.classList.add("muted");
      $micStatus.classList.remove("live");
      scheduleBoothReset(9000);
    }
  }

  function updateTrack(track) {
    const nextTrackKey = getTrackKey(track);
    const changed = nextTrackKey !== currentTrackKey;

    if (changed) {
      currentTrackKey = nextTrackKey;
      triggerTrackCrossfade();
    }

    if (!track) {
      document.body.classList.remove("has-track");
      currentTrackTiming = null;
      updateTrackCountdown();
      $trackName.textContent = "Waiting for Spotify…";
      $trackArtist.innerHTML = "&nbsp;";
      $albumArt.classList.remove("visible");
      $albumPlaceholder.classList.remove("hidden");
      updateBackdrop("");
      return;
    }

    document.body.classList.add("has-track");
    currentTrackTiming = {
      durationMs: Number(track.duration_ms) || 0,
      progressMs: Number(track.progress_ms) || 0,
      updatedAt: Date.now()
    };
    updateTrackCountdown();
    $trackName.textContent = track.name;
    $trackArtist.textContent = track.artist;

    if (track.album_art_url) {
      if ($albumArt.getAttribute("src") !== track.album_art_url) {
        $albumArt.src = track.album_art_url;
      }
      $albumArt.classList.add("visible");
      $albumPlaceholder.classList.add("hidden");
      updateBackdrop(track.album_art_url);
    } else {
      $albumArt.classList.remove("visible");
      $albumPlaceholder.classList.remove("hidden");
      updateBackdrop("");
    }
  }

  function updateNextTrack(track) {
    if ($nextTrack.textContent !== (track ? track.name + " \u2014 " + track.artist : "\u2014")) {
      $nextTrack.classList.remove("updated");
      void $nextTrack.offsetWidth;
      $nextTrack.classList.add("updated");
    }

    $nextTrack.textContent = track
      ? track.name + " \u2014 " + track.artist
      : "\u2014";
  }

  function showMonologue(text) {
    if (!text) {
      resetBooth();
      return;
    }
    // Cancel any pending auto-clear and stop current animation.
    if (boothResetTimer) { clearTimeout(boothResetTimer); boothResetTimer = null; }
    stopTypewriter();
    $teleprompter.classList.add("typing");
    $monologueText.textContent = "";
    $micStatus.textContent = "● ON MIC";
    $micStatus.classList.remove("muted");
    $micStatus.classList.add("live");

    var idx = 0;
    var cursor = document.createElement("span");
    cursor.className = "cursor";

    typewriterTimer = setInterval(function () {
      if (idx < text.length) {
        // Remove cursor, add char, re-add cursor.
        if (cursor.parentNode) cursor.parentNode.removeChild(cursor);
        $monologueText.textContent += text[idx];
        $monologueText.appendChild(cursor);
        idx++;
      } else {
        clearInterval(typewriterTimer);
        typewriterTimer = null;
        $teleprompter.classList.remove("typing");
        // Remove cursor after a short pause.
        setTimeout(function () {
          if (cursor.parentNode) cursor.parentNode.removeChild(cursor);
        }, 2000);
      }
    }, 30);
  }

  // Stop the typewriter animation without clearing the displayed text.
  function stopTypewriter() {
    if (typewriterTimer) {
      clearInterval(typewriterTimer);
      typewriterTimer = null;
    }
    $teleprompter.classList.remove("typing");
    var cursor = $monologueText.querySelector(".cursor");
    if (cursor && cursor.parentNode) cursor.parentNode.removeChild(cursor);
  }

  // Fully reset the DJ booth to its idle/waiting state.
  function resetBooth() {
    stopTypewriter();
    $monologueText.innerHTML = '<span class="mic-muted-placeholder">Hold tight. The DJ will speak shortly.</span>';
    $micStatus.textContent = "● MIC MUTED";
    $micStatus.classList.add("muted");
    $micStatus.classList.remove("live");
  }

  // Schedule a booth reset after `ms` milliseconds, cancelling any prior one.
  function scheduleBoothReset(ms) {
    if (boothResetTimer) { clearTimeout(boothResetTimer); boothResetTimer = null; }
    boothResetTimer = setTimeout(function () {
      boothResetTimer = null;
      resetBooth();
    }, ms);
  }

  // ── Control Room settings ─────────────────────────────────────────
  var $toggleDj        = document.getElementById('toggle-dj');
  var $toggleNews      = document.getElementById('toggle-news');
  var $toggleDuo       = document.getElementById('toggle-duo');
  var $toggleImaging   = document.getElementById('toggle-imaging');
  var $toggleCommercials = document.getElementById('toggle-commercials');
  var $triggerInput    = document.getElementById('trigger-before-end');
  var $visualMode      = document.getElementById('visual-mode');
  var $newsLinks       = document.getElementById('news-links');
  var $newsMeta        = document.getElementById('news-meta');
  var $newsRefresh     = document.getElementById('news-refresh');

  function applySettings(settings) {
    if (!settings) return;
    if ($toggleDj)        $toggleDj.checked = Boolean(settings.dj_enabled);
    if ($toggleNews)      $toggleNews.checked = Boolean(settings.top_of_hour_news_enabled);
    if ($toggleDuo)       $toggleDuo.checked = Boolean(settings.duo_mode_enabled);
    if ($toggleImaging)   $toggleImaging.checked = Boolean(settings.radio_imaging_enabled);
    if ($toggleCommercials) $toggleCommercials.checked = Boolean(settings.fake_commercials_enabled);
    if ($triggerInput && settings.trigger_before_end_sec != null) {
      $triggerInput.value = String(Math.round(Number(settings.trigger_before_end_sec)));
    }
  }

  function fetchSettings() {
    fetch("/api/settings")
      .then(function (r) { return r.json(); })
      .then(applySettings)
      .catch(function () { /* settings are non-critical */ });
  }

  function patchSettings(update) {
    fetch("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update)
    })
      .then(function (r) { return r.json(); })
      .then(applySettings)
      .catch(fetchSettings);
  }

  function bindToggle(el, key) {
    if (!el) return;
    el.addEventListener("change", function () {
      var update = {};
      update[key] = el.checked;
      patchSettings(update);
    });
  }

  function setVisualMode(mode) {
    var nextMode = mode === "calm" || mode === "neon" ? mode : "cinematic";
    document.body.classList.remove("mode-calm", "mode-cinematic", "mode-neon");
    document.body.classList.add("mode-" + nextMode);
    if ($visualMode) $visualMode.value = nextMode;
    try {
      window.localStorage.setItem("midnightRadioVisualMode", nextMode);
    } catch (_) { /* localStorage is optional */ }
  }

  function loadVisualMode() {
    var saved = "cinematic";
    try {
      saved = window.localStorage.getItem("midnightRadioVisualMode") || saved;
    } catch (_) { /* localStorage is optional */ }
    setVisualMode(saved);
  }

  bindToggle($toggleDj, "dj_enabled");
  bindToggle($toggleNews, "top_of_hour_news_enabled");
  bindToggle($toggleDuo, "duo_mode_enabled");
  bindToggle($toggleImaging, "radio_imaging_enabled");
  bindToggle($toggleCommercials, "fake_commercials_enabled");

  if ($triggerInput) {
    $triggerInput.addEventListener("change", function () {
      patchSettings({ trigger_before_end_sec: Number($triggerInput.value) });
    });
  }

  if ($visualMode) {
    $visualMode.addEventListener("change", function () {
      setVisualMode($visualMode.value);
    });
  }

  // ── Hourly news links ─────────────────────────────────────────────

  function categoryLabel(category) {
    if (category === "world") return "World";
    if (category === "country") return "Poland";
    if (category === "local") return "Warsaw";
    return "News";
  }

  function renderNewsLinks(payload) {
    if (!$newsLinks) return;
    var articles = payload && Array.isArray(payload.articles) ? payload.articles : [];
    $newsLinks.textContent = "";

    if ($newsMeta) {
      var metaText = "Latest RSS article links";
      if (payload && payload.hour) metaText = "Latest top-of-hour bulletin: " + payload.hour;
      if (payload && payload.updated_at) {
        var updated = new Date(payload.updated_at);
        if (!isNaN(updated.getTime())) {
          metaText += " · " + updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        }
      }
      $newsMeta.textContent = metaText;
    }

    if (!articles.length) {
      var empty = document.createElement("p");
      empty.className = "news-empty";
      empty.textContent = "No article links are available yet.";
      $newsLinks.appendChild(empty);
      return;
    }

    var groups = {};
    articles.forEach(function (article) {
      var category = article.category || "news";
      if (!groups[category]) groups[category] = [];
      groups[category].push(article);
    });

    ["world", "country", "local", "news"].forEach(function (category) {
      if (!groups[category] || !groups[category].length) return;

      var group = document.createElement("section");
      group.className = "news-group";

      var heading = document.createElement("h3");
      heading.textContent = categoryLabel(category);
      group.appendChild(heading);

      groups[category].forEach(function (article) {
        var link = document.createElement("a");
        link.className = "news-link";
        link.href = article.url || "#";
        link.target = "_blank";
        link.rel = "noopener noreferrer";

        var title = document.createElement("span");
        title.className = "news-title";
        title.textContent = article.title || "Untitled article";

        var source = document.createElement("span");
        source.className = "news-source";
        source.textContent = article.source || "RSS";

        link.appendChild(title);
        link.appendChild(source);
        group.appendChild(link);
      });

      $newsLinks.appendChild(group);
    });
  }

  function fetchNewsLinks() {
    if (!$newsLinks) return;
    if ($newsMeta) $newsMeta.textContent = "Loading latest articles...";
    fetch("/api/news/latest")
      .then(function (r) { return r.json(); })
      .then(renderNewsLinks)
      .catch(function () {
        if ($newsMeta) $newsMeta.textContent = "Article links are unavailable right now.";
        renderNewsLinks({ articles: [] });
      });
  }

  if ($newsRefresh) {
    $newsRefresh.addEventListener("click", fetchNewsLinks);
  }

  // ── Scroll section reveal ─────────────────────────────────────────

  function setupSectionReveal() {
    var sections = Array.prototype.slice.call(document.querySelectorAll(".reveal-section"));
    if (!sections.length) return;
    if (!("IntersectionObserver" in window) || prefersReducedMotion()) {
      sections.forEach(function (section) { section.classList.add("is-visible"); });
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) entry.target.classList.add("is-visible");
      });
    }, { threshold: 0.18 });

    sections.forEach(function (section) { observer.observe(section); });
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function setupScrollParallax() {
    var controlRoom = document.getElementById("control-room");
    var reduceMotion = prefersReducedMotion();
    var ticking = false;

    function setParallaxVar(name, value) {
      document.body.style.setProperty(name, value);
    }

    if (!controlRoom || reduceMotion) {
      [
        ["--control-progress", "1"],
        ["--radio-exit", "0"],
        ["--control-enter", "1"],
        ["--heading-enter", "1"],
        ["--settings-enter", "1"],
        ["--news-enter", "1"],
        ["--radio-opacity", "1"],
        ["--radio-y", "0px"],
        ["--radio-scale", "1"],
        ["--radio-blur", "0px"],
        ["--header-opacity", "1"],
        ["--header-y", "0px"],
        ["--header-scale", "1"],
        ["--album-opacity", "1"],
        ["--album-y", "0px"],
        ["--album-scale", "1"],
        ["--album-rotate", "0deg"],
        ["--album-blur", "0px"],
        ["--track-opacity", "1"],
        ["--track-y", "0px"],
        ["--booth-opacity", "1"],
        ["--booth-y", "0px"],
        ["--control-lift", "0px"],
        ["--control-glow-y", "0px"],
        ["--control-glow-scale", "1"],
        ["--heading-opacity", "1"],
        ["--heading-y", "0px"],
        ["--heading-z", "0px"],
        ["--heading-scale", "1"],
        ["--settings-opacity", "1"],
        ["--settings-x", "0px"],
        ["--settings-y", "0px"],
        ["--settings-z", "0px"],
        ["--settings-rotate", "0deg"],
        ["--settings-scale", "1"],
        ["--news-opacity", "1"],
        ["--news-x", "0px"],
        ["--news-y", "0px"],
        ["--news-z", "0px"],
        ["--news-rotate", "0deg"],
        ["--news-scale", "1"]
      ].forEach(function (item) { setParallaxVar(item[0], item[1]); });
      return;
    }

    function update() {
      ticking = false;
      var rect = controlRoom.getBoundingClientRect();
      var viewportHeight = window.innerHeight || document.documentElement.clientHeight || 1;
      var rawProgress = ((viewportHeight * 0.70) - rect.top) / (viewportHeight * 0.62);
      var progress = clamp(rawProgress, 0, 1);

      var radioExit = clamp(progress * 1.18, 0, 1);
      var headingEnter = clamp(progress * 1.65, 0, 1);
      var settingsEnter = clamp((progress - 0.10) * 1.75, 0, 1);
      var newsEnter = clamp((progress - 0.20) * 1.75, 0, 1);

      setParallaxVar("--control-progress", progress.toFixed(3));
      setParallaxVar("--radio-exit", radioExit.toFixed(3));
      setParallaxVar("--control-enter", progress.toFixed(3));
      setParallaxVar("--heading-enter", headingEnter.toFixed(3));
      setParallaxVar("--settings-enter", settingsEnter.toFixed(3));
      setParallaxVar("--news-enter", newsEnter.toFixed(3));

      setParallaxVar("--radio-opacity", (1 - radioExit * 0.58).toFixed(3));
      setParallaxVar("--radio-y", (-132 * radioExit).toFixed(1) + "px");
      setParallaxVar("--radio-scale", (1 - radioExit * 0.105).toFixed(4));
      setParallaxVar("--radio-blur", "0px");

      setParallaxVar("--header-opacity", (1 - radioExit * 0.82).toFixed(3));
      setParallaxVar("--header-y", (-92 * radioExit).toFixed(1) + "px");
      setParallaxVar("--header-scale", (1 - radioExit * 0.075).toFixed(4));

      setParallaxVar("--album-opacity", (1 - radioExit * 0.30).toFixed(3));
      setParallaxVar("--album-y", (-188 * radioExit).toFixed(1) + "px");
      setParallaxVar("--album-scale", (1 - radioExit * 0.24).toFixed(4));
      setParallaxVar("--album-rotate", (-4.5 * radioExit).toFixed(2) + "deg");
      setParallaxVar("--album-blur", "0px");

      setParallaxVar("--track-opacity", (1 - radioExit * 0.74).toFixed(3));
      setParallaxVar("--track-y", (-118 * radioExit).toFixed(1) + "px");
      setParallaxVar("--booth-opacity", (1 - radioExit * 0.68).toFixed(3));
      setParallaxVar("--booth-y", (86 * radioExit).toFixed(1) + "px");
      setParallaxVar("--control-lift", (96 * (1 - progress)).toFixed(1) + "px");
      setParallaxVar("--control-glow-y", (-40.3 * (1 - progress)).toFixed(1) + "px");
      setParallaxVar("--control-glow-scale", (0.74 + progress * 0.26).toFixed(4));

      setParallaxVar("--heading-opacity", (0.02 + headingEnter * 0.98).toFixed(3));
      setParallaxVar("--heading-y", (170 * (1 - headingEnter)).toFixed(1) + "px");
      setParallaxVar("--heading-z", (-260 * (1 - headingEnter)).toFixed(1) + "px");
      setParallaxVar("--heading-scale", (0.92 + headingEnter * 0.08).toFixed(4));
      setParallaxVar("--settings-opacity", (0.04 + settingsEnter * 0.96).toFixed(3));
      setParallaxVar("--settings-x", (-60 * (1 - settingsEnter)).toFixed(1) + "px");
      setParallaxVar("--settings-y", (230 * (1 - settingsEnter)).toFixed(1) + "px");
      setParallaxVar("--settings-z", (-340 * (1 - settingsEnter)).toFixed(1) + "px");
      setParallaxVar("--settings-rotate", (8 * (1 - settingsEnter)).toFixed(2) + "deg");
      setParallaxVar("--settings-scale", (0.88 + settingsEnter * 0.12).toFixed(4));
      setParallaxVar("--news-opacity", (0.03 + newsEnter * 0.97).toFixed(3));
      setParallaxVar("--news-x", (74 * (1 - newsEnter)).toFixed(1) + "px");
      setParallaxVar("--news-y", (290 * (1 - newsEnter)).toFixed(1) + "px");
      setParallaxVar("--news-z", (-430 * (1 - newsEnter)).toFixed(1) + "px");
      setParallaxVar("--news-rotate", (9 * (1 - newsEnter)).toFixed(2) + "deg");
      setParallaxVar("--news-scale", (0.86 + newsEnter * 0.14).toFixed(4));
    }

    function requestUpdate() {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(update);
    }

    update();
    window.addEventListener("scroll", requestUpdate, { passive: true });
    window.addEventListener("resize", requestUpdate, { passive: true });
  }

  // ── Boot ──────────────────────────────────────────────────────────
  loadVisualMode();
  runStationIntro();
  startClock();
  startProgressLoop();
  startVisualizer();
  setupSectionReveal();
  setupScrollParallax();
  fetchSettings();
  fetchNewsLinks();
  connect();
})();
