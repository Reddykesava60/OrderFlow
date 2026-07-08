# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - Recent Updates

### Added
- **KDS Menu Shortcut**: Added a "KDS" shortcut button on the public menu for logged-in staff and owners, and an "Open Menu" button in the KDS header, allowing quick seamless navigation between the public ordering page and the kitchen display.
- **Staff Auto-Collect feature**: The checkout system now recognizes when an authenticated staff member (with cash collection permissions) places a "CASH" order. The order automatically skips the `UNPAID` state, immediately jumps to `PENDING` (ready for the kitchen), and logs the cash collection securely without requiring manual interaction on the KDS Payments tab.
- **QR Code Footer**: Added a professional "POWERED BY ORDER-FLOW" footer to dynamically generated restaurant QR codes, utilizing the active theme colors.

### Changed
- **Brand Theme**: Updated the primary brand color palette in `tailwind.config.js` to a clean, professional blue standard.
- **KDS Layout & UI**: 
  - Adjusted individual KDS item action buttons (e.g., "Mark Done") to float on the right side of their respective rows, visually separating them from the "Complete All" order-level buttons.
  - Simplified the spice level display across the KDS to show only pepper icons (🌶️) instead of redundant text labels.
  - Standardized the order number badge styling across all KDS screens for visual consistency.
- **Admin Dashboard**: Ensured bulk actions in the Django admin panel (`RestaurantAdmin`) use clear "Deactivate selected restaurants" and "Activate selected restaurants" terminology. Deactivating a restaurant immediately shuts down its public menu and business operations.

### Security
- **Receipt Rate Limiting**: Applied a strict rate limit of 30 requests per minute to the `ReceiptView` to prevent bot scraping and brute-force traffic, matching the security parameters of the checkout flow.
