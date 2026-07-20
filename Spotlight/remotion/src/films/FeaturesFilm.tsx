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
  background: '#010706',
  deep: '#061713',
  primary: '#39d8b0',
  secondary: '#5aa8a1',
  highlight: '#b8ffe9',
};

const uiBars = [0.8, 0.52, 0.68, 0.42, 0.74];

const PanelContent = ({variant}: {variant: number}) => {
  const {phase} = useLoop();
  const scan = interpolate(
    (Math.sin(phase + variant * 0.9) + 1) / 2,
    [0, 1],
    [12, 78],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.inOut(Easing.cubic),
    },
  );

  return (
    <>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(115deg, rgba(255,255,255,0.075), transparent 34%, rgba(82,255,208,0.045) 70%, transparent)',
        }}
      />
      <div style={{display: 'flex', alignItems: 'center', gap: 11, padding: '22px 24px'}}>
        {[0, 1, 2].map((dot) => (
          <div
            key={dot}
            style={{
              width: dot === 0 ? 10 : 7,
              height: dot === 0 ? 10 : 7,
              borderRadius: '50%',
              background: dot === 0 ? '#9dffe4' : 'rgba(255,255,255,0.24)',
              boxShadow: dot === 0 ? '0 0 18px rgba(80,255,208,0.75)' : undefined,
            }}
          />
        ))}
        <div style={{height: 1, flex: 1, background: 'rgba(255,255,255,0.1)'}} />
        <div
          style={{
            width: 52,
            height: 15,
            borderRadius: 8,
            border: '1px solid rgba(255,255,255,0.13)',
          }}
        />
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: variant === 1 ? '1fr 1fr' : '84px 1fr',
          gap: 18,
          padding: '10px 24px 24px',
        }}
      >
        <div
          style={{
            minHeight: 190,
            borderRadius: 18,
            border: '1px solid rgba(255,255,255,0.1)',
            background: 'rgba(0,0,0,0.18)',
            padding: 15,
          }}
        >
          {Array.from({length: variant === 1 ? 4 : 6}, (_, row) => (
            <div
              key={row}
              style={{
                height: variant === 1 ? 28 : 16,
                marginBottom: 11,
                borderRadius: variant === 1 ? 8 : 5,
                background:
                  row === variant
                    ? 'linear-gradient(90deg, rgba(78,241,198,0.36), rgba(78,241,198,0.08))'
                    : 'rgba(255,255,255,0.055)',
                border: row === variant ? '1px solid rgba(116,255,220,0.24)' : undefined,
              }}
            />
          ))}
        </div>
        <div
          style={{
            position: 'relative',
            minHeight: 190,
            borderRadius: 18,
            border: '1px solid rgba(255,255,255,0.1)',
            background: 'linear-gradient(145deg, rgba(255,255,255,0.055), rgba(5,19,16,0.36))',
            padding: 23,
          }}
        >
          <div
            style={{
              position: 'absolute',
              left: `${scan}%`,
              top: 0,
              bottom: 0,
              width: 1,
              background: 'linear-gradient(transparent, rgba(112,255,220,0.55), transparent)',
              boxShadow: '0 0 20px rgba(67,255,210,0.45)',
            }}
          />
          <div style={{display: 'flex', gap: 9, marginBottom: 23}}>
            {Array.from({length: 4}, (_, item) => (
              <div
                key={item}
                style={{
                  width: item === 0 ? 48 : 28,
                  height: 28,
                  borderRadius: 14,
                  border: '1px solid rgba(255,255,255,0.12)',
                  background: item === 0 ? 'rgba(87,245,205,0.18)' : 'rgba(255,255,255,0.035)',
                }}
              />
            ))}
          </div>
          {uiBars.slice(0, variant === 2 ? 5 : 4).map((width, row) => (
            <div
              key={row}
              style={{
                width: `${width * (variant === 1 ? 78 : 100)}%`,
                height: row === 0 ? 12 : 7,
                marginBottom: 13,
                borderRadius: 6,
                background:
                  row === 0 ? 'rgba(218,255,246,0.31)' : 'rgba(255,255,255,0.11)',
              }}
            />
          ))}
        </div>
      </div>
    </>
  );
};

