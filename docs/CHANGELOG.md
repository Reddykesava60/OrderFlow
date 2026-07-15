# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - Recent Updates

### Added
- **Platform-Level Post-Payment Control**: Added `admin_post_payment_enabled` toggle to the platform admin, allowing admins to selectively disable post-payment for specific customers.
- **UI Responsiveness**: Added instant loading states (visual feedback) to the Owner Dashboard Modals (Edit Customer, Reset PIN, Record Payment, and Ledger) to improve the user experience.
- **KDS Menu Shortcut**: Added a "KDS" shortcut button on the public menu for logged-in staff and owners, and an "Open Menu" button in the KDS header, allowing quick seamless navigation between the public ordering page and the kitchen display.
- **Staff Auto-Collect feature**: The checkout system now recognizes when an authenticated staff member (with cash collection permissions) places a "CASH" order. The order automatically skips the `UNPAID` state, immediately jumps to `PENDING` (ready for the kitchen), and logs the cash collection securely without requiring manual interaction on the KDS Payments tab.
- **QR Code Footer**: Added a professional "POWERED BY ORDER-FLOW" footer to dynamically generated restaurant QR codes, utilizing the active theme colors.
- **Per-Restaurant Custom Fees**: Completely removed the global `PlatformSettings` singleton model. Platform fee configurations (`fee_mode`, `fee_percent`, `fee_fixed_amount`) are now strictly localized to the `Restaurant` model, permanently removing default global fallback logic to improve database performance and simplify pricing configuration.
- **Hybrid Fee Mode**: Added a new `HYBRID` fee mode that calculates platform fees as both a percentage AND a fixed amount per order to protect margins on low-value orders.
- **Admin Exports**: Added bulk CSV export capabilities to the `MonthlyPlatformFeeStatement` and `Order` models in the Django admin panel for easier accounting.

### Changed
- **Customer Creation Workflow**: Migrated customer creation entirely to the platform admin. Removed the "New Customer" button from the owner dashboard to centralize control and ensure only administrators can create post-payment accounts.
- **Brand Theme**: Updated the primary brand color palette in `tailwind.config.js` to a clean, professional blue standard.
- **KDS Architecture**: Completely removed the historical "All Orders" tab and the `allow_view_all_orders` permission flag. The KDS payload generation now strictly queries only active orders (`UNPAID`, `PREP_STARTED`, `READY`), vastly improving database query performance and reducing JSON payload sizes.
- **Cash Timeout Configuration**: Removed the global platform cash timeout setting and migrated the configuration entirely to the `RestaurantConfig` model, removing database lookups to the singleton and enforcing per-restaurant timing logic.

### Performance & Security
- **PIN Hashing Optimization**: Drastically reduced the PBKDF2 hash iterations for Customer PINs (from 260,000 to 20,000) to ensure lightning-fast checkout performance in constrained or local development environments, without compromising reasonable security for a 4-digit PIN.
- **KDS Layout & UI**: 
  - Overhauled the order item card layout on mobile devices, removing vertical bloat by enforcing a single-row flex layout.
  - Compacted the station filter buttons and the new horizontal aggregated items strip for a slimmer, more space-efficient design.
  - Repositioned the bottom navigation tab counts to sit adjacent to the labels (instead of below them) to save vertical screen real estate.
  - Replaced the "Open Menu" and "Kitchen Queue" text with cleaner variants, completely hiding the header block on the main queue to maximize visible order space.
  - Simplified the spice level display across the KDS to show only pepper icons (🌶️) instead of redundant text labels.
  - Added add-ons to the Pay tab order cards.
  - Standardized the order number badge styling across all KDS screens for visual consistency.
- **Receipt UI**: Payment methods are now color-coded, and the Owner receipt view dynamically routes the user back to their origin page (either Dashboard or Payments tab) via the `?next` URL parameter.
- **Admin Dashboard**: Ensured bulk actions in the Django admin panel (`RestaurantAdmin`) use clear "Deactivate " and "Activate" terminology. Deactivating a restaurant immediately shuts down its public menu and business operations.

### Security
- **Receipt Rate Limiting**: Applied a strict rate limit of 30 requests per minute to the `ReceiptView` to prevent bot scraping and brute-force traffic, matching the security parameters of the checkout flow.
