# Aerie Spotlight

Aerie Spotlight is the standalone GitHub Pages showcase site for **Aerie · 云栖**.

Live site: https://laser1209.github.io/Aerie_Spotlight/

## What This Repo Contains

- React + Vite + TypeScript + Tailwind CSS landing pages.
- Framer Motion page transitions and liquid-glass UI styling.
- Four local Remotion-generated background videos in `public/videos/`.
- A separate Remotion project in `remotion/` for regenerating those videos.
- GitHub Actions deployment to GitHub Pages.

## Development

```bash
npm ci
npm run dev
```

## Build

```bash
npm run build
```

## Deployment

Pushing to `main` runs `.github/workflows/deploy-pages.yml`, builds `dist`, and
publishes the result through GitHub Pages.

Large Windows release binaries are not committed to this Pages repository.
They are published as GitHub Release assets under `v0.1.0-beta.1`, and the
Download page links to those release assets directly.
