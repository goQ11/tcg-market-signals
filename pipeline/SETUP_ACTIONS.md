# Running Market Signals on GitHub Actions

The workflow `.github/workflows/market-signals.yml` runs the whole pipeline on GitHub's servers. Nothing depends on the box.

## When it runs
- **Every Monday at 18:13 UTC** (1:13 PM Central in summer, 12:13 PM in winter).
- **Every other day at 18:13 UTC**, but only if the published `signals.json` is more than 7 days old. This is the automatic next-day retry after a failed Monday.
- **By hand:** Actions tab > "Market Signals weekly update" > Run workflow. Tick **publish** to publish (on `main` only).
- **On pull requests** that change `pipeline/`: a small dry run (3 channels, no paid transcripts, never publishes).

## What it does
1. Finds new videos per channel: YouTube Data API if `YOUTUBE_API_KEY` is set, otherwise the RSS feed, otherwise the channel page. Videos already processed are skipped. Each channel has a short pause between requests, and every request retries with backoff.
2. Gets captions for each new video: Apify (if `APIFY_TOKEN` is set), then YouTube captions, then yt-dlp auto-captions, then the chapter list in the description.
3. Finds card mentions, has the AI judge rate them, builds `signals.json`, and checks every quote against the captions.
4. **Publish gate:** the new file must have every required field, a newer `generated_at`, at least 20 videos and 50 calls, and video/call counts between 0.4x and 4x of the published file. If anything fails, the job fails and the old file stays live.
5. Commits `signals.json` to `main`, and saves the pipeline memory (processed videos, judgments, cached captions from the last 45 days) to the `pipeline-state` branch.

## Secrets and variables (Settings > Secrets and variables > Actions)
| Name | Kind | Needed? | What it is |
|---|---|---|---|
| `LLM_API_KEY` | Secret | **Required to publish** | API key for the AI judge (any OpenAI-compatible chat API) |
| `LLM_BASE_URL` | Variable | **Required to publish** | That provider's API base URL, ending in `/v1` |
| `LLM_MODEL` | Variable | **Required to publish** | Model name at that provider |
| `APIFY_TOKEN` | Secret | Recommended | Same Apify token used today (about $0.12/week). Without it, free caption sources are used, which YouTube often blocks from cloud servers. |
| `YOUTUBE_API_KEY` | Secret | Recommended | Official YouTube API for listing videos (free) |

Without the judge settings, the job stops after collecting videos and captions, shows a warning, and publishes nothing.

## Create the YouTube API key (about 5 minutes, free)
1. Go to https://console.cloud.google.com/ and sign in with your Google account.
2. At the top, click the project picker, then **New project**. Name it `tcg-market-signals` and click **Create**.
3. In the search bar, type **YouTube Data API v3**, open it, and click **Enable**.
4. In the left menu, click **Credentials**, then **Create credentials** > **API key**. Copy the key.
5. Click **Edit API key** (or the key's name). Under **API restrictions**, choose **Restrict key** and tick only **YouTube Data API v3**. Click **Save**.
6. On GitHub, open `goQ11/tcg-market-signals` > **Settings** > **Secrets and variables** > **Actions** > **New repository secret**. Name: `YOUTUBE_API_KEY`. Paste the key. Click **Add secret**.

The free quota is 10,000 units a day. One run uses about 50.

## Before turning it on
- Turn off the box's weekly routine, so the two don't both publish on Monday.
- The repo is public, so the `pipeline-state` branch (cached captions and short judged snippets) will be public too.
