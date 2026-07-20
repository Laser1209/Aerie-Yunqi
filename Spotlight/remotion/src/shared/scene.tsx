import type {CSSProperties, ReactNode} from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

export type ScenePalette = {
  background: string;
  deep: string;
  primary: string;
  secondary: string;
  highlight: string;
};

const clamp = {
  extrapolateLeft: 'clamp',
  extrapolateRight: 'clamp',
} as const;

export const useLoop = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const phase = interpolate(frame, [0, durationInFrames], [0, Math.PI * 2], {
    ...clamp,
    easing: Easing.linear,
  });
  const breath = interpolate((Math.sin(phase) + 1) / 2, [0, 1], [0, 1], {
    ...clamp,
    easing: Easing.inOut(Easing.sin),
  });

  return {frame, durationInFrames, phase, breath};
};

export const loopValue = (
  phase: number,
  min: number,
  max: number,
  offset = 0,
) =>
  interpolate((Math.sin(phase + offset) + 1) / 2, [0, 1], [min, max], {
    ...clamp,
    easing: Easing.inOut(Easing.sin),
  });

const hexToRgba = (hex: string, alpha: number) => {
  const normalized = hex.replace('#', '');
  const value = Number.parseInt(normalized, 16);
  const red = (value >> 16) & 255;
  const green = (value >> 8) & 255;
  const blue = value & 255;
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
};

export const SceneBackdrop = ({
  palette,
  children,
}: {
  palette: ScenePalette;
  children: ReactNode;
}) => {
  const {phase, breath} = useLoop();
  const driftX = loopValue(phase, -55, 55, 0.4);
  const driftY = loopValue(phase, -34, 34, 1.8);
  const washOpacity = interpolate(breath, [0, 1], [0.3, 0.54], {
    ...clamp,
    easing: Easing.inOut(Easing.cubic),
  });

  return (
    <AbsoluteFill
      style={{
        overflow: 'hidden',
        backgroundColor: palette.background,
        color: '#fff',
        fontFamily: 'Arial, sans-serif',
      }}
    >
      <AbsoluteFill
        style={{
          background: [
            `radial-gradient(circle at 74% 48%, ${hexToRgba(palette.primary, 0.21)} 0%, transparent 35%)`,
            `radial-gradient(circle at 42% 96%, ${hexToRgba(palette.secondary, 0.12)} 0%, transparent 39%)`,
            `linear-gradient(115deg, ${palette.background} 0%, ${palette.deep} 58%, #020506 100%)`,
          ].join(','),
        }}
      />
      <div
        style={{
          position: 'absolute',
          width: 1160,
          height: 820,
          left: 870 + driftX,
          top: 115 + driftY,
          borderRadius: '50%',
          background: `radial-gradient(circle, ${hexToRgba(palette.highlight, 0.2)} 0%, ${hexToRgba(palette.primary, 0.08)} 42%, transparent 72%)`,
          filter: 'blur(76px)',
          opacity: washOpacity,
        }}
      />
      <AbsoluteFill
        style={{
          backgroundImage: [
            'linear-gradient(rgba(255,255,255,0.018) 1px, transparent 1px)',
            'linear-gradient(90deg, rgba(255,255,255,0.014) 1px, transparent 1px)',
          ].join(','),
          backgroundSize: '96px 96px',
          maskImage: 'linear-gradient(90deg, transparent 2%, rgba(0,0,0,0.35) 38%, #000 100%)',
        }}
      />
      {children}
      <AbsoluteFill
        style={{
          pointerEvents: 'none',
          background: [
            'radial-gradient(circle at 52% 48%, transparent 25%, rgba(0,0,0,0.18) 74%, rgba(0,0,0,0.68) 100%)',
            'linear-gradient(90deg, rgba(0,0,0,0.72) 0%, rgba(0,0,0,0.18) 38%, transparent 72%)',
          ].join(','),
        }}
      />
      <AbsoluteFill
        style={{
          pointerEvents: 'none',
          opacity: 0.045,
          backgroundImage:
            'url("data:image/svg+xml,%3Csvg viewBox=%270 0 180 180%27 xmlns=%27http://www.w3.org/2000/svg%27%3E%3Cfilter id=%27n%27%3E%3CfeTurbulence type=%27fractalNoise%27 baseFrequency=%27.9%27 numOctaves=%272%27 stitchTiles=%27stitch%27/%3E%3C/filter%3E%3Crect width=%27100%25%27 height=%27100%25%27 filter=%27url(%23n)%27 opacity=%27.65%27/%3E%3C/svg%3E")',
        }}
      />
    </AbsoluteFill>
  );
};

export const GlassPlane = ({
  children,
  style,
  tint,
}: {
  children?: ReactNode;
  style?: CSSProperties;
  tint: string;
}) => (
  <div
    style={{
      position: 'absolute',
      overflow: 'hidden',
      border: '1px solid rgba(255,255,255,0.22)',
      background: `linear-gradient(145deg, rgba(255,255,255,0.12), ${hexToRgba(tint, 0.07)} 44%, rgba(0,0,0,0.18))`,
      boxShadow: `inset 0 1px 1px rgba(255,255,255,0.22), 0 34px 100px rgba(0,0,0,0.38), 0 0 80px ${hexToRgba(tint, 0.08)}`,
      ...style,
    }}
  >
    {children}
  </div>
);

type ParticleFieldProps = {
  color: string;
  count?: number;
  seed?: number;
  rightWeighted?: boolean;
};

const pseudo = (index: number, seed: number) => {
  const value = Math.sin(index * 9283.17 + seed * 77.31) * 43758.5453;
  return value - Math.floor(value);
};

export const ParticleField = ({
  color,
  count = 44,
  seed = 1,
  rightWeighted = true,
}: ParticleFieldProps) => {
  const {phase} = useLoop();

  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      {Array.from({length: count}, (_, index) => {
        const baseX = pseudo(index, seed);
        const baseY = pseudo(index + 91, seed);
        const radius = 22 + pseudo(index + 171, seed) * 86;
        const offset = pseudo(index + 251, seed) * Math.PI * 2;
        const xZone = rightWeighted ? 610 + baseX * 1260 : baseX * 1920;
        const x = xZone + Math.cos(phase + offset) * radius;
        const y = baseY * 1080 + Math.sin(phase * (index % 3 === 0 ? -1 : 1) + offset) * radius;
        const size = 1.2 + pseudo(index + 401, seed) * 3.6;
        const alpha = loopValue(phase, 0.08, 0.48, offset);

        return (
          <div
            key={index}
            style={{
              position: 'absolute',
              left: x,
              top: y,
              width: size,
              height: size,
              borderRadius: '50%',
              backgroundColor: color,
              opacity: alpha,
              boxShadow: `0 0 ${size * 5}px ${color}`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

export const CornerFrame = ({color}: {color: string}) => {
  const {phase} = useLoop();
  const opacity = loopValue(phase, 0.18, 0.34, 2.1);
  const style: CSSProperties = {
    position: 'absolute',
    width: 78,
    height: 78,
    opacity,
  };

  return (
    <AbsoluteFill>
      <div style={{...style, top: 54, right: 64, borderTop: `1px solid ${color}`, borderRight: `1px solid ${color}`}} />
      <div style={{...style, right: 64, bottom: 54, borderRight: `1px solid ${color}`, borderBottom: `1px solid ${color}`}} />
    </AbsoluteFill>
  );
};
