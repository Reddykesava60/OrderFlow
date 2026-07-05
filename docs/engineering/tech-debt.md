# Tech Debt Notes

Tracked items for future optimisation and cleanup.

---

## TD-001 — `get_restaurant()` missing `select_related('config')`

**Logged:** 2026-07-05
**Area:** `core/mixins.py` → `ActiveStaffMixin.get_restaurant()`
**Impact:** Extra DB query per KDS action (every tap at high order volume)

**Problem:** `get_restaurant()` returns `request.user.restaurant` without
`select_related('config')`. Every KDS action view (`StartPrepView`,
`CompletePrepView`, etc.) then accesses `restaurant.config.kds_prep_enabled`
in a separate query. At high order volume this adds one extra round-trip per
staff tap.

**Proposed fix:** Add `.select_related('config')` to the restaurant fetch in
`get_restaurant()`, or override in each action view that needs it:

```python
# Option A — centralised (covers all views)
def get_restaurant(self):
    return Restaurant.objects.select_related('config').get(
        pk=self.request.user.restaurant_id
    )

# Option B — per-view (surgical, no impact on views that don't need config)
# Override get_restaurant() in KDS action views only.
```

**Risk:** Option A trades one extra JOIN for eliminating the N+1. The JOIN is
negligible for a single-row lookup. Option B is safer but requires touching
multiple views.
