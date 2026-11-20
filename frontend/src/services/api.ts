const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
const ACCESS_TOKEN_KEY = 'opsdesk.accessToken'

export type TicketStatus = 'open' | 'pending' | 'resolved' | 'closed'
export type TicketPriority = 'low' | 'normal' | 'high' | 'urgent'
export type AuthUser = {
  id: number
  agency_id: number
  agency_name: string
  full_name: string
  email: string
  role: 'admin' | 'agent' | 'escalation_manager'
  is_demo: boolean
}

export type LoginResponse = {
  access_token: string
  token_type: 'bearer'
  expires_at: string
  user: AuthUser
}

export type Ticket = {
  id: number
  reference: string
  agency_id: number
  agency_name: string
  created_by_id: number
  created_by_name: string
  subject: string
  description: string | null
  region: string | null
  check_in_at: string | null
  departure_at: string | null
  status: TicketStatus
  priority: TicketPriority
  created_at: string
  updated_at: string
  resolved_at: string | null
  sla: TicketSLASummary
}

export type TicketSLASummary = {
  response_due_at: string
  resolution_due_at: string
  travel_deadline_at: string | null
  travel_deadline_type: 'check_in' | 'departure' | null
  travel_data_status: 'available' | 'missing'
  response_status: string
  resolution_status: string
  sla_status: 'on_track' | 'approaching' | 'travel_urgent' | 'breached' | 'met'
  response_remaining_seconds: number | null
  resolution_remaining_seconds: number | null
  evaluated_at: string
}

export type SLAOverview = TicketSLASummary & {
  ticket_id: number
  escalation_history: Array<{
    id: number
    rule_key: 'approaching' | 'breached'
    triggered_at: string
    assignment_id: number | null
    assigned_to: string | null
    summary: string
  }>
}

export type InsightsFilters = {
  date_from?: string
  date_to?: string
  agency_id?: number
  priority?: TicketPriority | ''
}
export type InsightsReport = {
  date_from: string | null
  date_to: string | null
  agency_id: number
  priority: TicketPriority | null
  total_tickets: number
  resolved_tickets: number
  average_resolution_hours: number | null
  resolution_time_sample_size: number
  sla_breach_rate: number | null
  sla_breached_tickets: number
  sla_sample_size: number
  conversation_tickets: number
  volume_over_time: Array<{ period: string; count: number }>
  priority_breakdown: Array<{ label: string; count: number }>
  status_breakdown: Array<{ label: string; count: number }>
  agency_issue_frequency: Array<{ key: string; count: number }>
  operational_area_frequency: Array<{ key: string; count: number }>
  recurring_themes: Array<{
    label: string
    terms: string[]
    ticket_frequency: number
    evidence_kind: 'inferred'
    similarity_threshold: number
    examples: Array<{ ticket_id: number; reference: string; subject: string; excerpt: string }>
  }>
  data_quality: {
    theme_status: 'available' | 'insufficient_data'
    theme_note: string
    resolved_text_sample_size: number
    public_conversation_ticket_count: number
    resolution_time_sample_size: number
    sla_sample_size: number
    invalid_resolution_timestamp_count: number
  }
}

export type AgencyOption = { id: number; name: string }
export type TicketAssignment = {
  id: number
  ticket_id: number
  agent_id: number
  agent_name: string
  agent_role: string
  agent_regions: string[]
  workload: number
  score: number | null
  explanation: string
  assigned_at: string
  candidate_scores: RoutingCandidateScore[]
}
export type RoutingCandidateScore = {
  agent_id: number
  agent_name: string
  agent_role: string
  regional_expertise: string[]
  available: boolean
  regional_match: 'exact' | 'global' | 'none'
  region_points: number
  priority_points: number
  workload: number
  workload_points: number
  availability_points: number
  total_score: number
  explanation: string
}
export type RelatedTicket = {
  id: number
  reference: string
  subject: string
  status: TicketStatus
  priority: TicketPriority
  created_at: string
  similarity_score: number
  explanation: string
  match_type: 'booking_reference' | 'content'
  is_linked: boolean
}

export type TicketFilters = {
  q?: string
  status?: TicketStatus | ''
  priority?: TicketPriority | ''
  limit?: number
  offset?: number
  risk?: 'at_risk' | 'breached' | ''
}

export type TicketDashboardSummary = { total: number; open: number; pending: number; urgent: number }
export type TicketPage = { tickets: Ticket[]; total: number }

