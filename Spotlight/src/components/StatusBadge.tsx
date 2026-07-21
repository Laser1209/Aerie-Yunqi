import type { ProductStatus } from '../content/spotlight'

const statusLabel: Record<ProductStatus, string> = {
  shipped: 'Shipped',
  mainline: 'Mainline',
  building: 'Building',
  planned: 'Planned',
  gated: 'Prerequisite gated',
}

const statusClassName: Record<ProductStatus, string> = {
  shipped: 'border-emerald-200/25 bg-emerald-200/10 text-emerald-50',
  mainline: 'border-sky-200/30 bg-sky-200/10 text-sky-50',
  building: 'border-cyan-200/30 bg-cyan-200/10 text-cyan-50',
  planned: 'border-white/15 bg-white/[0.04] text-white/65',
  gated: 'border-rose-200/25 bg-rose-200/10 text-rose-50',
}

interface StatusBadgeProps {
  status: ProductStatus
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`inline-flex w-fit items-center rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase ${statusClassName[status]}`}>
      {statusLabel[status]}
    </span>
  )
}
