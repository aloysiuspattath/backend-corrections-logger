/* ============================================================
   BACKEND CORRECTIONS PORTAL — Frontend App
   Auth + Real-time + Full SPA
   ============================================================ */

// ─── STATE ────────────────────────────────────────────────────────────────────
let currentUser = null;
let isAdmin = false;
let corrections = [];
let totalRecords = 0;
let currentPage = 1;
const perPage = 20;
let sortCol = 'date';
let sortDir = 'desc';
let editingId = null;
let deleteId = null;
let socket = null;
let allUsers = [];

// ─── AUTH ─────────────────────────────────────────────────────────────────────

async function checkAuth() {
  try {
    const res = await fetch('/api/auth/me', { credentials: 'include' });
    if (res.ok) {
      const data = await res.json();
      if (data.authenticated) {
        onLoginSuccess(data.user);
        return;
      }
    }
  } catch (e) { /* not logged in */ }
  showLogin();
}

function showLogin() {
  document.getElementById('loginScreen').style.display = 'flex';
  document.getElementById('appWrapper').style.display = 'none';
  document.getElementById('loginUsername').focus();
}

function hideLogin() {
  document.getElementById('loginScreen').style.display = 'none';
  document.getElementById('appWrapper').style.display = 'flex';
}

function onLoginSuccess(user) {
  currentUser = user;
  isAdmin = user.role === 'admin';
  hideLogin();
  applyRoleVisibility();
  updateTopbarUser();
  loadUsersDropdown();
  initSocket();
  loadDashboard();
  loadCorrections();
  loadBackups();
  if (isAdmin) loadUsers();
}

async function doLogin(e) {
  e.preventDefault();
  const username = document.getElementById('loginUsername').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errEl = document.getElementById('loginError');
  const btn = document.getElementById('loginBtn');

  if (!username || !password) {
    errEl.textContent = 'Please enter username and password.';
    errEl.style.display = 'block';
    return;
  }

  btn.disabled = true;
  btn.innerHTML = 'Signing in...';
  errEl.style.display = 'none';

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (res.ok) {
      toast(data.message || 'Login successful!', 'success');
      onLoginSuccess(data.user);
    } else {
      errEl.textContent = data.error || 'Login failed.';
      errEl.style.display = 'block';
    }
  } catch (err) {
    errEl.textContent = 'Connection error. Is the server running?';
    errEl.style.display = 'block';
  }
  btn.disabled = false;
  btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg> Sign In';
}

async function doLogout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
  } catch (e) { /* ignore */ }
  currentUser = null;
  isAdmin = false;
  if (socket) socket.disconnect();
  showLogin();
  document.getElementById('loginUsername').value = '';
  document.getElementById('loginPassword').value = '';
  document.getElementById('loginError').style.display = 'none';
}

function applyRoleVisibility() {
  document.querySelectorAll('.admin-only').forEach(el => {
    if (isAdmin) el.classList.remove('hidden');
    else el.classList.add('hidden');
  });
}

function updateTopbarUser() {
  if (!currentUser) return;
  document.getElementById('topbarUsername').textContent = currentUser.display_name;
  document.getElementById('topbarAvatar').textContent = currentUser.display_name.charAt(0).toUpperCase();
  const roleEl = document.getElementById('topbarRole');
  roleEl.textContent = currentUser.role;
  roleEl.className = 'role-badge' + (currentUser.role === 'admin' ? ' admin' : '');
}

// ─── API HELPERS ──────────────────────────────────────────────────────────────

