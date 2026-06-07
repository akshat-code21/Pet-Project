'use client'
import { motion } from 'framer-motion'
import Link from 'next/link'
import { ArrowLeft, Edit, RefreshCw, FileText, Activity, Bell, Loader2, TrendingUp, TrendingDown, Minus, Plus, X, Cpu } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { useInvestor, useSyncInvestor } from '@/hooks/useInvestors'
import { useReports, useGenerateReport, REPORT_KEYS } from '@/hooks/useReports'
import { useAlerts } from '@/hooks/useAlerts'
import { SourceManager } from '@/components/investors/SourceManager'
import { TimelineFeed } from '@/components/investors/TimelineFeed'
import { contentApi, adminApi } from '@/lib/api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useToast } from '@/hooks/use-toast'

import { formatRelative, formatDate, formatCurrency, cn } from '@/lib/utils'
import type { PortfolioChange } from '@/types/api'
import { use } from 'react'

const changeConfig: Record<string, { label: string; icon: React.ElementType; color: string }> = {
  new_position: { label: 'New', icon: Plus, color: 'text-emerald-500 bg-emerald-500/10' },
  increased: { label: 'Increased', icon: TrendingUp, color: 'text-green-500 bg-green-500/10' },
  decreased: { label: 'Decreased', icon: TrendingDown, color: 'text-orange-500 bg-orange-500/10' },
  closed: { label: 'Closed', icon: X, color: 'text-red-500 bg-red-500/10' },
  unchanged: { label: 'Unchanged', icon: Minus, color: 'text-muted-foreground bg-muted' },
}

