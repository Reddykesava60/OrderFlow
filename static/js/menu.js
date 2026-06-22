    function dineflow() {
      return {
        cart:          [],
        activeItem:    null,
        selection:     { dining: 'DINE_IN', spice: 'MILD', qty: 1, addons: {} },
        showCart:      false,
        customerName:  '',
        tableNumber:   '',
        customerSerial: '',
        customerPin:   '',
        paymentMethod: 'CASH',
        consentGiven:  false,
        placing:       false,
        checkoutError: '',
        idempotencyKey: null,

        get cartCount() { return this.cart.reduce((s, l) => s + l.qty, 0); },

        loadCart() {
          try {
            this.cart = JSON.parse(sessionStorage.getItem('df_cart') || '[]');
          } catch(e) { this.cart = []; }

          // Back-button closes overlays instead of navigating away
          window.addEventListener('popstate', (e) => {
            if (this.showCart) {
              this.showCart = false;
              return;
            }
            if (this.activeItem) {
              this.activeItem = null;
              return;
            }
          });

          // Clean up stale history on fresh page load (e.g. after checkout redirect)
          if (history.state && history.state.dfOverlay) {
            history.replaceState(null, '');
          }
        },
        saveCart() {
          sessionStorage.setItem('df_cart', JSON.stringify(this.cart));
        },

        // ── Overlay history management ──
        openCart() {
          this.showCart = true;
          history.pushState({ dfOverlay: 'cart' }, '');
        },
        closeCart() {
          if (this.placing) return; // Don't close during payment
          this.showCart = false;
          // Pop the history entry we pushed (if it's ours)
          if (history.state && history.state.dfOverlay === 'cart') {
            history.back();
          }
        },
        openCustomization(id) {
          const item = MENU_DATA[id];
          if (!item) return;
          this.activeItem = item;
          this.selection = { dining: 'DINE_IN', spice: 'MILD', qty: 1, addons: {} };
          history.pushState({ dfOverlay: 'customize' }, '');
        },
        closeCustomization() {
          this.activeItem = null;
          if (history.state && history.state.dfOverlay === 'customize') {
            history.back();
          }
        },
        addToCartAndClose() {
          this.addToCart();
          // Pop the customization history entry
          if (history.state && history.state.dfOverlay === 'customize') {
            history.back();
          }
        },

        openItem(id) {
          this.openCustomization(id);
        },

        incAddon(addon) {
          const cur = this.selection.addons[addon.id] || 0;
          if (cur < addon.max_qty) this.selection.addons[addon.id] = cur + 1;
        },
        decAddon(addon) {
          const cur = this.selection.addons[addon.id] || 0;
          if (cur > 0) this.selection.addons[addon.id] = cur - 1;
        },

        itemSubtotal() {
          if (!this.activeItem) return 0;
          let total = this.activeItem.base_price;
          if (this.selection.dining === 'PARCEL') total += this.activeItem.parcel_surcharge;
          for (const [id, qty] of Object.entries(this.selection.addons)) {
            const addon = this.activeItem.addons.find(a => a.id === id);
            if (addon) total += addon.price * qty;
          }
          return (total * this.selection.qty).toFixed(2);
        },

        addToCart() {
          if (!this.activeItem) return;
          const addons = Object.entries(this.selection.addons)
            .filter(([,q]) => q > 0)
            .map(([id, qty]) => {
              const a = this.activeItem.addons.find(x => x.id === id);
              return { addon_id: id, name: a.name, price: a.price, quantity: qty };
            });
          this.cart.push({
            item_id:   this.activeItem.id,
            name:      this.activeItem.name,
            base_price:      this.activeItem.base_price,
            parcel_surcharge:this.activeItem.parcel_surcharge,
            qty:       this.selection.qty,
            dining:    this.selection.dining,
            spice:     this.activeItem.spice_configurable ? this.selection.spice : '',
            addons,
          });
          this.saveCart();
          this.activeItem = null;
        },

        removeFromCart(idx) {
          this.cart.splice(idx, 1);
          this.saveCart();
        },

        lineTotal(line) {
          let t = line.base_price;
          if (line.dining === 'PARCEL') t += line.parcel_surcharge;
          for (const a of line.addons) t += a.price * a.quantity;
          return (t * line.qty).toFixed(2);
        },
        lineDetail(line) {
          const parts = [];
          if (line.dining === 'PARCEL') parts.push('Parcel');
          if (line.spice) parts.push(line.spice.charAt(0) + line.spice.slice(1).toLowerCase());
          for (const a of line.addons) parts.push(a.name + ' ×' + a.quantity);
          return parts.join(' · ');
        },
        cartTotal() {
          return this.cart.reduce((s, l) => s + parseFloat(this.lineTotal(l)), 0).toFixed(2);
        },

        async placeOrder() {
          if (this.placing) return;
          this.checkoutError = '';
          this.placing = true;
          
          if (!this.idempotencyKey) {
            this.idempotencyKey = crypto.randomUUID();
          }
          
          const payload = {
            customer_name:  this.customerName.trim(),
            table_number:   this.tableNumber.trim(),
            payment_method: this.paymentMethod,
            customer_serial: this.customerSerial,
            customer_pin:    this.customerPin,
            consent_given:  this.consentGiven,
            cart: this.cart.map(l => ({
              item_id:       l.item_id,
              quantity:      l.qty,
              dining_option: l.dining,
              spice_level:   l.spice,
              addons:        l.addons.map(a => ({ addon_id: a.addon_id, quantity: a.quantity })),
            })),
            idempotency_key: this.idempotencyKey,
          };
          try {
            const res = await fetch(CHECKOUT_URL, {
              method:  'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken':  CSRF_TOKEN,
              },
              body: JSON.stringify(payload),
            });
            const data = await res.json();
            if (data.status === 'ok') {
              sessionStorage.removeItem('df_cart');
              // Clean history so back button doesn't return to stale cart
              history.replaceState(null, '');
              window.location.href = data.redirect;
            } else if (data.status === 'razorpay_pending') {
              const options = {
                key:         data.razorpay_key_id,
                amount:      data.total_paise,
                currency:    'INR',
                order_id:    data.razorpay_order_id,
                name:        '' + window.DINEFLOW_CONFIG.restaurantName + '',
                description: 'Order #' + data.order_number,
                prefill: {
                  name: this.customerName.trim(),
                },
                theme: { color: '#1a3c5e' },
                handler: async (response) => {
                  sessionStorage.removeItem('df_cart');
                  history.replaceState(null, '');
                  try {
                    const verifyRes = await fetch(RAZORPAY_VERIFY_URL, {
                      method: 'POST',
                      headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': CSRF_TOKEN,
                      },
                      body: JSON.stringify({
                        razorpay_order_id: response.razorpay_order_id,
                        razorpay_payment_id: response.razorpay_payment_id,
                        razorpay_signature: response.razorpay_signature,
                      }),
                    });
                    if (!verifyRes.ok) {
                      console.warn('[DineFlow] Payment verify response:', verifyRes.status, await verifyRes.text().catch(() => ''));
                    }
                  } catch (e) {
                    // Log the error for debugging — the receipt page will show
                    // payment status regardless, and the webhook/reconciliation
                    // cron will confirm the payment asynchronously.
                    console.error('[DineFlow] Payment verification failed:', e);
                  }
                  window.location.href = data.receipt_url + '?upi=1';
                }
              };
              const rzp = new Razorpay(options);
              rzp.open();
            } else {
              this.checkoutError = data.message || 'Something went wrong.';
              this.placing = false;
              this.idempotencyKey = null;
            }
          } catch(e) {
            this.checkoutError = 'Network error. Please try again.';
            this.placing = false;
            this.idempotencyKey = null;
          }
        },
      };
    }
