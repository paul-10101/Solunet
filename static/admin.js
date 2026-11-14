// 접근 키 처리
// - 팀 관리자: 관리자 키를 한 번 입력하면 이 브라우저에 저장 (x-admin-key)
// - 체험 대행사: 행사를 만들 때 받은 관리 링크(#k=...)의 키를 행사별로 저장 (x-event-key)
const Admin = (() => {
  const KEY = 'solunet_admin_key';
  const fid = new URLSearchParams(location.search).get('f') || '';
  const evKeyName = id => 'solunet_ev_' + id;
  let mem = '', evMem = '';
  const store = (k, v) => { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} };
  const load = k => { try { return localStorage.getItem(k) || ''; } catch (e) { return ''; } };
  const get = () => load(KEY) || mem;
  const set = k => { mem = k; store(KEY, k); };
  const clear = () => { mem = ''; store(KEY, null); };

  // 관리 링크로 들어오면 키를 저장하고 주소창에서는 지운다
  const m = location.hash.match(/k=([A-Za-z0-9_-]{16,})/);
  if (m && fid) { evMem = m[1]; store(evKeyName(fid), m[1]); history.replaceState(null, '', location.pathname + location.search); }
  const evKey = (id = fid) => (id === fid && evMem) || load(evKeyName(id));

  function headers(extra = {}) {
    const h = { 'Content-Type': 'application/json', ...extra };
    if (get()) h['x-admin-key'] = get();
    if (evKey()) h['x-event-key'] = evKey();
    return h;
  }

  async function api(url, opts = {}) {
    const r = await fetch(url, { ...opts, headers: headers(opts.headers || {}) });
    if (r.status === 401) { if (!evKey()) { clear(); location.reload(); } throw new Error('이 행사의 관리 링크가 맞지 않습니다'); }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || '요청 실패 (' + r.status + ')');
    return r.json();
  }

  // 행사 키(체험 대행사) 또는 관리자 키가 확인되면 resolve, 아니면 입력 상자
  function ready(mount) {
    return new Promise(async resolve => {
      if (fid && evKey()) {
        const r = await fetch('/api/admin/festival/' + encodeURIComponent(fid), { headers: headers() }).catch(() => null);
        if (r && r.ok) return resolve();
      }
      if (get()) {
        const r = await fetch('/api/admin/check', { headers: { 'x-admin-key': get() } }).catch(() => null);
        if (r && r.ok) return resolve();
        if (r && r.status === 401) clear();
      }
      mount.innerHTML = `<div class="card gate"><h2 style="margin-bottom:8px">관리 링크가 필요합니다</h2>
        <p class="muted" style="font-size:14px;margin-bottom:16px">행사를 만들 때 받은 <b>관리 링크</b>로 다시 들어오세요. 솔루넷 팀이라면 관리자 키를 입력하세요.</p>
        <form id="gateForm"><input id="gateKey" type="password" autocomplete="current-password" placeholder="관리자 키" required>
        <p id="gateMsg" style="font-size:13px;color:#B3261E;min-height:20px;margin-top:6px"></p>
        <button class="btn" type="submit">확인</button> <a class="btn line" href="/#start">무료로 행사 만들기</a></form></div>`;
      document.getElementById('gateForm').onsubmit = async e => {
        e.preventDefault();
        const k = document.getElementById('gateKey').value.trim();
        const r = await fetch('/api/admin/check', { headers: { 'x-admin-key': k } }).catch(() => null);
        if (r && r.ok) { set(k); mount.innerHTML = ''; resolve(); }
        else document.getElementById('gateMsg').textContent = r ? '키가 맞지 않습니다.' : '서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.';
      };
    });
  }
  // 행사 화면 공통 메뉴. 체험 대행사에게는 팀 전용 메뉴(행사 관리)를 숨긴다.
  function nav(active) {
    const q = fid ? '?f=' + encodeURIComponent(fid) : '';
    const items = [['my', '/my' + q, '내 행사'], ['qr', '/admin/qr' + q, 'QR 인쇄'], ['logs', '/admin/logs' + q, '실시간 현황'], ['dash', '/admin' + q, '분석·보고서'], ['settings', '/admin/settings' + q, '설정']];
    let list = fid ? items : [['my', '/my', '내 행사']];
    if (get()) list = list.concat([['events', '/admin/events', '행사 관리']]);  // 팀 관리자에게만
    document.querySelectorAll('[data-nav]').forEach(n => n.innerHTML = list
      .map(([k, h, l]) => `<a class="${k === active ? 'on' : ''}" href="${h}">${l}</a>`).join(''));
  }
  const isOwner = () => !!(fid && evKey()) && !get();
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const kst = iso => new Date(iso).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  return { api, ready, nav, esc, kst, isOwner, evKey, fid, logout: () => { clear(); location.reload(); } };
})();
