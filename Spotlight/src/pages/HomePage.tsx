import PageShell from '../components/PageShell'
import Hero from '../sections/Hero'

const video =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260619_191346_9d19d66e-86a4-47f7-8dc6-712c1788c3b2.mp4'

export default function HomePage() {
  return (
    <PageShell
      videoSrc={video}
      videoClassName="absolute object-cover object-top"
      videoStyle={{
        left: '50%',
        bottom: 0,
        width: '120%',
        maxWidth: 'none',
        height: '120%',
        transform: 'translateX(-50%) translateZ(0)',
      }}
    >
      <Hero />
    </PageShell>
  )
}
