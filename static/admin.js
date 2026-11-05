// 관리자 키 처리: 한 번 입력하면 이 브라우저에 저장하고, 모든 관리자 API 요청에 헤더로 붙인다.
const Admin = (() => {
  const KEY = 'solunet_admin_key';
  let mem = '';
  const get = () => { try { return localStorage.getItem(KEY) || mem; } catch (e) { return mem; } };
  const set = k => { mem = k; try { localStorage.setItem(KEY, k); } catch (e) {} };
  const clear = () => { mem = ''; try { localStorage.removeItem(KEY); } catch (e) {} };

  async function api(url, opts = {}) {
    const r = await fetch(url, { ...opts, headers: { 'Content-Type': 'application/json', 'x-admin-key': get(), ...(opts.headers || {}) } });
    if (r.status === 401) { clear(); location.reload(); throw new Error('관리자 키가 맞지 않습니다'); }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || '요청 실패 (' + r.status + ')');
    return r.json();
  }

  // 키가 없거나 틀리면 로그인 상자를 보여 주고, 확인되면 resolve
  function ready(mount) {
    return new Promise(async resolve => {
      if (get()) {
        const r = await fetch('/api/admin/check', { headers: { 'x-admin-key': get() } }).catch(() => null);
        if (r && r.ok) return resolve();
        if (r && r.status === 401) clear();
      }
      mount.innerHTML = `<div class="card gate"><h2 style="margin-bottom:8px">관리자 키 입력</h2>
        <p class="muted" style="font-size:14px;margin-bottom:16px">팀에서 정한 관리자 키를 입력하세요. 이 브라우저에만 저장됩니다.</p>
        <form id="gateForm"><input id="gateKey" type="password" autocomplete="current-password" required>
        <p id="gateMsg" style="font-size:13px;color:#B3261E;min-height:20px;margin-top:6px"></p>
        <button class="btn" type="submit">확인</button></form></div>`;
      document.getElementById('gateForm').onsubmit = async e => {
        e.preventDefault();
        const k = document.getElementById('gateKey').value.trim();
        const r = await fetch('/api/admin/check', { headers: { 'x-admin-key': k } }).catch(() => null);
        if (r && r.ok) { set(k); mount.innerHTML = ''; resolve(); }
        else document.getElementById('gateMsg').textContent = r ? '키가 맞지 않습니다.' : '서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.';
      };
    });
  }
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const kst = iso => new Date(iso).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  return { api, ready, esc, kst, logout: () => { clear(); location.reload(); } };
})();
