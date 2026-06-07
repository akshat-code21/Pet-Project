'use client'
import { AnimatePresence } from 'framer-motion'
import { BellOff } from 'lucide-react'
import { AlertItem } from './AlertItem'
import { Skeleton } from '@/components/ui/skeleton'
import type { Alert } from '@/types/api'

interface AlertFeedProps {
  alerts: Alert[]
  loading?: boolean
  onMarkRead?: (id: string) => void
  emptyMessage?: string
}

export function AlertFeed({ alerts, loading, onMarkRead, emptyMessage }: AlertFeedProps) {
  if (loading) {
    return (
      <div className="space-y-3">
        {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
      </div>
    )
  }

  if (alerts.length === 0) {
    return (
      <div className="text-center py-10">
        <BellOff className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
        <p className="text-sm text-muted-foreground">{emptyMessage ?? 'No alerts'}</p>
      </div>
    )
  }

  return (
    <AnimatePresence>
      <div className="space-y-2">
        {alerts.map((alert, i) => (
          <AlertItem key={alert.id} alert={alert} index={i} onMarkRead={onMarkRead} />
        ))}
      </div>
    </AnimatePresence>
  )
}
