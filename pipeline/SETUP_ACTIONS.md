# Market Signals: how it runs (no extra cost)

**The weekly update runs on the box**, Mondays 1:13 PM CT (`run_weekly.sh` -> judging -> `finish_weekly.sh` -> `publish.sh`).
The pipeline code in `pipeline/` is the same code the box uses.

## Weekly update (box)
1. **Find new videos** per channel: YouTube Data API if `YOUTUBE_API_KEY` is set, else the RSS feed, else the channel page. Already-processed video ids are skipped; each channel looks back from its own last good check; a pause between channels; every request retries with backoff.
2. **Captions** per new video: Apify (spend-capped, ~$0.12/week), then YouTube captions, then yt-dlp auto-captions, then description chapters. Each step retries.
3. **Judging**: the assistant reads `judge_queue.json` and writes `judgments.json` (no paid AI service).
4. **Build + check**: aggregate, verify every quote against captions (`06_validate.py`).
5. **Publish gate** (`gate.py`): required fields, same schema major version, newer `generated_at`, at least 20 videos and 50 calls, counts 0.4x-4x of the live file. If anything fails, nothing is pushed and last week's good file stays live.

## Daily watchdog (GitHub Actions, free, no secrets)
`.github/workflows/market-signals.yml` runs every day at 15:00 UTC (and on PRs). `pipeline/watchdog.py` downloads the live
`signals.json` and fails if it is older than 8 days or the schema is broken. GitHub emails the repo owner when a scheduled
workflow fails, so a missed Monday is noticed within a day. (Scheduled runs only start once this is on `main`.)

## Dormant: fully automated version (for later)
`pipeline/ci_run.sh` + `pipeline/judge_llm.py` can run the whole update in Actions with an AI judge
(`LLM_API_KEY` secret, `LLM_BASE_URL`/`LLM_MODEL` variables) and `APIFY_TOKEN` (YouTube blocks free caption sources from
cloud servers). Not wired into any workflow. To switch later: restore the `update` job from git history (commit f818704), add those
secrets, and turn off the box routine so both don't publish.

## Create the YouTube API key (about 5 minutes, free)
1. Go to https://console.cloud.google.com/ and sign in with your Google account.
2. At the top, click the project picker, then **New project**. Name it `tcg-market-signals` and click **Create**.
3. In the search bar, type **YouTube Data API v3**, open it, and click **Enable**.
4. In the left menu, click **Credentials**, then **Create credentials** > **API key**. Copy the key.
5. Click **Edit API key** (or the key's name). Under **API restrictions**, choose **Restrict key** and tick only **YouTube Data API v3**. Click **Save**.
6. Give the key to the box routine as the environment variable `YOUTUBE_API_KEY` (never commit it). Discovery then uses the API automatically; without it, it uses the RSS feed, then the channel page.

The free quota is 10,000 units a day. One run uses about 50.

