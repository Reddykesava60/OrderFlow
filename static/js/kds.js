function kds() {
  return {
    tab: 'kitchen',
    staffFilters: [],
    selectedFilter: 'all',
    kitchen: [],
    preparing: [],
    payments: [],
    allOrders: [],
    counts: { kitchen: 0, preparing: 0, payments: 0, all_orders: 0 },
    cashTimeoutMinutes: 10,
    loaded: false,
    online: true,
    failCount: 0,
    newOrderBanner: false,
    knownOrderIds: new Set(),
    canComplete: false,
    canCollect: false,
    canViewAll: false,
    canBulkUpdate: false,
    pollTimer: null,
    nowTickTimer: null,
    nowMs: Date.now(),
    toasts: [],
    toastCounter: 0,
    successStates: {},
    pendingActions: {},
    ws: null,
    reconnectTimer: null,

    init() {
      this.debouncedPoll = this.debounce(() => {
        setTimeout(() => this.pollImpl(), Math.random() * 500);
      }, 3000);
      this.poll = () => this.debouncedPoll();
      
      this.pollImpl(); // Initial load
      this.nowTickTimer = setInterval(() => { this.nowMs = Date.now(); }, 1000);
      this.connectWebSocket();
      
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
          this.poll();
          if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.connectWebSocket();
          }
        }
      });
    },

    connectWebSocket() {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = protocol + '//' + window.location.host + '/ws/kds/';
      
      if (this.ws) {
        this.ws.close();
      }
      
      this.ws = new WebSocket(wsUrl);
      
      this.ws.onopen = () => {
        console.log('KDS WebSocket connected');
        this.online = true;
      };
      
      this.ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.action === 'refresh') {
          this.poll();
        }
      };
      
      this.ws.onclose = () => {
        console.log('KDS WebSocket disconnected');
        this.online = false;
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(() => {
          if (document.visibilityState === 'visible') {
            this.connectWebSocket();
          }
        }, 3000);
      };
      
      this.ws.onerror = (err) => {
        console.error('KDS WebSocket error', err);
        this.ws.close();
      };
    },

    debounce(func, wait) {
      let timeout;
      return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => {
          func.apply(this, args);
        }, wait);
      };
    },

    showToast(msg, type) {
      type = type || 'error';
      const id = ++this.toastCounter;
      const toast = { id, msg, type, visible: true };
      this.toasts.push(toast);
      // Cap max visible toasts at 5 to prevent stacking during rush
      if (this.toasts.length > 5) {
        this.toasts.shift();
      }
      const duration = type === 'success' ? 2500 : 4000;
      setTimeout(() => {
        const t = this.toasts.find(x => x.id === id);
        if (t) t.visible = false;
        // Remove from array after leave transition completes
        setTimeout(() => {
          this.toasts = this.toasts.filter(x => x.id !== id);
        }, 300);
      }, duration);
    },

    flashSuccess(actionKey) {
      this.successStates[actionKey] = true;
      setTimeout(() => {
        delete this.successStates[actionKey];
      }, 800);
    },

    isLoading(actionKey) {
      return !!this.pendingActions[actionKey];
    },

    async withLoading(actionKey, fn) {
      if (this.pendingActions[actionKey]) return;
      this.pendingActions[actionKey] = true;
      try {
        await fn();
        // On success, we generally rely on poll() to rebuild the DOM.
        // Keeping it true prevents ghost clicks before the DOM removes the element.
      } catch (e) {
        this.pendingActions[actionKey] = false;
        throw e;
      }
    },

    filterItemIds() {
      const activeFilter = this.staffFilters.find((filter) => filter.id === this.selectedFilter);
      return new Set((activeFilter && activeFilter.item_ids) ? activeFilter.item_ids : []);
    },

    filteredOrders(orders) {
      const activeFilterItems = this.filterItemIds();
      return orders
        .filter((order) => (
          this.selectedFilter === 'all'
          || order.menu_item_ids.some((itemId) => activeFilterItems.has(itemId))
        ))
        .map((order) => ({
          ...order,
          visible_work_units: this.selectedFilter === 'all'
            ? (order.work_units || [])
            : (order.work_units || []).filter((unit) => unit.menu_item_id && activeFilterItems.has(unit.menu_item_id)),
        }))
        .filter((order) => order.visible_work_units.length > 0);
    },

    filteredAllOrders(orders) {
      const activeFilterItems = this.filterItemIds();
      return orders
        .map((order) => ({
          ...order,
          visible_items: this.selectedFilter === 'all'
            ? (order.items || []).map((item) => ({ ...item, visible_addons: item.addons || [] }))
            : (order.items || [])
                .filter((item) => item.menu_item_id && activeFilterItems.has(item.menu_item_id))
                .map((item) => ({ ...item, visible_addons: item.addons || [] })),
        }))
        .filter((order) => order.visible_items.length > 0);
    },

    async pollImpl() {
      try {
        const res = await fetch(window.KDS_CONFIG.pollUrl, { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Request failed');
        const data = await res.json();

        const incoming = [
          ...data.kitchen.map((o) => o.id),
          ...data.preparing.map((o) => o.id),
          ...data.payments.map((o) => o.id),
          ...(data.all_orders || []).map((o) => o.id),
        ];
        const firstLoad = this.knownOrderIds.size === 0 && !this.loaded;
        let hasNew = false;
        for (const id of incoming) {
          if (!this.knownOrderIds.has(id)) {
            if (!firstLoad) hasNew = true;
            this.knownOrderIds.add(id);
          }
        }

        if (hasNew) {
          this.newOrderBanner = true;
          setTimeout(() => { this.newOrderBanner = false; }, 3500);
        }

        this.staffFilters = data.staff_filters || [];
        this.cashTimeoutMinutes = Number(data.cash_timeout_minutes || 10);
        if (this.selectedFilter !== 'all' && !this.staffFilters.some((filter) => filter.id === this.selectedFilter)) {
          this.selectedFilter = 'all';
        }

        this.kitchen = data.kitchen || [];
        this.preparing = data.preparing || [];
        // Filter out CANCELLED/timed-out orders from payments immediately
        this.payments = (data.payments || []).filter((o) => {
          const expiresAt = new Date(o.created_at).getTime() + (Number(data.cash_timeout_minutes || 10) * 60 * 1000);
          return expiresAt > Date.now();
        });
        this.allOrders = data.all_orders || [];
        this.counts = data.tab_counts || this.counts;
        this.canComplete = !!data.permissions.can_complete;
        this.canCollect = !!data.permissions.can_collect;
        this.canViewAll = !!data.permissions.can_view_all;
        this.canBulkUpdate = !!data.permissions.can_bulk_update;

        if (!this.canCollect && this.tab === 'payments') this.tab = 'kitchen';
        if (!this.canViewAll && this.tab === 'all_orders') this.tab = 'kitchen';

        this.loaded = true;
        this.online = true;
        this.failCount = 0;
      } catch (error) {
        this.failCount += 1;
        if (this.failCount >= 2) this.online = false;
      }
    },

    async doPost(url) {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF, 'Content-Type': 'application/json' },
        credentials: 'same-origin',
      });
      const body = await res.text();
      if (!res.ok) {
        let message = 'Request failed (' + res.status + ')';
        try {
          const parsed = JSON.parse(body);
          message = parsed.message || parsed.error || message;
        } catch (error) {}
        throw new Error(message);
      }
      return JSON.parse(body);
    },

    startUrl(unit) {
      return unit.kind === 'addon'
        ? '/api/addon/' + unit.id + '/start-prep/'
        : '/api/item/' + unit.id + '/start-prep/';
    },

    completeUrl(unit) {
      return unit.kind === 'addon'
        ? '/api/addon/' + unit.id + '/complete/'
        : '/api/item/' + unit.id + '/complete/';
    },

    async startAll(orderId) {
      await this.withLoading('bulk-start-' + orderId, async () => {
        try {
          await this.doPost('/api/order/' + orderId + '/start-prep/');
          this.flashSuccess('bulk-start-' + orderId);
          this.showToast('Order moved to preparing', 'success');
          await this.poll();
        } catch (error) {
          this.showToast(error.message, 'error');
          throw error;
        }
      });
    },

    async completeAll(orderId) {
      await this.withLoading('bulk-done-' + orderId, async () => {
        try {
          await this.doPost('/api/order/' + orderId + '/complete-all/');
          this.flashSuccess('bulk-done-' + orderId);
          this.showToast('Order completed', 'success');
          await this.poll();
        } catch (error) {
          this.showToast(error.message, 'error');
          throw error;
        }
      });
    },

    async collectCash(orderId) {
      await this.withLoading('cash-' + orderId, async () => {
        try {
          await this.doPost('/api/cash/' + orderId + '/collect/');
          this.flashSuccess('cash-' + orderId);
          this.showToast('Cash collected', 'success');
          await this.poll();
        } catch (error) {
          this.showToast(error.message, 'error');
          throw error;
        }
      });
    },

    async startWork(unit) {
      const key = 'start-' + unit.kind + '-' + unit.id;
      await this.withLoading(key, async () => {
        try {
          await this.doPost(this.startUrl(unit));
          this.flashSuccess(key);
          this.showToast('Prep started', 'success');
          await this.poll();
        } catch (error) {
          this.showToast(error.message, 'error');
          throw error;
        }
      });
    },

    async completeWork(unit) {
      const key = 'done-' + unit.kind + '-' + unit.id;
      await this.withLoading(key, async () => {
        try {
          await this.doPost(this.completeUrl(unit));
          this.flashSuccess(key);
          this.showToast('Marked done', 'success');
          await this.poll();
        } catch (error) {
          this.showToast(error.message, 'error');
          throw error;
        }
      });
    },

    spiceIconCount(level) {
      const normalized = String(level || '').trim().toLowerCase();
      if (!normalized) return 0;
      if (normalized === 'mild' || normalized === 'low') return 1;
      if (normalized === 'medium') return 2;
      if (normalized === 'hot') return 3;
      return 0;
    },

    statusBadgeClass(status) {
      return {
        PENDING: 'bg-amber-50 text-amber-700',
        PREPARING: 'bg-brand-50 text-brand-700',
        PREP_STARTED: 'bg-brand-50 text-brand-700',
        COMPLETED: 'bg-emerald-50 text-emerald-700',
        UNPAID: 'bg-amber-50 text-amber-700',
        CANCELLED: 'bg-rose-50 text-rose-700',
      }[status] || 'bg-slate-100 text-slate-600';
    },

    paymentTimeMeta(order) {
      const expiresAt = new Date(order.created_at).getTime() + (this.cashTimeoutMinutes * 60 * 1000);
      const remainingMs = expiresAt - this.nowMs;
      if (remainingMs <= 0) return 'Timeout';
      const totalSeconds = Math.ceil(remainingMs / 1000);
      const mins = Math.floor(totalSeconds / 60);
      const secs = totalSeconds % 60;
      return 'Expires in ' + mins + 'm ' + String(secs).padStart(2, '0') + 's';
    },

    paymentTimeMetaClass(order) {
      const expiresAt = new Date(order.created_at).getTime() + (this.cashTimeoutMinutes * 60 * 1000);
      const remainingMs = expiresAt - this.nowMs;
      if (remainingMs <= 0) return 'text-rose-600';
      if (remainingMs <= 2 * 60 * 1000) return 'text-amber-600';
      return 'text-slate-400';
    },

    timeAgo(iso) {
      const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
      if (diff < 1) return 'Just now';
      if (diff === 1) return '1m ago';
      return diff + 'm ago';
    },
  };
}

// Navigation Transition Loader
document.addEventListener('DOMContentLoaded', () => {
  const loader = document.getElementById('global-page-loader');
  let isNavigating = false;

  document.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', (e) => {
      if (
        link.hostname === window.location.hostname &&
        !link.hash &&
        !link.target &&
        !link.hasAttribute('download') &&
        link.getAttribute('href') !== '#' &&
        !link.getAttribute('href').startsWith('javascript:')
      ) {
        if (isNavigating) {
          e.preventDefault();
          return;
        }
        isNavigating = true;
        loader.style.display = 'flex';
        requestAnimationFrame(() => {
          loader.classList.remove('opacity-0', 'pointer-events-none');
          loader.classList.add('opacity-100');
        });
      }
    });
  });

  window.addEventListener('pageshow', (e) => {
    if (e.persisted || isNavigating) {
      isNavigating = false;
      if (loader) {
        loader.classList.add('opacity-0', 'pointer-events-none');
        loader.classList.remove('opacity-100');
        setTimeout(() => { loader.style.display = 'none'; }, 200);
      }
    }
  });
});