async function api(url, opts = {}) {
  opts.credentials = 'include';
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    opts.headers = { ...(opts.headers || {}), 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(url, opts);
  if (res.status === 401) {
    const d = await res.json().catch(() => ({}));
    if (d.auth_required) { showLogin(); return null; }
  }
  return res;
}

// ─── USERS DROPDOWN ───────────────────────────────────────────────────────────

async function loadUsersDropdown() {
  try {
    const res = await api('/api/users');
    if (!res) return;
    allUsers = await res.json();
    populateExecutorDropdowns();
  } catch (e) { console.error('Users load error:', e); }
}

function populateExecutorDropdowns() {
  // Form dropdown
  const sel = document.getElementById('executedInput');
  const currentVal = sel.value;
  sel.innerHTML = '<option value="">-- Select User --</option>';
  allUsers.forEach(u => {
    const opt = document.createElement('option');
    opt.value = u.display_name;
    opt.textContent = u.display_name;
    sel.appendChild(opt);
  });
  // Auto-select current user if nothing was selected
  if (!currentVal && currentUser) {
    sel.value = currentUser.display_name;
  } else {
    sel.value = currentVal;
  }

  // Filter dropdown in corrections view
  const filterSel = document.getElementById('filterExecuted');
  const filterVal = filterSel.value;
  filterSel.innerHTML = '<option value="">All Executors</option>';
  allUsers.forEach(u => {
    const opt = document.createElement('option');
    opt.value = u.display_name;
    opt.textContent = u.display_name;
    filterSel.appendChild(opt);
  });
  filterSel.value = filterVal;

  // Search filter dropdown
  const searchFilterSel = document.getElementById('searchFilterExecutor');
  if (searchFilterSel) {
    const searchFilterVal = searchFilterSel.value;
    searchFilterSel.innerHTML = '<option value="">All Executors</option>';
    allUsers.forEach(u => {
      const opt = document.createElement('option');
      opt.value = u.display_name;
      opt.textContent = u.display_name;
      searchFilterSel.appendChild(opt);
    });
    searchFilterSel.value = searchFilterVal;
  }
}

// ─── USER MANAGEMENT (ADMIN) ─────────────────────────────────────────────────

async function loadUsers() {
  try {
    const res = await api('/api/users?all=1');
    if (!res) return;
    const users = await res.json();
    renderUsersTable(users);
  } catch (e) { console.error('Users load error:', e); }
}

function renderUsersTable(users) {
  const tbody = document.getElementById('usersBody');
  if (!tbody) return;
  if (users.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state-mini">No users found</td></tr>';
    return;
  }
  tbody.innerHTML = users.map(u => `
    <tr>
      <td><span class="ticket-badge">${esc(u.username)}</span></td>
      <td>${esc(u.display_name)}</td>
      <td><span class="role-badge ${u.role === 'admin' ? 'admin' : ''}">${u.role}</span></td>
      <td><span class="${u.active ? 'user-status-active' : 'user-status-inactive'}">${u.active ? 'Active' : 'Inactive'}</span></td>
      <td>${u.created_at || '-'}</td>
      <td class="col-actions">
        <div class="row-actions">
          <button class="action-btn edit-btn" title="Edit" onclick="openEditUser(${u.id})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>
          <button class="action-btn" title="Reset Password" onclick="openResetPw(${u.id},'${esc(u.display_name)}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></button>
          ${u.id !== currentUser.id ? `<button class="action-btn del-btn" title="Delete" onclick="deleteUser(${u.id})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg></button>` : ''}
        </div>
      </td>
    </tr>`).join('');
}

function openAddUser() {
  document.getElementById('userModalTitle').textContent = 'Add User';
  document.getElementById('userEditId').value = '';
  document.getElementById('userUsername').value = '';
  document.getElementById('userUsername').disabled = false;
  document.getElementById('userDisplayName').value = '';
  document.getElementById('userPassword').value = '';
  document.getElementById('userRole').value = 'user';
  document.getElementById('userPwGroup').style.display = '';
  document.getElementById('userActiveGroup').style.display = 'none';
  openModal('userModal');
}

function openEditUser(uid) {
  const u = allUsers.find(x => x.id === uid) || {};
  document.getElementById('userModalTitle').textContent = 'Edit User';
  document.getElementById('userEditId').value = uid;
  document.getElementById('userUsername').value = u.username || '';
  document.getElementById('userUsername').disabled = true;
  document.getElementById('userDisplayName').value = u.display_name || '';
  document.getElementById('userPassword').value = '';
  document.getElementById('userRole').value = u.role || 'user';
  document.getElementById('userPwGroup').style.display = 'none';
  document.getElementById('userActiveGroup').style.display = '';
  document.getElementById('userActive').value = u.active ? '1' : '0';
  openModal('userModal');
}

async function saveUser() {
  const editId = document.getElementById('userEditId').value;
  const username = document.getElementById('userUsername').value.trim();
  const displayName = document.getElementById('userDisplayName').value.trim();
  const password = document.getElementById('userPassword').value;
  const role = document.getElementById('userRole').value;

  if (!editId) {
    // Create
    if (!username || !displayName || !password) {
      toast('All fields are required.', 'error');
      return;
    }
    const res = await api('/api/users', { method: 'POST', body: { username, display_name: displayName, password, role } });
    if (!res) return;
    if (res.ok) {
      toast('User created!', 'success');
      closeAllModals();
      loadUsers();
      loadUsersDropdown();
    } else {
      const d = await res.json();
      toast(d.error || 'Failed to create user.', 'error');
    }
  } else {
    // Update
    if (!displayName) { toast('Display name is required.', 'error'); return; }
    const active = parseInt(document.getElementById('userActive').value);
    const res = await api(`/api/users/${editId}`, { method: 'PUT', body: { display_name: displayName, role, active } });
    if (!res) return;
    if (res.ok) {
      toast('User updated!', 'success');
      closeAllModals();
      loadUsers();
      loadUsersDropdown();
    } else {
      const d = await res.json();
      toast(d.error || 'Failed to update user.', 'error');
    }
  }
}

function openResetPw(uid, name) {
  document.getElementById('resetPwUserId').value = uid;
  document.getElementById('resetPwUserName').textContent = name;
  document.getElementById('resetPwValue').value = '';
  openModal('resetPwModal');
}

async function doResetPw() {
  const uid = document.getElementById('resetPwUserId').value;
  const pw = document.getElementById('resetPwValue').value;
  if (!pw || pw.length < 4) { toast('Password must be at least 4 characters.', 'error'); return; }
  const res = await api(`/api/users/${uid}/reset-password`, { method: 'POST', body: { password: pw } });
  if (!res) return;
  if (res.ok) {
    toast('Password reset!', 'success');
    closeAllModals();
  } else {
    const d = await res.json();
    toast(d.error || 'Reset failed.', 'error');
  }
}

async function deleteUser(uid) {
  if (!confirm('Delete this user permanently?')) return;
  const res = await api(`/api/users/${uid}`, { method: 'DELETE' });
  if (!res) return;
  if (res.ok) {
    toast('User deleted.', 'success');
    loadUsers();
    loadUsersDropdown();
  } else {
    const d = await res.json();
    toast(d.error || 'Delete failed.', 'error');
  }
}

async function doChangePassword() {
  const curr = document.getElementById('currentPwInput').value;
  const newPw = document.getElementById('newPwInput').value;
  if (!curr || !newPw) { toast('Both fields are required.', 'error'); return; }
  const res = await api('/api/auth/change-password', { method: 'POST', body: { current_password: curr, new_password: newPw } });
  if (!res) return;
  if (res.ok) {
    toast('Password changed!', 'success');
    document.getElementById('currentPwInput').value = '';
    document.getElementById('newPwInput').value = '';
  } else {
    const d = await res.json();
    toast(d.error || 'Failed.', 'error');
  }
}

// ─── SOCKET.IO ────────────────────────────────────────────────────────────────

function initSocket() {
  if (socket && socket.connected) return;
  socket = io({ transports: ['websocket', 'polling'] });

  socket.on('connect', () => {
    console.log('Socket connected');
    if (currentView === 'dashboard') loadDashboard();
    if (currentView === 'corrections') loadCorrections();
    document.getElementById('liveDot').title = 'Connected';
    document.querySelector('.dot-pulse').style.background = 'var(--success)';
    socket.emit('user_join', { username: currentUser ? currentUser.display_name : 'User' });
  });

  socket.on('disconnect', () => {
    document.getElementById('liveDot').title = 'Disconnected';
    document.querySelector('.dot-pulse').style.background = 'var(--danger)';
  });

  socket.on('users_online', users => {
    document.getElementById('onlineCount').textContent = users.length;
  });

  socket.on('correction_added', () => {
    loadCorrections();
    loadDashboard();
  });

  socket.on('correction_updated', () => {
    loadCorrections();
    loadDashboard();
  });

  socket.on('correction_deleted', () => {
    loadCorrections();
    loadDashboard();
  });

  socket.on('data_imported', () => {
    loadCorrections();
    loadDashboard();
    toast('Data was imported by another user.', 'info');
  });
}

// ─── NAVIGATION ───────────────────────────────────────────────────────────────

const viewTitles = {
  'dashboard': 'Dashboard',
  'corrections': 'All Corrections',
  'add': 'New Correction',
  'search': 'Search',
  'import-export': 'Import / Export',
  'backups': 'Backups',
  'settings': 'Settings'
};

function switchView(name) {
  // Block non-admin from admin views
  if (!isAdmin && (name === 'backups' || name === 'settings' || name === 'import-export')) {
    toast('Admin access required.', 'error');
    return;
  }

  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const view = document.getElementById('view-' + name);
  const nav = document.getElementById('nav-' + name);
  if (view) view.classList.add('active');
  if (nav) nav.classList.add('active');
  document.getElementById('pageTitle').textContent = viewTitles[name] || name;

  if (name === 'add' && !editingId) {
    resetForm();
  }
  if (name === 'backups') loadBackups();
  if (name === 'settings') {
    if (isAdmin) loadUsers();
    loadAppConfig();
  }

  // Close mobile sidebar
  document.getElementById('sidebar').classList.remove('mobile-open');
}

// ─── DASHBOARD ────────────────────────────────────────────────────────────────

async function loadDashboard() {
  try {
    const res = await api('/api/stats');
    if (!res) return;
    const s = await res.json();
    if (s.db_engine) {
      const dbTypeEl = document.getElementById('dbTypeDisplay');
      if (dbTypeEl) dbTypeEl.textContent = s.db_engine;
    }
    animateCount('statTotal', s.total);
    animateCount('statToday', s.today);
    animateCount('statWeek', s.week);
    animateCount('statMonth', s.month);
  } catch (e) { console.error(e); }

  try {
    const res = await api('/api/corrections?per_page=5&sort=date&dir=desc');
    if (!res) return;
    const d = await res.json();
    renderRecentList(d.data || []);
  } catch (e) { console.error(e); }

  try {
    const res = await api('/api/activity?days=14');
    if (!res) return;
    const data = await res.json();
    drawChart(data);
  } catch (e) { console.error(e); }
}

function animateCount(id, target) {
  const el = document.getElementById(id);
  const start = parseInt(el.textContent) || 0;
  if (start === target) { el.textContent = target; return; }
  const dur = 600;
  const st = performance.now();
  const step = ts => {
    const p = Math.min((ts - st) / dur, 1);
    el.textContent = Math.round(start + (target - start) * easeOut(p));
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

function renderRecentList(items) {
  const el = document.getElementById('recentList');
  if (items.length === 0) {
    el.innerHTML = '<div class="empty-state-mini">No corrections yet</div>';
    return;
  }
  el.innerHTML = items.map(r => `
    <div class="recent-item" onclick="viewCorrection(${r.id})">
      <div class="recent-item-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></div>
      <div class="recent-item-info"><div class="recent-ticket">${esc(r.ticket)}</div><div class="recent-exec">${esc(r.executed_by)}</div></div>
      <div class="recent-date">${r.date}</div>
    </div>`).join('');
}

// ─── CHART ────────────────────────────────────────────────────────────────────

function drawChart(data) {
  const canvas = document.getElementById('activityChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * (window.devicePixelRatio || 1);
  canvas.height = rect.height * (window.devicePixelRatio || 1);
  ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
  const W = rect.width, H = rect.height;
  ctx.clearRect(0, 0, W, H);

  if (!data || data.length === 0) {
    ctx.fillStyle = '#4a5568';
    ctx.font = '13px Inter';
    ctx.textAlign = 'center';
    ctx.fillText('No activity data', W / 2, H / 2);
    return;
  }

  const max = Math.max(...data.map(d => d.count), 1);
  const pad = { top: 10, right: 10, bottom: 36, left: 36 };
  const cW = W - pad.left - pad.right;
  const cH = H - pad.top - pad.bottom;
  const barW = Math.max(6, (cW / data.length) - 6);

  // Grid
  ctx.strokeStyle = '#232c42';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (cH / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
    ctx.fillStyle = '#4a5568'; ctx.font = '10px Inter'; ctx.textAlign = 'right';
    ctx.fillText(Math.round(max - (max / 4) * i), pad.left - 6, y + 3);
  }

  // Bars
  data.forEach((d, i) => {
    const x = pad.left + (cW / data.length) * i + (cW / data.length - barW) / 2;
    const bH = (d.count / max) * cH;
    const y = pad.top + cH - bH;
    const grad = ctx.createLinearGradient(x, y, x, pad.top + cH);
    grad.addColorStop(0, '#4f7ef8'); grad.addColorStop(1, '#6366f1');
    ctx.fillStyle = grad;
    ctx.beginPath();
    const r = Math.min(3, barW / 3);
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + barW - r, y);
    ctx.quadraticCurveTo(x + barW, y, x + barW, y + r);
    ctx.lineTo(x + barW, pad.top + cH);
    ctx.lineTo(x, pad.top + cH);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.fill();

    // Label
    ctx.fillStyle = '#4a5568'; ctx.font = '9px Inter'; ctx.textAlign = 'center';
    const lbl = d.date.slice(5);
    ctx.fillText(lbl, x + barW / 2, pad.top + cH + 14);
  });
}

// ─── CORRECTIONS ──────────────────────────────────────────────────────────────

async function loadCorrections() {
  const search = document.getElementById('tableSearch').value.trim();
  const executedBy = document.getElementById('filterExecuted').value;
  const status = document.getElementById('filterStatus').value;
  const dateFrom = document.getElementById('filterDateFrom').value;
  const dateTo = document.getElementById('filterDateTo').value;

  const params = new URLSearchParams({
    page: currentPage, per_page: perPage,
    sort: sortCol, dir: sortDir,
    search, executed_by: executedBy, status,
    date_from: dateFrom, date_to: dateTo
  });

  try {
    const res = await api('/api/corrections?' + params);
    if (!res) return;
    const d = await res.json();
    corrections = d.data || [];
    totalRecords = d.total || 0;
    renderTable();
    renderPagination();
    document.getElementById('recordCount').textContent = `${totalRecords} record${totalRecords !== 1 ? 's' : ''}`;
  } catch (e) { console.error(e); }
}

function renderTable() {
  const tbody = document.getElementById('correctionsBody');
  if (corrections.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><p>No corrections found</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = corrections.map(r => {
    const statusCls = r.status === 'Completed' ? 'badge-completed' :
                      r.status === 'Pending Verification' ? 'badge-pending' :
                      r.status === 'Rolled Back' ? 'badge-rolled' : 'badge-failed';
    const canEdit = isAdmin || r.executed_by === (currentUser ? currentUser.display_name : '');
    return `<tr>
      <td><span class="ticket-badge">${esc(r.ticket)}</span></td>
      <td><span class="query-preview" onclick="viewCorrection(${r.id})" title="Click to view">${esc(r.query)}</span></td>
      <td><div class="exec-cell"><div class="exec-avatar">${esc(r.executed_by).charAt(0).toUpperCase()}</div>${esc(r.executed_by)}</div></td>
      <td class="date-cell">${r.date}</td>
      <td><span class="badge ${statusCls}">${esc(r.status)}</span></td>
      <td class="col-actions"><div class="row-actions">
        <button class="action-btn view-btn" title="View" onclick="viewCorrection(${r.id})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></button>
        ${canEdit ? `<button class="action-btn edit-btn" title="Edit" onclick="editCorrection(${r.id})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>` : ''}
        ${isAdmin ? `<button class="action-btn del-btn" title="Delete" onclick="promptDelete(${r.id},'${esc(r.ticket)}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg></button>` : ''}
      </div></td>
    </tr>`;
  }).join('');
}

function renderPagination() {
  const pages = Math.ceil(totalRecords / perPage);
  const el = document.getElementById('pagination');
  if (pages <= 1) { el.innerHTML = ''; return; }
  let html = `<button class="page-btn" ${currentPage <= 1 ? 'disabled' : ''} onclick="goPage(${currentPage - 1})"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg></button>`;
  const start = Math.max(1, currentPage - 2);
  const end = Math.min(pages, currentPage + 2);
  if (start > 1) html += `<button class="page-btn" onclick="goPage(1)">1</button>`;
  if (start > 2) html += `<span style="color:var(--text-muted)">...</span>`;
  for (let i = start; i <= end; i++) {
    html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
  }
  if (end < pages - 1) html += `<span style="color:var(--text-muted)">...</span>`;
  if (end < pages) html += `<button class="page-btn" onclick="goPage(${pages})">${pages}</button>`;
  html += `<button class="page-btn" ${currentPage >= pages ? 'disabled' : ''} onclick="goPage(${currentPage + 1})"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg></button>`;
  el.innerHTML = html;
}

function goPage(p) {
  currentPage = p;
  loadCorrections();
}

// ─── FORM ─────────────────────────────────────────────────────────────────────

function resetForm() {
  editingId = null;
  document.getElementById('editId').value = '';
  document.getElementById('ticketInput').value = '';
  document.getElementById('executedInput').value = currentUser ? currentUser.display_name : '';
  document.getElementById('dateInput').value = new Date().toISOString().slice(0, 10);
  document.getElementById('statusInput').value = 'Completed';
  document.getElementById('queryInput').value = '';
  document.getElementById('notesInput').value = '';
  document.getElementById('formTitle').textContent = 'New Backend Correction';
  document.getElementById('formSubtitle').textContent = 'Log a backend query/command against a service ticket';
  document.querySelectorAll('.field-error').forEach(e => e.textContent = '');
}

async function handleSubmit(e) {
  e.preventDefault();
  const ticket = document.getElementById('ticketInput').value.trim();
  const executedBy = document.getElementById('executedInput').value;
  const date = document.getElementById('dateInput').value;
  const status = document.getElementById('statusInput').value;
  const query = document.getElementById('queryInput').value.trim();
  const notes = document.getElementById('notesInput').value.trim();

  let valid = true;
  document.querySelectorAll('.field-error').forEach(e => e.textContent = '');
  if (!ticket) { document.getElementById('ticketError').textContent = 'Required'; valid = false; }
  if (!executedBy) { document.getElementById('executedError').textContent = 'Please select a user'; valid = false; }
  if (!date) { document.getElementById('dateError').textContent = 'Required'; valid = false; }
  if (!query) { document.getElementById('queryError').textContent = 'Required'; valid = false; }
  if (!valid) return;

  const payload = { ticket, executed_by: executedBy, date, status, query, notes };
  const btn = document.getElementById('submitBtn');
  btn.disabled = true;

  try {
    let res;
    if (editingId) {
      res = await api(`/api/corrections/${editingId}`, { method: 'PUT', body: payload });
    } else {
      res = await api('/api/corrections', { method: 'POST', body: payload });
    }
    if (!res) { btn.disabled = false; return; }
    if (res.ok) {
      toast(editingId ? 'Correction updated!' : 'Correction saved!', 'success');
      resetForm();
      switchView('corrections');
      loadCorrections();
      loadDashboard();
    } else {
      const d = await res.json();
      toast(d.error || 'Save failed', 'error');
    }
  } catch (err) {
    toast('Connection error', 'error');
  }
  btn.disabled = false;
}

async function editCorrection(id) {
  try {
    const res = await api(`/api/corrections/${id}`);
    if (!res) return;
    if (!res.ok) { toast('Could not load correction.', 'error'); return; }
    const r = await res.json();
    editingId = id;
    document.getElementById('editId').value = id;
    document.getElementById('ticketInput').value = r.ticket || '';
    document.getElementById('executedInput').value = r.executed_by || '';
    document.getElementById('dateInput').value = r.date || '';
    document.getElementById('statusInput').value = r.status || 'Completed';
    document.getElementById('queryInput').value = r.query || '';
    document.getElementById('notesInput').value = r.notes || '';
    document.getElementById('formTitle').textContent = 'Edit Correction';
    document.getElementById('formSubtitle').textContent = `Editing: ${r.ticket}`;
    switchView('add');
  } catch (e) { toast('Error loading correction', 'error'); }
}

function viewCorrection(id) {
  const r = corrections.find(c => c.id === id);
  if (!r) return;
  document.getElementById('modalTicketTitle').textContent = r.ticket;
  document.getElementById('modalMeta').textContent = `by ${r.executed_by}`;
  document.getElementById('modalQuery').textContent = r.query;
  document.getElementById('modalDate').textContent = r.date;
  const badge = document.getElementById('modalStatus');
  badge.textContent = r.status;
  badge.className = 'badge ' + (r.status === 'Completed' ? 'badge-completed' : r.status === 'Pending Verification' ? 'badge-pending' : r.status === 'Rolled Back' ? 'badge-rolled' : 'badge-failed');
  const nb = document.getElementById('notesBlock');
  if (r.notes) { nb.style.display = ''; document.getElementById('modalNotes').textContent = r.notes; }
  else nb.style.display = 'none';

  document.getElementById('editFromModal').onclick = () => { closeAllModals(); editCorrection(id); };
  openModal('viewModal');
}

function promptDelete(id, ticket) {
  deleteId = id;
  document.getElementById('deleteTicketName').textContent = ticket;
  openModal('deleteModal');
}

async function confirmDelete() {
  if (!deleteId) return;
  try {
    const res = await api(`/api/corrections/${deleteId}`, { method: 'DELETE' });
    if (!res) return;
    if (res.ok) {
      toast('Correction deleted.', 'success');
      loadCorrections();
      loadDashboard();
    } else {
      const d = await res.json();
      toast(d.error || 'Delete failed', 'error');
    }
  } catch (e) { toast('Error', 'error'); }
  deleteId = null;
  closeAllModals();
}

// ─── SEARCH ───────────────────────────────────────────────────────────────────

async function doSearch() {
  const q = document.getElementById('searchInput').value.trim();
  if (!q) return;
  const el = document.getElementById('searchResults');
  el.innerHTML = '<div class="loading-row">Searching...</div>';
  try {
    const params = new URLSearchParams({ q });
    const se = document.getElementById('searchFilterExecutor').value;
    const ss = document.getElementById('searchFilterStatus').value;
    const sdf = document.getElementById('searchFilterDateFrom').value;
    const sdt = document.getElementById('searchFilterDateTo').value;
    if (se) params.set('executed_by', se);
    if (ss) params.set('status', ss);
    if (sdf) params.set('date_from', sdf);
    if (sdt) params.set('date_to', sdt);
    const res = await api('/api/search?' + params);
    if (!res) return;
    const d = await res.json();
    if (d.data && d.data.length > 0) {
      el.innerHTML = `<div class="result-count-bar">${d.total} result${d.total !== 1 ? 's' : ''} for "${esc(d.query)}"</div>` +
        d.data.map(r => `
          <div class="search-result-item" onclick="viewCorrection(${r.id})">
            <div class="search-result-header"><span class="ticket-badge">${esc(r.ticket)}</span><span class="badge ${r.status === 'Completed' ? 'badge-completed' : r.status === 'Failed' ? 'badge-failed' : 'badge-pending'}">${esc(r.status)}</span></div>
            <div class="search-result-query">${esc(r.query)}</div>
            <div class="search-result-meta"><span class="search-meta-item">${esc(r.executed_by)}</span><span class="search-meta-item">${r.date}</span></div>
          </div>`).join('');
      // Make viewCorrection work by adding results to corrections
      d.data.forEach(r => { if (!corrections.find(c => c.id === r.id)) corrections.push(r); });
    } else {
      el.innerHTML = '<div class="empty-state" style="padding:40px"><p>No results found</p></div>';
    }
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Search error</p></div>'; }
}

// ─── BACKUPS ──────────────────────────────────────────────────────────────────

async function loadBackups() {
  if (!isAdmin) return;
  try {
    const res = await api('/api/backups');
    if (!res) return;
    const backups = await res.json();
    const tbody = document.getElementById('backupsBody');
    if (backups.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state-mini">No backups yet</td></tr>';
      return;
    }
    tbody.innerHTML = backups.map(b => `<tr>
      <td>${esc(b.filename)}</td>
      <td><span class="backup-type-badge ${b.type === 'sqlite' ? 'backup-type-sqlite' : 'backup-type-oracle'}">${b.type}</span></td>
      <td>${b.size_human || b.size}</td>
      <td>${b.created || '-'}</td>
      <td style="text-align:right"><div class="row-actions"><a class="action-btn view-btn" href="/api/backups/${encodeURIComponent(b.filename)}/download" title="Download"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></a><button class="action-btn del-btn" title="Delete" onclick="deleteBackup('${esc(b.filename)}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg></button></div></td>
    </tr>`).join('');
  } catch (e) { console.error(e); }
}

async function createBackup() {
  const label = (document.getElementById('backupLabelInput') || {}).value || '';
  try {
    const res = await api('/api/backups', { method: 'POST', body: { label } });
    if (!res) return;
    if (res.ok) {
      const d = await res.json();
      toast(`Backup created: ${d.filename}`, 'success');
      closeAllModals();
      loadBackups();
    } else {
      const d = await res.json();
      toast(d.error || 'Backup failed', 'error');
    }
  } catch (e) { toast('Error creating backup', 'error'); }
}

async function deleteBackup(filename) {
  if (!confirm('Delete this backup?')) return;
  try {
    const res = await api(`/api/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    if (res && res.ok) { toast('Backup deleted.', 'success'); loadBackups(); }
  } catch (e) { toast('Error', 'error'); }
}

// ─── IMPORT / EXPORT ──────────────────────────────────────────────────────────

function showColumnMapping(headers, suggestions) {
  const section = document.getElementById('columnMappingSection');
  const grid = document.getElementById('mappingGrid');
  section.style.display = '';
  const fields = [
    { key: 'ticket', label: 'Service Ticket', required: true },
    { key: 'query', label: 'Query Executed', required: true },
    { key: 'executed_by', label: 'Executed By', required: false },
    { key: 'date', label: 'Date', required: false },
    { key: 'status', label: 'Status', required: false },
    { key: 'notes', label: 'Notes', required: false },
  ];
  grid.innerHTML = fields.map(f => {
    const suggested = suggestions[f.key] || '';
    const options = headers.map(h =>
      `<option value="${esc(h)}" ${h === suggested ? 'selected' : ''}>${esc(h)}</option>`
    ).join('');
    return `<div class="mapping-row">
      <label>${f.label}${f.required ? '<span class="required-tag">*</span>' : ''}</label>
      <select id="map_${f.key}" class="${suggested ? 'mapped' : ''}">
        <option value="">-- Skip --</option>${options}
      </select>
    </div>`;
  }).join('');
}

function getColumnMapping() {
  const fields = ['ticket', 'query', 'executed_by', 'date', 'status', 'notes'];
  const mapping = {};
  fields.forEach(f => {
    const sel = document.getElementById('map_' + f);
    if (sel && sel.value) mapping[f] = sel.value;
  });
  return Object.keys(mapping).length > 0 ? mapping : null;
}

function setupImportExport() {
  const dropZone = document.getElementById('importDropZone');
  const fileInput = document.getElementById('importFile');
  const previewBtn = document.getElementById('previewImportBtn');
  const doImportBtn = document.getElementById('doImportBtn');

  dropZone.onclick = () => fileInput.click();
  dropZone.ondragover = e => { e.preventDefault(); dropZone.classList.add('dragover'); };
  dropZone.ondragleave = () => dropZone.classList.remove('dragover');
  dropZone.ondrop = e => {
    e.preventDefault(); dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length) { fileInput.files = e.dataTransfer.files; onFileSelected(); }
  };
  fileInput.onchange = onFileSelected;

  async function onFileSelected() {
    if (!fileInput.files.length) return;
    dropZone.classList.add('has-file');
    dropZone.querySelector('p').textContent = fileInput.files[0].name;
    previewBtn.disabled = false;
    doImportBtn.disabled = false;
    // Fetch headers for column mapping
    const fd = new FormData();
    fd.append('file', fileInput.files[0]);
    try {
      const res = await api('/api/import/headers', { method: 'POST', body: fd });
      if (!res) return;
      const d = await res.json();
      if (d.headers && d.headers.length > 0) {
        showColumnMapping(d.headers, d.suggestions || {});
      }
    } catch (e) { console.error('Header detection error:', e); }
  }

  previewBtn.onclick = async () => {
    if (!fileInput.files.length) return;
    const fd = new FormData();
    fd.append('file', fileInput.files[0]);
    try {
      const res = await api('/api/sync/preview', { method: 'POST', body: fd });
      if (!res) return;
      const d = await res.json();
      const preview = document.getElementById('importPreview');
      preview.style.display = '';
      preview.innerHTML = `<div class="preview-row"><span>Total rows:</span><strong>${d.total_rows || 0}</strong></div>
        <div class="preview-row"><span class="preview-new">New:</span><strong class="preview-new">${d.new_records || 0}</strong></div>
        <div class="preview-row"><span class="preview-dup">Duplicates:</span><strong class="preview-dup">${d.duplicates || 0}</strong></div>`;
    } catch (e) { toast('Preview error', 'error'); }
  };

  doImportBtn.onclick = async () => {
    if (!fileInput.files.length) return;
    const fd = new FormData();
    fd.append('file', fileInput.files[0]);
    fd.append('mode', document.querySelector('input[name="importMode"]:checked').value);
    const colMap = getColumnMapping();
    if (colMap) fd.append('column_mapping', JSON.stringify(colMap));
    doImportBtn.disabled = true;
    doImportBtn.textContent = 'Importing...';
    try {
      const res = await api('/api/import/excel', { method: 'POST', body: fd });
      if (!res) { doImportBtn.disabled = false; doImportBtn.textContent = 'Import'; return; }
      const d = await res.json();
      if (d.error) toast(d.error, 'error');
      else {
        toast(`Imported ${d.imported || 0} records, ${d.skipped || 0} skipped.`, 'success');
        loadCorrections();
        loadDashboard();
      }
    } catch (e) { toast('Import error', 'error'); }
    doImportBtn.disabled = false;
    doImportBtn.textContent = 'Import';
  };

  document.getElementById('downloadXlsxBtn').onclick = () => window.location = '/api/export/excel';
  document.getElementById('downloadCsvBtn2').onclick = () => window.location = '/api/export/csv';
  document.getElementById('exportCsvBtn').onclick = () => window.location = '/api/export/csv';
  document.getElementById('exportXlsBtn').onclick = () => window.location = '/api/export/excel';
}

