const releaseAssetBase = 'https://github.com/Laser1209/Aerie_Spotlight/releases/download'

export const release = {
  version: '0.3.2-beta.0903-A12',
  url: `${releaseAssetBase}/v0.3.2-beta.0903-A12/Aerie%20Companion-0.3.2-beta.0903-A12-portable.exe`,
  filename: 'Aerie Companion-0.3.2-beta.0903-A12-portable.exe',
  installerUrl: `${releaseAssetBase}/v0.3.2-beta.0903-A12/Aerie%20Companion-0.3.2-beta.0903-A12-Setup.exe`,
  installerFilename: 'Aerie Companion-0.3.2-beta.0903-A12-Setup.exe',
  date: '2026-09-02',
} as const

export interface HistoricalRelease {
  version: string
  date: string
  url: string
  installerUrl: string
}

// 历史版本归档：保留旧版本下载入口，避免老用户找不到对应安装包。
export const historicalReleases: HistoricalRelease[] = [
  {
    version: '0.1.0-beta.1',
    date: '2026-07-19',
    url: `${releaseAssetBase}/v0.1.0-beta.1/Aerie-Cloud-0.1.0-beta.1-Portable.exe`,
    installerUrl: `${releaseAssetBase}/v0.1.0-beta.1/Aerie-Cloud-0.1.0-beta.1-Setup.exe`,
  },
]
