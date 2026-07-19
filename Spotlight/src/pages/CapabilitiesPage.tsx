import PageShell from '../components/PageShell'
import PageIntro from '../components/PageIntro'
import Capabilities from '../sections/Capabilities'

const video =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260622_093722_ccfc7ebf-182f-419f-8a62-2dc02db7dd9d.mp4'

export default function CapabilitiesPage() {
  return (
    <PageShell videoSrc={video} scrollable>
      <div className="flex min-h-screen flex-col px-6 pb-10 pt-28 md:px-16 lg:px-20">
        <PageIntro label="Capabilities" title={'One companion,\nend to end'} />
        <div className="mt-12 lg:mt-auto">
          <Capabilities />
        </div>
      </div>
    </PageShell>
  )
}