// ─── APP CONFIG (Server + Excel Sync) ─────────────────────────────────────────

async function loadAppConfig() {
  if (!isAdmin) return;
  try {
    const res = await api('/api/app-config');
    if (!res || !res.ok) return;
    const cfg = await res.json();
    document.getElementById('serverHost').value = cfg.host || '0.0.0.0';
    document.getElementById('serverPort').value = cfg.port || 5000;
    document.getElementById('sharedExcelPath').value = cfg.shared_excel_path || '';
    document.getElementById('autoSyncExcel').checked = !!cfg.auto_sync_excel;
    // Update access URL display
    const port = cfg.port || 5000;
    document.getElementById('accessUrlDisplay').textContent = `http://<machine-ip>:${port}`;
  } catch (e) { console.error('Config load error:', e); }
}

function setupAppConfig() {
  // Server config save
  document.getElementById('saveServerConfigBtn').addEventListener('click', async () => {
    const host = document.getElementById('serverHost').value.trim();
    const port = parseInt(document.getElementById('serverPort').value) || 5000;
    const msgEl = document.getElementById('serverConfigMsg');
    try {
      const res = await api('/api/app-config', { method: 'POST', body: { host, port } });
      if (!res) return;
      const d = await res.json();
      msgEl.style.display = '';
      if (d.success) {
        msgEl.className = 'oracle-test-result success-msg';
        msgEl.textContent = d.message || 'Saved! Restart the server for changes to take effect.';
        toast(d.message || 'Server config saved.', 'success');
      } else {
        msgEl.className = 'oracle-test-result error-msg';
        msgEl.textContent = d.error || 'Save failed.';
      }
    } catch (e) { toast('Error saving config.', 'error'); }
  });

  // Shared Excel save
  document.getElementById('saveExcelSyncBtn').addEventListener('click', async () => {
    const path = document.getElementById('sharedExcelPath').value.trim();
    const autoSync = document.getElementById('autoSyncExcel').checked;
    const msgEl = document.getElementById('excelSyncMsg');
    try {
      const res = await api('/api/app-config', { method: 'POST', body: { shared_excel_path: path, auto_sync_excel: autoSync } });
      if (!res) return;
      const d = await res.json();
      msgEl.style.display = '';
      if (d.success) {
        msgEl.className = 'oracle-test-result success-msg';
        msgEl.textContent = 'Excel sync settings saved.' + (autoSync ? ' Auto-sync is ON.' : '');
        toast('Excel sync settings saved.', 'success');
      } else {
        msgEl.className = 'oracle-test-result error-msg';
        msgEl.textContent = d.error || 'Save failed.';
      }
    } catch (e) { toast('Error saving settings.', 'error'); }
  });

  // Sync now
  document.getElementById('syncNowBtn').addEventListener('click', async () => {
    const btn = document.getElementById('syncNowBtn');
    const msgEl = document.getElementById('excelSyncMsg');
    btn.disabled = true; btn.textContent = 'Syncing...';
    try {
      const res = await api('/api/shared-excel/sync', { method: 'POST' });
      if (!res) { btn.disabled = false; btn.textContent = 'Sync Now'; return; }
      const d = await res.json();
      msgEl.style.display = '';
      if (d.success) {
        msgEl.className = 'oracle-test-result success-msg';
        msgEl.textContent = d.message;
        toast('Sync complete!', 'success');
      } else {
        msgEl.className = 'oracle-test-result error-msg';
        msgEl.textContent = d.error || 'Sync failed.';
        toast(d.error || 'Sync failed.', 'error');
      }
    } catch (e) { toast('Sync error.', 'error'); }
    btn.disabled = false; btn.textContent = 'Sync Now';
  });

  // Import from shared excel
  document.getElementById('importFromSharedBtn').addEventListener('click', async () => {
    const btn = document.getElementById('importFromSharedBtn');
    const msgEl = document.getElementById('excelSyncMsg');
    btn.disabled = true; btn.textContent = 'Importing...';
    try {
      const res = await api('/api/shared-excel/import', { method: 'POST' });
      if (!res) { btn.disabled = false; btn.textContent = 'Import from Shared Excel'; return; }
      const d = await res.json();
      msgEl.style.display = '';
      if (d.error) {
        msgEl.className = 'oracle-test-result error-msg';
        msgEl.textContent = d.error;
        toast(d.error, 'error');
      } else {
        msgEl.className = 'oracle-test-result success-msg';
        msgEl.textContent = `Imported ${d.imported || 0}, skipped ${d.skipped || 0}.`;
        toast(`Imported ${d.imported || 0} records from shared Excel.`, 'success');
        loadCorrections();
        loadDashboard();
      }
    } catch (e) { toast('Import error.', 'error'); }
    btn.disabled = false; btn.textContent = 'Import from Shared Excel';
  });

  // Oracle: Test Connection
  document.getElementById('testOracleBtn').addEventListener('click', async () => {
    const cfg = {
      host: document.getElementById('oracleHost').value.trim(),
      port: parseInt(document.getElementById('oraclePort').value) || 1521,
      service_name: document.getElementById('oracleService').value.trim(),
      service_type: document.getElementById('oracleServiceType').value,
      username: document.getElementById('oracleUser').value.trim(),
      password: document.getElementById('oraclePass').value
    };
    if (!cfg.host || !cfg.service_name || !cfg.username) { toast('Fill in all Oracle fields.', 'error'); return; }
    const resultEl = document.getElementById('oracleTestResult');
    resultEl.style.display = '';
    resultEl.textContent = 'Testing...';
    resultEl.className = 'oracle-test-result';
    try {
      const res = await api('/api/db/test-oracle', { method: 'POST', body: cfg });
      if (!res) return;
      const d = await res.json();
      if (d.success) {
        resultEl.className = 'oracle-test-result success-msg';
        resultEl.textContent = 'Connection successful! You can now migrate.';
        document.getElementById('migrateOracleBtn').disabled = false;
        // Save config
        await api('/api/db/config', { method: 'POST', body: cfg });
      } else {
        resultEl.className = 'oracle-test-result error-msg';
        resultEl.textContent = d.error || 'Connection failed.';
      }
    } catch (e) { resultEl.className = 'oracle-test-result error-msg'; resultEl.textContent = 'Test error.'; }
  });

  // Oracle: Migrate
  document.getElementById('migrateOracleBtn').addEventListener('click', async () => {
    if (!confirm('Migrate all data to Oracle DB? This will switch the active database.')) return;
    const btn = document.getElementById('migrateOracleBtn');
    btn.disabled = true; btn.textContent = 'Migrating...';
    try {
      const res = await api('/api/db/migrate-to-oracle', { method: 'POST' });
      if (!res) { btn.disabled = false; btn.textContent = 'Migrate to Oracle'; return; }
      const d = await res.json();
      if (d.success) {
        toast('Migration to Oracle complete!', 'success');
        document.getElementById('dbTypeDisplay').textContent = 'Oracle';
      } else {
        toast(d.error || 'Migration failed.', 'error');
      }
    } catch (e) { toast('Migration error.', 'error'); }
    btn.disabled = false; btn.textContent = 'Migrate to Oracle';
  });

  // CX Fetch
  document.getElementById('cxFetchBtn').addEventListener('click', async () => {
    const ticket = document.getElementById('ticketInput').value.trim();
    if (!ticket) { toast('Enter a ticket number first.', 'error'); return; }
    try {
      const res = await api('/api/cx/ticket/' + encodeURIComponent(ticket));
      if (!res) return;
      const d = await res.json();
      if (d.configured === false) {
        toast(d.message || 'Oracle CX not configured.', 'info');
      } else if (d.data) {
        toast('CX data loaded!', 'success');
      }
    } catch (e) { toast('CX fetch error.', 'error'); }
  });
}

