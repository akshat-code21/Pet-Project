import axios from 'axios'
import { getAccessToken } from './supabase'
import type {
  Investor, InvestorCreate, InvestorUpdate, InvestorDetail,
  Source, SourceCreate,
  ContentItem, PortfolioChange,
  Report, ReportDetail,
  AlertListResponse,
  SearchRequest, SearchResponse,
  PaginatedResponse,
} from '@/types/api'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
})

// Attach auth token to every request
apiClient.interceptors.request.use(async (config) => {
  const token = await getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// ── Auth ──────────────────────────────────────────────────────────────────────
export const authApi = {
  signup: (email: string, password: string, full_name?: string) =>
    apiClient.post('/auth/signup', { email, password, full_name }),
  login: (email: string, password: string) =>
    apiClient.post<{ access_token: string; user: { id: string; email: string } }>(
      '/auth/login', { email, password }
    ),
  logout: () => apiClient.post('/auth/logout'),
  me: () => apiClient.get('/auth/me'),
}

// ── Investors ─────────────────────────────────────────────────────────────────
export const investorsApi = {
  list: () => apiClient.get<Investor[]>('/investors'),
  get: (id: string) => apiClient.get<InvestorDetail>(`/investors/${id}`),
  create: (data: InvestorCreate) => apiClient.post<Investor>('/investors', data),
  update: (id: string, data: InvestorUpdate) => apiClient.patch<Investor>(`/investors/${id}`, data),
  delete: (id: string) => apiClient.delete(`/investors/${id}`),
  sync: (id: string) => apiClient.post(`/investors/${id}/sync`),
}

// ── Sources ───────────────────────────────────────────────────────────────────
export const sourcesApi = {
  list: (investorId: string) => apiClient.get<Source[]>(`/investors/${investorId}/sources`),
  create: (investorId: string, data: SourceCreate) =>
    apiClient.post<Source>(`/investors/${investorId}/sources`, data),
  delete: (investorId: string, sourceId: string) =>
    apiClient.delete(`/investors/${investorId}/sources/${sourceId}`),
}

// ── Content ───────────────────────────────────────────────────────────────────
export const contentApi = {
  list: (investorId: string, params?: { content_type?: string; limit?: number; offset?: number }) =>
    apiClient.get<ContentItem[]>(`/content`, { params: { investor_id: investorId, ...params } }),
  portfolioChanges: (investorId: string, params?: { filing_period?: string }) =>
    apiClient.get<PortfolioChange[]>(`/content/portfolio-changes`, { params: { investor_id: investorId, ...params } }),
}

// ── Reports ───────────────────────────────────────────────────────────────────
export const reportsApi = {
  list: (params?: { investor_id?: string; report_type?: string; limit?: number; offset?: number }) =>
    apiClient.get<PaginatedResponse<Report>>('/reports', { params }),
  get: (id: string) => apiClient.get<ReportDetail>(`/reports/${id}`),
  markRead: (id: string) => apiClient.patch(`/reports/${id}/read`),
  generate: (investorId: string) =>
    apiClient.post(`/reports/generate`, { investor_id: investorId }),
}

// ── Alerts ────────────────────────────────────────────────────────────────────
export const alertsApi = {
  list: (params?: { investor_id?: string; severity?: string; unread_only?: boolean }) =>
    apiClient.get<AlertListResponse>('/alerts', { params }),
  markRead: (id: string) => apiClient.patch(`/alerts/${id}/read`),
  markAllRead: () => apiClient.patch('/alerts/read-all'),
}

// ── Search ────────────────────────────────────────────────────────────────────
export const searchApi = {
  query: (data: SearchRequest) => apiClient.post<SearchResponse>('/search', data),
}

// ── Admin/Jobs ────────────────────────────────────────────────────────────────
export const adminApi = {
  getStatus: () => apiClient.get<{ data: { scheduler_running: boolean; jobs: any[]; pending_content_items: number } }>('/admin/jobs/status'),
  triggerJob: (job: string) => apiClient.post<{ message: string; result?: any; error?: string }>('/admin/jobs/trigger', { job }),
}

