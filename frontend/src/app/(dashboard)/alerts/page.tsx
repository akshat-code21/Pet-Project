'use client'
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { Bell, BellOff, CheckCheck, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useAlerts, useMarkAlertRead, useMarkAllAlertsRead } from '@/hooks/useAlerts'
import { useInvestors } from '@/hooks/useInvestors'
import { useToast } from '@/hooks/use-toast'
import { formatRelative, capitalise, cn } from '@/lib/utils'

const severityConfig = {
  critical: { variant: 'critical', dot: 'bg-red-500', ring: 'ring-red-500/20' },
  high: { variant: 'high', dot: 'bg-orange-500', ring: 'ring-orange-500/20' },
  medium: { variant: 'medium', dot: 'bg-amber-500', ring: 'ring-amber-500/20' },
  low: { variant: 'low', dot: 'bg-slate-400', ring: '' },
} as const

export default function AlertsPage() {
  const [severity, setSeverity] = useState<string>('all')
  const [investorId, setInvestorId] = useState<string>('all')
  const [unreadOnly, setUnreadOnly] = useState(false)
  const { data, isLoading } = useAlerts({
    severity: severity !== 'all' ? severity : undefined,
    investor_id: investorId !== 'all' ? investorId : undefined,
    unread_only: unreadOnly || undefined,
  })
  const { data: investors } = useInvestors()
  const { mutate: markRead } = useMarkAlertRead()
  const { mutate: markAll } = useMarkAllAlertsRead()
  const { toast } = useToast()

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="font-display font-bold text-3xl text-foreground">Alerts</h1>
          <p className="text-muted-foreground mt-1">
            {data?.unread_count ? (
              <span className="text-primary font-medium">{data.unread_count} unread</span>
            ) : 'All caught up'} · {data?.total ?? 0} total
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            variant={unreadOnly ? 'default' : 'outline'}
            size="sm"
            onClick={() => setUnreadOnly(!unreadOnly)}
          >
            <Bell className="w-4 h-4" />
            Unread only
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => { markAll(); toast({ title: 'All alerts marked as read' }) }}
          >
            <CheckCheck className="w-4 h-4" />
            Mark all read
          </Button>
          <Select value={severity} onValueChange={setSeverity}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All severities</SelectItem>
              <SelectItem value="critical">Critical</SelectItem>
              <SelectItem value="high">High</SelectItem>
              <SelectItem value="medium">Medium</SelectItem>
              <SelectItem value="low">Low</SelectItem>
            </SelectContent>
          </Select>
          <Select value={investorId} onValueChange={setInvestorId}>
            <SelectTrigger className="w-44">
              <SelectValue placeholder="All investors" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All investors</SelectItem>
              {(investors ?? []).map((inv) => (
                <SelectItem key={inv.id} value={inv.id}>{inv.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </motion.div>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
        </div>
      ) : data?.data.length === 0 ? (
        <div className="text-center py-16">
          <BellOff className="w-10 h-10 text-muted-foreground mx-auto mb-4 opacity-40" />
          <p className="text-foreground font-medium">No alerts</p>
          <p className="text-sm text-muted-foreground mt-1">
            {unreadOnly ? 'No unread alerts' : 'Alerts will appear here when events are detected'}
          </p>
        </div>
      ) : (
        <AnimatePresence>
          <div className="space-y-2">
            {data?.data.map((alert, i) => {
              const cfg = severityConfig[alert.severity]
              return (
                <motion.div
                  key={alert.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  transition={{ delay: i * 0.03 }}
                  onClick={() => !alert.is_read && markRead(alert.id)}
                  className={cn(
                    'flex items-start gap-4 p-4 rounded-xl border border-border/50 transition-all cursor-pointer',
                    !alert.is_read ? 'bg-card hover:border-primary/30' : 'opacity-60 hover:opacity-80',
                    cfg.ring && `ring-1 ${cfg.ring}`
                  )}
                >
                  {/* Severity dot */}
                  <div className="flex-shrink-0 flex flex-col items-center gap-1 mt-0.5">
                    <div className={cn('w-2.5 h-2.5 rounded-full', cfg.dot)} />
                    <span className="text-[9px] font-mono text-muted-foreground leading-none">
                      {alert.score}
                    </span>
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="font-medium text-sm text-foreground">{alert.title}</p>
                      <Badge variant={cfg.variant as any} className="text-[10px]">{alert.severity}</Badge>
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
            })}
          </div>
        </AnimatePresence>
      )}
    </div>
  )
}
