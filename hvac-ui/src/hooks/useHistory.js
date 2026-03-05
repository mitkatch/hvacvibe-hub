// hooks/useHistory.js
// Fetches daily RMS history for a sensor from /api/history/{sensor_id}
// Re-fetches when sensor_id changes or on manual refresh.

import { useState, useEffect } from 'react'

export function useHistory(sensorId) {
  const [history,  setHistory]  = useState([])
  const [loading,  setLoading]  = useState(false)

  useEffect(() => {
    if (!sensorId) return
    setLoading(true)
    fetch(`/api/history/${sensorId}`)
      .then(r => r.json())
      .then(d => setHistory(d.history || []))
      .catch(e => console.warn('History fetch error', e))
      .finally(() => setLoading(false))
  }, [sensorId])

  return { history, loading }
}
