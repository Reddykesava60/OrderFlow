(function() {
         const createdAt = new Date(window.RECEIPT_CONFIG.createdAt);
         const timeoutMins = window.RECEIPT_CONFIG.timeoutMins;
         const expireAt = new Date(createdAt.getTime() + timeoutMins * 60000);
         
         function checkExpiration() {
           const now = new Date();
           if (expireAt - now <= 0) {
             window.location.reload();
           }
         }
         // Check immediately, then every 5 seconds
         checkExpiration();
         setInterval(checkExpiration, 5000);
      })();
    