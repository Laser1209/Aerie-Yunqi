import {Composition, Folder} from 'remotion';
import {ArchitectureFilm} from './films/ArchitectureFilm';
import {DownloadFilm} from './films/DownloadFilm';
import {FeaturesFilm} from './films/FeaturesFilm';
import {JournalFilm} from './films/JournalFilm';

export const VIDEO_WIDTH = 1920;
export const VIDEO_HEIGHT = 1080;
export const VIDEO_FPS = 30;
export const VIDEO_DURATION = VIDEO_FPS * 12;

export const RemotionRoot = () => {
  const compositionProps = {
    width: VIDEO_WIDTH,
    height: VIDEO_HEIGHT,
    fps: VIDEO_FPS,
    durationInFrames: VIDEO_DURATION,
  } as const;

  return (
    <Folder name="Spotlight-Backgrounds">
      <Composition id="Features" component={FeaturesFilm} {...compositionProps} />
      <Composition id="Architecture" component={ArchitectureFilm} {...compositionProps} />
      <Composition id="Journal" component={JournalFilm} {...compositionProps} />
      <Composition id="Download" component={DownloadFilm} {...compositionProps} />
    </Folder>
  );
};
