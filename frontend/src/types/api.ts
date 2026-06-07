export interface Investor {
  id: string
  name: string
  cik_number: string | null
  is_active: boolean
  last_synced_at: string | null
  created_at: string
  sources_count: number
}

export interface InvestorDetail extends Investor {
  stats: {
    content_count: number
    report_count: number
    unread_alerts: number
  }
}

export interface InvestorCreate {
  name: string
  cik_number?: string
}

export interface InvestorUpdate {
  name?: string
  cik_number?: string
  is_active?: boolean
}

export interface Source {
  id: string
  investor_id: string
  source_type: 'sec_13f' | 'website' | 'youtube' | 'rss' | 'twitter' | 'custom'
  url: string
  is_active: boolean
  check_frequency_hours: number
  consecutive_failures: number
  last_checked_at: string | null
  created_at: string
  config: Record<string, unknown>
}

export interface SourceCreate {
  source_type: Source['source_type']
  url: string
  check_frequency_hours?: number
}

export interface ContentItem {
  id: string
  investor_id: string
  content_type: 'filing' | 'article' | 'video' | 'newsletter' | 'website_page' | 'custom'
  title: string | null
  url: string | null
  processing_status: 'pending' | 'processing' | 'completed' | 'failed' | 'skipped'
  metadata: Record<string, unknown>
  created_at: string
}

export interface PortfolioChange {
  id: string
  investor_id: string
  ticker_symbol: string
  company_name: string | null
  cusip: string | null
  change_type: 'new_position' | 'increased' | 'decreased' | 'closed' | 'unchanged'
  shares_previous: number
  shares_current: number
  value_usd: number | null
  percent_of_portfolio: number | null
  filing_period: string
  report_date: string | null
  created_at: string
}

export interface Report {
  id: string
  investor_id: string | null
  investor_name: string | null
  report_type: 'investor_report' | 'daily_digest' | 'event_report'
  title: string
  summary: string | null
  is_read: boolean
  period_start: string | null
  period_end: string | null
  generated_at: string
}

export interface ReportDetail extends Report {
  content_markdown: string
  source_item_ids: string[]
}

export interface Alert {
  id: string
  investor_id: string | null
  investor_name: string | null
  content_item_id: string | null
  report_id: string | null
  alert_type: 'new_filing' | 'new_company_mention' | 'new_thesis' | 'high_conviction' | 'portfolio_change' | 'daily_digest_ready'
  title: string
  summary: string | null
  severity: 'low' | 'medium' | 'high' | 'critical'
  score: number
  is_read: boolean
  email_sent: boolean
  metadata: Record<string, unknown>
  created_at: string
}

export interface AlertListResponse {
  data: Alert[]
  unread_count: number
  total: number
}

export interface SearchRequest {
  query: string
  investor_id?: string
  limit?: number
}

export interface SearchResult {
  content_item_id: string
  chunk_text: string
  investor_name: string
  source_url: string
  similarity: number
}

export interface SearchResponse {
  results: SearchResult[]
  query: string
}

export interface PaginatedResponse<T> {
  data: T[]
  total: number
  limit: number
  offset: number
}