async function request<T>(path: string, init?: RequestInit, onHeaders?: (headers: Headers) => void): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body = await response.json()
      message = typeof body.detail === 'string' ? body.detail : message
    } catch {
      // Keep the status-based message for non-JSON responses.
    }
    if (response.status === 401 && path !== '/auth/login') {
      clearAccessToken()
      window.dispatchEvent(new Event('opsdesk:unauthorized'))
    }
    throw new ApiError(message, response.status)
  }
  onHeaders?.(response.headers)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function getAccessToken(): string | null {
  return window.sessionStorage.getItem(ACCESS_TOKEN_KEY)
}

function storeAccessToken(token: string) {
  window.sessionStorage.setItem(ACCESS_TOKEN_KEY, token)
}

export function clearAccessToken() {
  window.sessionStorage.removeItem(ACCESS_TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function getApiHealth(): Promise<{ status: string; service: string }> {
  return request('/health')
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const result = await request<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  storeAccessToken(result.access_token)
  return result
}

export async function demoLogin(): Promise<LoginResponse> {
  const result = await request<LoginResponse>('/auth/demo', { method: 'POST' })
  storeAccessToken(result.access_token)
  return result
}

export async function getCurrentUser(): Promise<AuthUser> {
  return request('/auth/me')
}

export async function logout(): Promise<void> {
  try {
    await request<void>('/auth/logout', { method: 'POST' })
  } finally {
    clearAccessToken()
  }
}

export async function getTickets(filters: TicketFilters = {}): Promise<Ticket[]> {
  return requestTicketList(filters)
}

async function requestTicketList(filters: TicketFilters, onHeaders?: (headers: Headers) => void): Promise<Ticket[]> {
  const params = new URLSearchParams()
  if (filters.q) params.set('q', filters.q)
  if (filters.status) params.set('status', filters.status)
  if (filters.priority) params.set('priority', filters.priority)
  if (filters.risk) params.set('risk', filters.risk)
  if (filters.limit) params.set('limit', String(filters.limit))
  if (filters.offset) params.set('offset', String(filters.offset))
  const query = params.toString()
  return request(`/tickets${query ? `?${query}` : ''}`, undefined, onHeaders)
}

export async function getTicketPage(filters: TicketFilters = {}): Promise<TicketPage> {
  let total = 0
  const tickets = await requestTicketList(filters, (headers) => {
    const value = headers.get('X-Total-Count')
    if (value !== null && Number.isFinite(Number(value))) total = Number(value)
  })
  return { tickets, total }
}

export async function getTicketSummary(): Promise<TicketDashboardSummary> {
  return request('/tickets/summary')
}

export async function getTicket(ticketId: number): Promise<Ticket> {
  return request(`/tickets/${ticketId}`)
}

export async function createTicket(payload: {
  subject: string
  description: string | null
  region: string | null
  priority: TicketPriority
  check_in_at: string | null
  departure_at: string | null
}): Promise<Ticket> {
  return request('/tickets', { method: 'POST', body: JSON.stringify(payload) })
}

export async function updateTicket(
  ticketId: number,
  payload: Partial<Pick<Ticket, 'subject' | 'description' | 'status' | 'priority' | 'check_in_at' | 'departure_at'>>,
): Promise<Ticket> {
  return request(`/tickets/${ticketId}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export async function getTicketSLA(ticketId: number): Promise<SLAOverview> {
  return request(`/tickets/${ticketId}/sla`)
}

export async function getInsights(filters: InsightsFilters = {}): Promise<InsightsReport> {
  const params = new URLSearchParams()
  if (filters.date_from) params.set('date_from', filters.date_from)
  if (filters.date_to) params.set('date_to', filters.date_to)
  if (filters.agency_id) params.set('agency_id', String(filters.agency_id))
  if (filters.priority) params.set('priority', filters.priority)
  return request(`/insights${params.size ? `?${params.toString()}` : ''}`)
}

export async function getAgencies(): Promise<AgencyOption[]> {
  return request('/agencies')
}

export async function getRelatedTickets(ticketId: number): Promise<RelatedTicket[]> {
  return request(`/tickets/${ticketId}/related`)
}

export async function confirmTicketLink(ticketId: number, linkedTicketId: number): Promise<void> {
  await request(`/tickets/${ticketId}/links`, {
    method: 'POST',
    body: JSON.stringify({ linked_ticket_id: linkedTicketId }),
  })
}

export async function getCurrentAssignment(ticketId: number): Promise<TicketAssignment | null> {
  try {
    return await request(`/tickets/${ticketId}/assignment`)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404 && error.message.includes('no active assignment')) {
      return null
    }
    throw error
  }
}

export async function routeTicket(ticketId: number): Promise<TicketAssignment> {
  return request(`/tickets/${ticketId}/assign`, { method: 'POST' })
}
