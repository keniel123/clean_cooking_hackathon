import { useEffect, useState } from 'react'

export interface AsyncData<T> {
  data: T | null
  loading: boolean
  error: Error | null
}

/**
 * Minimal data-fetching hook over the DataProvider. `fn` is re-run whenever
 * `deps` change; stale responses from superseded runs are discarded.
 */
export function useAsyncData<T>(fn: () => Promise<T>, deps: unknown[]): AsyncData<T> {
  const [state, setState] = useState<AsyncData<T>>({ data: null, loading: true, error: null })

  useEffect(() => {
    let stale = false
    setState((s) => ({ ...s, loading: true, error: null }))
    fn().then(
      (data) => {
        if (!stale) setState({ data, loading: false, error: null })
      },
      (error: unknown) => {
        if (!stale) {
          setState({
            data: null,
            loading: false,
            error: error instanceof Error ? error : new Error(String(error)),
          })
        }
      },
    )
    return () => {
      stale = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}
