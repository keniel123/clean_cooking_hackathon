import clsx from 'clsx'
import { useMemo, useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nContext'
import { EmptyState } from './EmptyState'

export interface Column<T> {
  key: string
  header: string
  /** Raw value used for sorting and as the default cell content. */
  value: (row: T) => string | number
  render?: (row: T) => ReactNode
  sortable?: boolean
  align?: 'left' | 'right'
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  searchText,
  searchPlaceholder = 'Search…',
  emptyLabel = 'No records',
  initialSort,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
  /** When provided, a search box filters rows against this text. */
  searchText?: (row: T) => string
  searchPlaceholder?: string
  emptyLabel?: string
  initialSort?: { key: string; dir: 'asc' | 'desc' }
}) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(
    initialSort ?? null,
  )

  const visible = useMemo(() => {
    let out = rows
    if (searchText && query.trim()) {
      const q = query.trim().toLowerCase()
      out = out.filter((r) => searchText(r).toLowerCase().includes(q))
    }
    if (sort) {
      const col = columns.find((c) => c.key === sort.key)
      if (col) {
        const dir = sort.dir === 'asc' ? 1 : -1
        out = [...out].sort((a, b) => {
          const va = col.value(a)
          const vb = col.value(b)
          if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
          return String(va).localeCompare(String(vb)) * dir
        })
      }
    }
    return out
  }, [rows, query, sort, columns, searchText])

  const toggleSort = (col: Column<T>) => {
    if (!col.sortable) return
    setSort((s) =>
      s?.key === col.key ? { key: col.key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key: col.key, dir: 'asc' },
    )
  }

  return (
    <div>
      {searchText && (
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={searchPlaceholder}
          className="mb-3 w-full max-w-xs rounded-lg border border-gridline bg-surface px-3 py-1.5 text-sm outline-none placeholder:text-ink-muted focus:border-baseline"
        />
      )}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-gridline text-left text-xs text-ink-muted">
              {columns.map((col) => (
                <th
                  key={col.key}
                  onClick={() => toggleSort(col)}
                  aria-sort={
                    sort?.key === col.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined
                  }
                  className={clsx(
                    'px-3 py-2 font-medium whitespace-nowrap',
                    col.align === 'right' && 'text-right',
                    col.sortable && 'cursor-pointer select-none hover:text-ink',
                  )}
                >
                  {col.header}
                  {sort?.key === col.key && (
                    <span aria-hidden className="ml-1">
                      {sort.dir === 'asc' ? '↑' : '↓'}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={clsx(
                  'border-b border-gridline/60 last:border-b-0',
                  onRowClick && 'cursor-pointer hover:bg-page',
                )}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={clsx(
                      'px-3 py-2 whitespace-nowrap',
                      col.align === 'right' && 'text-right tabular-nums',
                    )}
                  >
                    {col.render ? col.render(row) : col.value(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && <EmptyState message={query ? t.common.noMatches : emptyLabel} />}
      </div>
    </div>
  )
}
