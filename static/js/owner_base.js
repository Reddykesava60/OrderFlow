  function toastManager() {
    return {
      toasts: [],
      counter: 0,
      init() {
        // Convert Django messages into floating toasts on page load
        DJANGO_MESSAGES.forEach((m, i) => {
          setTimeout(() => this.show(m.msg, m.type), i * 150);
        });
      },
      show(msg, type) {
        type = type || 'info';
        const id = ++this.counter;
        this.toasts.push({ id, msg, type, visible: true });
        if (this.toasts.length > 5) this.toasts.shift();
        const duration = type === 'error' ? 5000 : 3000;
        setTimeout(() => {
          const t = this.toasts.find(x => x.id === id);
          if (t) t.visible = false;
          setTimeout(() => {
            this.toasts = this.toasts.filter(x => x.id !== id);
          }, 300);
        }, duration);
      }
    };
  }

  // Global Navigation Transition & Click Debounce
  document.addEventListener('DOMContentLoaded', () => {
    const loader = document.getElementById('global-page-loader');
    let isNavigating = false;

    document.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', (e) => {
        // Only intercept standard internal navigation links
        if (
          link.hostname === window.location.hostname &&
          !link.hash &&
          !link.target &&
          !link.hasAttribute('download') &&
          link.getAttribute('href') !== '#' &&
          !link.getAttribute('href').startsWith('javascript:')
        ) {
          if (isNavigating) {
            e.preventDefault(); // Prevent duplicate rapid clicks
            return;
          }
          isNavigating = true;
          
          loader.style.display = 'flex';
          // Small delay to allow display:flex to apply before opacity transition
          requestAnimationFrame(() => {
            loader.classList.remove('opacity-0', 'pointer-events-none');
            loader.classList.add('opacity-100');
          });
        }
      });
    });

    // Handle browser back/forward buttons & ensure loader hides
    window.addEventListener('pageshow', (e) => {
      if (e.persisted || isNavigating) {
        isNavigating = false;
        if (loader) {
          loader.classList.add('opacity-0', 'pointer-events-none');
          loader.classList.remove('opacity-100');
          setTimeout(() => {
            loader.style.display = 'none';
          }, 200);
        }
      }
    });
  });
