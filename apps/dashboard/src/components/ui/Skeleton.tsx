import clsx from 'clsx'

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse rounded-lg bg-gridline/60', className)} />
}

export function KpiSkeletonRow({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-24" />
      ))}
    </div>
  )
}