// ─── MODALS ───────────────────────────────────────────────────────────────────

function openModal(id) {
  document.getElementById(id).classList.add('open');
}

function closeAllModals() {
  document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('open'));
}

// ─── TOAST ────────────────────────────────────────────────────────────────────

function toast(msg, type = 'info') {
  const c = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  const iconMap = {
    success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
    error: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
  };
  t.innerHTML = `<span class="toast-icon">${iconMap[type] || iconMap.info}</span><span class="toast-msg">${msg}</span>`;
  c.appendChild(t);
  setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 300); }, 3500);
}

// ─── HELPERS ──────────────────────────────────────────────────────────────────

function esc(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// ─── GLOBAL SEARCH ────────────────────────────────────────────────────────────

function setupGlobalSearch() {
  let timer;
  const input = document.getElementById('globalSearch');
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const q = input.value.trim();
      if (q.length >= 2) {
        document.getElementById('searchInput').value = q;
        switchView('search');
        doSearch();
      }
    }, 400);
  });
}

// ─── SORTING ──────────────────────────────────────────────────────────────────

function setupSorting() {
  document.querySelectorAll('.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (sortCol === col) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
      else { sortCol = col; sortDir = 'asc'; }
      document.querySelectorAll('.sortable').forEach(t => t.classList.remove('asc', 'desc'));
      th.classList.add(sortDir);
      loadCorrections();
    });
  });
}

