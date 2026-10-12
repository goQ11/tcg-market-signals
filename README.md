# TCG Market Signals

Weekly `signals.json` feed for TCG Seller Hub. Card names, short quotes, and links to public YouTube videos. Not financial advice.

Schema 1.4.0: cards carry `reserved` (on Wizards' Reserved List, never reprinted), `paper_sets` (distinct paper set names, oldest first), `first_printed`, `first_printed_set`, `is_reprint` (printed in 2+ distinct paper sets), `reprint_count`, `latest_reprint_set`, `latest_reprint_date`. (`is_new` was removed in 1.3.0.)

## How it's updated
`pipeline/` holds the pipeline. `.github/workflows/market-signals.yml` runs it every week on GitHub Actions and publishes only if the new file passes validation. See `pipeline/SETUP_ACTIONS.md`. `generated_at` (ISO 8601) records when the file was built.
