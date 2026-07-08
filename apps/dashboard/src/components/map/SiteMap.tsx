import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet'
import type { VillageStatus, VillageSummary } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import { formatNumber, formatPct } from '../../lib/format'

/**
 * All Leaflet imports live in this file (the swap boundary): if an
 * offline-friendly SVG map is ever needed, it replaces this component
 * behind the same props.
 */

const STATUS_COLOR: Record<VillageStatus, string> = {
  operational: '#0ca30c',
  degraded: '#fab219',
  offline: '#d03b3b',
}

export function SiteMap({
  sites,
  onSelect,
}: {
  sites: VillageSummary[]
  onSelect: (villageId: string) => void
}) {
  const { t } = useI18n()

  return (
    <MapContainer
      center={[0.6, 37.5]}
      zoom={6}
      scrollWheelZoom={false}
      className="z-0 h-full w-full"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {sites.map((site) => (
        <CircleMarker
          key={site.village.id}
          center={[site.village.latitude, site.village.longitude]}
          radius={9}
          pathOptions={{
            fillColor: STATUS_COLOR[site.village.status],
            fillOpacity: 0.9,
            color: '#ffffff', // 2px surface ring keeps markers legible on any tile
            weight: 2,
          }}
        >
          <Popup>
            <div className="min-w-44 text-sm">
              <div className="font-semibold">{site.village.name}</div>
              <div className="text-xs text-ink-secondary">
                {t.common.county(site.village.county)} · {t.status[site.village.status]}
              </div>
              <dl className="mt-2 space-y-0.5 text-xs">
                <div className="flex justify-between gap-4">
                  <dt className="text-ink-secondary">{t.map.customers}</dt>
                  <dd className="font-medium tabular-nums">{formatNumber(site.customerCount)}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-ink-secondary">{t.map.batterySoc}</dt>
                  <dd className="font-medium tabular-nums">{formatPct(site.currentSocPct)}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-ink-secondary">{t.map.pvCapacity}</dt>
                  <dd className="font-medium tabular-nums">{site.village.pvCapacityKwp} kWp</dd>
                </div>
              </dl>
              <button
                type="button"
                onClick={() => onSelect(site.village.id)}
                className="mt-2 w-full rounded-md bg-ink px-2 py-1 text-xs font-medium text-white hover:bg-ink/85"
              >
                {t.map.openVillage}
              </button>
            </div>
          </Popup>
        </CircleMarker>
      ))}
    </MapContainer>
  )
}
