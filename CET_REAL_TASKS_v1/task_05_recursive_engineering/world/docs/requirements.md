# Requirements
- Invalid signatures must be rejected before parsing or storage.
- Each event id must have at-most-once side effects.
- Duplicate delivery must return successful idempotent response without incrementing counters.
- Duplicate detection must not require a linear scan of all historical events.