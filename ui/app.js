// تجميعة: the whole interface. Plain JS, no framework: state in S, views as HTML strings, actions by data-action.
// Every visible word goes through L(arabic, english), so both languages sit side by side and never drift apart.
(function () {
  "use strict";

  const B = window.TajmeeaBridge;
  const $app = document.getElementById("app");

  // ---------- Language

  let LANG = "ar";
  const L = (ar, en) => (LANG === "en" ? en : ar);
  function setLanguage(lang) {
    LANG = lang === "en" ? "en" : "ar";
    document.documentElement.lang = LANG;
    document.documentElement.dir = LANG === "en" ? "ltr" : "rtl";
    document.title = L("تجميعة", "Tajmeea");
  }
  // The engine answers in Arabic; these are the English words for the errors people actually meet.
  const ENGINE_ERRORS_EN = {
    offline: "Can't reach Telegram. Check your internet and try again.",
    bad_key: "That key is wrong. Copy it again from the Telegram page.",
    key_not_found: "We couldn't find the key in that text.",
    hash_hidden: "api_hash is hidden as dots. Copy it with the button next to it.",
    not_found: "No channel with that name. Check the link.",
    private: "That's a private channel. Tajmeea works with public channels only.",
    not_channel: "That link is a person or a bot, not a channel.",
    not_telegram: "That's not a Telegram link. It should start with t.me",
    bad_name: "That channel name isn't valid. Copy the link from Telegram again.",
    empty: "Paste a channel link or name.",
    logged_out: "You've been signed out. Sign in again.",
    flood: "Telegram asked us to wait a little before continuing.",
    disk_full: "Your disk is full. Free some space and continue.",
    folder: "We can't save to that folder. Choose another one.",
    rescan: "Check the channel again before downloading.",
    protected: "This channel's owner turned off saving its content, so Tajmeea won't download from it.",
    folder_missing: "We can't find the channel's folder. If you moved it, tell us where it went; if it's on a drive, plug it in.",
    relink_none: "The channel's files aren't in that folder. Pick the channel's own folder.",
    disk_space: "There isn't enough free space for this download. Free some space or pick another folder.",
    shelf_name: "Give the shelf a name.",
    kinds: "Choose at least one kind of file.",
    phone: "Type your full number with the country code, like +965…",
    keychain: "The Keychain couldn't be reached.",
    unexpected: "Something unexpected happened. Try again.",
  };
  const errorText = (error) => (LANG === "en" && ENGINE_ERRORS_EN[error.code]) || error.message;

  // ---------- Formatting

  const esc = (value) =>
    String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const num = (n) => Number(n || 0).toLocaleString("en-US");

  function bytes(n) {
    n = Number(n || 0);
    if (n < 1024) return L(`${n} بايت`, `${n} B`);
    const units = LANG === "en" ? [["KB", 1024], ["MB", 1024 ** 2], ["GB", 1024 ** 3]]
      : [["كيلو", 1024], ["ميجا", 1024 ** 2], ["جيجا", 1024 ** 3]];
    let [label, size] = units[0];
    for (const unit of units) if (n >= unit[1]) [label, size] = unit;
    const v = n / size;
    return `${v >= 100 ? Math.round(v) : v.toFixed(1).replace(/\.0$/, "")} ${label}`;
  }
  function date(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return new Intl.DateTimeFormat(L("ar-u-nu-latn", "en-GB"), { day: "numeric", month: "long", year: "numeric" }).format(d);
  }
  function ago(iso) {
    if (!iso) return L("ما تحدّثت للحين", "Not updated yet");
    const days = Math.floor((Date.now() - new Date(iso)) / 86400000);
    if (days <= 0) return L("تحدّثت اليوم", "Updated today");
    if (days === 1) return L("تحدّثت أمس", "Updated yesterday");
    if (days === 2) return L("قبل يومين", "2 days ago");
    if (days <= 10) return L(`قبل ${days} أيام`, `${days} days ago`);
    return date(iso);
  }
  // Arabic counting: 1 دقيقة، 2 دقيقتين، 3–10 دقايق، 11+ دقيقة.
  function counted(n, one, two, few, enOne, enMany) {
    if (LANG === "en") return n === 1 ? `1 ${enOne}` : `${n} ${enMany}`;
    if (n === 1) return one;
    if (n === 2) return two;
    return n <= 10 ? `${n} ${few}` : `${n} ${one}`;
  }
  function eta(sec) {
    if (sec == null) return L("نحسبه…", "Working it out…");
    if (sec < 60) return L("أقل من دقيقة", "Under a minute");
    const m = Math.round(sec / 60);
    const minutes = (k) => counted(k, "دقيقة", "دقيقتين", "دقايق", "minute", "minutes");
    if (m < 60) return L(`${minutes(m)} تقريباً`, `About ${minutes(m)}`);
    const h = Math.floor(m / 60), r = m % 60;
    const hours = counted(h, "ساعة", "ساعتين", "ساعات", "hour", "hours");
    return r ? L(`${hours} و${minutes(r)}`, `${hours} ${minutes(r)}`) : hours;
  }
  // The type tag already says PDF/وورد, and a trailing ".pdf" flips around in right-to-left text.
  function displayName(name) {
    return String(name || "").replace(/\.[A-Za-z0-9]{1,5}$/, "");
  }
  const clock = (sec) => { sec = Math.max(0, Math.round(sec)); return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`; };
  function initials(title) {
    const words = String(title || "").replace(/[^\p{L}\p{N}\s]/gu, "").trim().split(/\s+/);
    const first = (w) => ((w.length > 3 && w.startsWith("ال") ? w.slice(2) : w)[0] || "");
    return first(words[0] || "") + first(words[1] || "");
  }
  // "/Users/k/Downloads/تجميعة/قناة" → "التنزيلات › تجميعة › قناة" (a raw mixed path scrambles in right-to-left text).
  function prettyPath(path) {
    if (!path) return "";
    const home = S.home;
    const places = [[`${home}/Downloads`, L("التنزيلات", "Downloads")], [`${home}/Documents`, L("المستندات", "Documents")],
      [`${home}/Desktop`, L("سطح المكتب", "Desktop")], [home, L("مجلدك", "Home")]];
    let rest = path;
    let label = "";
    for (const [prefix, name] of places) {
      if (home && (path === prefix || path.startsWith(prefix + "/"))) { label = name; rest = path.slice(prefix.length); break; }
    }
    const parts = rest.split("/").filter(Boolean);
    if (label) parts.unshift(label);
    return parts.map((p) => `<bdi>${esc(p)}</bdi>`).join(" › ");
  }

  // ---------- Icons

  const svg = (d, size = 20, extra = "") =>
    `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`;
  const I = {
    list: (s) => svg('<path d="M4 6h16M4 12h16M4 18h10"/>', s),
    books: (s) => svg('<path d="M5 4h3v16H5zM10 4h3v16h-3zM15.4 5.2l2.9.8-3.7 14.3-2.9-.8z"/>', s),
    sliders: (s) => svg('<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>', s),
    plus: (s) => svg('<path d="M12 5v14M5 12h14"/>', s),
    folder: (s) => svg('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>', s),
    pause: (s) => svg('<path d="M9 6v12M15 6v12"/>', s),
    play: (s) => svg('<path d="M8 5l11 7-11 7z"/>', s),
    stop: (s) => svg('<rect x="6" y="6" width="12" height="12" rx="2"/>', s),
    check: (s) => svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', s, 'stroke-width="2.4"'),
    refresh: (s) => svg('<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>', s),
    hourglass: (s) => svg('<path d="M6 3h12M6 21h12M8 3v3l4 6-4 6v3M16 3v3l-4 6 4 6v3"/>', s),
    lock: (s) => svg('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>', s),
    external: (s) => svg('<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>', s),
    search: (s) => svg('<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>', s),
    phone: (s) => svg('<rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 18h2"/>', s),
    qr: (s) => svg('<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2v2h-2zM18 18h2v2h-2zM14 18h2M18 14h2"/>', s),
    download: (s) => svg('<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>', s),
    calendar: (s) => svg('<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>', s),
    pen: (s) => svg('<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/>', s),
    warn: (s) => svg('<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>', s),
    paste: (s) => svg('<rect x="8" y="3" width="8" height="4" rx="1"/><path d="M16 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2"/>', s),
    tag: (s) => svg('<path d="M4 4h7l9 9-7 7-9-9z"/><circle cx="8.5" cy="8.5" r="1.3"/>', s),
    globe: (s) => svg('<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.6 2.5 14.4 0 17M12 3.5c-2.5 2.6-2.5 14.4 0 17"/>', s),
    sparkle: (s) => svg('<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M18 6l-2.5 2.5M8.5 15.5L6 18"/>', s),
    undo: (s) => svg('<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>', s),
    star: (s) => svg('<path d="M12 3.8l2.5 5.1 5.6.8-4 3.9 1 5.6-5.1-2.7-5.1 2.7 1-5.6-4-3.9 5.6-.8z"/>', s),
    starFill: (s) => svg('<path d="M12 3.8l2.5 5.1 5.6.8-4 3.9 1 5.6-5.1-2.7-5.1 2.7 1-5.6-4-3.9 5.6-.8z" fill="currentColor"/>', s),
    shelfAdd: (s) => svg('<path d="M3 20h18M5 16V6h3v10M10 16V9h3v7"/><path d="M18 4v6M15 7h6"/>', s),
    filter: (s) => svg('<path d="M4 5h16l-6 7.5V19l-4-2v-4.5z"/>', s),
    chevron: (s) => svg('<path d="M10 6l6 6-6 6"/>', s, 'class="flip-rtl"'),
    trash: (s) => svg('<path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 12.5h9l1-12.5M10 11v5.5M14 11v5.5"/>', s),
    more: (s) => svg('<circle cx="5.5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18.5" cy="12" r="1.3"/>', s, 'fill="currentColor"'),
  };
  const logo = (size = 36) =>
    `<svg width="${size}" height="${size}" viewBox="0 0 36 36" aria-hidden="true"><rect x="5" y="10" width="6.5" height="19" rx="1.5" fill="#F2A541"/><rect x="13.5" y="5" width="6.5" height="24" rx="1.5" fill="#F2A541" opacity="0.75"/><rect x="23" y="11" width="6.5" height="18" rx="1.5" fill="#F2A541" opacity="0.5" transform="rotate(-14 26 20)"/><rect x="3" y="30" width="30" height="3" rx="1.5" fill="#F4EEE3" opacity="0.45"/></svg>`;
  const brandName = () => L("تجميعة", "Tajmeea");

  // ---------- Words

  const KIND = {
    pdf: () => ({ label: L("ملفات PDF", "PDF files"), tag: "PDF" }),
    word: () => ({ label: L("ملفات وورد", "Word files"), tag: L("وورد", "Word") }),
    excel: () => ({ label: L("جداول إكسل", "Excel sheets"), tag: L("إكسل", "Excel") }),
    slides: () => ({ label: L("عروض باوربوينت", "Presentations"), tag: L("عرض", "Slides") }),
    books: () => ({ label: L("كتب إلكترونية", "E-books"), tag: L("كتاب", "Book") }),
    audio: () => ({ label: L("صوتيات ومقاطع", "Audio and tracks"), tag: L("صوت", "Audio") }),
    voice: () => ({ label: L("بصمات", "Voice notes"), tag: L("بصمة", "Voice") }),
    archives: () => ({ label: L("ملفات مضغوطة", "Archives"), tag: L("مضغوط", "Zip") }),
    images: () => ({ label: L("صور", "Photos"), tag: L("صورة", "Photo") }),
    videos: () => ({ label: L("فيديو", "Videos"), tag: L("فيديو", "Video") }),
    other: () => ({ label: L("ملفات ثانية", "Other files"), tag: L("ملف", "File") }),
  };
  const kind = (k) => (KIND[k] ? KIND[k]() : { label: k, tag: L("ملف", "File") });
  const KIND_ORDER = ["pdf", "word", "excel", "slides", "books", "audio", "voice", "archives", "images", "videos", "other"];
  // An «other» file shows its own extension (PSD, TTF…) instead of a kind.
  const extOf = (name) => { const m = /\.([A-Za-z0-9]{1,10})$/.exec(name || ""); return m ? m[1].toUpperCase() : ""; };
  const tagOf = (f) => (f.kind === "other" && extOf(f.name)) || kind(f.kind).tag;
  // Sections are words from the channel itself, shown as the channel wrote them; only «أخرى» is ours.
  const topicName = (t) => (t === "أخرى" ? L("أخرى", "Other") : t);
  const typeLabel = (c) => (c.group
    ? (c.private ? L("قروب خاص", "Private group") : L("قروب عام", "Public group"))
    : (c.private ? L("قناة خاصة", "Private channel") : L("قناة عامة", "Public channel")));
  const shelfName = (s) => (s.favorites ? L("المفضلة", "Favorites") : s.name);
  const FAVORITES = 1;
  const ACTIVE = ["queued", "scanning", "running", "paused", "waiting"];
  const sideState = (state) => ({
    queued: L("بالدور", "Queued"),
    scanning: L("يدوّر على الجديد", "Looking for new files"),
    running: L("تنزّل الحين", "Downloading"),
    paused: L("موقوفة مؤقتاً", "Paused"),
    waiting: L("تنطر تيليجرام", "Waiting for Telegram"),
  })[state] || "";

  // ---------- State

  const S = {
    view: "splash",
    step: "key",
    key: freshKey(),
    login: { mode: "qr", step: "qr", matrix: null, expiresAt: 0, phone: "", code: "", password: "", hint: "", via: "", error: "", busy: false },
    me: null,
    keyMasked: "",
    offline: false,
    version: "",
    channels: [],
    totals: { files: 0, bytes: 0, channels: 0 },
    page: "empty",
    selected: null,
    detail: null,
    live: {},
    liveFiles: {},
    shownBooks: {},
    add: freshAdd(),
    mine: { list: null, loading: false, error: "", q: "" },
    lib: { q: "", topic: "", shelf: null, topics: [], results: [], searched: false },
    shelves: [],
    shelfMenu: null,
    channelMenu: null,
    newShelf: { open: false, name: "" },
    renameShelf: null,
    editFilters: null,
    statusText: "",
    update: null,
    updating: false,
  };
  function freshKey() {
    return { id: "", hash: "", idText: "", hashText: "", error: "", busy: false, help: false };
  }
  function freshAdd() {
    return { link: "", busy: false, scanned: 0, waiting: 0, result: null, error: "", kinds: [], folder: "",
      yearFolders: true, topicFolders: false, smartNames: true, autoUpdate: false, adding: false,
      since: "", until: "", words: "", maxMb: "", filtered: null, filteredOthers: null, counting: false, skipExts: [],
      free: null };
  }
  const channelById = (id) => S.channels.find((c) => c.id === id);
  // By bytes received, so two big files don't sit at 0% until one of them finishes.
  const percentOf = (job) => (job.bytesTotal ? Math.min(100, Math.floor((100 * job.bytesDone) / job.bytesTotal))
    : job.total ? Math.floor((100 * job.processed) / job.total) : null);
  const jobOf = (id) => S.live[id] || (channelById(id) || {}).job || {};
  const isActive = (job) => ACTIVE.includes(job.state);

  // The Mac app asks this before quitting (to warn about running downloads), and its menu bar icon
  // can start an update of every channel.
  window.TajmeeaApp = {
    busy: () => S.channels.filter((c) => isActive(jobOf(c.id))).length,
    updateAll: () => S.channels.filter((c) => !isActive(jobOf(c.id))).forEach((c) => startUpdate(c.id, false)),
  };

  // ---------- Rendering

  function render() {
    const views = { splash: splashView, setup: setupView, onboard: onboardView, main: shellView };
    // Re-rendering replaces the inputs; keep the caret where the person was typing.
    const active = document.activeElement;
    const model = active && active.dataset && active.dataset.model;
    const caret = model && "selectionStart" in active ? [active.selectionStart, active.selectionEnd] : null;
    $app.innerHTML = views[S.view]();
    const again = model && $app.querySelector(`[data-model="${model}"]`);
    if (again) {
      again.focus();
      if (caret) try { again.setSelectionRange(caret[0], caret[1]); } catch (error) { /* date and number fields */ }
      return;
    }
    const focus = $app.querySelector("[data-autofocus]");
    if (focus && (!document.activeElement || document.activeElement === document.body)) focus.focus();
  }

  let liveFrame = 0;
  let liveTimer = 0;
  // Animation frames stop while the window is covered or closed, which left the page showing an
  // old 0%. A timer backs the frame up; whichever comes first draws.
  function scheduleLive() {
    if (liveFrame) return;
    const draw = () => {
      cancelAnimationFrame(liveFrame);
      clearTimeout(liveTimer);
      liveFrame = 0;
      drawLive();
    };
    liveFrame = requestAnimationFrame(draw);
    liveTimer = setTimeout(draw, 500);
  }
  function drawLive() {
    if (S.view !== "main") return;
    const side = document.getElementById("side-channels");
    if (side) side.innerHTML = sideChannels();
    if (S.page === "channel") {
      const live = document.getElementById("live");
      const head = document.getElementById("channel-actions");
      const files = document.getElementById("channel-files");
      if (live) live.innerHTML = liveSection();
      if (head) head.innerHTML = channelActions();
      if (files) files.innerHTML = filesSection();
    }
  }

  function splashView() {
    return `<div class="splash">${logo(64)}<div class="rakkas" style="font-size:44px;color:var(--gold)">${brandName()}</div>
      <div class="row muted"><div class="spin"></div>${L("نجهّز…", "Getting ready…")}</div></div>`;
  }

  function setupView() {
    return `<div class="splash" style="max-width:560px;margin:0 auto;text-align:center;gap:16px">
      ${logo(56)}<h1 style="font-size:28px">${L("باقي خطوة بسيطة", "One small step left")}</h1>
      <p class="text-2">${L("تجميعة تحتاج تكمّل تركيبها. سكّر التطبيق، وشغّل أمر التركيب مرة ثانية بالطرفية.",
        "Tajmeea needs to finish installing. Quit the app and run the install command again in Terminal.")}</p>
      <p class="muted small">${L("إذا تكرر، أرسل لنا سجل الأخطاء من مجلد", "If it keeps happening, send us the log from")} ~/Library/Logs/Tajmeea</p></div>`;
  }

  // ---------- Onboarding

  function onboardView() {
    const stepPill = (name, index, label) => {
      const order = ["key", "login"];
      const done = order.indexOf(S.step) > order.indexOf(name);
      if (done) return `<span class="pill done">${I.check(13)}${label}</span>`;
      return `<span class="pill ${S.step === name ? "on" : ""}">${index} · ${label}</span>`;
    };
    const content = S.step === "key" ? keyContent() : loginContent();
    const art = S.step === "login" && S.login.mode === "qr" && S.login.step === "qr" ? qrArt() : emptyShelfArt();
    return `<div class="onboard">
      <section class="content">
        <div class="row"><div class="brand spacer">${logo(30)}<span class="rakkas" style="font-size:28px">${brandName()}</span></div>
          <button class="btn sm" data-action="switch-language">${I.globe(15)}${L("English", "العربية")}</button></div>
        <div class="row" style="gap:8px">${stepPill("key", 1, L("مفتاحك", "Your key"))}${stepPill("login", 2, L("دخولك", "Sign in"))}<span class="pill">3 · ${L("أول قناة", "First channel")}</span></div>
        ${content}
      </section>
      <section class="art">${art}</section></div>`;
  }

  // my.telegram.org hides api_hash as dots and puts a copy button by each value,
  // so each value gets its own box with a paste button.
  function keyContent() {
    const k = S.key;
    const ready = Boolean(k.id && k.hash);
    const box = (slot, n, title, tech, done) => `<div class="row" style="padding:12px 0;gap:12px">
        <span class="num" style="${done ? "background:var(--green-tint);color:var(--green-text)" : ""}">${done ? I.check(14) : n}</span>
        <div style="width:112px;flex:none"><div style="font-weight:500">${title}</div><div class="tiny muted"><span class="ltr">${tech}</span></div></div>
        <input class="slot-input mono ltr" data-model="key.${slot}Text" value="${esc(k[slot + "Text"])}" aria-label="${title}" autocomplete="off" spellcheck="false">
        <button class="btn sm tint" data-action="paste-slot" data-slot="${slot}">${I.paste(15)}${L("لصق", "Paste")}</button></div>`;
    const help = k.help ? `<div class="card" style="padding:16px 18px">
        <p style="font-weight:600;margin-bottom:6px">${L("إذا موقع تيليجرام ما زبط معاك", "If the Telegram site gives you trouble")}</p>
        <ul class="text-2 small" style="margin:0;padding-inline-start:18px;line-height:1.9">
          <li>${L("الكود يوصلك داخل تطبيق تيليجرام نفسه، مو برسالة SMS.", "The code arrives inside the Telegram app, not by SMS.")}</li>
          <li>${L("إذا طلع لك ERROR وأنت تسوي التطبيق: طفّ الـ VPN، وجرّب من متصفح ثاني، واكتب اسم إنجليزي بسيط.",
            "If you see ERROR while creating the app: turn off any VPN, try another browser, and use a simple English name.")}</li>
          <li>${L("إذا الصفحة فاضية، انطر دقايق وجرّب مرة ثانية. موقع تيليجرام أحياناً يتعطل.",
            "If the page is blank, wait a few minutes and try again. The site goes down sometimes.")}</li>
        </ul></div>` : "";
    return `<div>
        <h1 style="font-size:40px;font-weight:600;line-height:1.25;margin-bottom:8px">${L("مفتاحك الخاص", "Your own key")}</h1>
        <p class="text-2" style="font-size:16px">${L("تيليجرام يبي كل شخص يسوي مفتاح لنفسه. ياخذ دقيقتين، ومرة وحدة بس.",
          "Telegram asks everyone to make their own key. It takes two minutes, once.")}</p>
      </div>
      <div class="row" style="gap:12px">
        <span class="spacer text-2">${L("انسخ الرقم والمفتاح من أزرار النسخ بموقع تيليجرام، والصقهم هني.",
          "Copy the number and the key with the copy buttons on the Telegram site, and paste them here.")}</span>
        <button class="btn sm" data-action="open-site">${L("افتح الموقع", "Open the site")} ${I.external(14)}</button></div>
      <section class="card rows" style="padding:2px 18px">
        ${box("id", 1, L("رقم التطبيق", "App number"), "api_id", k.id)}
        ${box("hash", 2, L("المفتاح", "Key"), "api_hash", k.hash)}
      </section>
      ${k.error ? `<p class="small" style="color:var(--red-text)">${esc(k.error)}</p>` : ""}
      ${help}
      <div class="row" style="gap:18px;margin-top:auto">
        <button class="btn gold big" data-action="save-key" ${ready && !k.busy ? "" : "disabled"}>${k.busy ? '<div class="spin"></div>' : L("كمّل", "Continue")}</button>
        <a data-action="toggle-help">${k.help ? L("خلاص فهمت", "Got it") : L("عندي مشكلة بموقع تيليجرام", "Trouble with the Telegram site")}</a>
        ${k.id || k.hash ? `<a class="small muted" data-action="reset-key">${L("ابدأ من جديد", "Start over")}</a>` : ""}
      </div>
      <p class="tiny muted row" style="gap:8px">${I.lock(14)}${L("المفتاح ينحفظ بالـ Keychain بجهازك، وما يطلع منه أبداً.", "The key is kept in your Mac's Keychain and never leaves it.")}</p>`;
  }

  function loginContent() {
    const Lg = S.login;
    const error = Lg.error ? `<div class="notice red">${I.warn(18)}<span>${esc(Lg.error)}</span></div>` : "";
    const title = (text) => `<h1 style="font-size:40px;font-weight:600;line-height:1.25;margin-bottom:8px">${text}</h1>`;
    if (Lg.step === "password") {
      return `<div>${title(L("كلمة السر الإضافية", "Two-step password"))}
        <p class="text-2" style="font-size:16px">${L("حسابك محمي بكلمة سر إضافية. اكتبها عشان نكمل.", "Your account has a two-step password. Type it to continue.")}</p></div>
        <form data-submit="password" class="stack" style="gap:14px">
          <label class="field"><span class="hidden">${L("كلمة السر", "Password")}</span>${I.lock(18)}
            <input type="password" data-model="login.password" placeholder="${Lg.hint ? L("التلميح: ", "Hint: ") + esc(Lg.hint) : L("كلمة السر", "Password")}" autocomplete="current-password" data-autofocus></label>
          ${error}
          <div><button class="btn gold big" type="submit" ${Lg.busy ? "disabled" : ""}>${Lg.busy ? '<div class="spin"></div>' : L("ادخل", "Sign in")}</button></div>
        </form>`;
    }
    if (Lg.mode === "phone") {
      const codeStep = Lg.step === "code";
      const lead = codeStep
        ? (Lg.via === "app" ? L("أرسلنا لك كود داخل تطبيق تيليجرام.", "We sent a code to your Telegram app.") : L("أرسلنا لك كود برسالة.", "We sent you a code by SMS."))
        : L("اكتب رقمك كامل مع مفتاح الدولة.", "Type your full number with the country code.");
      return `<div>${title(L("ادخل برقمك", "Sign in with your number"))}<p class="text-2" style="font-size:16px">${lead}</p></div>
        <form data-submit="${codeStep ? "code" : "phone"}" class="stack" style="gap:14px">
          ${codeStep
            ? `<label class="field"><span class="hidden">${L("الكود", "Code")}</span><input class="ltr mono" data-model="login.code" inputmode="numeric" placeholder="12345" autocomplete="one-time-code" data-autofocus></label>`
            : `<label class="field"><span class="hidden">${L("رقمك", "Your number")}</span>${I.phone(18)}<input class="ltr" data-model="login.phone" value="${esc(Lg.phone)}" placeholder="+965 5555 5555" autocomplete="tel" data-autofocus></label>`}
          ${error}
          <div class="row" style="gap:12px"><button class="btn gold big" type="submit" ${Lg.busy ? "disabled" : ""}>${Lg.busy ? '<div class="spin"></div>' : codeStep ? L("تأكيد", "Confirm") : L("أرسل الكود", "Send the code")}</button>
          ${codeStep ? `<button class="btn" type="button" data-action="phone-again">${L("غيّر الرقم", "Change number")}</button>` : ""}</div>
        </form>
        <a style="margin-top:auto" data-action="login-qr">${L("ارجع للدخول بالكود المصوّر", "Back to the QR code")}</a>`;
    }
    const stepRow = (icon, text) => `<div class="row" style="gap:14px"><span class="icon-tile">${icon}</span><span style="font-size:16px">${text}</span></div>`;
    return `<div>${title(L("اربط حسابك", "Link your account"))}
        <p class="text-2" style="font-size:16px">${L("صوّر الكود من تلفونك، وخلاص. ما تحتاج تكتب رقمك ولا تنطر رسالة.", "Scan the code with your phone and you're done. No number to type, no message to wait for.")}</p></div>
      <div class="stack" style="gap:14px">
        ${stepRow(I.phone(22), L("افتح تيليجرام بتلفونك", "Open Telegram on your phone"))}
        ${stepRow(I.sliders(22), L("الإعدادات › الأجهزة › ربط جهاز", "Settings › Devices › Link Desktop Device"))}
        ${stepRow(I.qr(22), L("صوّر الكود اللي جنبك", "Scan the code next to this"))}
      </div>
      <p class="notice plain small" style="line-height:1.8">${L("إذا حسابك عليه كلمة سر إضافية، بنطلبها منك بعد ما تصوّر.", "If your account has a two-step password, we'll ask for it after you scan.")}</p>
      ${error}
      <div class="stack" style="gap:10px;margin-top:auto">
        <a data-action="login-phone">${L("أو ادخل برقمك بدال الكود", "Or sign in with your number instead")}</a>
        <a class="small muted" data-action="back-to-key">${L("غيّر المفتاح", "Change the key")}</a>
        <p class="tiny muted row" style="gap:8px">${I.lock(14)}${L("جلستك تنحفظ بجهازك بس، وتقدر تطلع منها بأي وقت من تلفونك.", "Your session stays on this Mac, and you can end it any time from your phone.")}</p>
      </div>`;
  }

  function qrSvg(matrix) {
    const n = matrix.length;
    let rects = "";
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (matrix[y][x] === "1") rects += `M${x} ${y}h1v1h-1z`;
    return `<svg viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges" role="img" aria-label="${L("كود الدخول", "Sign-in code")}"><path d="${rects}" fill="#120F1C"/></svg>`;
  }
  const qrTimerText = () => L(`الكود يتجدد بعد <b class="ltr" style="color:var(--text)">${clock((S.login.expiresAt - Date.now()) / 1000)}</b>`,
    `New code in <b class="ltr" style="color:var(--text)">${clock((S.login.expiresAt - Date.now()) / 1000)}</b>`);

  function qrArt() {
    const Lg = S.login;
    const card = Lg.matrix
      ? `<div class="qr-card">${qrSvg(Lg.matrix)}<div class="qr-logo">${logo(30)}</div></div>`
      : `<div class="qr-card loading"><svg viewBox="0 0 10 10"><rect width="10" height="10" fill="#120F1C"/></svg><div class="qr-logo"><div class="spin"></div></div></div>`;
    return `${card}<div class="row text-2 small" id="qr-timer">${Lg.matrix ? qrTimerText() : L("نجهّز الكود…", "Preparing the code…")}</div>`;
  }

  function emptyShelfArt(message, sub) {
    message = message || L("رفك فاضي", "Your shelf is empty");
    sub = sub || L("خلنا نعبّيه بأول قناة.", "Let's fill it with a first channel.");
    return `<div class="disc"><div style="position:relative;width:340px">
        ${shelf({ slots: 12, filled: 0, height: 130, seed: 3 })}
        <div style="position:absolute;top:-34px;inset-inline-end:18px;width:26px;height:118px;border-radius:3px 3px 1px 1px;background:var(--gold);transform:rotate(-12deg);display:flex;flex-direction:column"><div class="book" style="width:100%;height:100%;background:transparent"><div class="band"></div><div class="foot"></div></div></div>
      </div></div>
      <div style="text-align:center"><div class="rakkas" style="font-size:40px;line-height:1.2;color:var(--gold)">${message}</div>
      <div class="text-2" style="font-size:16px;margin-top:4px">${sub}</div></div>`;
  }

  // ---------- Shelf

  const HEIGHTS = [84, 98, 76, 104, 90, 80, 100, 88, 72, 94, 106, 82];
  const WIDTHS = [20, 16, 23, 18, 21, 17, 24, 19];
  const GOLDS = ["#F2A541", "#E3953A", "#F6C27A", "#C98436", "#EDB25E", "#D99C4C"];

  function shelf({ slots, filled, filling = null, height = 108, seed = 0, scale = 1, newFrom = null, label = "" }) {
    let books = "";
    for (let i = 0; i < slots; i++) {
      const h = Math.round(HEIGHTS[(i * 5 + seed) % HEIGHTS.length] * scale * (height / 108));
      const w = Math.round(WIDTHS[(i + seed) % WIDTHS.length] * scale);
      if (i < filled) {
        const anim = newFrom !== null && i >= newFrom ? " new" : "";
        books += `<div class="book${anim}" style="width:${w}px;height:${h}px;background:${GOLDS[(i * 4 + seed) % GOLDS.length]}">${scale >= 0.8 ? '<div class="band"></div><div class="foot"></div>' : ""}</div>`;
      } else if (i === filled && filling !== null) {
        books += `<div class="book filling" style="width:${w}px;height:${h}px"><div class="fill" style="height:${Math.round(h * filling)}px"></div></div>`;
      } else {
        books += `<div class="book ghost" style="width:${w}px;height:${h}px"></div>`;
      }
    }
    return `<div class="shelf" role="img" aria-label="${esc(label)}"><div class="books" style="height:${height}px">${books}</div><div class="plank"></div></div>`;
  }

  // ---------- Main shell

  function shellView() {
    const onChannels = ["channel", "add", "empty"].includes(S.page);
    const update = S.update && S.update.available
      ? `<div class="card stack" style="padding:12px 14px;gap:8px;background:var(--gold-tint)">
          <div class="small" style="color:var(--gold-light);font-weight:600">${I.sparkle(15)} ${L("فيه نسخة جديدة", "A new version is out")} <span class="ltr">${esc(S.update.latest)}</span></div>
          <button class="btn sm gold" data-action="run-update" ${S.updating ? "disabled" : ""}>${S.updating ? '<div class="spin"></div>' : L("حدّث الحين", "Update now")}</button></div>`
      : "";
    return `<div class="shell">
      <aside class="side">
        <div class="brand">${logo(36)}<span class="rakkas">${brandName()}</span>
          <button class="btn sm lang-toggle" data-action="switch-language" title="${L("English", "العربية")}">${I.globe(14)}${L("EN", "ع")}</button></div>
        <nav class="nav">
          <button class="${onChannels ? "active" : ""}" data-action="go-channels">${I.list(20)}${L("القنوات", "Channels")}</button>
          <button class="${S.page === "library" ? "active" : ""}" data-action="go-library">${I.books(20)}${L("المكتبة", "Library")}</button>
          <button class="${S.page === "settings" ? "active" : ""}" data-action="go-settings">${I.sliders(20)}${L("الإعدادات", "Settings")}</button>
        </nav>
        <div class="stack" style="gap:4px" id="side-channels">${sideChannels()}</div>
        <div class="stack" style="gap:10px;margin-top:auto">${update}
        <button class="btn add-channel ${S.page === "add" ? "active" : ""}" data-action="go-add">${I.plus(18)}${L("أضف قناة", "Add channel")}</button></div>
      </aside>
      <main class="main" id="main">${pageView()}</main></div>`;
  }

  function avatar(channel, size, dim = false) {
    const inner = channel.photo ? `<img src="${esc(channel.photo)}" alt="">` : esc(initials(channel.title));
    return `<span class="avatar ${dim && !channel.photo ? "dim" : ""}" style="width:${size}px;height:${size}px;font-size:${Math.round(size / 2.8)}px">${inner}</span>`;
  }

  const filesCount = (n) => L(`${num(n)} ملف`, `${num(n)} ${n === 1 ? "file" : "files"}`);

  function sideChannels() {
    if (!S.channels.length) return "";
    return `<p class="side-label">${L("قنواتك", "Your channels")}</p>` + S.channels.map((c) => {
      const job = jobOf(c.id);
      const live = isActive(job);
      let sub = `${filesCount(c.files)} · ${ago(c.lastSync)}`;
      const pct = percentOf(job);
      if (live) sub = `${sideState(job.state)}${pct != null ? ` · ${pct}%` : ""}`;
      else if (c.failed) sub = `${filesCount(c.files)} · ${L(`${num(c.failed)} ما نزلت`, `${num(c.failed)} failed`)}`;
      const active = S.page === "channel" && S.selected === c.id;
      const open = S.channelMenu && S.channelMenu.id === c.id;
      return `<div class="channel-row ${active ? "active" : ""}" data-id="${c.id}"><button class="channel-item ${active ? "active" : ""}" data-action="open-channel" data-id="${c.id}">
        ${avatar(c, 36, !active)}<div style="min-width:0;flex:1"><div class="name">${esc(c.title)}</div><div class="sub ${live ? "live" : ""}">${sub}</div></div></button>
        <button class="icon-btn row-more ${open ? "open" : ""}" data-action="channel-menu" data-id="${c.id}" title="${L("خيارات القناة", "Channel options")}" aria-label="${L("خيارات القناة", "Channel options")}" aria-haspopup="menu">${I.more(18)}</button></div>`;
    }).join("");
  }

  // What you can do with a channel, from its row in the sidebar: the ⋯ button or a right-click.
  function channelMenu() {
    const M = S.channelMenu;
    const c = M && channelById(M.id);
    if (!c) return "";
    const item = (action, icon, label, extra = "") =>
      `<button class="pop-item ${action === "remove-channel" ? "danger" : ""}" role="menuitem" data-action="${action}" ${extra}>${icon}<span class="spacer">${label}</span></button>`;
    return `<div class="popover channel-pop" role="menu" style="width:210px;top:${M.top}px;${M.side}:${M.x}px">
      ${isActive(jobOf(c.id)) ? "" : item("update", I.refresh(17), L("حدّث", "Update"), `data-id="${c.id}"`)}
      ${item("reveal", I.folder(17), L("افتح المجلد", "Open folder"), `data-path="${esc(c.folder)}"`)}
      ${item("remove-channel", I.trash(17), L("شيل القناة", "Remove channel"), `data-id="${c.id}"`)}</div>`;
  }

  function openChannelMenu(id, rect, point) {
    const rtl = document.documentElement.dir === "rtl";
    const width = 210;
    const height = 140;
    // From the ⋯ button the menu hangs under it; from a right-click it opens where you clicked.
    const edge = point ? point.x : rtl ? rect.right : rect.left;
    const x = Math.max(12, Math.min(rtl ? innerWidth - edge : edge, innerWidth - width - 12));
    const below = point ? point.y : rect.bottom + 6;
    const top = below + height > innerHeight - 12 ? Math.max(12, (point ? point.y : rect.top - 6) - height) : below;
    S.shelfMenu = null;
    S.channelMenu = { id, side: rtl ? "right" : "left", x, top };
    drawMenus();
    scheduleLive();
  }

  function closeChannelMenu() {
    if (!S.channelMenu) return;
    S.channelMenu = null;
    drawMenus();
    scheduleLive();
  }

  function pageView() {
    switch (S.page) {
      case "channel": return channelPage();
      case "add": return addPage();
      case "library": return libraryPage();
      case "settings": return settingsPage();
      default: return emptyPage();
    }
  }

  function emptyPage() {
    return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:26px">
      ${emptyShelfArt(L("رفك فاضي", "Your shelf is empty"), L("الصق رابط قناة أو اختارها من قنواتك، وتجميعة تجمع لك ملفاتها هني.", "Paste a channel link or pick one of yours, and Tajmeea gathers its files here."))}
      <button class="btn gold big" data-action="go-add">${I.plus(20)}${L("أضف أول قناة", "Add your first channel")}</button></div>`;
  }

  // ---------- Channel page

  const channelLine = (c) => [
    c.username ? `<span class="ltr">@${esc(c.username)}</span>` : "",
    typeLabel(c),
    c.members ? L(`${num(c.members)} ${c.group ? "عضو" : "مشترك"}`, `${num(c.members)} ${c.group ? "members" : "subscribers"}`) : "",
  ].filter(Boolean).join(" · ");

  function channelPage() {
    const c = channelById(S.selected);
    if (!c) return emptyPage();
    const auto = L("حدّثها لحالها كل يوم", "Update it by itself every day");
    return `<div class="row" style="gap:18px">
        <div class="ring" style="width:68px;height:68px">${avatar(c, 62)}</div>
        <div style="flex:1;min-width:0"><h1 style="font-size:30px;font-weight:600;line-height:1.25">${esc(c.title)}</h1>
          <p class="text-2 small">${channelLine(c)}</p></div>
        <div class="row" id="channel-actions">${channelActions()}</div>
      </div>
      <div id="live" class="stack" style="gap:20px">${liveSection()}</div>
      <div id="channel-files">${filesSection()}</div>
      <div class="card row" style="padding:12px 20px;gap:14px">
        <span class="text-2">${I.refresh(18)}</span><span class="spacer">${auto}</span>
        <button class="switch" role="switch" aria-checked="${c.autoUpdate}" aria-label="${auto}" data-action="toggle-auto" data-id="${c.id}"></button>
      </div>
      ${filterCard(c)}
      <div class="row tiny muted" style="gap:14px">
        <span class="row" style="gap:6px">${I.folder(14)}<a data-action="reveal" data-path="${esc(c.folder)}" title="${esc(c.folder)}" style="color:var(--muted)">${prettyPath(c.folder)}</a></span>
        <span class="spacer"></span><button class="btn sm danger" data-action="remove-channel" data-id="${c.id}">${I.trash(15)}${L("شيل القناة", "Remove channel")}</button>
      </div>`;
  }

  function filterSummary(F) {
    const parts = [
      F.since ? L(`من ${F.since}`, `from ${F.since}`) : "",
      F.until ? L(`لين ${F.until}`, `to ${F.until}`) : "",
      F.words ? L(`فيه «${esc(F.words)}»`, `containing “${esc(F.words)}”`) : "",
      F.maxMb ? L(`أصغر من ${num(F.maxMb)} ميغا`, `under ${num(F.maxMb)} MB`) : "",
    ].filter(Boolean);
    return parts.length ? L("الفلتر: ", "Filter: ") + parts.join(" · ") : "";
  }

  function filterCard(c) {
    const E = S.editFilters && S.editFilters.id === c.id ? S.editFilters : null;
    if (E) {
      return `<section class="card stack" style="padding:16px 20px;gap:14px">
        <div class="row" style="gap:10px"><span class="text-2">${I.filter(18)}</span><span class="small">${L("الفلتر", "Filter")}</span></div>
        ${filterFields("editFilters", E)}
        <div class="row" style="gap:10px">
          <button class="btn sm gold" data-action="save-filters" data-id="${c.id}">${L("احفظ وحدّث", "Save and update")}</button>
          <button class="btn sm" data-action="cancel-filters">${L("إلغاء", "Cancel")}</button>
          <span class="tiny muted" style="margin-inline-start:auto">${L("بنمر على القناة كلها مرة ثانية. اللي نزل قبل يبقى بمكانه.", "We'll go through the whole channel again. Files already saved stay.")}</span></div>
      </section>`;
    }
    const summary = filterSummary(c.filters || {});
    return `<div class="card row" style="padding:12px 20px;gap:14px"><span class="text-2">${I.filter(18)}</span>
      <span class="spacer small ${summary ? "" : "muted"}">${summary || L("بدون فلتر: ينزل كل شي من الأنواع اللي اخترتها.", "No filter: everything of the kinds you chose.")}</span>
      <button class="btn sm" data-action="edit-filters" data-id="${c.id}">${summary ? L("عدّل", "Edit") : L("أضف فلتر", "Add a filter")}</button></div>`;
  }

  // Date boxes are drawn in the Mac's own date format, so they follow the Mac's language direction,
  // not the interface's; otherwise an Arabic date breaks apart inside an English page.
  const DATE_DIR = /^(ar|fa|he|ur)\b/i.test(navigator.language || "") ? "rtl" : "ltr";

  // The same four fields on the add page and on a channel page.
  function filterFields(group, v) {
    const field = (label, input) => `<label class="filter-field"><span class="tiny muted">${label}</span>${input}</label>`;
    return `<div class="filters">
      ${field(L("من تاريخ", "From"), `<input type="date" dir="${DATE_DIR}" class="input" data-model="${group}.since" value="${esc(v.since || "")}">`)}
      ${field(L("لين تاريخ", "To"), `<input type="date" dir="${DATE_DIR}" class="input" data-model="${group}.until" value="${esc(v.until || "")}">`)}
      ${field(L("لازم يكون فيه (بالاسم أو الوصف)", "Must contain (in name or post)"), `<input class="input" data-model="${group}.words" value="${esc(v.words || "")}" placeholder="${L("مثال: تعميم 2024", "e.g. circular 2024")}">`)}
      ${field(L("أكبر حجم (ميغا)", "Largest size (MB)"), `<input type="number" min="0" step="1" class="input ltr" data-model="${group}.maxMb" value="${v.maxMb ? esc(v.maxMb) : ""}" placeholder="${L("بلا حد", "No limit")}">`)}
    </div>`;
  }
  const hasFilter = (v) => Boolean(v.since || v.until || (v.words || "").trim() || Number(v.maxMb) > 0);
  const filtersOf = (v) => ({ since: v.since || "", until: v.until || "", words: (v.words || "").trim(), maxMb: Number(v.maxMb) || 0 });

  function channelActions() {
    const c = channelById(S.selected);
    if (!c) return "";
    const job = jobOf(c.id);
    const openLabel = `${I.folder(18)}${L("افتح المجلد", "Open folder")}`;
    if (job.state === "paused") {
      return `<button class="btn gold" data-action="resume" data-id="${c.id}">${I.play(16)}${L("كمّل", "Resume")}</button>
        <button class="btn" data-action="cancel" data-id="${c.id}">${I.stop(16)}${L("إلغاء", "Cancel")}</button>
        <button class="btn" data-action="reveal" data-path="${esc(c.folder)}">${openLabel}</button>`;
    }
    if (isActive(job)) {
      return `<button class="btn" data-action="pause" data-id="${c.id}">${I.pause(18)}${L("إيقاف مؤقت", "Pause")}</button>
        <button class="btn" data-action="reveal" data-path="${esc(c.folder)}">${openLabel}</button>`;
    }
    return `<button class="btn tint" data-action="update" data-id="${c.id}">${I.refresh(18)}${L("حدّث", "Update")}</button>
      <button class="btn gold" data-action="reveal" data-path="${esc(c.folder)}">${openLabel}</button>`;
  }

  function bigNumber(value, caption) {
    return `<div class="row" style="align-items:baseline;gap:14px"><span class="rakkas" style="font-size:92px;line-height:0.9;color:var(--gold)">${value}</span>
      <span style="font-size:22px;color:var(--soft)">${caption}</span></div>`;
  }
  const stat = (label, value) => `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`;

  function liveSection() {
    const c = channelById(S.selected);
    if (!c) return "";
    const job = jobOf(c.id);
    const seed = c.id % 7;
    if (isActive(job)) {
      const total = job.total || 0;
      const slots = Math.min(Math.max(total, 1), 38);
      const filled = total ? Math.floor((slots * job.processed) / total) : 0;
      const current = job.current && job.current.size ? job.current.received / job.current.size : null;
      const previous = S.shownBooks[c.id];
      S.shownBooks[c.id] = filled;
      const notice = liveNotice(job);
      if (job.state === "scanning" || (job.state === "queued" && !total)) {
        const text = job.state === "queued"
          ? L("بالدور… بتبدأ بعد ما تخلص القناة اللي قبلها.", "Queued… starts when the channel before it finishes.")
          : L("ندوّر على الملفات الجديدة…", "Looking for new files…");
        return `<div class="row" style="gap:14px"><div class="spin"></div><span class="text-2" style="font-size:18px">${text}</span></div>
          ${shelf({ slots: 24, filled: 0, seed, label: L("رف فاضي", "Empty shelf") })}${notice}`;
      }
      return `<div class="row" style="align-items:flex-end;gap:28px">
          ${bigNumber(num(job.processed), L(`من ${num(total)} ملف`, `of ${num(total)} files`))}
          <div class="row" style="margin-inline-start:auto;gap:10px">
            ${stat(L("الحجم", "Size"), L(`${bytes(job.bytesDone)} من ${bytes(job.bytesTotal)}`, `${bytes(job.bytesDone)} of ${bytes(job.bytesTotal)}`))}
            ${stat(L("الباقي", "Left"), job.state === "running" ? eta(job.eta) : "—")}
          </div></div>
        ${shelf({ slots, filled, filling: filled < slots ? current : null, seed, newFrom: previous != null && filled > previous ? previous : null,
          label: L(`رف فيه ${job.processed} ملف من ${total}`, `Shelf with ${job.processed} of ${total} files`) })}
        ${notice}`;
    }
    const slots = Math.min(c.files, 38);
    const notices = [];
    const again = (label) => `<button class="btn sm" data-action="update" data-id="${c.id}">${label}</button>`;
    if (job.state === "failed") {
      notices.push(`<div class="notice red">${I.warn(18)}<span class="spacer">${esc(LANG === "en" && ENGINE_ERRORS_EN[job.errorCode] || job.error || L("التنزيل وقف.", "The download stopped."))}</span>${again(L("جرّب مرة ثانية", "Try again"))}</div>`);
    } else if (c.failed) {
      notices.push(`<div class="notice gold">${I.refresh(18)}<span class="spacer">${L(`${num(c.failed)} ملفات ما نزلت. بنحاول فيها مرة ثانية بالتحديث الجاي.`, `${num(c.failed)} files didn't download. We'll try them again next update.`)}</span>${again(L("جرّب الحين", "Try now"))}</div>`);
    } else if (job.state === "done" && job.total === 0) {
      notices.push(`<div class="notice green">${I.check(18)}<span>${L("ما فيه ملفات جديدة. رفك محدّث.", "Nothing new. Your shelf is up to date.")}</span></div>`);
    } else if (job.state === "done") {
      const extra = L(
        `${job.skipped ? `، و${num(job.skipped)} كانت موجودة من قبل` : ""}${job.rejected ? `، و${num(job.rejected)} رفضناها لأنها مو PDF حقيقي` : ""}`,
        `${job.skipped ? `, ${num(job.skipped)} were already here` : ""}${job.rejected ? `, ${num(job.rejected)} refused as fake PDFs` : ""}`);
      notices.push(`<div class="notice green">${I.check(18)}<span>${L(`خلصنا: نزل ${num(job.done)} ملف${extra}.`, `Done: ${num(job.done)} new files${extra}.`)}</span></div>`);
    } else if (job.state === "stopped") {
      notices.push(`<div class="notice plain">${I.stop(16)}<span class="spacer">${L("ألغيت التنزيل. اللي نزل باقي بمكانه.", "Download cancelled. What was saved stays.")}</span>${again(L("كمّل من وين وقفنا", "Continue where it stopped"))}</div>`);
    }
    const away = c.folderState && c.folderState.state !== "ok" ? c.folderState : null;
    if (away) {
      const text = away.state === "volume"
        ? L(`الهارد «${esc(away.volume)}» اللي فيه ملفات القناة مو موصول. وصّله وترجع الملفات بمكانها.`, `The drive “${esc(away.volume)}” holding this channel's files isn't plugged in. Plug it in and they're back.`)
        : L("ما لقينا مجلد القناة بمكانه. إذا نقلته، قل لنا وين صار وندوّر على ملفاتها هناك.", "The channel's folder isn't where it was. If you moved it, tell us where and we'll find its files there.");
      const again = away.state === "missing" ? `<button class="btn sm" data-action="recreate-folder" data-id="${c.id}">${L("نزّلها من جديد", "Download again")}</button>` : "";
      notices.push(`<div class="notice gold">${I.folder(18)}<span class="spacer">${text}</span>
        <button class="btn sm tint" data-action="relink-folder" data-id="${c.id}">${L("وين صار؟", "Where is it?")}</button>${again}</div>`);
    }
    if (c.missing) {
      notices.push(`<div class="notice plain">${I.undo(17)}<span class="spacer">${L(`${num(c.missing)} ملفات حذفتها أو نقلتها من المجلد، وما بنرجّعها إلا إذا طلبت.`, `${num(c.missing)} files were deleted or moved from the folder. We won't bring them back unless you ask.`)}</span>
        <button class="btn sm" data-action="restore-missing" data-id="${c.id}">${L("رجّعها", "Bring them back")}</button></div>`);
    }
    return `<div class="row" style="align-items:flex-end;gap:28px">
        ${bigNumber(num(c.files), L("ملف على رفك", c.files === 1 ? "file on your shelf" : "files on your shelf"))}
        <div class="row" style="margin-inline-start:auto;gap:10px">
          ${stat(L("الحجم", "Size"), bytes(c.bytes))}
          ${stat(L("آخر تحديث", "Last update"), ago(c.lastSync))}
        </div></div>
      ${slots ? shelf({ slots, filled: slots, seed, label: L(`رف فيه ${c.files} ملف`, `Shelf with ${c.files} files`) }) : shelf({ slots: 24, filled: 0, seed, label: L("رف فاضي", "Empty shelf") })}
      ${notices.join("")}`;
  }

  function liveNotice(job) {
    if (job.state === "waiting") {
      S.waitUntil = Date.now() + (job.waitSeconds || 0) * 1000;
      const timer = `<b class="ltr" id="wait-timer" style="font-weight:600">${clock(job.waitSeconds)}</b>`;
      return `<div class="notice gold">${I.hourglass(20)}<span>${L(`تيليجرام طلب نرتاح شوي. بنكمل لحالنا بعد ${timer}`, `Telegram asked us to pause. We'll continue by ourselves in ${timer}`)}</span></div>`;
    }
    if (job.state === "paused") return `<div class="notice plain">${I.pause(18)}<span>${L("وقفنا مؤقتاً. اضغط «كمّل» متى ما تبي.", "Paused. Press Resume whenever you like.")}</span></div>`;
    if (job.state === "running") return `<p class="tiny muted">${L("تقدر تسكّر النافذة، والتنزيل يكمل. تجميعة تبقى فوق بشريط القوائم.", "You can close the window and it keeps going from the menu bar.")}</p>`;
    return "";
  }

  // A file's face: its cover when macOS made one (click to preview), otherwise its type tag.
  function face(f) {
    if (f.cover && f.status === "done") {
      return `<button class="cover" data-action="preview" data-path="${esc(f.path)}" title="${L("معاينة", "Preview")}"><img src="covers/${f.channelId}/${f.msgId}.png" alt=""></button>`;
    }
    return `<span class="tag">${esc(tagOf(f))}</span>`;
  }

  function fileRow(f) {
    let meta = `<div class="meta">${date(f.date)}${f.size ? ` · ${bytes(f.size)}` : ""}${f.topic && f.topic !== "أخرى" ? ` · ${esc(topicName(f.topic))}` : ""}</div>`;
    let mark = "";
    if (f.status === "done") mark = `<span style="color:var(--green)">${I.check(20)}</span>`;
    if (f.status === "duplicate") meta = `<div class="meta">${L("نفس الملف موجود من قبل، فما كررناه", "Already on your shelf, so not saved twice")}</div>`;
    if (f.status === "rejected") meta = `<div class="meta bad">${L("الملف مو PDF حقيقي، فما حفظناه", "Not a real PDF, so it wasn't saved")}</div>`;
    if (f.status === "failed") {
      meta = `<div class="meta warn">${L("ما نزل. بنعيد المحاولة.", "Didn't download. We'll try again.")}</div>`;
      mark = `<span style="color:var(--amber)">${I.refresh(18)}</span>`;
    }
    const open = f.status === "done" && f.path ? `data-action="open-file" data-path="${esc(f.path)}" style="cursor:pointer"` : "";
    return `<div class="file-row">${face(f)}<div style="flex:1;min-width:0" ${open}><div class="name" title="${esc(f.name)}">${esc(displayName(f.name))}</div>${meta}</div>${fileTools(f)}${mark}</div>`;
  }

  function fileTools(f) {
    if (f.status !== "done" || !f.channelId) return "";
    const fav = (f.shelves || []).includes(FAVORITES);
    const where = `data-channel="${f.channelId}" data-msg="${f.msgId}"`;
    return `<button class="icon-btn ${fav ? "on" : ""}" data-action="toggle-favorite" ${where} title="${fav ? L("شيله من المفضلة", "Remove from Favorites") : L("أضفه للمفضلة", "Add to Favorites")}">${fav ? I.starFill(17) : I.star(17)}</button>
      <button class="icon-btn" data-action="shelf-menu" ${where} title="${L("حطه برف", "Put it on a shelf")}">${I.shelfAdd(17)}</button>
      <button class="icon-btn danger" data-action="remove-file" ${where} title="${L("شيله", "Remove")}" aria-label="${L("شيله", "Remove")}">${I.trash(17)}</button>`;
  }

  function filesSection() {
    const c = channelById(S.selected);
    if (!c) return "";
    const job = jobOf(c.id);
    const seen = new Set();
    const rows = [];
    const now = isActive(job) ? (job.active && job.active.length ? job.active : job.current ? [job.current] : []) : [];
    for (const current of now) {
      const pct = current.size ? Math.round((100 * current.received) / current.size) : 0;
      rows.push(`<div class="file-row"><span class="tag">…</span><div style="flex:1;min-width:0"><div class="name">${esc(displayName(current.name))}</div>
        <div class="row" style="gap:10px;margin-top:6px"><div class="minibar"><div style="width:${pct}%"></div></div><span class="meta">${pct}% · ${bytes(current.size)}</span></div></div></div>`);
    }
    for (const f of (S.liveFiles[c.id] || []).concat((S.detail && S.detail.id === c.id && S.detail.recent) || [])) {
      if (seen.has(f.msgId)) continue;
      seen.add(f.msgId);
      rows.push(fileRow(f));
      if (rows.length >= 8) break;
    }
    if (!rows.length) return "";
    return `<section class="card files rows">${rows.join("")}</section>`;
  }

  // ---------- Add page

  function addPage() {
    const A = S.add;
    const r = A.result;
    let body = "";
    if (A.busy) {
      const found = A.scanned ? L(` لقينا ${num(A.scanned)} ملف لين الحين`, ` ${num(A.scanned)} found so far`) : "";
      const wait = A.waiting ? L(` · تيليجرام طلب ننطر ${A.waiting} ثانية`, ` · Telegram asked us to wait ${A.waiting}s`) : "";
      body = `<div class="card row" style="padding:22px;gap:14px"><div class="spin"></div><span class="text-2">${L("نفحص القناة…", "Checking the channel…")}${found}${wait}</span></div>`;
    } else if (A.error) {
      body = `<div class="notice red">${I.warn(18)}<span>${esc(A.error)}</span></div>`;
    } else if (r) {
      body = scanResult(r);
    }
    if (!A.busy && !r) body += minePicker();
    return `<div><h1 class="page-title">${L("أضف قناة", "Add a channel")}</h1><p class="text-2">${L("الصق رابط قناة عامة أو أي منشور فيها، أو اختار من قنواتك وقروباتك تحت.", "Paste a link to a public channel or any post in it, or pick from your channels and groups below.")}</p></div>
      <form data-submit="inspect" class="row" style="gap:10px">
        <label class="field ${r ? "good" : ""}" style="flex:1"><span class="hidden">${L("رابط القناة", "Channel link")}</span>
          ${r ? `<span style="color:var(--green)">${I.check(20)}</span>` : I.search(20)}
          <input class="ltr mono" data-model="add.link" value="${esc(A.link)}" placeholder="https://t.me/…" data-autofocus data-paste="inspect" style="text-align:left"></label>
        <button class="btn big" type="submit" ${A.busy ? "disabled" : ""}>${L("افحص", "Check")}</button>
      </form>${body}`;
  }

  function minePicker() {
    const M = S.mine;
    if (M.loading) {
      return `<section class="card row" style="padding:18px 22px;gap:12px"><div class="spin"></div><span class="text-2 small">${L("نجيب قنواتك وقروباتك…", "Getting your channels and groups…")}</span></section>`;
    }
    if (M.error) {
      return `<div class="notice plain">${I.warn(18)}<span class="spacer">${esc(M.error)}</span><button class="btn sm" data-action="load-mine">${L("جرّب مرة ثانية", "Try again")}</button></div>`;
    }
    if (!M.list) return "";
    if (!M.list.length) return `<p class="small muted">${L("ما لقينا قنوات أو قروبات بحسابك.", "There are no channels or groups in your account.")}</p>`;
    return `<section class="card stack" style="padding:16px 18px 10px;gap:10px">
        <div class="row" style="gap:12px"><span class="small muted spacer">${L("أو اختار من قنواتك وقروباتك", "Or pick from your channels and groups")}</span>
          <label class="field slim" style="width:240px"><span class="hidden">${L("دوّر بقنواتك", "Filter your channels")}</span>${I.search(16)}
            <input data-model="mine.q" value="${esc(M.q)}" placeholder="${L("دوّر", "Filter")}"></label></div>
        <div class="mine-list" id="mine-list">${mineRows()}</div></section>`;
  }

  function mineRows() {
    const q = S.mine.q.trim().toLowerCase();
    const rows = S.mine.list.filter((c) => !q || c.title.toLowerCase().includes(q) || c.username.toLowerCase().includes(q)).map((c) => {
      let side = I.chevron(16);
      let action = `data-action="pick-mine" data-id="${c.id}"`;
      if (c.protected) {
        side = `<span class="tiny muted row" style="gap:5px">${I.lock(13)}${L("صاحبها مانع الحفظ", "Saving is turned off")}</span>`;
        action = "disabled";
      } else if (c.added) {
        side = `<span class="tiny" style="color:var(--green-text)">${L("على رفك", "On your shelf")}</span>`;
        action = `data-action="open-channel" data-id="${c.id}"`;
      }
      return `<button class="mine-row" type="button" ${action}>${avatar(c, 34, true)}
        <span style="flex:1;min-width:0"><span class="mine-title">${esc(c.title)}</span><span class="tiny muted">${channelLine(c)}</span></span>
        <span class="text-2">${side}</span></button>`;
    }).join("");
    return rows || `<p class="small muted" style="padding:8px 4px">${L("ما في شي بهالاسم.", "Nothing by that name.")}</p>`;
  }

  function scanCard(r) {
    const c = r.channel;
    const { count, size } = chosenTotals(r);
    const years = r.firstDate ? `${new Date(r.firstDate).getFullYear()}` : "";
    const [sizeNumber, sizeUnit] = bytes(size).split(" ");
    const figure = (value, label, gold) => `<div><div class="rakkas" style="font-size:36px;line-height:1${gold ? ";color:var(--gold)" : ""}">${value}</div><div class="tiny muted" style="margin-top:4px">${label}</div></div>`;
    return `<section class="card row" style="padding:20px 22px;gap:18px">
        <div class="ring" style="width:64px;height:64px">${avatar(c, 58)}</div>
        <div style="flex:1;min-width:0"><div style="font-size:24px;font-weight:600;line-height:1.3">${esc(c.title)}</div>
          <div class="text-2 small">${channelLine(c)}</div></div>
        <div class="row" style="gap:26px;padding-inline-start:22px;border-inline-start:1px solid var(--line)">
          ${figure(num(count), L("ملف مختار", "files chosen"), true)}
          ${figure(sizeNumber, sizeUnit || "")}
          ${years ? figure(years, L("لين اليوم", "to today")) : ""}
        </div></section>`;
  }

  // Counts follow the filter once the engine has re-counted; until then, the whole channel.
  function chosenTotals(r) {
    const counts = kindCounts(r);
    const chosen = KIND_ORDER.filter((k) => r.kinds[k] && r.kinds[k].count > 0 && S.add.kinds.includes(k));
    return { count: chosen.reduce((s, k) => s + counts[k].count, 0), size: chosen.reduce((s, k) => s + counts[k].bytes, 0) };
  }

  // Per kind after the filter, with «other» narrowed to the formats left on.
  function kindCounts(r) {
    const A = S.add;
    const counts = { ...(A.filtered || r.kinds) };
    const others = (A.filteredOthers || r.others || []).filter((o) => !A.skipExts.includes(o.ext));
    if (counts.other) counts.other = { count: others.reduce((s, o) => s + o.count, 0), bytes: others.reduce((s, o) => s + o.bytes, 0) };
    return counts;
  }

  function otherFormats(r) {
    const A = S.add;
    if (!A.kinds.includes("other") || !(r.others || []).length) return "";
    const counts = Object.fromEntries((A.filteredOthers || r.others).map((o) => [o.ext, o.count]));
    const chips = r.others.map((o) => {
      const on = !A.skipExts.includes(o.ext);
      const label = o.ext ? o.ext.slice(1).toUpperCase() : L("بدون امتداد", "No extension");
      return `<button class="chip small ${on ? "on" : ""}" type="button" data-action="toggle-ext" data-ext="${esc(o.ext)}" aria-pressed="${on}">${esc(label)} <span>${num(counts[o.ext] || 0)}</span></button>`;
    }).join("");
    return `<div class="other-formats"><p class="tiny muted">${L("الصيغ اللي لقيناها. شيل اللي ما تبيه:", "Formats we found. Turn off what you don't want:")}</p><div class="chips">${chips}</div></div>`;
  }

  function kindsList(r) {
    const A = S.add;
    const counts = kindCounts(r);
    const blocked = r.blocked && r.blocked.count
      ? `<p class="tiny muted row" style="gap:6px;padding-top:10px">${I.lock(13)}${L(
        `وفيه ${counted(r.blocked.count, "برنامج", "برنامجين", "برامج", "", "")} (${r.blocked.exts.map((e) => e.slice(1)).join("، ")}) ما نجمعها، عشان سلامة جهازك.`,
        `Plus ${counted(r.blocked.count, "", "", "", "program", "programs")} (${r.blocked.exts.map((e) => e.slice(1)).join(", ")}) we don't collect, to keep your Mac safe.`)}</p>` : "";
    return `<p class="small muted" style="padding-bottom:4px">${L("شنو تبي تنزّل؟", "What should we download?")}</p>` +
      KIND_ORDER.filter((k) => r.kinds[k] && r.kinds[k].count > 0).map((k) => {
        const on = A.kinds.includes(k);
        const row = `<button class="row" type="button" data-action="toggle-kind" data-kind="${k}" role="checkbox" aria-checked="${on}" style="padding:10px 0;border:none;background:none;width:100%;cursor:pointer;font-size:15px;text-align:start">
          <span class="check ${on ? "on" : ""}">${on ? I.check(14) : ""}</span><span class="spacer">${kind(k).label}</span>
          <span style="color:${on ? "var(--gold-light)" : "var(--muted)"};font-weight:500">${num(counts[k].count)}</span></button>`;
        return k === "other" ? `<div>${row}${otherFormats(r)}</div>` : row;
      }).join("") + blocked;
  }

  function goRow(r) {
    const A = S.add;
    const { count, size } = chosenTotals(r);
    // Better to say so now than to stop halfway with a full disk.
    const tooBig = A.free != null && size > A.free;
    const note = tooBig
      ? `<span class="small" style="margin-inline-start:auto;color:var(--red-text)">${L(`المساحة ما تكفي: تحتاج ${bytes(size)}، والفاضي هني ${bytes(A.free)}. اختر أنواع أقل أو فلتر أو مجلد ثاني.`, `Not enough space: this needs ${bytes(size)} and ${bytes(A.free)} is free here. Choose fewer kinds, a filter, or another folder.`)}</span>`
      : `<span class="small muted" style="margin-inline-start:auto">${L("تقدر تكمّل شغلك، والتنزيل يصير بالخلفية.", "Carry on with your work; it downloads in the background.")}</span>`;
    return `<button class="btn gold big" data-action="start-download" ${count && !A.adding && !tooBig ? "" : "disabled"}>${A.adding ? '<div class="spin"></div>' : I.download(20)}${L(`نزّل ${num(count)} ملف · ${bytes(size)}`, `Download ${num(count)} files · ${bytes(size)}`)}</button>
      <button class="btn big" data-action="reset-add">${L("إلغاء", "Cancel")}</button>${note}`;
  }

  function filterState() {
    const A = S.add;
    return `${A.counting ? '<div class="spin"></div>' : ""}${hasFilter(A) ? `<button class="btn sm" data-action="clear-filters">${L("امسح الفلتر", "Clear filter")}</button>` : ""}`;
  }

  // Typing in the filter re-counts without re-drawing the fields, so a half-typed date stays put.
  function patchScan() {
    const r = S.add.result;
    if (S.page !== "add" || !r) return;
    const parts = { "scan-card": () => scanCard(r), "scan-kinds": () => kindsList(r), "scan-go": () => goRow(r), "filter-state": filterState };
    for (const [id, make] of Object.entries(parts)) {
      const el = document.getElementById(id);
      if (el) el.innerHTML = make();
    }
  }

  function scanResult(r) {
    const A = S.add;
    const c = r.channel;
    const available = KIND_ORDER.filter((k) => r.kinds[k] && r.kinds[k].count > 0);
    const chosen = available.filter((k) => A.kinds.includes(k));
    const card = `<div id="scan-card">${scanCard(r)}</div>`;
    if (r.existing) {
      return card + `<div class="notice gold">${I.books(18)}<span class="spacer">${L("هذي القناة موجودة برفك من قبل.", "This channel is already on your shelf.")}</span><button class="btn sm" data-action="open-channel" data-id="${c.id}">${L("روح لها", "Go to it")}</button></div>`;
    }
    if (!available.length) {
      return card + `<div class="notice plain">${I.warn(18)}<span>${L("ما لقينا بهالقناة ملفات نقدر نجمعها.", "We found no files to collect in this channel.")}</span></div>`;
    }
    const option = (key, icon, label) => `<div class="row" style="padding:12px 0;gap:12px"><span class="text-2">${icon}</span><span class="spacer small">${label}</span>
      <button class="switch" role="switch" aria-checked="${A[key]}" aria-label="${label}" data-action="toggle-option" data-key="${key}"></button></div>`;
    const media = chosen.some((k) => k === "images" || k === "videos")
      ? `<p class="small muted">${L("الصور والفيديو تاخذ مساحة أكبر بواجد. تأكد إن عندك مكان.", "Photos and videos take much more space. Make sure you have room.")}</p>` : "";
    return card + `<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px">
        <section class="card rows" style="padding:12px 20px" id="scan-kinds">${kindsList(r)}</section>
        <section class="card rows" style="padding:6px 20px">
          <div class="row" style="padding:10px 0;gap:12px"><span class="text-2">${I.folder(20)}</span>
            <div style="flex:1;min-width:0"><div class="tiny muted">${L("مكان الحفظ", "Save to")}</div><div class="small" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(A.folder)}">${prettyPath(A.folder)}</div>
              ${A.free != null ? `<div class="tiny muted">${L(`فيه ${bytes(A.free)} فاضية هني`, `${bytes(A.free)} free here`)}</div>` : ""}</div>
            <button class="btn sm" data-action="pick-folder">${L("تغيير", "Change")}</button></div>
          ${option("topicFolders", I.tag(20), L("مجلد لكل قسم (من هاشتاقات القناة وأسماء ملفاتها)", "A folder per section (from the channel's hashtags and file names)"))}
          ${option("yearFolders", I.calendar(20), L("مجلد لكل سنة", "A folder per year"))}
          ${option("smartNames", I.pen(20), L("إذا اسم الملف عام، سمّه من وصف الرسالة", "If a file's name is generic, name it from the post"))}
          ${option("autoUpdate", I.refresh(20), L("حدّثها لحالها كل يوم", "Update it by itself every day"))}
        </section></div>
      <section class="card stack" style="padding:14px 20px 18px;gap:12px">
        <div class="row" style="gap:10px"><span class="text-2">${I.filter(18)}</span><span class="small">${L("فلتر", "Filter")} <span class="muted">${L("(اختياري)", "(optional)")}</span></span>
          <span class="row" id="filter-state" style="gap:10px;margin-inline-start:auto">${filterState()}</span></div>
        ${filterFields("add", A)}</section>
      ${media}
      <div class="row" style="gap:12px" id="scan-go">${goRow(r)}</div>`;
  }

  // ---------- Library page

  function highlight(text, query) {
    const tokens = query.trim().split(/\s+/).filter(Boolean).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const html = esc(text);
    if (!tokens.length) return html;
    const re = new RegExp(`(${tokens.map(esc).join("|")})`, "gi");
    return html.replace(re, "<mark>$1</mark>");
  }

  function shelfChips() {
    const Lb = S.lib;
    const chips = S.shelves.map((s) => `<button class="chip ${Lb.shelf === s.id ? "on" : ""}" data-action="pick-shelf" data-shelf="${s.id}">${s.favorites ? I.starFill(14) : I.books(14)}${esc(shelfName(s))} <span>${num(s.files)}</span></button>`).join("");
    const add = S.newShelf.open
      ? `<form data-submit="create-shelf" class="chip-form"><input class="input slim" data-model="newShelf.name" value="${esc(S.newShelf.name)}" placeholder="${L("اسم الرف، مثل: بحثي", "Shelf name, e.g. Research")}" maxlength="40"></form>`
      : `<button class="chip ghost" data-action="new-shelf">${I.plus(14)}${L("رف جديد", "New shelf")}</button>`;
    return chips + add;
  }

  function topicChips() {
    const Lb = S.lib;
    return Lb.topics.map((t) => `<button class="chip ${Lb.topic === t.topic ? "on" : ""}" data-action="pick-topic" data-topic="${esc(t.topic)}">${esc(topicName(t.topic))} <span>${num(t.files)}</span></button>`).join("");
  }

  function shelfHeader() {
    const s = S.shelves.find((x) => x.id === S.lib.shelf);
    if (!s) return "";
    const R = S.renameShelf && S.renameShelf.id === s.id ? S.renameShelf : null;
    if (R) {
      return `<form data-submit="rename-shelf" class="row" style="gap:8px;margin-bottom:12px">
        <input class="input slim" data-model="renameShelf.name" value="${esc(R.name)}" maxlength="40" style="max-width:300px">
        <button class="btn sm gold" type="submit">${L("احفظ", "Save")}</button><button class="btn sm" type="button" data-action="cancel-rename">${L("إلغاء", "Cancel")}</button></form>`;
    }
    const tools = s.favorites ? "" : `<button class="btn sm" data-action="rename-shelf">${I.pen(14)}${L("غيّر الاسم", "Rename")}</button>
      <button class="btn sm danger" data-action="delete-shelf">${L("احذف الرف", "Delete shelf")}</button>`;
    return `<div class="row" style="gap:10px;margin-bottom:12px"><span class="row" style="gap:8px;font-weight:600;font-size:17px">${s.favorites ? `<span style="color:var(--gold)">${I.starFill(17)}</span>` : I.books(17)}${esc(shelfName(s))}</span>
      <span class="small muted spacer">${filesCount(s.files)}</span>${tools}</div>`;
  }

  function libraryResults() {
    const Lb = S.lib;
    if (!(Lb.q.trim() || Lb.topic || Lb.shelf) || !Lb.searched) return "";
    const head = Lb.shelf ? shelfHeader() : "";
    if (!Lb.results.length) {
      const empty = Lb.shelf
        ? L("الرف فاضي. حط فيه ملفات من زر الرف اللي جنب أي ملف.", "This shelf is empty. Add files with the shelf button next to any file.")
        : L("ما لقينا شي. جرّب كلمة ثانية أو جزء من الاسم.", "Nothing found. Try another word or part of the name.");
      return `${head}<div class="notice plain">${empty}</div>`;
    }
    return `${head}<section class="card files rows">${Lb.results.map((f) => `<div class="file-row">
        ${face(f)}
        <div style="flex:1;min-width:0"><div class="name" title="${esc(f.name)}">${highlight(displayName(f.name), Lb.q)}</div>
          <div class="meta">${esc(f.channelTitle)} · ${date(f.date)} · ${bytes(f.size)}${f.topic ? ` · ${esc(topicName(f.topic))}` : ""}${f.matchedIn === "caption" && Lb.q.trim() ? L(" · لقيناه من وصف الرسالة", " · found in the post text") : ""}</div></div>
        ${fileTools(f)}
        <button class="btn sm tint" data-action="open-file" data-path="${esc(f.path)}">${L("افتح", "Open")}</button>
        <a class="small row" style="gap:4px;color:var(--text-2)" data-action="open-url" data-url="${esc(f.link)}">${L("المنشور", "Post")} ${I.external(13)}</a></div>`).join("")}</section>`;
  }

  function libraryTotal() {
    return L(
      `<span class="rakkas" style="color:var(--gold);font-size:20px">${num(S.totals.files)}</span> ملف على رفك من ${num(S.channels.length)} قنوات · ${bytes(S.totals.bytes)}`,
      `<span class="rakkas" style="color:var(--gold);font-size:20px">${num(S.totals.files)}</span> files on your shelf from ${num(S.channels.length)} channels · ${bytes(S.totals.bytes)}`);
  }

  function channelCards() {
    return S.channels.map((c) => {
      const job = jobOf(c.id);
      const note = isActive(job) ? `<span class="tiny" style="color:var(--gold-light)">${sideState(job.state)}</span>`
        : c.failed ? `<span class="tiny" style="color:var(--amber)">${L(`${num(c.failed)} ما نزلت`, `${num(c.failed)} failed`)}</span>`
        : `<span class="tiny" style="color:var(--green-text)">${c.autoUpdate ? L("تتحدث لحالها", "Updates by itself") : L("محفوظة", "Saved")}</span>`;
      return `<section class="card stack" style="padding:16px 18px;gap:10px">
        ${shelf({ slots: Math.max(3, Math.min(c.files, 16)), filled: Math.min(c.files, 16), height: 64, scale: 0.6, seed: c.id % 7, label: c.title })}
        <div><div style="font-weight:500">${esc(c.title)}</div><div class="tiny muted">${filesCount(c.files)} · ${ago(c.lastSync)}</div></div>
        <div class="row" style="gap:8px;margin-top:auto">
          <button class="btn sm" data-action="update" data-id="${c.id}" ${isActive(job) ? "disabled" : ""}>${I.refresh(14)}${L("حدّث", "Update")}</button>
          <button class="btn sm" data-action="open-channel" data-id="${c.id}">${L("افتح", "Open")}</button>
          <button class="icon-btn danger" data-action="remove-channel" data-id="${c.id}" title="${L("شيل القناة", "Remove channel")}" aria-label="${L("شيل القناة", "Remove channel")}">${I.trash(16)}</button>
          <span class="spacer"></span>${note}</div></section>`;
    }).join("");
  }

  function libraryPage() {
    const Lb = S.lib;
    const chips = Lb.topics.length > 1 ? `<div class="stack" style="gap:8px"><p class="small muted">${L("الأقسام", "Sections")}</p><div class="chips" id="lib-topics">${topicChips()}</div></div>` : "";
    const ownShelves = `<div class="stack" style="gap:8px"><p class="small muted">${L("رفوفك الخاصة", "Your own shelves")}</p><div class="chips" id="lib-shelves">${shelfChips()}</div></div>`;
    const count = (Lb.q.trim() || Lb.topic || Lb.shelf) && Lb.searched ? L(`${num(Lb.results.length)} نتيجة`, `${num(Lb.results.length)} results`) : "";
    return `<div><h1 class="page-title">${L("المكتبة", "Library")}</h1><p class="text-2" id="lib-total">${libraryTotal()}</p></div>
      <label class="field"><span class="hidden">${L("ابحث", "Search")}</span><span style="color:var(--gold-light)">${I.search(20)}</span>
        <input data-model="lib.q" value="${esc(Lb.q)}" placeholder="${L("ابحث باسم الملف أو بكلمة من وصفه", "Search by file name or a word from its post")}" data-autofocus>
        <span class="small muted" id="lib-count">${count}</span></label>
      ${ownShelves}
      ${chips}
      <div id="lib-results">${libraryResults()}</div>
      ${S.channels.length ? `<p class="small muted">${L("قنواتك", "Your channels")}</p><div class="shelf-grid" id="lib-channels">${channelCards()}</div>` :`<div class="notice plain">${L("رفك فاضي. أضف قناة وترجع هني تدوّر بملفاتها.", "Your shelf is empty. Add a channel and come back to search its files.")}</div>`}`;
  }

  // ---------- Settings page

  function settingsPage() {
    const me = S.me || {};
    const updateLine = S.update === null ? L("نشيك…", "Checking…")
      : S.update.available ? L(`فيه نسخة جديدة: ${esc(S.update.latest)}`, `New version: ${esc(S.update.latest)}`)
      : S.update.latest ? L("عندك آخر نسخة.", "You have the latest version.")
      : L("ما قدرنا نشيك الحين.", "Couldn't check right now.");
    return `<h1 class="page-title">${L("الإعدادات", "Settings")}</h1>
      <section class="card rows" style="padding:6px 22px">
        <div class="row" style="padding:16px 0;gap:14px"><span class="avatar dim" style="width:44px;height:44px">${esc(initials(me.name || L("حسابك", "You")))}</span>
          <div class="spacer"><div style="font-weight:500">${esc(me.name || L("حسابك", "Your account"))}</div><div class="small muted ltr" style="text-align:start">${esc(me.phone || "")}${me.username ? ` · @${esc(me.username)}` : ""}</div></div>
          <button class="btn danger" data-action="logout">${L("اطلع من الحساب", "Sign out")}</button></div>
        <div class="row" style="padding:16px 0;gap:14px"><span class="icon-tile">${I.lock(20)}</span>
          <div class="spacer"><div style="font-weight:500">${L("مفتاحك الخاص", "Your own key")}</div><div class="small muted mono ltr" style="text-align:start">${esc(S.keyMasked || "")}</div></div>
          <button class="btn" data-action="forget-key">${L("غيّر المفتاح", "Change key")}</button></div>
        <div class="row" style="padding:16px 0;gap:14px"><span class="icon-tile">${I.globe(20)}</span>
          <div class="spacer"><div style="font-weight:500">${L("اللغة", "Language")}</div></div>
          <div class="segmented"><button class="${LANG === "ar" ? "on" : ""}" data-action="set-language" data-lang="ar">العربية</button><button class="${LANG === "en" ? "on" : ""}" data-action="set-language" data-lang="en">English</button></div></div>
        <div class="row" style="padding:16px 0;gap:14px"><span class="icon-tile">${I.sparkle(20)}</span>
          <div class="spacer"><div style="font-weight:500">${L("التحديثات", "Updates")}</div><div class="small muted">${updateLine}</div></div>
          ${S.update && S.update.available
            ? `<button class="btn gold" data-action="run-update" ${S.updating ? "disabled" : ""}>${S.updating ? '<div class="spin"></div>' : L("حدّث الحين", "Update now")}</button>`
            : `<button class="btn" data-action="check-update">${L("تحقق الحين", "Check now")}</button>`}</div>
      </section>
      <section class="card stack" style="padding:20px 22px;gap:10px">
        <div class="row" style="gap:10px">${logo(28)}<span class="rakkas" style="font-size:24px;color:var(--gold)">${brandName()}</span><span class="small muted">${L("الإصدار", "Version")} ${esc(S.version)}</span></div>
        <p class="text-2 small" style="line-height:1.9">${L(
          'تجميعة تجمع ملفات القنوات العامة بتيليجرام على جهازك. تستخدم واجهة تيليجرام الرسمية <span class="ltr">(Telegram API)</span> بمفتاحك أنت، وكل شي يصير بجهازك: الملفات والسجل والجلسة. ما فيه أي خادم بالنص.',
          "Tajmeea collects files from public Telegram channels onto your Mac. It uses the official Telegram API with your own key, and everything happens on your Mac: files, history and session. There's no server in between.")}</p>
        <p class="tiny muted">${L("تجميعة مو تطبيق رسمي من تيليجرام. استخدمها للمحتوى اللي يحق لك تحفظه.", "Tajmeea is not an official Telegram app. Use it for content you're entitled to keep.")}</p>
      </section>`;
  }

  // ---------- Putting a file on a shelf

  function filesMatching(channelId, msgId) {
    const lists = [S.lib.results, (S.detail && S.detail.recent) || [], S.liveFiles[channelId] || []];
    return lists.flat().filter((f) => f.msgId === msgId && (f.channelId || channelId) === channelId);
  }

  function shelfMenu() {
    const M = S.shelfMenu;
    if (!M) return "";
    const f = filesMatching(M.channelId, M.msgId)[0] || {};
    const items = S.shelves.map((s) => {
      const on = (f.shelves || []).includes(s.id);
      return `<button class="pop-item" data-action="shelf-toggle" data-shelf="${s.id}" role="checkbox" aria-checked="${on}">
        <span class="check ${on ? "on" : ""}">${on ? I.check(12) : ""}</span><span class="spacer">${esc(shelfName(s))}</span></button>`;
    }).join("");
    return `<div class="popover" style="top:${M.top}px;${M.side}:${M.x}px"><p class="tiny muted" style="padding:4px 8px 6px">${L("حطه برف", "Put it on a shelf")}</p>${items}
      <form data-submit="menu-new-shelf" class="row" style="gap:6px;padding:8px 4px 2px">
        <input class="input slim" data-model="shelfMenu.name" value="${esc(M.name || "")}" placeholder="${L("رف جديد…", "New shelf…")}" maxlength="40">
        <button class="btn sm" type="submit" aria-label="${L("أضف", "Add")}">${I.plus(14)}</button></form></div>`;
  }

  function drawMenus() {
    let root = document.getElementById("popover-root");
    if (!root) {
      root = document.createElement("div");
      root.id = "popover-root";
      document.body.appendChild(root);
    }
    root.innerHTML = shelfMenu() + channelMenu();
  }

  async function loadShelves() {
    try { S.shelves = await call("shelf.list"); } catch (error) { /* shelves are extra; the rest still works */ }
  }

  async function putOnShelf(channelId, msgId, shelfId, on) {
    try {
      const { shelves } = await call("shelf.put", { shelfId, channelId, msgId, on });
      S.shelves = shelves;
      for (const f of filesMatching(channelId, msgId)) {
        const set = new Set(f.shelves || []);
        if (on) set.add(shelfId); else set.delete(shelfId);
        f.shelves = [...set].sort((a, b) => a - b);
      }
      if (S.lib.shelf === shelfId && !on) S.lib.results = S.lib.results.filter((f) => !(f.channelId === channelId && f.msgId === msgId));
      if (S.page === "channel") scheduleLive();
      patchLibrary();
      drawMenus();
    } catch (error) { toast(error.message, true); }
  }

  // ---------- Status for the menu bar icon

  function reportStatus() {
    const busy = S.channels.filter((c) => isActive(jobOf(c.id)));
    let text = L("كل شي محدّث", "Everything is up to date");
    if (busy.length) {
      const c = busy[0];
      const job = jobOf(c.id);
      text = job.state === "running" && job.total
        ? L(`ينزّل من «${c.title}»: ${num(job.processed)} من ${num(job.total)} · ${percentOf(job)}%`, `Downloading “${c.title}”: ${num(job.processed)} of ${num(job.total)} · ${percentOf(job)}%`)
        : `${sideState(job.state)} · ${c.title}`;
      if (busy.length > 1) text += ` (+${busy.length - 1})`;
    }
    if (text === S.statusText) return;
    S.statusText = text;
    B.native("status", { text }).catch(() => {});
  }

  // ---------- Toast and modal

  let toastTimer = 0;
  function toast(message, isError = false) {
    const el = document.getElementById("toast");
    el.textContent = message;
    el.className = isError ? "error" : "";
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 4200);
  }

  // With `option`, a checkbox sits above the buttons and the answer is { ok, checked }.
  function confirmBox({ title, body, yes, danger = false, option = "", optionNote = "" }) {
    return new Promise((resolve) => {
      const root = document.getElementById("modal-root");
      const extra = option ? `<label class="modal-option"><input type="checkbox" id="modal-option">
          <span><span>${esc(option)}</span>${optionNote ? `<span class="tiny muted">${esc(optionNote)}</span>` : ""}</span></label>` : "";
      root.innerHTML = `<div class="modal-back"><div class="modal" role="dialog" aria-modal="true">
        <h2 style="font-size:20px;font-weight:600">${esc(title)}</h2><p class="text-2">${esc(body)}</p>${extra}
        <div class="row" style="gap:10px;justify-content:flex-end"><button class="btn" data-answer="no">${L("ارجع", "Back")}</button>
        <button class="btn ${danger ? "danger" : "gold"}" data-answer="yes">${esc(yes)}</button></div></div></div>`;
      root.querySelector('[data-answer="yes"]').focus();
      root.onclick = (e) => {
        const btn = e.target.closest("[data-answer]");
        if (!btn && e.target !== root.firstElementChild) return;
        const ok = Boolean(btn && btn.dataset.answer === "yes");
        const box = root.querySelector("#modal-option");
        const checked = Boolean(box && box.checked);
        root.innerHTML = "";
        root.onclick = null;
        resolve(option ? { ok, checked } : ok);
      };
    });
  }

  // ---------- Talking to the engine

  async function call(method, params) {
    try {
      return await B.call(method, params);
    } catch (error) {
      error.message = errorText(error);
      if (error.code === "logged_out") {
        S.view = "onboard";
        S.step = "login";
        S.login = { ...S.login, mode: "qr", step: "qr", matrix: null, error: error.message };
        render();
        startQr();
      }
      throw error;
    }
  }

  async function boot() {
    if (new URLSearchParams(location.search).get("setup") === "missing") {
      S.view = "setup";
      return render();
    }
    try {
      const settings = await call("settings.get");
      setLanguage(settings.language);
      if (LANG === "en") B.native("setLanguage", { language: "en" }).catch(() => {});
    } catch (error) { setLanguage(/^ar/i.test(navigator.language) ? "ar" : "en"); }
    render();
    try {
      apply(await call("app.state"));
    } catch (error) {
      toast(error.message, true);
    }
  }

  function apply(state) {
    S.version = state.version;
    S.home = (state.downloadRoot || "").replace(/\/Downloads\/[^/]+$/, "");
    S.keyMasked = state.keyMasked || "";
    S.offline = state.offline;
    S.channels = state.channels || [];
    S.totals = state.totals || S.totals;
    if (!state.hasKey) {
      S.view = "onboard";
      S.step = "key";
      render();
    } else if (!state.authorized) {
      S.view = "onboard";
      S.step = "login";
      render();
      startQr();
    } else {
      S.me = state.me;
      enterMain();
      if (state.offline) toast(L("ما فيه نت الحين. تقدر تتصفح مكتبتك، والتنزيل يرجع لما يرجع النت.", "You're offline. Your library still works, and downloads resume when you're back online."), true);
    }
  }

  function enterMain() {
    S.view = "main";
    loadShelves();
    reportStatus();
    const busy = S.channels.find((c) => isActive(c.job || {}));
    if (S.channels.length) openChannel((busy || S.channels[0]).id);
    else { S.page = "empty"; render(); }
    checkUpdate();
  }

  // Once at start and then daily: is there a newer Tajmeea on GitHub?
  let updateTimer = 0;
  async function checkUpdate() {
    clearTimeout(updateTimer);
    updateTimer = setTimeout(checkUpdate, 24 * 3600 * 1000);
    try { S.update = await call("app.checkUpdate"); } catch (error) { S.update = { available: false, latest: null }; }
    if (S.view === "main") render();
  }

  async function refreshChannels() {
    const overview = await call("library.overview");
    S.channels = overview.channels;
    S.totals = overview.totals;
    for (const c of S.channels) if (c.job && c.job.state) S.live[c.id] = c.job;
  }

  async function openChannel(id) {
    S.page = "channel";
    S.selected = id;
    render();
    try {
      const detail = await call("channel.get", { channelId: id });
      S.detail = detail;
      const index = S.channels.findIndex((c) => c.id === id);
      if (index >= 0) S.channels[index] = { ...S.channels[index], ...detail };
      if (detail.job && detail.job.state) S.live[id] = detail.job;
      S.liveFiles[id] = [];
      if (S.page === "channel" && S.selected === id) render();
    } catch (error) {
      toast(error.message, true);
    }
  }

  // Key step

  // Put whatever part of the key the pasted text holds (one copied value, or a whole page) into its box.
  // `slot` is the box the person pasted into; nothing is ever taken from the clipboard on its own.
  const wrong = (what) => ({
    id: L("هذا مو رقم التطبيق. انسخه من الزر اللي جنب api_id.", "That's not the app number. Copy it with the button next to api_id."),
    hash: L("هذا مو المفتاح. انسخه من الزر اللي جنب api_hash.", "That's not the key. Copy it with the button next to api_hash."),
    hidden: L("المفتاح طالع نقاط. انسخه من الزر اللي جنب api_hash.", "The key shows as dots. Copy it with the button next to api_hash."),
  })[what];
  async function absorbKey(text, slot) {
    const raw = (text || "").trim();
    if (!raw) {
      if (slot) { S.key[slot] = ""; S.key.error = ""; renderKeyStatus(); }
      return;
    }
    let found;
    try { found = await call("key.scan", { text }); } catch (error) { S.key.error = error.message; return renderKeyStatus(); }
    if (found.apiId) Object.assign(S.key, { id: String(found.apiId), idText: String(found.apiId) });
    if (found.apiHash) Object.assign(S.key, { hash: found.apiHash, hashText: found.apiHash });
    S.key.error = "";
    if (slot === "id" && !found.apiId) {
      S.key.id = "";
      if (raw.length >= 5) S.key.error = wrong("id");
    }
    if (slot === "hash" && !found.apiHash) {
      S.key.hash = "";
      if (raw.length >= 8) S.key.error = wrong(found.hashHidden ? "hidden" : "hash");
    }
    renderKeyStatus();
  }
  let typedTimer = 0;
  function absorbTypedSoon(slot) {
    clearTimeout(typedTimer);
    typedTimer = setTimeout(() => absorbKey(S.key[slot + "Text"], slot), 400);
  }
  function renderKeyStatus() {
    if (S.view === "onboard" && S.step === "key") render();
  }

  // Login step

  let qrTimer = 0;
  function startQr() {
    S.login = { ...S.login, mode: "qr", step: "qr", matrix: null, error: "" };
    call("auth.qr.start").catch((error) => {
      if (error.code === "bad_key" || error.code === "no_key") {
        S.step = "key";
        S.key.error = error.message;
      } else {
        S.login.error = error.message;
      }
      render();
    });
    clearInterval(qrTimer);
    qrTimer = setInterval(() => {
      const el = document.getElementById("qr-timer");
      if (el && S.login.matrix) el.innerHTML = qrTimerText();
      const wait = document.getElementById("wait-timer");
      if (wait && S.waitUntil) wait.textContent = clock((S.waitUntil - Date.now()) / 1000);
    }, 1000);
  }

  // Tell the person when a download they're not watching finishes.
  function notifyFinished(channelId, job) {
    const c = channelById(channelId);
    if (!c) return;
    let body = "";
    if (job.state === "done" && job.done > 0) body = L(`نزل ${num(job.done)} ملف جديد من «${c.title}».`, `${num(job.done)} new files from “${c.title}”.`);
    if (job.state === "failed") body = L(`وقف التنزيل من «${c.title}».`, `Downloading from “${c.title}” stopped.`);
    if (body) B.native("notify", { title: brandName(), body }).catch(() => {});
  }

  // ---------- Events from the engine

  B.on("auth.qr", (d) => {
    S.login.matrix = d.matrix;
    S.login.expiresAt = Date.now() + d.expiresIn * 1000;
    S.login.error = "";
    if (S.view === "onboard" && S.step === "login" && S.login.mode === "qr") render();
  });
  B.on("auth.password", (d) => {
    S.login.step = "password";
    S.login.hint = d.hint || "";
    S.login.error = "";
    render();
  });
  B.on("auth.done", async (d) => {
    S.me = d.me;
    try { await refreshChannels(); } catch (error) { /* first run: nothing yet */ }
    enterMain();
  });
  B.on("auth.error", (d) => {
    const message = errorText(d);
    if (d.code === "bad_key") { S.step = "key"; S.key.error = message; }
    else S.login.error = message;
    render();
  });
  B.on("job.progress", (d) => {
    const before = S.live[d.channelId] || {};
    S.live[d.channelId] = d;
    reportStatus();
    if (before.state !== d.state && ["done", "failed", "stopped"].includes(d.state)) {
      notifyFinished(d.channelId, d);
      refreshChannels().then(() => {
        if (S.page === "channel" && S.selected === d.channelId) openChannel(d.channelId);
        else render();
      }).catch(() => scheduleLive());
      return;
    }
    scheduleLive();
  });
  B.on("job.file", (d) => {
    (S.liveFiles[d.channelId] = S.liveFiles[d.channelId] || []).unshift({ ...d.file, channelId: d.channelId });
    scheduleLive();
  });
  B.on("file.cover", (d) => {
    const lists = [S.liveFiles[d.channelId] || [], (S.detail && S.detail.recent) || [], S.lib.results];
    for (const list of lists) for (const f of list) if (f.msgId === d.msgId && (f.channelId || d.channelId) === d.channelId) f.cover = true;
    scheduleLive();
  });
  B.on("channels.changed", (d) => {
    S.channels = d.channels;
    reportStatus();
    scheduleLive();
  });
  B.on("scan.progress", (d) => {
    S.add.scanned = d.documents;
    if (S.page === "add") render();
  });
  B.on("scan.wait", (d) => {
    S.add.waiting = d.seconds;
    if (S.page === "add") render();
  });
  B.on("notice", (d) => toast(d.message));
  B.on("engine.restarted", () => {
    toast(L("صار خلل بسيط ورجّعنا التطبيق يشتغل. وإذا كان فيه تنزيل، بيكمّل لحاله من وين وقف.", "Something hiccupped and we restarted. A download that was running carries on by itself."), true);
    call("app.state").then(apply).catch(() => {});
  });
  // Closing the window starts the key screen over, so a half-pasted key never waits there.
  B.on("window.closed", () => {
    if (S.view === "onboard" && S.step === "key") { S.key = freshKey(); render(); }
  });
  B.on("engine.failed", () => {
    S.view = "setup";
    render();
  });

  // ---------- Actions

  async function changeLanguage(lang) {
    setLanguage(lang);
    render();
    S.statusText = "";
    if (S.view === "main") reportStatus();
    B.native("setLanguage", { language: LANG }).catch(() => {});
    try { await call("settings.set", { key: "language", value: LANG }); } catch (error) { toast(error.message, true); }
  }

  const actions = {
    "open-site": () => B.native("openURL", { url: "https://my.telegram.org/apps" }),
    "toggle-help": () => { S.key.help = !S.key.help; render(); },
    "reset-key": () => { S.key = freshKey(); render(); },
    "switch-language": () => changeLanguage(LANG === "en" ? "ar" : "en"),
    "set-language": (el) => changeLanguage(el.dataset.lang),
    "paste-slot": async (el) => {
      const slot = el.dataset.slot;
      let text = "";
      try { text = await B.native("readClipboard"); } catch (error) { /* treated as empty below */ }
      if (!text || !text.trim()) {
        S.key.error = L("ما فيه شي منسوخ. اضغط زر النسخ بموقع تيليجرام أول.", "Nothing is copied yet. Press the copy button on the Telegram site first.");
        return render();
      }
      absorbKey(text, slot);
    },
    "save-key": async () => {
      S.key.busy = true;
      render();
      try {
        const saved = await call("key.save", { text: `api_id: ${S.key.id}\napi_hash: ${S.key.hash}` });
        S.keyMasked = saved.masked;
        S.key = freshKey();
        S.step = "login";
        render();
        startQr();
      } catch (error) {
        S.key.busy = false;
        S.key.error = error.message;
        render();
      }
    },
    "back-to-key": async () => {
      await call("auth.qr.stop").catch(() => {});
      S.step = "key";
      render();
    },
    "login-phone": async () => {
      await call("auth.qr.stop").catch(() => {});
      S.login = { ...S.login, mode: "phone", step: "phone", error: "" };
      render();
    },
    "login-qr": () => { startQr(); render(); },
    "phone-again": () => { S.login.step = "phone"; S.login.error = ""; render(); },
    "go-channels": () => {
      if (S.selected && channelById(S.selected)) openChannel(S.selected);
      else if (S.channels.length) openChannel(S.channels[0].id);
      else { S.page = "empty"; render(); }
    },
    "go-library": async () => {
      S.page = "library";
      render();
      try {
        await refreshChannels();
        await loadShelves();
        S.lib.topics = await call("library.topics");
        if (S.page === "library") { render(); if (S.lib.q || S.lib.topic || S.lib.shelf) search(); }
      } catch (error) { toast(error.message, true); }
    },
    "pick-topic": (el) => {
      S.lib.topic = S.lib.topic === el.dataset.topic ? "" : el.dataset.topic;
      S.lib.shelf = null;
      render();
      search();
    },
    "pick-shelf": (el) => {
      const id = Number(el.dataset.shelf);
      Object.assign(S.lib, { shelf: S.lib.shelf === id ? null : id, topic: "", q: "", results: [], searched: false });
      S.renameShelf = null;
      render();
      search();
    },
    "new-shelf": () => {
      S.newShelf = { open: true, name: "" };
      patchLibrary();
      const input = document.querySelector('[data-model="newShelf.name"]');
      if (input) input.focus();
    },
    "rename-shelf": () => {
      const s = S.shelves.find((x) => x.id === S.lib.shelf);
      if (!s) return;
      S.renameShelf = { id: s.id, name: s.name };
      patchLibrary();
      const input = document.querySelector('[data-model="renameShelf.name"]');
      if (input) { input.focus(); input.select(); }
    },
    "cancel-rename": () => { S.renameShelf = null; patchLibrary(); },
    "delete-shelf": async () => {
      const s = S.shelves.find((x) => x.id === S.lib.shelf);
      if (!s) return;
      const ok = await confirmBox({
        title: L(`تحذف رف «${s.name}»؟`, `Delete the “${s.name}” shelf?`),
        body: L("الملفات نفسها ما تنحذف. بس الرف يختفي.", "The files themselves stay. Only the shelf goes."),
        yes: L("احذفه", "Delete"), danger: true,
      });
      if (!ok) return;
      await call("shelf.delete", { shelfId: s.id }).catch((e) => toast(e.message, true));
      await loadShelves();
      Object.assign(S.lib, { shelf: null, results: [], searched: false });
      render();
    },
    "toggle-favorite": (el) => {
      const channelId = Number(el.dataset.channel);
      const msgId = Number(el.dataset.msg);
      const f = filesMatching(channelId, msgId)[0] || {};
      putOnShelf(channelId, msgId, FAVORITES, !(f.shelves || []).includes(FAVORITES));
    },
    "remove-file": async (el) => {
      const channelId = Number(el.dataset.channel);
      const msgId = Number(el.dataset.msg);
      const name = displayName((filesMatching(channelId, msgId)[0] || {}).name || "");
      const ok = await confirmBox({
        title: L(`تشيل «${name}»؟`, `Remove “${name}”?`),
        body: L("بيروح لسلة المهملات، ويختفي من المكتبة والرفوف والمفضلة، والتحديث ما بينزله مرة ثانية. لو ندمت رجّعه من السلة، ويرجع مكانه.",
          "It goes to the Trash and leaves the library, your shelves and Favorites, and updates won't download it again. Changed your mind? Put it back from the Trash and it returns."),
        yes: L("شيله", "Remove"), danger: true,
      });
      if (!ok) return;
      let stuck = false;
      try {
        const removed = await call("file.remove", { channelId, msgId });
        const others = (f) => !(f.msgId === msgId && (f.channelId || channelId) === channelId);
        S.lib.results = S.lib.results.filter(others);
        if (S.detail && S.detail.recent) S.detail.recent = S.detail.recent.filter(others);
        if (S.liveFiles[channelId]) S.liveFiles[channelId] = S.liveFiles[channelId].filter(others);
        const T = removed.trash;
        if (T) {
          const moved = await B.native("trash", { paths: T.paths, folder: T.folder, ownFolder: T.ownFolder });
          // A file the Trash couldn't take is still in its place, so the library keeps it.
          stuck = moved.moved !== 1;
          S.shelves = (await call("file.trashed", { channelId, msgId, moved: !stuck })).shelves;
          toast(stuck ? L("ما قدرنا نحركه لسلة المهملات، يمكن مفتوح ببرنامج ثاني. فخليناه بالمكتبة.", "Couldn't move it to the Trash; it may be open in another app. So it stays in the library.")
            : L("ودّيناه لسلة المهملات.", "Moved it to the Trash."), stuck);
        } else {
          await loadShelves();
          toast(L("شلناه من المكتبة.", "Removed it from the library."));
        }
      } catch (e) { toast(errorText(e), true); }
      // Patch the page in place rather than redraw it, so a long list doesn't jump back to the top.
      await refreshChannels().catch(() => {});
      if (S.page === "library") {
        S.lib.topics = await call("library.topics").catch(() => S.lib.topics);
        if (stuck) search(); else patchLibrary();
      } else if (S.page === "channel") {
        if (stuck) openChannel(channelId); else scheduleLive();
      }
    },
    "shelf-menu": (el) => {
      const rect = el.getBoundingClientRect();
      const rtl = document.documentElement.dir === "rtl";
      const width = 250;
      const height = 96 + 40 * S.shelves.length;
      const x = Math.max(12, Math.min(rtl ? innerWidth - rect.right : rect.left, innerWidth - width - 12));
      const below = rect.bottom + 6;
      const top = below + height > innerHeight - 12 ? Math.max(12, rect.top - 6 - height) : below;
      S.channelMenu = null;
      S.shelfMenu = { channelId: Number(el.dataset.channel), msgId: Number(el.dataset.msg), side: rtl ? "right" : "left", x, top, name: "" };
      drawMenus();
    },
    "shelf-toggle": (el) => {
      const M = S.shelfMenu;
      if (!M) return;
      const id = Number(el.dataset.shelf);
      const f = filesMatching(M.channelId, M.msgId)[0] || {};
      putOnShelf(M.channelId, M.msgId, id, !(f.shelves || []).includes(id));
    },
    "go-settings": () => { S.page = "settings"; render(); },
    "go-add": () => {
      S.page = "add";
      render();
      if (S.mine.list === null) loadMine();
    },
    "load-mine": () => loadMine(),
    "pick-mine": (el) => {
      const c = (S.mine.list || []).find((x) => x.id === Number(el.dataset.id));
      if (!c) return;
      S.add.link = c.username ? `@${c.username}` : "";
      inspectChannel({ channelId: c.id });
    },
    "clear-filters": () => {
      Object.assign(S.add, { since: "", until: "", words: "", maxMb: "", filtered: null, filteredOthers: null, counting: false });
      render();
    },
    "edit-filters": (el) => {
      const c = channelById(Number(el.dataset.id));
      if (!c) return;
      const F = c.filters || {};
      S.editFilters = { id: c.id, since: F.since || "", until: F.until || "", words: F.words || "", maxMb: F.maxMb || "" };
      render();
    },
    "cancel-filters": () => { S.editFilters = null; render(); },
    "save-filters": async (el) => {
      const id = Number(el.dataset.id);
      try {
        const channel = await call("channel.setFilters", { channelId: id, filters: filtersOf(S.editFilters) });
        S.editFilters = null;
        S.live[id] = channel.job;
        S.liveFiles[id] = [];
        await refreshChannels();
        render();
      } catch (error) { toast(errorText(error), true); }
    },
    "open-channel": (el) => openChannel(Number(el.dataset.id)),
    "channel-menu": (el) => {
      const id = Number(el.dataset.id);
      if (S.channelMenu && S.channelMenu.id === id) closeChannelMenu();
      else openChannelMenu(id, el.getBoundingClientRect());
    },
    "toggle-kind": (el) => {
      const k = el.dataset.kind;
      S.add.kinds = S.add.kinds.includes(k) ? S.add.kinds.filter((x) => x !== k) : S.add.kinds.concat(k);
      render();
    },
    "toggle-option": (el) => { S.add[el.dataset.key] = !S.add[el.dataset.key]; render(); },
    "toggle-ext": (el) => {
      const ext = el.dataset.ext;
      const A = S.add;
      A.skipExts = A.skipExts.includes(ext) ? A.skipExts.filter((e) => e !== ext) : A.skipExts.concat(ext);
      patchScan();
    },
    "pick-folder": async () => {
      try {
        const folder = await B.native("pickFolder", { start: S.add.folder });
        if (folder) { S.add.folder = folder; render(); checkFree(); }
      } catch (error) { toast(error.message, true); }
    },
    "reset-add": () => { S.add = freshAdd(); render(); },
    "start-download": async () => {
      const A = S.add;
      A.adding = true;
      render();
      try {
        const channel = await call("channel.add", {
          channelId: A.result.channel.id, kinds: A.kinds, folder: A.folder, yearFolders: A.yearFolders,
          topicFolders: A.topicFolders, smartNames: A.smartNames, autoUpdate: A.autoUpdate, filters: filtersOf(A),
          skipExts: A.skipExts,
        });
        S.channels = S.channels.filter((c) => c.id !== channel.id).concat(channel);
        const picked = (S.mine.list || []).find((c) => c.id === channel.id);
        if (picked) picked.added = true;
        S.add = freshAdd();
        openChannel(channel.id);
      } catch (error) {
        A.adding = false;
        render();
        toast(error.message, true);
      }
    },
    pause: (el) => call("job.pause", { channelId: Number(el.dataset.id) }).then((j) => { S.live[Number(el.dataset.id)] = j; scheduleLive(); }),
    resume: (el) => call("job.resume", { channelId: Number(el.dataset.id) }).then((j) => { S.live[Number(el.dataset.id)] = j; scheduleLive(); }),
    cancel: async (el) => {
      const ok = await confirmBox({
        title: L("تلغي التنزيل؟", "Cancel the download?"),
        body: L("الملفات اللي نزلت تبقى بمكانها، وتقدر تكمّل بعدين من «حدّث».", "Files already saved stay, and Update continues later."),
        yes: L("ألغِ التنزيل", "Cancel download"), danger: true,
      });
      if (ok) call("job.cancel", { channelId: Number(el.dataset.id) }).catch((e) => toast(e.message, true));
    },
    update: (el) => startUpdate(Number(el.dataset.id), false),
    "relink-folder": async (el) => {
      const id = Number(el.dataset.id);
      const c = channelById(id);
      try {
        const folder = await B.native("pickFolder", {
          start: c.folder,
          message: L(`وين صار مجلد «${c.title}»؟`, `Where is the folder of “${c.title}” now?`),
          prompt: L("هذا هو", "This one"),
        });
        if (!folder) return;
        const result = await call("channel.relink", { channelId: id, folder });
        toast(L(`لقينا ${num(result.found)} من ${num(result.total)} ملف بمكانها الجديد.`, `Found ${num(result.found)} of ${num(result.total)} files in their new place.`));
        await refreshChannels();
        openChannel(id);
      } catch (error) { toast(errorText(error), true); }
    },
    "recreate-folder": async (el) => {
      const id = Number(el.dataset.id);
      const ok = await confirmBox({
        title: L("ننزّل ملفات القناة من جديد؟", "Download the channel's files again?"),
        body: L("بنسوي المجلد بمكانه القديم وننزّل كل ملفاتها مرة ثانية. إذا المجلد عندك بمكان ثاني، اختار «وين صار؟» بدال.", "We'll make the folder again where it was and download all its files. If the folder is somewhere else, choose “Where is it?” instead."),
        yes: L("نزّلها", "Download"),
      });
      if (ok) startUpdate(id, true, true);
    },
    "restore-missing": async (el) => {
      const ok = await confirmBox({
        title: L("نرجّع الملفات المحذوفة؟", "Bring the deleted files back?"),
        body: L("بننزّل من جديد الملفات اللي ما عادت موجودة بالمجلد.", "We'll download again the files that are no longer in the folder."),
        yes: L("رجّعها", "Bring them back"),
      });
      if (ok) startUpdate(Number(el.dataset.id), true);
    },
    "toggle-auto": async (el) => {
      const id = Number(el.dataset.id);
      const c = channelById(id);
      try {
        const updated = await call("channel.autoUpdate", { channelId: id, on: !c.autoUpdate });
        Object.assign(c, { autoUpdate: updated.autoUpdate });
        render();
      } catch (error) { toast(error.message, true); }
    },
    "remove-channel": async (el) => {
      const id = Number(el.dataset.id);
      const c = channelById(id);
      const answer = await confirmBox({
        title: L(`تشيل «${c.title}» من تجميعة؟`, `Remove “${c.title}” from Tajmeea?`),
        body: L("القناة تختفي من التطبيق: من قنواتك والبحث والمفضلة ورفوفك. وملفاتها تبقى بمجلدها، إلا إذا اخترت تحت.", "The channel leaves the app: your channels, search, favorites and shelves. Its files stay in their folder unless you choose below."),
        option: L("ودّ ملفاتها لسلة المهملات بعد", "Also move its files to the Trash"),
        optionNote: L("بس الملفات اللي نزّلتها تجميعة. تقدر ترجّعها من السلة.", "Only the files Tajmeea downloaded. You can put them back from the Trash."),
        yes: L("شيلها", "Remove"), danger: true,
      });
      if (!answer.ok) return;
      try {
        const removed = await call("channel.remove", { channelId: id, trashFiles: answer.checked });
        if (removed.trash) {
          const T = removed.trash;
          const moved = await B.native("trash", { paths: T.paths, folder: T.folder, ownFolder: T.ownFolder });
          const parts = [L(`ودّينا ${num(moved.moved)} ملف لسلة المهملات.`, `Moved ${num(moved.moved)} files to the Trash.`)];
          if (T.shared) parts.push(L(`وخلّينا ${num(T.shared)} لأن قنوات ثانية تستخدمها.`, `Kept ${num(T.shared)} that other channels use.`));
          if (moved.failed) parts.push(L(`و${num(moved.failed)} ما قدرنا نحركها، يمكن مفتوحة.`, `${num(moved.failed)} couldn't be moved; they may be open.`));
          toast(parts.join(" "), Boolean(moved.failed));
        }
      } catch (e) { toast(errorText(e), true); }
      const picked = (S.mine.list || []).find((x) => x.id === id);
      if (picked) picked.added = false;
      await refreshChannels();
      if (S.page === "library") {
        // Stay on the library; its sections, shelves and results lose that channel's files.
        await loadShelves();
        S.lib.topics = await call("library.topics").catch(() => S.lib.topics);
        render();
        if (S.lib.q || S.lib.topic || S.lib.shelf) search();
      } else if (S.page !== "channel" || S.selected !== id) render();  // removed from the sidebar: stay where you are
      else if (S.channels.length) openChannel(S.channels[0].id);
      else { S.page = "empty"; render(); }
    },
    reveal: (el) => B.native("reveal", { path: el.dataset.path }).catch((e) => toast(e.message, true)),
    "open-file": (el) => B.native("openPath", { path: el.dataset.path }).catch((e) => toast(e.message, true)),
    preview: (el) => B.native("preview", { path: el.dataset.path }).catch((e) => toast(e.message, true)),
    "open-url": (el) => B.native("openURL", { url: el.dataset.url }),
    "check-update": () => { S.update = null; render(); checkUpdate(); },
    "run-update": async () => {
      const ok = await confirmBox({
        title: L("نحدّث تجميعة؟", "Update Tajmeea?"),
        body: L("التطبيق بيسكّر ويرجع يفتح بعد دقيقة تقريباً. ملفاتك ومكتبتك ما تنلمس.", "The app closes and reopens in about a minute. Your files and library aren't touched."),
        yes: L("حدّث", "Update"),
      });
      if (!ok) return;
      S.updating = true;
      render();
      try { await call("app.update"); toast(L("نحدّث الحين… بيسكّر ويرجع يفتح لحاله.", "Updating… it will close and reopen by itself.")); }
      catch (error) { S.updating = false; render(); toast(error.message, true); }
    },
    logout: async () => {
      const ok = await confirmBox({
        title: L("تطلع من حسابك؟", "Sign out?"),
        body: L("ملفاتك ومكتبتك تبقى. بس بتحتاج تصوّر الكود مرة ثانية عشان تحدّث قنواتك.", "Your files and library stay. You'll scan the code again to update channels."),
        yes: L("اطلع", "Sign out"), danger: true,
      });
      if (!ok) return;
      await call("auth.logout").catch(() => {});
      S.view = "onboard";
      S.step = "login";
      render();
      startQr();
    },
    "forget-key": async () => {
      const ok = await confirmBox({
        title: L("تغيّر المفتاح؟", "Change the key?"),
        body: L("بنمسح المفتاح والجلسة من جهازك، وبتحتاج تحط مفتاح جديد وتدخل مرة ثانية. ملفاتك ما تنلمس.", "We'll remove the key and session from this Mac; you'll add a key and sign in again. Your files aren't touched."),
        yes: L("غيّره", "Change it"), danger: true,
      });
      if (!ok) return;
      await call("key.forget").catch(() => {});
      S.view = "onboard";
      S.step = "key";
      render();
    },
  };

  async function startUpdate(id, restoreMissing, recreateFolder = false) {
    try {
      const channel = await call("channel.update", { channelId: id, restoreMissing, recreateFolder });
      S.live[id] = channel.job;
      S.liveFiles[id] = [];
      if (recreateFolder) await refreshChannels();
      scheduleLive();
      if (S.page === "library" || recreateFolder) render();
    } catch (error) { toast(errorText(error), true); }
  }

  async function loadMine() {
    const M = S.mine;
    if (M.loading) return;
    Object.assign(M, { loading: true, error: "" });
    if (S.page === "add") render();
    try { M.list = await call("channel.mine"); } catch (error) { M.error = errorText(error); }
    M.loading = false;
    if (S.page === "add") render();
  }

  async function inspectChannel(params) {
    const A = S.add;
    if (A.busy) return;
    Object.assign(A, { busy: true, error: "", result: null, scanned: 0, waiting: 0,
      since: "", until: "", words: "", maxMb: "", filtered: null, filteredOthers: null, counting: false, skipExts: [] });
    render();
    try {
      const result = await call("channel.inspect", params);
      const available = KIND_ORDER.filter((k) => result.kinds[k] && result.kinds[k].count > 0);
      Object.assign(A, { busy: false, result, folder: result.suggestedFolder,
        kinds: available.includes("pdf") ? ["pdf"] : available.slice(0, 1) });
    } catch (error) {
      Object.assign(A, { busy: false, error: errorText(error) });
    }
    if (S.page === "add") render();
    if (A.result) checkFree();
  }

  async function checkFree() {
    const A = S.add;
    try {
      const { free } = await call("disk.free", { folder: A.folder });
      if (S.add !== A) return;
      A.free = free;
      if (S.page === "add") render();
    } catch (error) { /* without a number we simply don't warn */ }
  }

  let countTimer = 0;
  function recount() {
    clearTimeout(countTimer);
    const A = S.add;
    if (!A.result) return;
    if (!hasFilter(A)) {
      Object.assign(A, { filtered: null, filteredOthers: null, counting: false });
      return patchScan();
    }
    A.counting = true;
    patchScan();
    countTimer = setTimeout(async () => {
      const asked = JSON.stringify(filtersOf(A));
      try {
        const { kinds, others } = await call("channel.count", { channelId: A.result.channel.id, filters: filtersOf(A) });
        if (S.add !== A || asked !== JSON.stringify(filtersOf(A))) return;
        Object.assign(A, { filtered: kinds, filteredOthers: others });
      } catch (error) { toast(errorText(error), true); }
      A.counting = false;
      patchScan();
    }, 300);
  }

  const submits = {
    inspect: () => {
      if (S.add.link.trim()) inspectChannel({ link: S.add.link });
    },
    "create-shelf": async () => {
      const name = S.newShelf.name.trim();
      S.newShelf = { open: false, name: "" };
      if (!name) return patchLibrary();
      try {
        const shelf = await call("shelf.create", { name });
        await loadShelves();
        Object.assign(S.lib, { shelf: shelf.id, topic: "", q: "", results: [], searched: false });
        render();
        search();
      } catch (error) { toast(errorText(error), true); patchLibrary(); }
    },
    "rename-shelf": async () => {
      const R = S.renameShelf;
      if (!R) return;
      try {
        await call("shelf.rename", { shelfId: R.id, name: R.name });
        S.renameShelf = null;
        await loadShelves();
        patchLibrary();
      } catch (error) { toast(errorText(error), true); }
    },
    "menu-new-shelf": async () => {
      const M = S.shelfMenu;
      if (!M || !(M.name || "").trim()) return;
      try {
        const shelf = await call("shelf.create", { name: M.name });
        M.name = "";
        await putOnShelf(M.channelId, M.msgId, shelf.id, true);
      } catch (error) { toast(errorText(error), true); }
    },
    phone: async () => {
      const Lg = S.login;
      Lg.busy = true; Lg.error = ""; render();
      try {
        const sent = await call("auth.phone.send", { phone: Lg.phone });
        Object.assign(Lg, { busy: false, step: "code", via: sent.via, code: "" });
      } catch (error) { Object.assign(Lg, { busy: false, error: error.message }); }
      render();
    },
    code: async () => {
      const Lg = S.login;
      Lg.busy = true; Lg.error = ""; render();
      try {
        const result = await call("auth.phone.verify", { code: Lg.code });
        Lg.busy = false;
        if (result.needPassword) { Object.assign(Lg, { step: "password", hint: result.hint }); render(); }
        else { S.me = result.me; await refreshChannels().catch(() => {}); enterMain(); }
      } catch (error) { Object.assign(Lg, { busy: false, error: error.message }); render(); }
    },
    password: async () => {
      const Lg = S.login;
      Lg.busy = true; Lg.error = ""; render();
      try {
        const result = await call("auth.password", { password: Lg.password });
        Lg.password = "";
        S.me = result.me;
        await refreshChannels().catch(() => {});
        enterMain();
      } catch (error) { Object.assign(Lg, { busy: false, error: error.message, password: "" }); render(); }
    },
  };

  let searchTimer = 0;
  function search() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      const { q, topic, shelf } = S.lib;
      if (!q.trim() && !topic && !shelf) { S.lib.results = []; S.lib.searched = false; return patchLibrary(); }
      try {
        const { results } = shelf
          ? await call("shelf.files", { shelfId: shelf })
          : await call("library.search", { query: q, topic: topic || null });
        if (q !== S.lib.q || topic !== S.lib.topic || shelf !== S.lib.shelf) return;
        S.lib.results = results;
        S.lib.searched = true;
        patchLibrary();
      } catch (error) { toast(error.message, true); }
    }, 180);
  }
  function patchLibrary() {
    if (S.page !== "library") return;
    const parts = { "lib-results": libraryResults, "lib-shelves": shelfChips, "lib-topics": topicChips, "lib-total": libraryTotal, "lib-channels": channelCards };
    for (const [id, make] of Object.entries(parts)) {
      const el = document.getElementById(id);
      if (el) el.innerHTML = make();
    }
    const count = document.getElementById("lib-count");
    if (count) count.textContent = (S.lib.q.trim() || S.lib.topic || S.lib.shelf) && S.lib.searched ? L(`${num(S.lib.results.length)} نتيجة`, `${num(S.lib.results.length)} results`) : "";
  }

  document.addEventListener("click", (event) => {
    const el = event.target.closest("[data-action]");
    if (!el || el.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    // Picking something in the channel menu closes it first.
    if (S.channelMenu && el.closest(".channel-pop")) closeChannelMenu();
    const action = actions[el.dataset.action];
    if (action) action(el, event);
  });
  document.addEventListener("submit", (event) => {
    event.preventDefault();
    const handler = submits[event.target.dataset.submit];
    if (handler) handler();
  });
  document.addEventListener("input", (event) => {
    const model = event.target.dataset && event.target.dataset.model;
    if (!model) return;
    const [group, key] = model.split(".");
    S[group][key] = event.target.value;
    if (model === "key.idText" || model === "key.hashText") absorbTypedSoon(model.slice(4, -4));
    if (model === "lib.q") {
      if (S.lib.shelf) { S.lib.shelf = null; S.renameShelf = null; }
      search();
    }
    if (model === "mine.q") {
      const list = document.getElementById("mine-list");
      if (list) list.innerHTML = mineRows();
    }
    if (group === "add" && ["since", "until", "words", "maxMb"].includes(key)) recount();
  });
  document.addEventListener("paste", (event) => {
    if (event.target.dataset && event.target.dataset.paste === "inspect") setTimeout(() => submits.inspect(), 30);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && S.shelfMenu) {
      S.shelfMenu = null;
      drawMenus();
    } else if (event.key === "Escape" && S.channelMenu) {
      closeChannelMenu();
    } else if (event.key === "Escape" && document.getElementById("modal-root").firstElementChild) {
      document.getElementById("modal-root").firstElementChild.click();
    }
  });
  // A menu closes when you click anywhere else.
  document.addEventListener("mousedown", (event) => {
    const el = event.target instanceof Element ? event.target : null;
    if (S.shelfMenu && !(el && (el.closest(".popover") || el.closest('[data-action="shelf-menu"]')))) {
      S.shelfMenu = null;
      drawMenus();
    }
    if (S.channelMenu && !(el && (el.closest(".channel-pop") || el.closest('[data-action="channel-menu"]')))) closeChannelMenu();
  });
  // Right-click on a channel in the sidebar opens its menu where you clicked.
  document.addEventListener("contextmenu", (event) => {
    const row = event.target instanceof Element && event.target.closest(".channel-row");
    if (!row) return;
    event.preventDefault();
    openChannelMenu(Number(row.dataset.id), row.getBoundingClientRect(), { x: event.clientX, y: event.clientY });
  });

  boot();
})();
