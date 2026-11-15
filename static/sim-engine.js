// 혼잡 시뮬레이션 엔진 (시뮬레이션 화면과 시연 화면이 함께 쓴다)
const mins = s => s < 60 ? Math.round(s) + '초' : s >= 7200 ? Math.floor(s / 3600) + '시간 ' + Math.round(s % 3600 / 60) + '분' : (s / 60 >= 10 ? Math.round(s / 60) : Math.round(s / 6) / 10) + '분';
/* ================= 시뮬레이션 엔진 =================
   거점 = 창구(수용 인원만큼 동시에 이용, 나머지는 선착순 대기), 통로 = 밀도에 따라 속도가 줄어드는 구간.
   상태: 0 미입장 1 대기 2 이용 3 이동 4 중도 이탈 5 완주 */
function rng(seed) { let a = seed >>> 0; return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const V0 = 1.34, RHO_MAX = 5.4;
const speedAt = rho => rho < 0.05 ? V0 : Math.max(0.1, V0 * (1 - Math.exp(-1.913 * (1 / rho - 1 / RHO_MAX))));  // Weidmann 기본도
const lvQ = (q, cap) => q >= cap ? 2 : q >= Math.max(2, cap * 0.5) ? 1 : 0;      // 대기 줄이 수용 인원 이상이면 혼잡
const lvRho = r => r >= 2 ? 2 : r >= 1 ? 1 : 0;                                   // 통로 밀도 2명/㎡ 이상이면 혼잡

class Sim {
  constructor(c) {
    const rnd = this.rnd = rng(20261117), N = this.N = c.N, T = this.T = c.hours * 3600, K = this.K = c.cps.length;
    this.c = c; this.t = 0; this.dt = 5;
    const arr = new Float64Array(N);
    for (let i = 0; i < N; i++) { const u = rnd(); arr[i] = T * (c.pattern === 'early' ? u * u : c.pattern === 'peak' ? (u + rnd()) / 2 : u); }
    this.arr = arr.sort();
    this.st = new Uint8Array(N); this.cp = new Int16Array(N); this.tm = new Float64Array(N); this.pg = new Float32Array(N);
    // 분산 유도(c.guide = { follow })를 켜면 추천을 받은 사람 일부가 정해진 순서 대신 한산한 거점으로 먼저 간다. 끄면 아래 필드는 쓰이지 않는다.
    this.g = c.guide || null; this.rnd2 = rng(20261118);   // 추천 수락 여부는 별도 난수로 뽑아 켬/끔이 같은 도착 순서를 쓰게 한다
    this.mask = new Int32Array(N); this.cnt = new Int16Array(N); this.tg = new Int16Array(N); this.pref = new Int16Array(N).fill(-1); this.tl = new Float64Array(N);
    this.arr10 = c.cps.map(() => []); this.ah = new Int32Array(K); this.gIssued = 0; this.gFollowed = 0; this.gOnSec = 0; this.gActive = false;
    this.next = 0; this.left = 0; this.fin = 0; this.onsite = 0; this.peakOn = 0; this.peakOnT = 0;
    this.q = c.cps.map(() => []); this.qh = new Int32Array(K); this.serving = new Int32Array(K);
    this.len = []; for (let i = 0; i < K - 1; i++) { const a = c.cps[i], b = c.cps[i + 1]; this.len.push(Math.max(5, Math.hypot(b.x - a.x, b.y - a.y) * c.cell_m * 1.2)); }  // 직선거리의 1.2배를 걷는다고 본다
    this.seg = new Int32Array(Math.max(K, 1)); this.rho = new Float32Array(Math.max(K, 1));
    this.D = c.cps.map(a => c.cps.map(b => Math.max(5, Math.hypot(b.x - a.x, b.y - a.y) * c.cell_m * 1.2)));
    this.m = c.cps.map(() => ({ peakQ: 0, peakT: 0, waitSum: 0, waitN: 0, waitMax: 0, alertSec: 0, first: null, lv: 0, in10: 0, peakIn: 0, served: 0 }));
    this.sm = this.len.map(() => ({ peakRho: 0, peakT: 0, alertSec: 0, first: null, lv: 0 }));
    this.log = []; this.line = []; this.done = false; this._win = 0;
  }
  _enq(i, k) { this.st[i] = 1; this.cp[i] = k; this.tm[i] = this.t; this.q[k].push(i); this.m[k].in10++;
    this.mask[i] |= 1 << k; this.cnt[i]++;
    if (this.g) { this.arr10[k].push(this.t); this.pref[i] = -1;
      if (this.gActive && this.cnt[i] < this.K) { const r = this._rec(this.mask[i]); if (r >= 0) { this.gIssued++; if (this.rnd2() < this.g.follow) { this.pref[i] = r; this.gFollowed++; } } } } }
  // 실제 서비스(app/spread.py)와 같은 규칙: 최근 10분 방문자 수를 거점 수로 균등 배분한 값과 비교한다.
  _guide() {
    const K = this.K, lim = this.t - 600; let tot = 0; const n = new Array(K);
    for (let k = 0; k < K; k++) { const a = this.arr10[k]; while (this.ah[k] < a.length && a[this.ah[k]] < lim) this.ah[k]++; n[k] = a.length - this.ah[k]; tot += n[k];
      if (this.ah[k] > 4096) { this.arr10[k] = a.slice(this.ah[k]); this.ah[k] = 0; } }
    const ex = tot / K; this.gN = n; this.gEx = ex;
    const on = this.gActive ? 1.2 : 1.5; let hot = false; for (let k = 0; k < K; k++) if (ex && n[k] >= 8 && n[k] / ex >= on) hot = true;
    this.gActive = hot;
  }
  _rec(mask) {   // 아직 안 간 한산한 거점(예상의 0.7배 이하) 중 비율이 가장 낮은 곳
    let best = -1, br = 9; for (let k = 0; k < this.K; k++) if (!(mask >> k & 1) && this.gEx && this.gN[k] / this.gEx <= 0.7 && this.gN[k] / this.gEx < br) { br = this.gN[k] / this.gEx; best = k; }
    return best;
  }
  step() {
    if (this.done) return;
    const { c, dt, K, st, cp, tm, pg, m, cnt } = this, t = this.t += dt;
    const RS = this.g ? K : K - 1;   // 유도를 켜면 마지막 거점에서 되돌아가는 통로도 있다 (길이는 마지막 구간과 같게 본다)
    for (let s = 0; s < RS; s++) this.rho[s] = this.seg[s] / (this.len[Math.min(s, K - 2)] * c.width);
    if (this.g) { this._guide(); if (this.gActive) this.gOnSec += dt; }
    while (this.next < this.N && this.arr[this.next] <= t) { this._enq(this.next++, 0); this.onsite++; }
    for (let i = 0; i < this.next; i++) {
      const s = st[i];
      if (s === 2) { if (t >= tm[i]) { const k = cp[i]; this.serving[k]--; m[k].served++;
          // 이탈은 '몇 번째 거점인지'를 기준으로 뽑는다 (정해진 순서에서는 거점별 이탈률과 같다). 그래서 유도가 완주율을 바꾸지 않는다.
          if (this.rnd() < c.cps[cnt[i] - 1].drop) { st[i] = 4; this.left++; this.onsite--; }
          else if (cnt[i] === K) { st[i] = 5; this.fin++; this.onsite--; }
          else { let nk = k + 1; if (this.g) { let j = 0; while (this.mask[i] >> j & 1) j++; nk = this.pref[i] >= 0 ? this.pref[i] : j; }
            st[i] = 3; pg[i] = 0; this.seg[k]++; this.tg[i] = nk; this.tl[i] = nk === k + 1 ? this.len[k] : this.D[k][nk]; } } }
      else if (s === 3) { const k = cp[i]; pg[i] += speedAt(this.rho[k]) * dt / this.tl[i]; if (pg[i] >= 1) { this.seg[k]--; this._enq(i, this.tg[i]); } }
    }
    for (let k = 0; k < K; k++) {
      const q = this.q[k], cap = c.cps[k].cap, svc = c.cps[k].svc, mk = m[k];
      while (this.serving[k] < cap && this.qh[k] < q.length) { const i = q[this.qh[k]++], w = t - tm[i]; mk.waitSum += w; mk.waitN++; if (w > mk.waitMax) mk.waitMax = w;
        st[i] = 2; tm[i] = t + svc * (0.5 + this.rnd()); this.serving[k]++; }
      if (this.qh[k] > 4096 && this.qh[k] * 2 > q.length) { this.q[k] = q.slice(this.qh[k]); this.qh[k] = 0; }
      const ql = this.q[k].length - this.qh[k]; if (ql > mk.peakQ) { mk.peakQ = ql; mk.peakT = t; }
      const lv = lvQ(ql, cap); if (lv === 2) { mk.alertSec += dt; if (mk.first == null) mk.first = t; }
      if (lv === 2 && !mk.on) { mk.on = true; this.log.push({ t, k, kind: 'cp', on: true, n: ql }); } else if (mk.on && ql < cap * 0.6) { mk.on = false; this.log.push({ t, k, kind: 'cp', on: false }); }
      mk.lv = lv;
    }
    for (let s = 0; s < K - 1; s++) { const r = this.seg[s] / (this.len[s] * c.width), x = this.sm[s], lv = lvRho(r);
      if (r > x.peakRho) { x.peakRho = r; x.peakT = t; } if (lv === 2) { x.alertSec += dt; if (x.first == null) x.first = t; }
      if (lv === 2 && !x.on) { x.on = true; this.log.push({ t, k: s, kind: 'seg', on: true, n: this.seg[s] }); } else if (x.on && r < 1.2) { x.on = false; this.log.push({ t, k: s, kind: 'seg', on: false }); }
      x.lv = lv; }
    if (this.onsite > this.peakOn) { this.peakOn = this.onsite; this.peakOnT = t; }
    if (t - this._win >= 600) { this._win = t; for (const mk of m) { if (mk.in10 > mk.peakIn) mk.peakIn = mk.in10; mk.in10 = 0; } }
    if (Math.round(t) % 60 === 0) this.line.push(this.onsite);
    if ((this.next >= this.N && this.onsite === 0) || t > this.T * 4) { this.done = true; for (const mk of m) if (mk.in10 > mk.peakIn) mk.peakIn = mk.in10; }
  }
  runAll() { while (!this.done) this.step(); return this; }
  qlen(k) { return this.q[k].length - this.qh[k]; }
  summary() {
    const cps = this.c.cps.map((p, k) => { const x = this.m[k]; return { name: p.name, cap: p.cap, peakQ: x.peakQ, peakT: x.peakT, waitAvg: x.waitN ? x.waitSum / x.waitN : 0, waitMax: x.waitMax, alertSec: x.alertSec, first: x.first,
      need: Math.ceil(x.peakIn / 600 * p.svc * 1.15) }; });
    const worst = cps.reduce((a, b) => (b.alertSec > a.alertSec || (b.alertSec === a.alertSec && b.waitMax > a.waitMax)) ? b : a, cps[0]);
    const segs = this.sm.map((x, s) => ({ name: `${this.c.cps[s].name} → ${this.c.cps[s + 1].name}`, len: this.len[s], peakRho: x.peakRho, alertSec: x.alertSec, first: x.first }));
    return { N: this.N, end: this.t, peakOn: this.peakOn, peakOnT: this.peakOnT, fin: this.fin, left: this.left, cps, segs, worst,
      guide: this.g ? { follow: this.g.follow, issued: this.gIssued, followed: this.gFollowed, onSec: this.gOnSec } : null,
      anyAlert: cps.some(x => x.alertSec > 0) || segs.some(x => x.alertSec > 0), alertSec: Math.max(0, ...cps.map(x => x.alertSec), ...segs.map(x => x.alertSec)) };
  }
}


/* 행사 집계(/api/stats)와 배치(/api/layout)에서 시뮬레이션 조건을 만든다. 배치가 없으면 기본값. */
const SimBase = {
  build(st, lay) {
    const f = st.festival, byId = lay ? Object.fromEntries(lay.checkpoints.map(c => [c.id, c])) : {};
    const order = lay && lay.route && lay.route.length ? lay.route.filter(id => f.checkpoints.some(c => c.id === id)) : f.checkpoints.map(c => c.id);
    f.checkpoints.forEach(c => { if (!order.includes(c.id)) order.push(c.id); });
    const drop = Object.fromEntries(st.current.checkpoints.map(c => [c.id, c.drop_rate / 100])), placed = order.every(id => byId[id] && byId[id].x != null);
    return { placed, base: { cell_m: (lay && lay.grid && lay.grid.cell_m) || 1, cps: order.map((id, i) => { const c = f.checkpoints.find(x => x.id === id), l = byId[id] || {};
      return { id, name: c.name, x: placed ? l.x : 10 + i * 60, y: placed ? l.y : (i % 2 ? 18 : 42), cap: l.capacity || 30, svc: l.service_sec || 180, drop: drop[id] || 0 }; }) } };
  },
  config(base, N, o = {}) { return { N, hours: o.hours || 6, width: o.width || 3, pattern: o.pattern || 'even', cell_m: base.cell_m, cps: base.cps.map((c, i) => ({ ...c, drop: i === base.cps.length - 1 ? 0 : c.drop })) }; },
};
