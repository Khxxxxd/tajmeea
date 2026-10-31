// A pretend engine for opening ui/index.html in a normal browser while designing.
// Inside the Mac app the real engine is there and this file does nothing.
// Try ?demo=fresh (first run), ?demo=login, ?demo=main, ?demo=busy (a download in progress).
(function () {
  const B = window.TajmeeaBridge;
  if (B.available) return;
  window.TajmeeaMock = true;

  const demo = new URLSearchParams(location.search).get("demo") || "busy";
  const emit = (event, data) => setTimeout(() => B.receive({ event, data }), 0);
  const iso = (daysAgo) => new Date(Date.now() - daysAgo * 86400000).toISOString();
  const MB = 1024 * 1024;
  let hasKey = demo !== "fresh";
  let authorized = demo === "main" || demo === "busy";

  const channel = (id, username, title, files, bytes, extra) => ({
    id, username, title, about: "", members: 0, photo: "", folder: `/Users/you/Downloads/تجميعة/${title}`,
    kinds: ["pdf"], yearFolders: true, smartNames: true, autoUpdate: false, lastScannedId: files, addedAt: iso(20),
    lastSync: iso(0), files, bytes, failed: 0, job: {}, group: false, private: false,
    filters: { since: "", until: "", words: "", maxMb: 0 }, folderState: { state: "ok" }, pending: 0, ...extra,
  });
  const channels = authorized ? [
    channel(101, "law_library", "مكتبة القوانين", 1240, 3.2 * 1024 * MB, { members: 18400, missing: 3 }),
    channel(102, "moe_circulars", "تعاميم الوزارة", 320, 410 * MB, { autoUpdate: true, members: 5200 }),
    channel(103, "gulf_history", "كتب التاريخ الخليجي", 86, 980 * MB, { lastSync: iso(2), members: 2100, failed: 2, folderState: { state: "missing" } }),
  ] : [];

  const NAMES = [
    "قانون رقم 6 لسنة 2010 بشأن العمل في القطاع الأهلي.pdf", "مرسوم بقانون رقم 67 لسنة 1980.pdf",
    "الجريدة الرسمية · العدد 1650.pdf", "اللائحة التنفيذية لقانون العمل 2019.pdf", "قانون المرور وتعديلاته.pdf",
    "تعميم بشأن ساعات العمل في رمضان.pdf", "قانون الأحوال الشخصية.pdf", "قرار وزاري رقم 12 لسنة 2021.pdf",
  ];
  const TOPICS = ["قانون", "مرسوم", "الكويت اليوم", "لائحة", "قانون", "تعميم", "قانون", "قرار"];
  const shelves = [{ id: 1, name: "", favorites: true }, { id: 2, name: "بحثي", favorites: false }];
  const onShelf = new Map([["101:48", new Set([1, 2])], ["101:3", new Set([1])], ["101:5", new Set([2])]]);
  const shelvesOf = (channelId, msgId) => [...(onShelf.get(`${channelId}:${msgId}`) || [])].sort();
  const removedFiles = new Set();
  const kept = (f) => !removedFiles.has(`${f.channelId}:${f.msgId}`);
  const fileFor = (channelId, msgId, status = "done") => ({
    channelId, msgId, kind: "pdf", name: NAMES[msgId % NAMES.length], path: `/Users/you/Downloads/${msgId}.pdf`,
    size: (300 + (msgId * 97) % 5000) * 1024, date: iso(msgId % 400), caption: "", status,
    note: status === "failed" ? "ما قدرنا نوصل لتيليجرام" : "", topic: TOPICS[msgId % TOPICS.length], cover: false,
    shelves: shelvesOf(channelId, msgId),
  });
  const shelfList = () => shelves.map((s) => ({ ...s, files: [...onShelf.entries()].filter(([key, set]) => set.has(s.id) && !removedFiles.has(key)).length }));
  const MINE = [
    { id: 101, title: "مكتبة القوانين", username: "law_library", group: false, private: false, protected: false, members: 18400 },
    { id: 301, title: "ملفات دفعة الحقوق ٢٠٢٤", username: "", group: true, private: true, protected: false, members: 312 },
    { id: 302, title: "ملخصات القانون المدني", username: "", group: false, private: true, protected: false, members: 1460 },
    { id: 303, title: "دورة الصياغة القانونية", username: "", group: false, private: true, protected: true, members: 820 },
    { id: 201, title: "الكويت اليوم · الجريدة الرسمية", username: "kuwait_gazette", group: false, private: false, protected: false, members: 41200 },
    { id: 304, title: "قروب مكتب المحاماة", username: "", group: true, private: true, protected: false, members: 14 },
  ];
  const scanned = {};
  let language = new URLSearchParams(location.search).get("lang") || "ar";
  const totals = () => ({
    files: channels.reduce((s, c) => s + c.files, 0), bytes: channels.reduce((s, c) => s + c.bytes, 0), channels: channels.length,
  });

  function matrix(seed) {
    const n = 33;
    const rows = [];
    for (let y = 0; y < n; y++) {
      let row = "";
      for (let x = 0; x < n; x++) {
        const corner = [[0, 0], [n - 7, 0], [0, n - 7]].find(([a, b]) => x >= a && x < a + 7 && y >= b && y < b + 7);
        if (corner) {
          const dx = x - corner[0], dy = y - corner[1];
          row += dx === 0 || dy === 0 || dx === 6 || dy === 6 || (dx >= 2 && dx <= 4 && dy >= 2 && dy <= 4) ? "1" : "0";
        } else {
          seed = (seed * 9301 + 49297) % 233280;
          row += seed / 233280 > 0.5 ? "1" : "0";
        }
      }
      rows.push(row);
    }
    return rows;
  }

  const jobs = {};
  function runJob(c, total, startAt = 0) {
    const job = { state: "running", total, done: startAt, skipped: 0, failed: 0, rejected: 0, processed: startAt,
      bytesTotal: total * 2.6 * MB, bytesDone: startAt * 2.6 * MB, speed: 4.1 * MB, eta: 0, waitSeconds: 0,
      current: null, error: "", errorCode: "" };
    jobs[c.id] = job;
    c.job = job;
    let tick = 0;
    let waitLeft = 0;
    const timer = setInterval(() => {
      if (job.state === "paused") return emit("job.progress", { channelId: c.id, ...job });
      if (job.state === "stopped") { clearInterval(timer); return; }
      tick++;
      if (tick === 18) { job.state = "waiting"; waitLeft = 9; }
      if (job.state === "waiting") {
        job.waitSeconds = waitLeft--;
        if (waitLeft < 0) job.state = "running";
        return emit("job.progress", { channelId: c.id, ...job });
      }
      const size = 2.6 * MB;
      job.active = job.active || [];
      while (job.active.length < Math.min(3, job.total - job.processed)) {
        job.active.push({ name: NAMES[(job.processed + job.active.length + 3) % NAMES.length], size, received: size * job.active.length / 3 });
      }
      for (const file of job.active) file.received = Math.min(size, file.received + size / 3);
      for (const file of job.active.filter((f) => f.received >= size)) {
        job.processed++; job.done++;
        emit("job.file", { channelId: c.id, file: fileFor(c.id, 2000 + job.processed) });
      }
      job.active = job.active.filter((f) => f.received < size);
      job.current = job.active[0] || null;
      job.bytesDone = job.processed * size + job.active.reduce((s, f) => s + f.received, 0);
      job.eta = Math.round(((job.total - job.processed) * size) / job.speed);
      if (job.processed >= job.total) {
        clearInterval(timer);
        job.state = "done";
        c.files += total - startAt;
        c.lastSync = new Date().toISOString();
      }
      emit("job.progress", { channelId: c.id, ...job });
    }, 1000);
  }
  if (demo === "busy") setTimeout(() => runJob(channels[0], 1240, 312), 400);

  const fail = (message, code) => { const e = new Error(message); e.code = code; throw e; };

  const handlers = {
    "app.state": () => ({
      version: "0.2.0", hasKey, authorized, offline: false, keyMasked: hasKey ? "2041733 · 7f3c…5f60" : "",
      me: authorized ? { name: "سارة", username: "sara", phone: "+965•••78" } : null,
      channels, totals: totals(), downloadRoot: "/Users/you/Downloads/تجميعة",
    }),
    "key.parse": ({ text }) => {
      const id = /api[\s_-]*id\D{0,24}?(\d{4,10})/i.exec(text);
      const hash = /api[\s_-]*hash\W{0,24}?([0-9a-f]{32})/i.exec(text);
      if (!id || !hash) fail("ما لقينا المفتاح بالنص. تأكد إنك نسخت صفحة App configuration كاملة.", "key_not_found");
      return { apiId: Number(id[1]), masked: `${id[1]} · ${hash[1].slice(0, 4)}…${hash[1].slice(-4)}` };
    },
    "key.scan": ({ text }) => {
      const id = /api[\s_-]*id\D{0,24}?(\d{4,10})/i.exec(text) || /^\s*(\d{5,10})\s*$/.exec(text);
      const hash = /([0-9a-f]{32})/i.exec(text);
      return { apiId: id ? Number(id[1]) : null, apiHash: hash ? hash[1].toLowerCase() : null,
        hashHidden: !hash && /api[\s_-]*hash[\s\S]{0,60}?•{6,}/i.test(text) };
    },
    "key.save": (p) => { const parsed = handlers["key.parse"](p); hasKey = true; return { masked: parsed.masked }; },
    "key.forget": () => { hasKey = false; authorized = false; return { forgotten: true }; },
    "auth.qr.start": () => {
      emit("auth.qr", { matrix: matrix(7), expiresIn: 30 });
      setTimeout(() => {
        authorized = true;
        emit("auth.done", { me: { name: "سارة", username: "sara", phone: "+965•••78" } });
      }, 12000);
      return { started: true };
    },
    "auth.qr.stop": () => ({ stopped: true }),
    "auth.phone.send": () => ({ via: "app" }),
    "auth.phone.verify": () => ({ needPassword: true, hint: "اسم أول مدرسة" }),
    "auth.password": () => { authorized = true; return { me: { name: "سارة", username: "sara", phone: "+965•••78" } }; },
    "auth.logout": () => { authorized = false; return { loggedOut: true }; },
    "channel.mine": () => new Promise((resolve) => setTimeout(() => resolve(MINE.map((c) => ({ ...c, added: channels.some((x) => x.id === c.id) }))), 900)),
    "channel.count": ({ channelId, filters }) => {
      const r = scanned[channelId];
      let share = 1;
      if (filters.since) share *= Math.min(1, Math.max(0.02, (Date.now() - Date.parse(filters.since)) / (2900 * 86400000)));
      if (filters.until) share *= 0.8;
      if (filters.words) share *= 0.18;
      const kinds = {};
      for (const [k, v] of Object.entries(r.kinds)) {
        const count = Math.round(v.count * share);
        kinds[k] = { count: filters.maxMb && k === "videos" ? 0 : count, bytes: v.count ? (v.bytes / v.count) * count : 0 };
      }
      const others = r.others.map((o) => ({ ...o, count: Math.round(o.count * share), bytes: o.bytes * share }));
      return { kinds, others, blocked: r.blocked };
    },
    "channel.setFilters": ({ channelId, filters }) => {
      const c = channels.find((x) => x.id === channelId);
      c.filters = { since: filters.since, until: filters.until, words: filters.words, maxMb: filters.maxMb };
      setTimeout(() => runJob(c, 4, 0), 600);
      return { ...c, job: { state: "scanning", total: 0, processed: 0 } };
    },
    "shelf.list": () => shelfList(),
    "disk.free": () => ({ free: 4.1 * 1024 * MB }),
    "channel.relink": ({ channelId, folder }) => {
      const c = channels.find((x) => x.id === channelId);
      if (/nowhere/.test(folder)) fail("ما لقينا ملفات القناة بهالمجلد. اختر مجلد القناة نفسه.", "relink_none");
      Object.assign(c, { folder, folderState: { state: "ok" } });
      return { found: c.files, total: c.files, folder, channel: c };
    },
    "shelf.create": ({ name }) => {
      if (!(name || "").trim()) fail("اكتب اسم للرف.", "shelf_name");
      const shelf = { id: Math.max(...shelves.map((s) => s.id)) + 1, name: name.trim(), favorites: false };
      shelves.push(shelf);
      return { ...shelf, files: 0 };
    },
    "shelf.rename": ({ shelfId, name }) => { const shelf = shelves.find((s) => s.id === shelfId); shelf.name = name.trim(); return shelf; },
    "shelf.delete": ({ shelfId }) => {
      shelves.splice(shelves.findIndex((s) => s.id === shelfId), 1);
      for (const set of onShelf.values()) set.delete(shelfId);
      return { deleted: true };
    },
    "shelf.put": ({ shelfId, channelId, msgId, on }) => {
      const key = `${channelId}:${msgId}`;
      const set = onShelf.get(key) || new Set();
      if (on) set.add(shelfId); else set.delete(shelfId);
      onShelf.set(key, set);
      return { shelves: shelfList() };
    },
    "shelf.files": ({ shelfId }) => ({
      results: [...onShelf.entries()].filter(([key, set]) => set.has(shelfId) && !removedFiles.has(key)).map(([key]) => {
        const [channelId, msgId] = key.split(":").map(Number);
        return { ...fileFor(channelId, msgId), channelTitle: "مكتبة القوانين", link: `https://t.me/law_library/${msgId}` };
      }),
    }),
    "channel.inspect": ({ link = "", channelId = 0 }) => new Promise((resolve, reject) => {
      const picked = MINE.find((c) => c.id === channelId);
      if (picked && picked.protected) {
        const e = new Error("صاحب هالقناة مانع حفظ محتواها، فتجميعة ما تنزّل منها."); e.code = "protected"; return reject(e);
      }
      if (/\+|joinchat/.test(link)) {
        const e = new Error("هذا رابط قناة خاصة. تجميعة تشتغل مع القنوات العامة بس."); e.code = "private"; return reject(e);
      }
      let count = 0;
      const timer = setInterval(() => { count += 400; emit("scan.progress", { documents: count }); }, 300);
      setTimeout(() => {
        clearInterval(timer);
        const known = channels.find((c) => (picked ? c.id === picked.id : link.includes(c.username)));
        const info = picked ? { ...picked, photo: "" } : { id: 201, username: "kuwait_gazette", title: "الكويت اليوم · الجريدة الرسمية", members: 41200, photo: "", group: false, private: false };
        scanned[info.id] = null;
        const result = {
          channel: known || info,
          kinds: { pdf: { count: 2310, bytes: 5.6 * 1024 * MB }, word: { count: 86, bytes: 40 * MB }, excel: { count: 12, bytes: 6 * MB },
            slides: { count: 0, bytes: 0 }, books: { count: 0, bytes: 0 }, audio: { count: 40, bytes: 900 * MB }, archives: { count: 0, bytes: 0 },
            images: { count: 520, bytes: 260 * MB }, videos: { count: 34, bytes: 2.1 * 1024 * MB },
            voice: { count: 61, bytes: 120 * MB }, other: { count: 74, bytes: 731 * MB } },
          others: [{ ext: ".psd", count: 40, bytes: 700 * MB }, { ext: ".ttf", count: 22, bytes: 30 * MB }, { ext: ".srt", count: 12, bytes: 1 * MB }],
          blocked: { count: 9, exts: [".apk", ".exe"] },
          firstDate: iso(2900), lastDate: iso(1), documents: 2448, existing: known || null,
          suggestedFolder: `/Users/you/Downloads/تجميعة/${info.title}`,
        };
        scanned[info.id] = result;
        resolve(result);
      }, 1600);
    }),
    "channel.add": (p) => {
      const info = scanned[p.channelId].channel;
      const c = channel(p.channelId, info.username, info.title, 0, 0,
        { folder: p.folder, kinds: p.kinds, autoUpdate: p.autoUpdate, members: info.members, lastSync: "",
          group: info.group, private: info.private, filters: { ...p.filters } });
      channels.push(c);
      c.job = { state: "queued", total: 0, processed: 0 };
      setTimeout(() => runJob(c, 2310), 1500);
      return c;
    },
    "channel.update": ({ channelId, recreateFolder }) => {
      const c = channels.find((x) => x.id === channelId);
      if (c.folderState.state !== "ok" && !recreateFolder) fail("ما لقينا مجلد القناة. إذا نقلته، قل لنا وين صار.", "folder_missing");
      if (recreateFolder) c.folderState = { state: "ok" };
      setTimeout(() => runJob(c, 3, 0), 600);
      return { ...c, job: { state: "scanning", total: 0, processed: 0 } };
    },
    "channel.get": ({ channelId }) => {
      const c = channels.find((x) => x.id === channelId);
      const recent = [];
      for (let i = 0; i < 6; i++) recent.push(fileFor(channelId, 50 - i, c.failed && i < c.failed ? "failed" : "done"));
      return { ...c, job: jobs[channelId] || c.job || {}, recent: recent.filter(kept) };
    },
    "channel.autoUpdate": ({ channelId, on }) => { const c = channels.find((x) => x.id === channelId); c.autoUpdate = on; return c; },
    "channel.remove": ({ channelId, trashFiles }) => {
      const [c] = channels.splice(channels.findIndex((x) => x.id === channelId), 1);
      return { removed: true, trash: trashFiles ? { paths: Array.from({ length: c.files }, (_, i) => `${c.folder}/${i}.pdf`), folder: c.folder, ownFolder: true, shared: 2 } : null };
    },
    "job.pause": ({ channelId }) => { jobs[channelId].state = "paused"; return jobs[channelId]; },
    "job.resume": ({ channelId }) => { jobs[channelId].state = "running"; return jobs[channelId]; },
    "job.cancel": ({ channelId }) => { jobs[channelId].state = "stopped"; emit("job.progress", { channelId, ...jobs[channelId] }); return jobs[channelId]; },
    "library.search": ({ query, topic }) => ({
      results: NAMES.map((name, i) => ({
        ...fileFor(101, i + 1), name, channelTitle: "مكتبة القوانين", link: `https://t.me/law_library/${i + 1}`,
        matchedIn: "name",
      })).filter((f) => (query || "").split(/\s+/).every((t) => f.name.includes(t)))
        .filter((f) => !topic || f.topic === topic).filter(kept),
    }),
    "file.remove": ({ channelId, msgId }) => {
      removedFiles.add(`${channelId}:${msgId}`);
      const c = channels.find((x) => x.id === channelId);
      if (c) c.files -= 1;
      return { removed: true, trash: { paths: [`/Users/you/Downloads/${msgId}.pdf`], folder: "/Users/you/Downloads", ownFolder: false } };
    },
    "file.trashed": ({ channelId, msgId, moved }) => {
      if (!moved) {
        removedFiles.delete(`${channelId}:${msgId}`);
        const c = channels.find((x) => x.id === channelId);
        if (c) c.files += 1;
      }
      return { shelves: shelfList() };
    },
    "library.overview": () => ({ totals: totals(), channels: channels.map((c) => ({ ...c, job: jobs[c.id] || c.job || {} })) }),
    "library.topics": () => [
      { topic: "قانون", files: 640 }, { topic: "مرسوم", files: 310 }, { topic: "تعميم", files: 280 },
      { topic: "قرار", files: 190 }, { topic: "لائحة", files: 120 }, { topic: "أخرى", files: 106 },
    ],
    "settings.get": () => ({ language }),
    "settings.set": ({ value }) => { language = value; return { language }; },
    "app.checkUpdate": () => ({ current: "0.2.0", latest: "0.3.0", available: true }),
    "app.update": () => ({ started: true }),
  };

  B.send = (message) => {
    const handler = handlers[message.method];
    Promise.resolve()
      .then(() => {
        if (!handler) fail("طلب مو معروف.", "unknown_method");
        return handler(message.params || {});
      })
      .then((result) => setTimeout(() => B.receive({ id: message.id, result }), 120))
      .catch((error) => setTimeout(() => B.receive({ id: message.id, error: { message: error.message, code: error.code || "error" } }), 120));
  };

  B.sendNative = (message) => {
    const answers = {
      pickFolder: "/Users/you/Documents/قوانين الكويت",
      readClipboard: "",
      trash: { moved: (message.args.paths || []).length, failed: 0 },
    };
    setTimeout(() => B.receive({ id: message.id, result: answers[message.action] ?? true }), 50);
  };
})();
