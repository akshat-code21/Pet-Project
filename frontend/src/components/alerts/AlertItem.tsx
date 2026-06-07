'use client'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { ExternalLink } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn, formatRelative, capitalise } from '@/lib/utils'
import type { Alert } from '@/types/api'

const severityConfig = {
  critical: { dot: 'bg-red-500', ring: 'ring-red-500/20' },
  high: { dot: 'bg-orange-500', ring: 'ring-orange-500/20' },
  medium: { dot: 'bg-amber-500', ring: 'ring-amber-500/20' },
  low: { dot: 'bg-slate-400', ring: '' },
} as const

interface AlertItemProps {
  alert: Alert
  index?: number
  onMarkRead?: (id: string) => void
}

export function AlertItem({ alert, index = 0, onMarkRead }: AlertItemProps) {
  const cfg = severityConfig[alert.severity]

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.03 }}
      onClick={() => !alert.is_read && onMarkRead?.(alert.id)}
      className={cn(
        'flex items-start gap-4 p-4 rounded-xl border border-border/50 transition-all cursor-pointer',
        !alert.is_read ? 'bg-card hover:border-primary/30' : 'opacity-60 hover:opacity-80',
        cfg.ring && `ring-1 ${cfg.ring}`
      )}
    >
      <div className="flex-shrink-0 flex flex-col items-center gap-1 mt-0.5">
        <div className={cn('w-2.5 h-2.5 rounded-full', cfg.dot)} />
        <span className="text-[9px] font-mono text-muted-foreground leading-none">{alert.score}</span>
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="font-medium text-sm text-foreground">{alert.title}</p>
          <Badge variant={cfg.dot.includes('red') ? 'destructive' : 'outline'} className="text-[10px]">
            {alert.severity}
          </Badge>
          <Badge variant="outline" className="text-[10px]">{capitalise(alert.alert_type)}</Badge>
        </div>
        {alert.summary && <p className="text-sm text-muted-foreground mt-0.5 line-clamp-2">{alert.summary}</p>}
        <div className="flex items-center gap-3 mt-1.5">
          <p className="text-xs text-muted-foreground/60">{formatRelative(alert.created_at)}</p>
          {alert.investor_name && (
            <span className="text-xs text-muted-foreground">· {alert.investor_name}</span>
          )}
          {alert.report_id && (
            <Link href={`/reports/${alert.report_id}`} onClick={(e) => e.stopPropagation()}>
              <span className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                <ExternalLink className="w-3 h-3" />
                View Report
              </span>
            </Link>
          )}
        </div>
      </div>

      {!alert.is_read && (
        <div className="flex-shrink-0 w-2 h-2 rounded-full bg-primary mt-2" />
      )}
    </motion.div>
  )
}