const CapabilityMesh = () => {
  const {phase} = useLoop();
  const bases = [
    [1035, 215],
    [1325, 145],
    [1590, 315],
    [1690, 610],
    [1428, 790],
    [1110, 720],
  ];
  const nodes = bases.map(([x, y], index) => ({
    x: x + Math.cos(phase + index * 1.21) * (11 + index * 1.2),
    y: y + Math.sin(phase + index * 0.83) * (13 + index),
  }));
  const edges = [
    [0, 1],
    [1, 2],
    [2, 3],
    [3, 4],
    [4, 5],
    [5, 0],
    [0, 3],
    [1, 4],
    [2, 5],
  ];

  return (
    <svg width="1920" height="1080" style={{position: 'absolute', inset: 0}}>
      <defs>
        <linearGradient id="feature-edge" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#83ffe1" stopOpacity="0.04" />
          <stop offset="0.55" stopColor="#52dfbd" stopOpacity="0.34" />
          <stop offset="1" stopColor="#a8ffe8" stopOpacity="0.08" />
        </linearGradient>
        <radialGradient id="feature-node">
          <stop offset="0" stopColor="#e6fff8" />
          <stop offset="0.28" stopColor="#7dffdd" stopOpacity="0.9" />
          <stop offset="1" stopColor="#4bd4b2" stopOpacity="0" />
        </radialGradient>
      </defs>
      {edges.map(([start, end], index) => (
        <line
          key={index}
          x1={nodes[start].x}
          y1={nodes[start].y}
          x2={nodes[end].x}
          y2={nodes[end].y}
          stroke="url(#feature-edge)"
          strokeWidth={index > 5 ? 0.8 : 1.3}
        />
      ))}
      {nodes.map((node, index) => {
        const pulse = loopValue(phase, 0.55, 1, index * 0.91);
        return (
          <g key={index} opacity={pulse}>
            <circle cx={node.x} cy={node.y} r={38} fill="url(#feature-node)" opacity="0.22" />
            <circle cx={node.x} cy={node.y} r={5.5} fill="#c7fff1" />
            <circle cx={node.x} cy={node.y} r={13} fill="none" stroke="#7affdc" strokeOpacity="0.28" />
          </g>
        );
      })}
    </svg>
  );
};

export const FeaturesFilm = () => {
  const {phase} = useLoop();
  const cameraX = loopValue(phase, -16, 16, 0.2);
  const cameraY = loopValue(phase, -10, 12, 2.2);
  const panelOneY = loopValue(phase, -22, 22, 0.5);
  const panelTwoY = loopValue(phase, -18, 18, 2.7);
  const panelThreeY = loopValue(phase, -15, 15, 4.8);

  return (
    <SceneBackdrop palette={palette}>
      <ParticleField color="#76ffdc" count={50} seed={31} />
      <CapabilityMesh />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          perspective: 1550,
          transform: `translate3d(${cameraX}px, ${cameraY}px, 0)`,
        }}
      >
        <GlassPlane
          tint={palette.primary}
          style={{
            width: 650,
            height: 358,
            left: 1080,
            top: 345,
            borderRadius: 34,
            transform: `translateY(${panelOneY}px) rotateX(5deg) rotateY(-12deg) rotateZ(-1.5deg)`,
          }}
        >
          <PanelContent variant={0} />
        </GlassPlane>
        <GlassPlane
          tint={palette.secondary}
          style={{
            width: 460,
            height: 292,
            left: 880,
            top: 180,
            borderRadius: 29,
            opacity: 0.63,
            transform: `translateY(${panelTwoY}px) translateZ(-180px) rotateX(7deg) rotateY(-8deg) rotateZ(3deg)`,
          }}
        >
          <PanelContent variant={1} />
        </GlassPlane>
        <GlassPlane
          tint="#77ffd8"
          style={{
            width: 430,
            height: 270,
            left: 1280,
            top: 690,
            borderRadius: 28,
            opacity: 0.72,
            transform: `translateY(${panelThreeY}px) translateZ(-90px) rotateX(-4deg) rotateY(-14deg) rotateZ(-2deg)`,
          }}
        >
          <PanelContent variant={2} />
        </GlassPlane>
      </div>
      <CornerFrame color="rgba(132,255,223,0.8)" />
    </SceneBackdrop>
  );
};
