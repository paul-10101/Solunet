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
    this.next = 0; this.left = 0; this.fin = 0; this.onsite = 0; this.peakOn = 0; this.peakOnT = 0;
    this.q = c.cps.map(() => []); this.qh = new Int32Array(K); this.serving = new Int32Array(K);
    this.len = []; for (let i = 0; i < K - 1; i++) { const a = c.cps[i], b = c.cps[i + 1]; this.len.push(Math.max(5, Math.hypot(b.x - a.x, b.y - a.y) * c.cell_m * 1.2)); }  // 직선거리의 1.2배를 걷는다고 본다
    this.seg = new Int32Array(Math.max(K - 1, 1)); this.rho = new Float32Array(Math.max(K - 1, 1));
    this.m = c.cps.map(() => ({ peakQ: 0, peakT: 0, waitSum: 0, waitN: 0, waitMax: 0, alertSec: 0, first: null, lv: 0, in10: 0, peakIn: 0, served: 0 }));
    this.sm = this.len.map(() => ({ peakRho: 0, peakT: 0, alertSec: 0, first: null, lv: 0 }));
    this.log = []; this.line = []; this.done = false; this._win = 0;
  }
  _enq(i, k) { this.st[i] = 1; this.cp[i] = k; this.tm[i] = this.t; this.q[k].push(i); this.m[k].in10++; }
  step() {
    if (this.done) return;
    const { c, dt, K, st, cp, tm, pg, m } = this, t = this.t += dt;
    for (let s = 0; s < K - 1; s++) this.rho[s] = this.seg[s] / (this.len[s] * c.width);
    while (this.next < this.N && this.arr[this.next] <= t) { this._enq(this.next++, 0); this.onsite++; }
    for (let i = 0; i < this.next; i++) {
      const s = st[i];
      if (s === 2) { if (t >= tm[i]) { const k = cp[i]; this.serving[k]--; m[k].served++;
          if (this.rnd() < c.cps[k].drop) { st[i] = 4; this.left++; this.onsite--; }
          else if (k === K - 1) { st[i] = 5; this.fin++; this.onsite--; }
          else { st[i] = 3; pg[i] = 0; this.seg[k]++; } } }
      else if (s === 3) { const k = cp[i]; pg[i] += speedAt(this.rho[k]) * dt / this.len[k]; if (pg[i] >= 1) { this.seg[k]--; this._enq(i, k + 1); } }
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