export default function InvestorDetailPage({ params }: { params: { id: string } }) {
  const { id } = params
  const { data: investor, isLoading } = useInvestor(id)
  const { data: reportsData } = useReports({ investor_id: id, limit: 10 })
  const { data: alertData } = useAlerts({ investor_id: id })
  const { mutate: sync, isPending: syncing } = useSyncInvestor()
  const { toast } = useToast()

  const queryClient = useQueryClient()
  const { mutate: generateReport, isPending: generatingReport } = useGenerateReport()

  const { mutate: triggerProcessing, isPending: triggeringProcessing } = useMutation({
    mutationFn: () => adminApi.triggerJob('process_pending').then(r => r.data),
    onSuccess: (res) => {
      if (res?.error) {
        toast({ title: 'Processing failed', description: res.error, variant: 'destructive' })
      } else {
        toast({ title: 'Processing triggered', description: 'Pipeline processing is running...' })
        queryClient.invalidateQueries({ queryKey: ['content', id] })
      }
    },
    onError: (err: any) => {
      toast({
        title: 'Error',
        description: err.response?.data?.error || err.message || 'Failed to trigger processing',
        variant: 'destructive',
      })
    }
  })

  const handleGenerateReport = () => {
    toast({
      title: 'Report generation started',
      description: 'The AI is analyzing content and generating the intelligence report. This may take 10-30 seconds...',
    })
    generateReport(id, {
      onSuccess: (res: any) => {
        if (res?.error) {
          toast({
            title: 'Failed to generate report',
            description: res.error,
            variant: 'destructive',
          })
        } else {
          toast({
            title: 'Report generated successfully',
            description: 'A new intelligence report is ready for this investor.',
          })
          queryClient.invalidateQueries({ queryKey: REPORT_KEYS.filtered({ investor_id: id, limit: 10 }) })
          queryClient.invalidateQueries({ queryKey: REPORT_KEYS.all })
        }
      },
      onError: (err: any) => {
        toast({
          title: 'Error',
          description: err.response?.data?.error || err.message || 'Failed to generate report',
          variant: 'destructive',
        })
      }
    })
  }


  const { data: contentItems, isLoading: loadingContent } = useQuery({
    queryKey: ['content', id],
    queryFn: () => contentApi.list(id, { limit: 20 }).then(r => r.data),
    enabled: !!id,
  })

  const hasPendingItems = (contentItems ?? []).some(
    item => item.processing_status === 'pending' || item.processing_status === 'processing'
  )


  const { data: portfolioChanges, isLoading: loadingPortfolio } = useQuery({
    queryKey: ['portfolio', id],
    queryFn: () => contentApi.portfolioChanges(id).then(r => r.data),
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

  // Group portfolio changes by filing period
  const portfolioByPeriod = (portfolioChanges ?? []).reduce<Record<string, PortfolioChange[]>>((acc, pc) => {
    ; (acc[pc.filing_period] ||= []).push(pc)
    return acc
  }, {})
  const periods = Object.keys(portfolioByPeriod).sort().reverse()

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
              onClick={handleGenerateReport}
              disabled={generatingReport}
              className="gap-1.5"
            >
              <FileText className={`w-4 h-4 ${generatingReport ? 'animate-spin' : ''}`} />
              {generatingReport ? 'Generating...' : 'Generate Report'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => { sync(id); toast({ title: 'Sync started', description: 'Fetching latest data...' }) }}
              disabled={syncing}
              className="gap-1.5"
            >
              <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
              {syncing ? 'Syncing...' : 'Sync'}
            </Button>
            <Link href={`/investors/${id}/edit`}>
              <Button variant="outline" size="sm" className="gap-1.5"><Edit className="w-4 h-4" /> Edit</Button>
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
          <TabsTrigger value="portfolio">Portfolio</TabsTrigger>
          <TabsTrigger value="sources">Sources</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
          <TabsTrigger value="alerts">Alerts</TabsTrigger>
        </TabsList>

        <TabsContent value="content">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-base">Content Timeline</CardTitle>
              {hasPendingItems && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => triggerProcessing()}
                  disabled={triggeringProcessing}
                  className="h-8 gap-1.5"
                >
                  <Cpu className={`w-3.5 h-3.5 ${triggeringProcessing ? 'animate-spin' : ''}`} />
                  {triggeringProcessing ? 'Processing...' : 'Process Content'}
                </Button>
              )}
            </CardHeader>
            <CardContent>
              <TimelineFeed items={contentItems ?? []} loading={loadingContent} />
            </CardContent>
          </Card>
        </TabsContent>


        {/* Portfolio Tab — 13F Holdings */}
        <TabsContent value="portfolio">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">13F Portfolio Holdings</CardTitle>
            </CardHeader>
            <CardContent>
              {loadingPortfolio ? (
                <div className="space-y-3">
                  {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}
                </div>
              ) : periods.length === 0 ? (
                <div className="text-center py-10">
                  <TrendingUp className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
                  <p className="text-sm text-muted-foreground">No 13F portfolio data yet</p>
                  <p className="text-xs text-muted-foreground/60 mt-1">Portfolio changes appear after SEC 13F filings are processed</p>
                </div>
              ) : (
                <div className="space-y-8">
                  {periods.map(period => {
                    const changes = portfolioByPeriod[period]
                    return (
                      <div key={period}>
                        <div className="flex items-center gap-2 mb-4">
                          <Badge variant="outline" className="text-xs font-mono">{period}</Badge>
                          <span className="text-xs text-muted-foreground">{changes.length} holdings</span>
                        </div>
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="border-b border-border/50 text-xs text-muted-foreground">
                                <th className="text-left py-2 pr-4 font-medium">Company</th>
                                <th className="text-left py-2 pr-4 font-medium">Ticker</th>
                                <th className="text-right py-2 pr-4 font-medium">Shares</th>
                                <th className="text-right py-2 pr-4 font-medium">Value</th>
                                <th className="text-right py-2 pr-4 font-medium">% Port</th>
                                <th className="text-center py-2 font-medium">Change</th>
                              </tr>
                            </thead>
                            <tbody>
                              {changes.map((pc) => {
                                const cfg = changeConfig[pc.change_type] || changeConfig.unchanged
                                const ChangeIcon = cfg.icon
                                return (
                                  <motion.tr
                                    key={pc.id}
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="border-b border-border/30 hover:bg-accent/30 transition-colors"
                                  >
                                    <td className="py-2.5 pr-4 text-foreground font-medium">{pc.company_name ?? '—'}</td>
                                    <td className="py-2.5 pr-4 font-mono text-xs text-primary">{pc.ticker_symbol}</td>
                                    <td className="py-2.5 pr-4 text-right tabular-nums text-muted-foreground">
                                      {pc.shares_current.toLocaleString()}
                                    </td>
                                    <td className="py-2.5 pr-4 text-right tabular-nums text-muted-foreground">
                                      {pc.value_usd != null ? formatCurrency(pc.value_usd * 1000) : '—'}
                                    </td>
                                    <td className="py-2.5 pr-4 text-right tabular-nums text-muted-foreground">
                                      {pc.percent_of_portfolio != null ? `${pc.percent_of_portfolio.toFixed(1)}%` : '—'}
                                    </td>
                                    <td className="py-2.5 text-center">
                                      <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium', cfg.color)}>
                                        <ChangeIcon className="w-3 h-3" />
                                        {cfg.label}
                                      </span>
                                    </td>
                                  </motion.tr>
                                )
                              })}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
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
                <div className="text-center py-8 space-y-3">
                  <FileText className="w-8 h-8 text-muted-foreground mx-auto opacity-40" />
                  <p className="text-sm text-muted-foreground">No reports generated yet</p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleGenerateReport}
                    disabled={generatingReport}
                    className="mx-auto gap-1.5"
                  >
                    <RefreshCw className={`w-4 h-4 ${generatingReport ? 'animate-spin' : ''}`} />
                    Generate First Report
                  </Button>
                </div>
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
                      <div className="flex items-center gap-3 mt-1">
                        <p className="text-xs text-muted-foreground/60">{formatRelative(alert.created_at)}</p>
                        {alert.report_id && (
                          <Link href={`/reports/${alert.report_id}`} onClick={(e) => e.stopPropagation()}>
                            <span className="text-xs text-primary hover:underline">View Report →</span>
                          </Link>
                        )}
                      </div>
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
