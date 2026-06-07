'use client'
import { use, useEffect } from 'react'
import { motion } from 'framer-motion'
import Link from 'next/link'
import { ArrowLeft, Calendar, Clock } from 'lucide-react'
import { Streamdown } from 'streamdown'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useReport, useMarkReportRead } from '@/hooks/useReports'
import { formatDate, formatRelative } from '@/lib/utils'

function cleanMarkdown(content: string): string {
  if (!content) return ''
  let cleaned = content.trim()
  
  // 1. Remove markdown code block fences if present (e.g. from LLM output wrapping)
  cleaned = cleaned.replace(/^```markdown\s*/i, '')
  cleaned = cleaned.replace(/```$/, '')
  cleaned = cleaned.trim()

  // 2. Strip redundant metadata header if it exists
  const hrIndex = cleaned.search(/^(?:---|___|\*\*\*)\s*$/m)
  if (hrIndex !== -1 && hrIndex < 500) {
    const afterHr = cleaned.slice(hrIndex).replace(/^(?:---|___|\*\*\*)\s*$/m, '').trim()
    return afterHr
  }

  return cleaned
}

export default function ReportDetailPage({ params }: { params: { id: string } }) {
  const { id } = params
  const { data: report, isLoading } = useReport(id)
  const { mutate: markRead } = useMarkReportRead()

  useEffect(() => {
    if (report && !report.is_read) markRead(id)
  }, [report?.id])

  if (isLoading) {
    return (
      <div className="space-y-6 max-w-3xl">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }
  if (!report) return <p className="text-muted-foreground">Report not found</p>

  // Hide summary if it contains raw generated metadata (common on legacy database records)
  const isMetadataSummary = report.summary?.includes('**Generated:**') || report.summary?.includes('**Period:**') || report.summary?.includes('**Date:**')
  const displaySummary = isMetadataSummary ? null : report.summary

  return (
    <div className="max-w-3xl space-y-6">
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
        <Link href="/reports">
          <Button variant="ghost" size="sm" className="mb-4 text-muted-foreground">
            <ArrowLeft className="w-4 h-4" /> Reports
          </Button>
        </Link>

        {/* Meta */}
        <div className="flex items-center gap-3 flex-wrap mb-3">
          <Badge variant={report.report_type === 'daily_digest' ? 'cyan' : 'default'}>
            {report.report_type.replace('_', ' ')}
          </Badge>
          {report.period_start && (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Calendar className="w-3.5 h-3.5" />
              {formatDate(report.period_start)} – {report.period_end ? formatDate(report.period_end) : 'present'}
            </span>
          )}
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="w-3.5 h-3.5" />
            {formatRelative(report.generated_at)}
          </span>
        </div>

        <h1 className="font-display font-bold text-3xl text-foreground">{report.title}</h1>
        {displaySummary && <p className="text-muted-foreground mt-2">{displaySummary}</p>}
      </motion.div>

      {/* Markdown content */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1 }}
        className="bg-card border border-border/50 rounded-2xl overflow-hidden"
      >
        <div className="p-8 prose-custom">
          <Streamdown>
            {cleanMarkdown(report.content_markdown)}
          </Streamdown>
        </div>
      </motion.div>
    </div>
  )
}

