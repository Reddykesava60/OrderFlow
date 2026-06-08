# Alpine.js Integration Examples

## 1. UPI Intent Capability + QR Fallback

```javascript
function paymentUx() {
  return {
    canUseIntent: false,
    intentUrls: {},
    qrImageUrl: '',
    init(payment) {
      const ua = navigator.userAgent || '';
      const isMobile = /Android|iPhone|iPad/i.test(ua);
      this.canUseIntent = isMobile && Boolean(payment.intent_uri);
      this.intentUrls = payment.intent_urls || {};
      this.qrImageUrl = payment.qr_image_url || '';
    },
    launch() {
      if (this.canUseIntent && this.intentUrls.any) {
        window.location.href = this.intentUrls.any;
        return;
      }
      // Fallback path: keep user on QR view.
    }
  }
}
```

## 2. Safe Customer PIN Handling

```javascript
async function submitPostPayment(payload) {
  try {
    const res = await fetch(payload.checkoutUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': payload.csrf,
      },
      body: JSON.stringify(payload.data),
    });
    const data = await res.json();
    return data;
  } finally {
    // Always clear PIN from reactive state after request completion.
    payload.data.customer_pin = '';
  }
}
```

## 3. Payment Polling with Signed Access Token

```javascript
async function pollPayment(statusUrl) {
  const res = await fetch(statusUrl, { method: 'GET', credentials: 'same-origin' });
  if (!res.ok) {
    throw new Error('Unable to fetch payment status');
  }
  return res.json();
}
```

## 4. Retry with Timeout and User Feedback

```javascript
async function retryPayment(retryUrl, csrf) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const res = await fetch(retryUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf },
      signal: controller.signal,
    });
    return await res.json();
  } finally {
    clearTimeout(timeout);
  }
}
```
