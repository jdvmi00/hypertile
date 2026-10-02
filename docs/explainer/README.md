# Hosted explainer

The narrated 1:56 explainer is served from Jim's Cloudflare account:

- Player: https://hypertile.jimmartin.workers.dev/
- MP4: https://hypertile.jimmartin.workers.dev/media/hypertile-explainer-f42cf8b86a60.mp4
- Poster: https://hypertile.jimmartin.workers.dev/poster.jpg

The `hypertile` Worker serves the static player and streams this one public
object from the private `hypertile-media` R2 bucket. Byte-range requests support
seeking, and CORS allows the MP4 to be embedded on the marketplace. The player
uses native browser controls, no autoplay, and no video preload. No plugin
installation or runtime code depends on this hosting.

R2 fits this small, already encoded MP4: Standard storage has a free allowance
and no bandwidth charges. Worker requests have their own account allowance.
Cloudflare Stream would add adaptive transcoding, but requires paid storage
capacity. See [R2 pricing](https://developers.cloudflare.com/r2/pricing/),
[Worker pricing](https://developers.cloudflare.com/workers/platform/pricing/),
and [Stream pricing](https://developers.cloudflare.com/stream/pricing/).

## Deploy

Run from this directory with Wrangler authenticated to Jim's account:

```bash
node --test worker.test.mjs
npx wrangler@4.145.0 deploy
```

The initial R2 object was uploaded from the supplied original, without
re-encoding. Its SHA-256 is
`f42cf8b86a60095b428b988392445dfae9c467129e00b4a00158ea767d1d3ffc`.
The original file stays outside the plugin repository.

```bash
npx wrangler@4.145.0 r2 object put hypertile-media/hypertile-explainer-f42cf8b86a60.mp4 \
  --remote --file /path/to/hypertile-explainer_1080.mp4 \
  --content-type video/mp4 --cache-control 'public, max-age=31536000, immutable'
```

For a replacement, use a new content-hash filename, update the Worker allowlist
and the player source, then redeploy. Keep the old object so existing links
continue working. The Worker allowlist must retain any older public filenames
that still need to work.

## Marketplace placement

The marketplace currently renders its catalog, not the plugin README. Root
`preview.png` supplies a screenshot; it cannot link to a video. Inline playback
requires marketplace support, reviewed and deployed by its maintainer.

The proposed placement is a video with controls immediately below the plugin
description and before installation, with the hosted poster, no autoplay, and
`preload="none"`. Use the direct MP4 URL above; retain the existing screenshot
as a fallback. A curated video URL in listing metadata would allow this without
changing the verified plugin snapshot.
