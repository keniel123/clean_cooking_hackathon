import type { SurveyResponse } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import { formatDateTime } from '../../lib/format'
import { EmptyState } from '../ui/EmptyState'

export function SurveyHistoryList({ surveys }: { surveys: SurveyResponse[] }) {
  const { t } = useI18n()
  if (surveys.length === 0) return <EmptyState message={t.customerPage.noSurveys} />

  return (
    <ul className="divide-y divide-gridline/60">
      {surveys.map((survey) => (
        <li key={survey.id} className="py-2">
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center gap-2">
              <span aria-hidden className="text-xs text-ink-muted group-open:rotate-90">
                ▶
              </span>
              <span className="text-sm font-medium text-ink">
                {t.campaigns[survey.campaign] ?? survey.campaign}
              </span>
              <span className="ml-auto text-xs text-ink-muted">
                {t.customerPage.sent(formatDateTime(survey.sentAt))}
              </span>
              {survey.respondedAt ? (
                <span className="rounded-full bg-status-good/10 px-2 py-0.5 text-xs font-medium text-status-good-text">
                  {t.customerPage.responded}
                </span>
              ) : (
                <span className="rounded-full bg-ink-muted/10 px-2 py-0.5 text-xs font-medium text-ink-secondary">
                  {t.customerPage.noResponse}
                </span>
              )}
            </summary>
            <div className="mt-2 ml-5 rounded-lg bg-page p-3">
              {survey.respondedAt ? (
                <>
                  <div className="mb-1.5 text-xs text-ink-muted">
                    {t.customerPage.respondedVia(formatDateTime(survey.respondedAt))}
                  </div>
                  <dl className="space-y-1">
                    {Object.entries(survey.answers).map(([question, answer]) => (
                      <div key={question} className="text-xs">
                        <dt className="inline font-medium text-ink-secondary">
                          {t.surveyQuestions[question] ?? question.replaceAll('_', ' ')}:
                        </dt>{' '}
                        <dd className="inline text-ink">{answer}</dd>
                      </div>
                    ))}
                  </dl>
                </>
              ) : (
                <div className="text-xs text-ink-muted">{t.customerPage.noResponseBody}</div>
              )}
            </div>
          </details>
        </li>
      ))}
    </ul>
  )
}
