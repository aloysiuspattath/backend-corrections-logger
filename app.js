let currentUser = null;
let isAdmin = false;
let currentView = 'dashboard';
let socket = null;
let activityChart = null;

// Modals
const correctionModal = document.getElementById('correctionModal');
let editingId = null;

// Pagination state
let currentPage = 1;
let perPage = 20;

const App = {
  init() {
    this.bindEvents();
    this.checkAuth();
  },

  bindEvents() {
    document.getElementById('loginForm').addEventListener('submit', this.handleLogin.bind(this));
    document.getElementById('logoutBtn').addEventListener('click', this.handleLogout.bind(this));
    
    document.querySelectorAll('.nav-link').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        this.switchView(e.currentTarget.dataset.view);
      });
    });

    // Correction Modal
    document.getElementById('newCorrectionBtn').addEventListener('click', () => this.openCorrectionModal());
    document.querySelectorAll('.close-modal').forEach(btn => {
      btn.addEventListener('click', () => this.closeCorrectionModal());
    });
    document.getElementById('correctionForm').addEventListener('submit', this.saveCorrection.bind(this));

    // Filters
    document.getElementById('searchCorrections').addEventListener('input', this.debounce(() => { currentPage = 1; this.loadCorrections(); }, 500));
    document.getElementById('filterStatus').addEventListener('change', () => { currentPage = 1; this.loadCorrections(); });
    document.getElementById('exportBtn').addEventListener('click', this.exportCSV.bind(this));

    // Settings
    document.getElementById('passwordForm').addEventListener('submit', this.updatePassword.bind(this));
  },

  async api(endpoint, options = {}) {
    options.credentials = 'include';
    if (options.body && typeof options.body === 'object') {
      options.headers = { ...options.headers, 'Content-Type': 'application/json' };
      options.body = JSON.stringify(options.body);
    }
    const res = await fetch(endpoint, options);
    if (res.status === 401) {
      const data = await res.json().catch(() => ({}));
      if (data.auth_required || data.authenticated === false) {
        this.showLoginScreen();
        return null;
      }
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Request failed.' }));
      throw new Error(err.error || 'Server error');
    }
    return res;
  },

  async checkAuth() {
    try {
      const res = await this.api('/api/auth/me');
      if (res) {
        const data = await res.json();
        this.onLoginSuccess(data.user);
      }
    } catch (e) {
      this.showLoginScreen();
    }
  },

  async handleLogin(e) {
    e.preventDefault();
    const btn = document.getElementById('loginBtn');
    btn.textContent = 'Authenticating...';
    btn.disabled = true;

    try {
      const username = document.getElementById('loginUsername').value;
      const password = document.getElementById('loginPassword').value;
      
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      
      const data = await res.json();
      if (res.ok && data.authenticated) {
        this.onLoginSuccess(data.user);
        this.toast(`Welcome back, ${data.user.display_name}!`, 'success');
      } else {
        throw new Error(data.error || 'Invalid credentials');
      }
    } catch (err) {
      const errorEl = document.getElementById('loginError');
      errorEl.textContent = err.message;
      errorEl.style.display = 'block';
    } finally {
      btn.textContent = 'Sign In';
      btn.disabled = false;
    }
  },

  async handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST' });
    window.location.reload();
  },

  onLoginSuccess(user) {
    currentUser = user;
    isAdmin = user.role === 'admin';
    
    document.getElementById('userName').textContent = user.display_name;
    document.getElementById('userRole').textContent = isAdmin ? 'Administrator' : 'User';
    document.getElementById('userAvatar').textContent = user.display_name.charAt(0).toUpperCase();

    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('appWrapper').style.display = 'flex';
    
    if (isAdmin) {
      document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'flex');
    }

    this.initSocket();
    this.switchView('dashboard');
  },

  showLoginScreen() {
    document.getElementById('appWrapper').style.display = 'none';
    document.getElementById('loginScreen').style.display = 'flex';
  },

  switchView(viewName) {
    currentView = viewName;
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    document.getElementById(`view-${viewName}`).classList.add('active');
    
    document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active'));
    document.querySelector(`.nav-link[data-view="${viewName}"]`).classList.add('active');

    const titles = {
      'dashboard': 'Dashboard',
      'corrections': 'Corrections Database',
      'users': 'User Management',
      'settings': 'Settings'
    };
    document.getElementById('topbarTitle').textContent = titles[viewName];

    if (viewName === 'dashboard') this.loadDashboard();
    if (viewName === 'corrections') this.loadCorrections();
    if (viewName === 'users' && isAdmin) this.loadUsers();
  },

  async loadDashboard() {
    try {
      const [statsRes, recentRes, actRes] = await Promise.all([
        this.api('/api/stats'),
        this.api('/api/corrections?per_page=5&sort=date&dir=desc'),
        this.api('/api/activity?days=14')
      ]);

      if (statsRes) {
        const stats = await statsRes.json();
        this.animateCount('statTotal', stats.total);
        this.animateCount('statToday', stats.today);
        this.animateCount('statWeek', stats.week);
        this.animateCount('statMonth', stats.month);
      }

      if (recentRes) {
        const recent = await recentRes.json();
        this.renderRecentTable(recent.data || []);
      }

      if (actRes) {
        const activity = await actRes.json();
        this.renderChart(activity);
      }
    } catch (e) {
      console.error("Dashboard Load Error:", e);
      this.toast("Failed to load dashboard data", "error");
    }
  },

  async loadCorrections() {
    const search = document.getElementById('searchCorrections').value;
    const status = document.getElementById('filterStatus').value;
    
    try {
      const qs = new URLSearchParams({ page: currentPage, per_page: perPage, search, status, sort: 'date', dir: 'desc' });
      const res = await this.api(`/api/corrections?${qs}`);
      if (!res) return;
      
      const data = await res.json();
      this.renderCorrectionsTable(data.data || []);
      this.renderPagination(data.total, data.page, data.per_page);
    } catch (e) {
      console.error(e);
      this.toast("Failed to load corrections", "error");
    }
  },

  renderRecentTable(data) {
    const container = document.getElementById('recentList');
    if (data.length === 0) {
      container.innerHTML = '<div class="empty-state">No recent corrections found.</div>';
      return;
    }
    
    let html = `<table class="data-table">
      <thead><tr><th>Ticket</th><th>Executed By</th><th>Date</th><th>Status</th></tr></thead>
      <tbody>`;
    data.forEach(r => {
      html += `<tr>
        <td><strong>${this.escapeHTML(r.ticket)}</strong></td>
        <td>${this.escapeHTML(r.executed_by)}</td>
        <td>${r.date}</td>
        <td><span class="badge ${r.status.toLowerCase().replace(' ', '-')}">${r.status}</span></td>
      </tr>`;
    });
    html += `</tbody></table>`;
    container.innerHTML = html;
  },

  renderCorrectionsTable(data) {
    const container = document.getElementById('correctionsList');
    if (data.length === 0) {
      container.innerHTML = '<div class="empty-state">No corrections found matching your filters.</div>';
      return;
    }
    
    let html = `<table class="data-table">
      <thead><tr><th>Ticket</th><th>Executed By</th><th>Date</th><th>Status</th><th>Notes</th><th>Actions</th></tr></thead>
      <tbody>`;
    data.forEach(r => {
      html += `<tr>
        <td><strong>${this.escapeHTML(r.ticket)}</strong></td>
        <td>${this.escapeHTML(r.executed_by)}</td>
        <td>${r.date}</td>
        <td><span class="badge ${r.status.toLowerCase().replace(' ', '-')}">${r.status}</span></td>
        <td class="text-muted" style="max-width: 200px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${this.escapeHTML(r.notes || '-')}</td>
        <td>
          <button class="btn btn-icon btn-sm" onclick="App.editCorrection(${r.id})" title="Edit">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
          </button>
          ${isAdmin ? `<button class="btn btn-icon btn-sm text-danger" onclick="App.deleteCorrection(${r.id})" title="Delete">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          </button>` : ''}
        </td>
      </tr>`;
    });
    html += `</tbody></table>`;
    container.innerHTML = html;
  },

  renderPagination(total, page, limit) {
    const container = document.getElementById('paginationControls');
    const totalPages = Math.ceil(total / limit);
    if (totalPages <= 1) { container.innerHTML = ''; return; }

    let html = `<button class="page-btn" ${page === 1 ? 'disabled' : ''} onclick="App.goToPage(${page - 1})">Prev</button>`;
    for (let i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || (i >= page - 2 && i <= page + 2)) {
        html += `<button class="page-btn ${i === page ? 'active' : ''}" onclick="App.goToPage(${i})">${i}</button>`;
      } else if (i === page - 3 || i === page + 3) {
        html += `<span style="color:var(--text-muted)">...</span>`;
      }
    }
    html += `<button class="page-btn" ${page === totalPages ? 'disabled' : ''} onclick="App.goToPage(${page + 1})">Next</button>`;
    container.innerHTML = html;
  },

  goToPage(p) {
    currentPage = p;
    this.loadCorrections();
  },

  async editCorrection(id) {
    try {
      const res = await this.api(`/api/corrections/${id}`);
      if (!res) return;
      const data = await res.json();
      
      document.getElementById('editId').value = data.id;
      document.getElementById('ticketInput').value = data.ticket;
      document.getElementById('dateInput').value = data.date;
      document.getElementById('queryInput').value = data.query;
      document.getElementById('statusInput').value = data.status;
      document.getElementById('executedInput').value = data.executed_by;
      document.getElementById('notesInput').value = data.notes || '';
      
      document.getElementById('modalTitle').textContent = 'Edit Correction';
      correctionModal.classList.add('active');
    } catch (e) {
      this.toast(e.message, 'error');
    }
  },

  async deleteCorrection(id) {
    if (!confirm('Are you sure you want to delete this correction permanently?')) return;
    try {
      await this.api(`/api/corrections/${id}`, { method: 'DELETE' });
      this.toast('Correction deleted', 'success');
      if (currentView === 'corrections') this.loadCorrections();
      if (currentView === 'dashboard') this.loadDashboard();
    } catch (e) {
      this.toast(e.message, 'error');
    }
  },

  openCorrectionModal() {
    document.getElementById('correctionForm').reset();
    document.getElementById('editId').value = '';
    document.getElementById('dateInput').value = new Date().toISOString().split('T')[0];
    document.getElementById('executedInput').value = currentUser.display_name;
    document.getElementById('statusInput').value = 'Completed';
    document.getElementById('modalTitle').textContent = 'New Correction';
    correctionModal.classList.add('active');
  },

  closeCorrectionModal() {
    correctionModal.classList.remove('active');
  },

  async saveCorrection(e) {
    e.preventDefault();
    const id = document.getElementById('editId').value;
    const payload = {
      ticket: document.getElementById('ticketInput').value,
      date: document.getElementById('dateInput').value,
      query: document.getElementById('queryInput').value,
      status: document.getElementById('statusInput').value,
      executed_by: document.getElementById('executedInput').value,
      notes: document.getElementById('notesInput').value
    };

    try {
      const method = id ? 'PUT' : 'POST';
      const url = id ? `/api/corrections/${id}` : '/api/corrections';
      await this.api(url, { method, body: payload });
      this.closeCorrectionModal();
      this.toast(`Correction ${id ? 'updated' : 'added'} successfully!`, 'success');
      
      if (currentView === 'corrections') this.loadCorrections();
      if (currentView === 'dashboard') this.loadDashboard();
    } catch (err) {
      this.toast(err.message, 'error');
    }
  },

  exportCSV() {
    window.location.href = '/api/export/csv';
  },

  async updatePassword(e) {
    e.preventDefault();
    const current_password = document.getElementById('currentPassword').value;
    const new_password = document.getElementById('newPassword').value;
    
    try {
      await this.api('/api/auth/password', {
        method: 'PUT',
        body: { current_password, new_password }
      });
      this.toast('Password updated successfully', 'success');
      document.getElementById('passwordForm').reset();
    } catch (err) {
      this.toast(err.message, 'error');
    }
  },

  renderChart(data) {
    const ctx = document.getElementById('activityChart');
    if (!ctx || !window.Chart) return;
    
    if (activityChart) activityChart.destroy();
    
    activityChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.map(d => d.date.split('-').slice(1).join('/')),
        datasets: [{
          label: 'Corrections',
          data: data.map(d => d.count),
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59, 130, 246, 0.2)',
          borderWidth: 2,
          tension: 0.4,
          fill: true,
          pointBackgroundColor: '#1e293b',
          pointBorderColor: '#3b82f6',
          pointBorderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
          y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8', stepSize: 1 } }
        }
      }
    });
  },

  animateCount(id, target) {
    const el = document.getElementById(id);
    if (!el) return;
    const start = parseInt(el.textContent) || 0;
    if (start === target) { el.textContent = target; return; }
    
    const dur = 800;
    const st = performance.now();
    
    const step = ts => {
      const p = Math.min((ts - st) / dur, 1);
      el.textContent = Math.floor(start + (target - start) * p);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  },

  toast(msg, type = 'info') {
    const container = document.getElementById('toastContainer');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `
      <div class="toast-icon">
        ${type === 'success' ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>' : 
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'}
      </div>
      <div>${this.escapeHTML(msg)}</div>
    `;
    container.appendChild(el);
    setTimeout(() => {
      el.classList.add('fade-out');
      setTimeout(() => el.remove(), 300);
    }, 4000);
  },

  escapeHTML(str) {
    if (!str) return '';
    return str.toString().replace(/[&<>'"]/g, tag => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[tag] || tag));
  },

  debounce(func, wait) {
    let timeout;
    return function(...args) {
      clearTimeout(timeout);
      timeout = setTimeout(() => func.apply(this, args), wait);
    };
  },

  initSocket() {
    if (socket) return;
    socket = io({ transports: ['websocket', 'polling'] });
    
    socket.on('connect', () => {
      document.getElementById('liveText').textContent = 'Live Sync Active';
      document.getElementById('livePulse').style.background = 'var(--success)';
      document.getElementById('livePulse').style.boxShadow = '0 0 0 0 rgba(16, 185, 129, 0.4)';
      
      // Auto-refresh current view to ensure no stale data
      if (currentView === 'dashboard') this.loadDashboard();
      if (currentView === 'corrections') this.loadCorrections();
    });

    socket.on('disconnect', () => {
      document.getElementById('liveText').textContent = 'Disconnected';
      document.getElementById('livePulse').style.background = 'var(--danger)';
      document.getElementById('livePulse').style.boxShadow = 'none';
    });

    socket.on('correction_added', () => {
      if (currentView === 'dashboard') this.loadDashboard();
      if (currentView === 'corrections') this.loadCorrections();
    });
    socket.on('correction_updated', () => {
      if (currentView === 'dashboard') this.loadDashboard();
      if (currentView === 'corrections') this.loadCorrections();
    });
    socket.on('correction_deleted', () => {
      if (currentView === 'dashboard') this.loadDashboard();
      if (currentView === 'corrections') this.loadCorrections();
    });
  }
};

document.addEventListener('DOMContentLoaded', () => App.init());
