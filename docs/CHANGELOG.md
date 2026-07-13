# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - Recent Updates

### Added
- **KDS Menu Shortcut**: Added a "KDS" shortcut button on the public menu for logged-in staff and owners, and an "Open Menu" button in the KDS header, allowing quick seamless navigation between the public ordering page and the kitchen display.
- **Staff Auto-Collect feature**: The checkout system now recognizes when an authenticated staff member (with cash collection permissions) places a "CASH" order. The order automatically skips the `UNPAID` state, immediately jumps to `PENDING` (ready for the kitchen), and logs the cash collection securely without requiring manual interaction on the KDS Payments tab.
- **QR Code Footer**: Added a professional "POWERED BY ORDER-FLOW" footer to dynamically generated restaurant QR codes, utilizing the active theme colors.
- **Hybrid Fee Mode**: Added a new `HYBRID` mode for `PlatformSettings` that calculates platform fees as both a percentage AND a fixed amount per order to protect margins on low-value orders.
- **Per-Restaurant Custom Fees**: Replaced the limited `commission_rate` field with a robust per-restaurant override system allowing administrators to set custom fee modes (Percentage, Fixed, or Hybrid) alongside custom amounts exclusively for specific restaurants.
- **Admin Exports**: Added bulk CSV export capabilities to the `MonthlyPlatformFeeStatement` and `Order` models in the Django admin panel for easier accounting.

### Changed
- **Brand Theme**: Updated the primary brand color palette in `tailwind.config.js` to a clean, professional blue standard.
- **KDS Architecture**: Completely removed the historical "All Orders" tab and the `allow_view_all_orders` permission flag. The KDS payload generation now strictly queries only active orders (`UNPAID`, `PREP_STARTED`, `READY`), vastly improving database query performance and reducing JSON payload sizes.
- **KDS Layout & UI**: 
  - Adjusted individual KDS item action buttons (e.g., "Mark Done") to float on the right side of their respective rows, visually separating them from the "Complete All" order-level buttons.
  - Simplified the spice level display across the KDS to show only pepper icons (🌶️) instead of redundant text labels.
  - Standardized the order number badge styling across all KDS screens for visual consistency.
- **Receipt UI**: Payment methods are now color-coded, and the Owner receipt view dynamically routes the user back to their origin page (either Dashboard or Payments tab) via the `?next` URL parameter.
- **Admin Dashboard**: Ensured bulk actions in the Django admin panel (`RestaurantAdmin`) use clear "Deactivate " and "Activate" terminology. Deactivating a restaurant immediately shuts down its public menu and business operations.

### Security
- **Receipt Rate Limiting**: Applied a strict rate limit of 30 requests per minute to the `ReceiptView` to prevent bot scraping and brute-force traffic, matching the security parameters of the checkout flow.
