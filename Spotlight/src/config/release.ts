const releaseAssetBase = 'https://github.com/Laser1209/Aerie-Yunqi/releases/download'

export const release = {
  version: '0.3.2-beta.0904-A12',
  url: `${releaseAssetBase}/v0.3.2-beta.0904-A12/Aerie.Companion-0.3.2-beta.0904-A12-portable.exe`,
  filename: 'Aerie.Companion-0.3.2-beta.0904-A12-portable.exe',
  installerUrl: `${releaseAssetBase}/v0.3.2-beta.0904-A12/Aerie.Companion-0.3.2-beta.0904-A12-Setup.exe`,
  installerFilename: 'Aerie.Companion-0.3.2-beta.0904-A12-Setup.exe',
  date: '2026-09-04',
} as const

export interface HistoricalRelease {
  version: string
  date: string
  url: string
  installerUrl: string
}

// Keep only the two releases immediately preceding the current build.
export const historicalReleases: HistoricalRelease[] = [
  {
    version: '0.3.2-beta.0903-A10',
    date: '2026-09-03',
    url: `${releaseAssetBase}/v0.3.2-beta.0903-A10/Aerie.Companion-0.3.2-beta.0903-A10-portable.exe`,
    installerUrl: `${releaseAssetBase}/v0.3.2-beta.0903-A10/Aerie.Companion-0.3.2-beta.0903-A10-Setup.exe`,
  },
  {
    version: '0.3.2-beta.0903-A09',
    date: '2026-09-03',
    url: `${releaseAssetBase}/v0.3.2-beta.0903-A09/Aerie.Companion-0.3.2-beta.0903-A09-portable.exe`,
    installerUrl: `${releaseAssetBase}/v0.3.2-beta.0903-A09/Aerie.Companion-0.3.2-beta.0903-A09-Setup.exe`,
  },
]
