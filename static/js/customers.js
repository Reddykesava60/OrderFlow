function customerDashboard() {
    return {
        customers: [],
        errorMsg: '',
        successMsg: '',
        
        createModal: false,
        paymentModal: false,
        editModal: false,
        pinModal: false,
        ledgerModal: false,
        
        selectedCustomer: null,
        ledgerEntries: [],
        
        form: { name: '', phone: '', pin: '', credit_limit: '' },
        paymentForm: { amount: '', method: 'Cash' },
        editForm: { is_post_payment_enabled: true, is_blocked: false, credit_limit: '' },
        pinForm: { new_pin: '' },

        init() {
            this.fetchCustomers();
        },
        
        async fetchCustomers() {
            try {
                const res = await fetch(window.CUSTOMERS_CONFIG.urls.api);
                const data = await res.json();
                this.customers = data.customers;
            } catch (e) {
                this.errorMsg = 'Failed to load customers.';
            }
        },
        
        openCreateModal() {
            this.form = { name: '', phone: '', pin: '', credit_limit: '' };
            this.createModal = true;
        },
        
        async submitCreate() {
            const formData = new FormData();
            formData.append('name', this.form.name);
            formData.append('phone', this.form.phone);
            formData.append('pin', this.form.pin);
            if (this.form.credit_limit) formData.append('credit_limit', this.form.credit_limit);
            formData.append('csrfmiddlewaretoken', window.CUSTOMERS_CONFIG.csrfToken);
            
            try {
                const res = await fetch(window.CUSTOMERS_CONFIG.urls.add, { method: 'POST', body: formData });
                const data = await res.json();
                if (data.success) {
                    this.createModal = false;
                    this.successMsg = 'Customer created!';
                    this.fetchCustomers();
                } else {
                    this.errorMsg = data.error;
                }
            } catch (e) {
                this.errorMsg = 'Request failed.';
            }
        },

        openPaymentModal(c) {
            this.selectedCustomer = c;
            this.paymentForm = { amount: '', method: 'Cash' };
            this.paymentModal = true;
        },
        
        async submitPayment() {
            const formData = new FormData();
            formData.append('amount', this.paymentForm.amount);
            formData.append('payment_method', this.paymentForm.method);
            formData.append('csrfmiddlewaretoken', window.CUSTOMERS_CONFIG.csrfToken);
            
            try {
                const url = window.CUSTOMERS_CONFIG.urls.payment.replace('00000000-0000-0000-0000-000000000000', this.selectedCustomer.id);
                const res = await fetch(url, { method: 'POST', body: formData });
                const data = await res.json();
                if (data.success) {
                    this.paymentModal = false;
                    this.successMsg = 'Payment recorded!';
                    this.fetchCustomers();
                } else {
                    this.errorMsg = data.error;
                }
            } catch (e) {
                this.errorMsg = 'Request failed.';
            }
        },
        
        openEditModal(c) {
            this.selectedCustomer = c;
            this.editForm = {
                is_post_payment_enabled: c.is_post_payment_enabled,
                is_blocked: c.is_blocked,
                credit_limit: c.credit_limit !== null ? c.credit_limit : ''
            };
            this.editModal = true;
        },
        
        async submitEdit() {
            const formData = new FormData();
            formData.append('is_post_payment_enabled', this.editForm.is_post_payment_enabled);
            formData.append('is_blocked', this.editForm.is_blocked);
            if (this.editForm.credit_limit !== '') {
                formData.append('credit_limit', this.editForm.credit_limit);
            }
            formData.append('csrfmiddlewaretoken', window.CUSTOMERS_CONFIG.csrfToken);
            
            try {
                const url = window.CUSTOMERS_CONFIG.urls.edit.replace('00000000-0000-0000-0000-000000000000', this.selectedCustomer.id);
                const res = await fetch(url, { method: 'POST', body: formData });
                const data = await res.json();
                if (data.success) {
                    this.editModal = false;
                    this.successMsg = 'Customer updated!';
                    this.fetchCustomers();
                } else {
                    this.errorMsg = data.error;
                }
            } catch (e) {
                this.errorMsg = 'Request failed.';
            }
        },

        openPinModal(c) {
            this.selectedCustomer = c;
            this.pinForm = { new_pin: '' };
            this.pinModal = true;
        },
        
        async submitPin() {
            const formData = new FormData();
            formData.append('new_pin', this.pinForm.new_pin);
            formData.append('csrfmiddlewaretoken', window.CUSTOMERS_CONFIG.csrfToken);
            
            try {
                const url = window.CUSTOMERS_CONFIG.urls.resetPin.replace('00000000-0000-0000-0000-000000000000', this.selectedCustomer.id);
                const res = await fetch(url, { method: 'POST', body: formData });
                const data = await res.json();
                if (data.success) {
                    this.pinModal = false;
                    this.successMsg = 'PIN reset successfully!';
                } else {
                    this.errorMsg = data.error;
                }
            } catch (e) {
                this.errorMsg = 'Request failed.';
            }
        },

        async openLedgerModal(c) {
            this.selectedCustomer = c;
            this.ledgerEntries = [];
            this.ledgerModal = true;
            
            try {
                const url = window.CUSTOMERS_CONFIG.urls.ledger.replace('00000000-0000-0000-0000-000000000000', this.selectedCustomer.id);
                const res = await fetch(url);
                const data = await res.json();
                this.ledgerEntries = data.entries;
            } catch (e) {
                this.errorMsg = 'Failed to load ledger.';
            }
        }
    }
}
