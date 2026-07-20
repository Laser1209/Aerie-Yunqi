import {Easing, interpolate} from 'remotion';
import {
  CornerFrame,
  GlassPlane,
  ParticleField,
  SceneBackdrop,
  loopValue,
  useLoop,
} from '../shared/scene';

const palette = {
  background: '#01050a',
  deep: '#071426',
  primary: '#4d9fff',
  secondary: '#70c7ee',
  highlight: '#d8f4ff',
};

type Point = {x: number; y: number};

const cubicPoint = (start: Point, first: Point, second: Point, end: Point, t: number) => {
  const inverse = 1 - t;
  return {
    x:
      inverse ** 3 * start.x +
      3 * inverse ** 2 * t * first.x +
      3 * inverse * t ** 2 * second.x +
      t ** 3 * end.x,
    y:
      inverse ** 3 * start.y +
      3 * inverse ** 2 * t * first.y +
      3 * inverse * t ** 2 * second.y +
      t ** 3 * end.y,
  };
};

const LayerStack = () => {
  const {phase} = useLoop();

  return (
    <div style={{position: 'absolute', inset: 0, perspective: 1700}}>
      {Array.from({length: 5}, (_, index) => {
        const lift = loopValue(phase, -9, 9, index * 0.8);
        const x = 1030 + index * 34;
        const y = 190 + index * 124;
        return (
          <GlassPlane
            key={index}
            tint={index === 4 ? '#ef6d79' : palette.primary}
            style={{
              width: 650 - index * 24,
              height: 104,
              left: x,
              top: y,
              borderRadius: 24,
              opacity: 0.78 - index * 0.045,
              transform: `translateY(${lift}px) rotateX(58deg) rotateZ(-4deg) translateZ(${index * 24}px)`,
            }}
          >
            <div style={{display: 'flex', alignItems: 'center', height: '100%', padding: '0 27px', gap: 18}}>
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: index === 4 ? '50%' : 13,
                  border: `1px solid ${index === 4 ? 'rgba(255,112,126,0.48)' : 'rgba(151,211,255,0.34)'}`,
                  background: index === 4 ? 'rgba(255,68,87,0.2)' : 'rgba(83,159,255,0.13)',
                  boxShadow: index === 4 ? '0 0 30px rgba(255,65,83,0.22)' : '0 0 24px rgba(55,150,255,0.12)',
                }}
              />
              <div style={{display: 'flex', flexDirection: 'column', gap: 11, flex: 1}}>
                <div style={{width: `${46 + index * 6}%`, height: 8, borderRadius: 5, background: 'rgba(224,245,255,0.31)'}} />
                <div style={{width: `${70 - index * 5}%`, height: 5, borderRadius: 5, background: 'rgba(210,237,255,0.12)'}} />
              </div>
              {Array.from({length: 3}, (_, dot) => (
                <div
                  key={dot}
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    background: dot === index % 3 ? '#c8efff' : 'rgba(255,255,255,0.18)',
                  }}
                />
              ))}
            </div>
          </GlassPlane>
        );
      })}
    </div>
  );
};

const DataRibbons = () => {
  const {frame, durationInFrames, phase} = useLoop();
  const paths = [
    'M 460 236 C 760 140, 1010 360, 1740 214',
    'M 390 380 C 820 520, 1100 185, 1775 408',
    'M 490 550 C 760 410, 1110 705, 1740 558',
    'M 415 720 C 820 860, 1210 560, 1780 760',
    'M 530 880 C 820 700, 1240 985, 1690 884',
  ];
  const shift = interpolate(frame, [0, durationInFrames], [0, -120], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.linear,
  });

  const controlSets = [
    [{x: 460, y: 236}, {x: 760, y: 140}, {x: 1010, y: 360}, {x: 1740, y: 214}],
    [{x: 390, y: 380}, {x: 820, y: 520}, {x: 1100, y: 185}, {x: 1775, y: 408}],
    [{x: 490, y: 550}, {x: 760, y: 410}, {x: 1110, y: 705}, {x: 1740, y: 558}],
    [{x: 415, y: 720}, {x: 820, y: 860}, {x: 1210, y: 560}, {x: 1780, y: 760}],
    [{x: 530, y: 880}, {x: 820, y: 700}, {x: 1240, y: 985}, {x: 1690, y: 884}],
  ];

  return (
    <svg width="1920" height="1080" style={{position: 'absolute', inset: 0}}>
      <defs>
        <linearGradient id="architecture-ribbon" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#72c7ff" stopOpacity="0" />
          <stop offset="0.34" stopColor="#57aaff" stopOpacity="0.28" />
          <stop offset="0.72" stopColor="#b4e7ff" stopOpacity="0.62" />
          <stop offset="1" stopColor="#59a6ff" stopOpacity="0.05" />
        </linearGradient>
        <filter id="architecture-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="8" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {paths.map((path, index) => (
        <g key={path}>
          <path d={path} fill="none" stroke="#3f8bdc" strokeWidth={24 - index * 2.5} strokeOpacity={0.028 + index * 0.008} />
          <path
            d={path}
            fill="none"
            stroke="url(#architecture-ribbon)"
            strokeWidth={1.4 + index * 0.25}
            strokeDasharray="32 88"
            strokeDashoffset={shift + index * 21}
            filter="url(#architecture-glow)"
          />
        </g>
      ))}
      {controlSets.flatMap((set, pathIndex) =>
        [0.12, 0.48, 0.76].map((offset, dotIndex) => {
          const t = ((phase / (Math.PI * 2) + offset + pathIndex * 0.08) % 1 + 1) % 1;
          const point = cubicPoint(set[0], set[1], set[2], set[3], t);
          const opacity = interpolate(Math.sin(Math.PI * t), [0, 1], [0, 0.9], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
            easing: Easing.out(Easing.cubic),
          });
          return (
            <g key={`${pathIndex}-${dotIndex}`} opacity={opacity} filter="url(#architecture-glow)">
              <circle cx={point.x} cy={point.y} r={dotIndex === 1 ? 4.5 : 3} fill="#d5f4ff" />
              <circle cx={point.x} cy={point.y} r={12} fill="#54a9ff" opacity="0.13" />
            </g>
          );
        }),
      )}
      {[{x: 1504, y: 318}, {x: 1618, y: 638}, {x: 1308, y: 812}].map((node, index) => {
        const pulse = loopValue(phase, 0.35, 0.9, index * 2.1);
        return (
          <g key={index} opacity={pulse}>
            <circle cx={node.x} cy={node.y} r={25} fill="#ff5365" opacity="0.06" />
            <circle cx={node.x} cy={node.y} r={7} fill="#ff6c7a" />
            <circle cx={node.x} cy={node.y} r={14} fill="none" stroke="#ff8590" strokeOpacity="0.38" />
          </g>
        );
      })}
    </svg>
  );
};

export const ArchitectureFilm = () => {
  return (
    <SceneBackdrop palette={palette}>
      <ParticleField color="#84caff" count={34} seed={62} />
      <DataRibbons />
      <LayerStack />
      <CornerFrame color="rgba(127,196,255,0.75)" />
    </SceneBackdrop>
  );
};
