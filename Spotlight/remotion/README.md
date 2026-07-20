# Aerie Spotlight background films

This isolated Remotion project renders the four local atmospheric backgrounds used by the Spotlight site. It intentionally has its own dependencies and does not ship in the Vite application bundle.

```bash
npm install
npm run typecheck
npm run video:still
npm run video:render
```

Outputs are H.264 MP4 files at 1920x1080, 30fps and 12 seconds:

- `../public/videos/features.mp4`
- `../public/videos/architecture.mp4`
- `../public/videos/journal.mp4`
- `../public/videos/download.mp4`

All animation is frame-driven through Remotion. The compositions contain no audio, readable text, or watermark.