// ─── INIT ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  // Date display
  const now = new Date();
  document.getElementById('topbarDate').textContent = now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });

  // Login form
  document.getElementById('loginForm').addEventListener('submit', doLogin);

  // Logout
  document.getElementById('logoutBtn').addEventListener('click', doLogout);

  // Navigation
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', e => {
      e.preventDefault();
      switchView(item.dataset.view);
    });
  });

  // Sidebar toggle (FIXED — larger button with clear visibility)
  document.getElementById('sidebarToggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('collapsed');
  });

  // Mobile menu
  document.getElementById('mobileMenuBtn').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('mobile-open');
  });

  // Correction form
  document.getElementById('correctionForm').addEventListener('submit', handleSubmit);
  document.getElementById('quickAddBtn').addEventListener('click', () => { resetForm(); switchView('add'); });
  document.getElementById('cancelFormBtn').addEventListener('click', () => { resetForm(); switchView('corrections'); });
  document.getElementById('clearQueryBtn').addEventListener('click', () => { document.getElementById('queryInput').value = ''; });

  // Filters
  ['tableSearch', 'filterExecuted', 'filterStatus', 'filterDateFrom', 'filterDateTo'].forEach(id => {
    const el = document.getElementById(id);
    el.addEventListener(id === 'tableSearch' ? 'input' : 'change', () => { currentPage = 1; loadCorrections(); });
  });
  document.getElementById('clearFilters').addEventListener('click', () => {
    document.getElementById('tableSearch').value = '';
    document.getElementById('filterExecuted').value = '';
    document.getElementById('filterStatus').value = '';
    document.getElementById('filterDateFrom').value = '';
    document.getElementById('filterDateTo').value = '';
    currentPage = 1;
    loadCorrections();
  });

  // Search
  document.getElementById('searchBtn').addEventListener('click', doSearch);
  document.getElementById('searchInput').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
  document.querySelectorAll('.search-chip').forEach(c => {
    c.addEventListener('click', () => { document.getElementById('searchInput').value = c.dataset.q; doSearch(); });
  });
  document.getElementById('clearSearchFilters').addEventListener('click', () => {
    document.getElementById('searchFilterExecutor').value = '';
    document.getElementById('searchFilterStatus').value = '';
    document.getElementById('searchFilterDateFrom').value = '';
    document.getElementById('searchFilterDateTo').value = '';
  });

  // Modals
  document.getElementById('closeViewModal').addEventListener('click', closeAllModals);
  document.getElementById('closeViewModal2').addEventListener('click', closeAllModals);
  document.getElementById('closeDeleteModal').addEventListener('click', closeAllModals);
  document.getElementById('cancelDeleteBtn').addEventListener('click', closeAllModals);
  document.getElementById('confirmDeleteBtn').addEventListener('click', confirmDelete);
  document.getElementById('copyQueryBtn').addEventListener('click', () => {
    const txt = document.getElementById('modalQuery').textContent;
    navigator.clipboard.writeText(txt).then(() => {
      const btn = document.getElementById('copyQueryBtn');
      btn.classList.add('copied'); btn.innerHTML = 'Copied!';
      setTimeout(() => { btn.classList.remove('copied'); btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy'; }, 2000);
    });
  });

  // Backup modal
  document.getElementById('createBackupBtn').addEventListener('click', () => openModal('backupModal'));
  document.getElementById('closeBackupModal').addEventListener('click', closeAllModals);
  document.getElementById('cancelBackupModal').addEventListener('click', closeAllModals);
  document.getElementById('confirmBackupBtn').addEventListener('click', createBackup);

  // User modal
  document.getElementById('addUserBtn').addEventListener('click', openAddUser);
  document.getElementById('closeUserModal').addEventListener('click', closeAllModals);
  document.getElementById('cancelUserModal').addEventListener('click', closeAllModals);
  document.getElementById('saveUserBtn').addEventListener('click', saveUser);

  // Reset password modal
  document.getElementById('closeResetPwModal').addEventListener('click', closeAllModals);
  document.getElementById('cancelResetPw').addEventListener('click', closeAllModals);
  document.getElementById('confirmResetPw').addEventListener('click', doResetPw);

  // Change own password
  document.getElementById('changePwBtn').addEventListener('click', doChangePassword);

  // Theme
  document.querySelectorAll('.theme-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      if (btn.dataset.theme === 'light') document.body.classList.add('theme-light');
      else document.body.classList.remove('theme-light');
      localStorage.setItem('bcp-theme', btn.dataset.theme);
    });
  });
  // Restore theme
  const savedTheme = localStorage.getItem('bcp-theme');
  if (savedTheme === 'light') {
    document.body.classList.add('theme-light');
    document.getElementById('themeDark').classList.remove('active');
    document.getElementById('themeLight').classList.add('active');
  }

  // Escape closes modals
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAllModals(); });

  // Click outside modal
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => { if (e.target === overlay) closeAllModals(); });
  });

  // Setup
  setupSorting();
  setupImportExport();
  setupGlobalSearch();
  setupAppConfig();

  // Check auth on load
  checkAuth();
});
