'use client'
import { motion } from 'framer-motion'
import Link from 'next/link'
import { ArrowLeft, Edit, RefreshCw, FileText, Activity, Bell, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { useInvestor, useSyncInvestor } from '@/hooks/useInvestors'
import { useReports } from '@/hooks/useReports'
import { useAlerts } from '@/hooks/useAlerts'
import { SourceManager } from '@/components/investors/SourceManager'
import { TimelineFeed } from '@/components/investors/TimelineFeed'
import { contentApi } from '@/lib/api'
import { useQuery } from '@tanstack/react-query'
import { useToast } from '@/hooks/use-toast'
import { formatRelative, formatDate } from '@/lib/utils'

export default function InvestorDetailPage({ params }: { params: { id: string } }) {
  const { id } = params
  const { data: investor, isLoading } = useInvestor(id)
  const { data: reportsData } = useReports({ investor_id: id, limit: 10 })
  const { data: alertData } = useAlerts({ investor_id: id })
  const { mutate: sync, isPending: syncing } = useSyncInvestor()
  const { toast } = useToast()

  const { data: contentItems, isLoading: loadingContent } = useQuery({
    queryKey: ['content', id],
    queryFn: () => contentApi.list(id, { limit: 20 }).then(r => r.data),
    enabled: !!id,
  })

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
        </div>
        <Skeleton className="h-64 rounded-xl" />
      </div>
    )
  }

  if (!investor) return <p className="text-muted-foreground">Investor not found</p>

  return (
    <div className="space-y-6">
      {/* Header */}
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
        <Link href="/investors">
          <Button variant="ghost" size="sm" className="mb-4 text-muted-foreground">
            <ArrowLeft className="w-4 h-4" /> Investors
          </Button>
        </Link>

        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500/20 to-violet-500/20 flex items-center justify-center border border-border/50">
              <span className="font-display font-bold text-2xl text-primary">{investor.name[0]}</span>
            </div>
            <div>
              <h1 className="font-display font-bold text-3xl text-foreground">{investor.name}</h1>
              {investor.cik_number && (
                <p className="text-sm font-mono text-muted-foreground">CIK {investor.cik_number}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => { sync(id); toast({ title: 'Sync started', description: 'Fetching latest data...' }) }}
              disabled={syncing}
            >
              <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
              {syncing ? 'Syncing...' : 'Sync'}
            </Button>
            <Link href={`/investors/${id}/edit`}>
              <Button variant="outline" size="sm"><Edit className="w-4 h-4" /> Edit</Button>
            </Link>
          </div>
        </div>
      </motion.div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { label: 'Content Items', value: investor.stats?.content_count ?? 0, icon: Activity, color: 'text-indigo-500' },
          { label: 'Reports', value: investor.stats?.report_count ?? 0, icon: FileText, color: 'text-violet-500' },
          { label: 'Unread Alerts', value: investor.stats?.unread_alerts ?? 0, icon: Bell, color: 'text-amber-500' },
        ].map(({ label, value, icon: Icon, color }, i) => (
          <motion.div key={label} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.07 }}>
            <Card className="p-5">
              <div className="flex items-center gap-3">
                <Icon className={`w-5 h-5 ${color}`} />
                <div>
                  <p className="font-display font-bold text-2xl text-foreground">{value}</p>
                  <p className="text-xs text-muted-foreground">{label}</p>
                </div>
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* Tabs */}
      <Tabs defaultValue="content">
        <TabsList>
          <TabsTrigger value="content">Content</TabsTrigger>
          <TabsTrigger value="sources">Sources</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
          <TabsTrigger value="alerts">Alerts</TabsTrigger>
        </TabsList>

        <TabsContent value="content">
          <Card>
            <CardHeader><CardTitle className="text-base">Content Timeline</CardTitle></CardHeader>
            <CardContent>
              <TimelineFeed items={contentItems ?? []} loading={loadingContent} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="sources">
          <Card>
            <CardContent className="pt-6">
              <SourceManager investorId={id} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="reports">
          <Card>
            <CardContent className="pt-6 space-y-3">
              {reportsData?.data.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">No reports yet</p>
              ) : (
                reportsData?.data.map((r, i) => (
                  <motion.div key={r.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.04 }}>
                    <Link href={`/reports/${r.id}`}>
                      <div className="p-4 rounded-xl border border-border/50 hover:border-primary/30 hover:bg-accent/30 transition-all cursor-pointer">
                        <div className="flex items-center gap-2 mb-1">
                          <Badge variant="default" className="text-[10px]">{r.report_type.replace('_', ' ')}</Badge>
                          {!r.is_read && <div className="w-1.5 h-1.5 rounded-full bg-primary" />}
                        </div>
                        <p className="font-medium text-sm text-foreground">{r.title}</p>
                        {r.period_start && <p className="text-xs text-muted-foreground mt-1">{formatDate(r.period_start)} — {r.period_end ? formatDate(r.period_end) : 'present'}</p>}
                      </div>
                    </Link>
                  </motion.div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="alerts">
          <Card>
            <CardContent className="pt-6 space-y-2">
              {alertData?.data.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">No alerts for this investor</p>
              ) : (
                alertData?.data.map((alert, i) => (
                  <motion.div
                    key={alert.id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.04 }}
                    className="flex items-start gap-3 p-3 rounded-xl border border-border/50 hover:bg-accent/30 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-foreground">{alert.title}</p>
                        <Badge variant={alert.severity as any} className="text-[10px]">{alert.severity}</Badge>
                      </div>
                      {alert.summary && <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">{alert.summary}</p>}
                      <p className="text-xs text-muted-foreground/60 mt-1">{formatRelative(alert.created_at)}</p>
                    </div>
                    {!alert.is_read && <div className="w-2 h-2 rounded-full bg-primary mt-2 flex-shrink-0" />}
                  </motion.div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
