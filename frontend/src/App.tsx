import { FormEvent, ReactNode, useCallback, useEffect, useState } from 'react'
import { Icon } from './components/Icon'
import {
  AuthUser,
  clearAccessToken,
  confirmTicketLink,
  createTicket,
  getApiHealth,
  getAccessToken,
  getCurrentUser,
  getCurrentAssignment,
  getRelatedTickets,
  getTicket,
  getTicketPage,
  getTicketSummary,
  getTicketSLA,
  getInsights,
  getAgencies,
  InsightsReport,
  AgencyOption,
  SLAOverview,
  Ticket,
  TicketDashboardSummary,
  TicketAssignment,
  TicketPriority,
  RelatedTicket,
  TicketStatus,
  updateTicket,
  routeTicket,
  login,
  logout,
} from './services/api'

const statuses: TicketStatus[] = ['open', 'pending', 'resolved', 'closed']
const priorities: TicketPriority[] = ['low', 'normal', 'high', 'urgent']

function TicketWorkspace({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const [activePage, setActivePage] = useState<'tickets' | 'insights'>(window.location.pathname === '/insights' ? 'insights' : 'tickets')
  const [apiStatus, setApiStatus] = useState<'checking' | 'connected' | 'offline'>('checking')
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [filteredTotal, setFilteredTotal] = useState(0)
  const [summary, setSummary] = useState<TicketDashboardSummary | null>(null)
  const [summaryError, setSummaryError] = useState('')
  const [page, setPage] = useState(0)
  const pageSize = 25
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<TicketStatus | ''>('')
  const [priorityFilter, setPriorityFilter] = useState<TicketPriority | ''>('')
  const [riskFilter, setRiskFilter] = useState<'' | 'at_risk' | 'breached'>('')
  const [reloadToken, setReloadToken] = useState(0)
  const [selectedTicketId, setSelectedTicketId] = useState<number | null>(ticketIdFromLocation)
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [subject, setSubject] = useState('')
  const [description, setDescription] = useState('')
  const [region, setRegion] = useState('')
  const [formPriority, setFormPriority] = useState<TicketPriority>('normal')
  const [checkInAt, setCheckInAt] = useState('')
  const [departureAt, setDepartureAt] = useState('')

  useEffect(() => {
    let active = true
    const checkHealth = () => getApiHealth()
      .then(() => { if (active) setApiStatus('connected') })
      .catch(() => { if (active) setApiStatus('offline') })
    void checkHealth()
    const timer = window.setInterval(() => { void checkHealth() }, 15_000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    const timer = window.setTimeout(() => {
      getTicketPage({
          q: search.trim() || undefined,
          status: statusFilter,
          priority: priorityFilter,
          risk: riskFilter,
          limit: pageSize,
          offset: page * pageSize,
        })
        .then(({ tickets: visibleTickets, total }) => {
          if (!active) return
          setTickets(visibleTickets)
          setFilteredTotal(total)
          setPage((current) => total === 0 ? 0 : Math.min(current, Math.ceil(total / pageSize) - 1))
        })
        .catch((requestError: Error) => {
          if (active) {
            setTickets([])
            setFilteredTotal(0)
            setError(requestError.message)
          }
        })
        .finally(() => {
          if (active) setLoading(false)
        })
    }, search ? 220 : 0)

    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [search, statusFilter, priorityFilter, riskFilter, reloadToken, page])

  useEffect(() => {
    let active = true
    getTicketSummary()
      .then((result) => { if (active) { setSummary(result); setSummaryError('') } })
      .catch((requestError: Error) => { if (active) { setSummary(null); setSummaryError(requestError.message) } })
    return () => { active = false }
  }, [reloadToken])

  useEffect(() => {
    const syncLocation = () => {
      setSelectedTicketId(ticketIdFromLocation())
      setActivePage(window.location.pathname === '/insights' ? 'insights' : 'tickets')
    }
    window.addEventListener('popstate', syncLocation)
    return () => window.removeEventListener('popstate', syncLocation)
  }, [])

  useEffect(() => {
    if (selectedTicketId === null) {
      setSelectedTicket(null)
      setDetailLoading(false)
      return
    }
    let active = true
    setSelectedTicket(null)
    setDetailLoading(true)
    setError('')
    getTicket(selectedTicketId)
      .then((ticket) => { if (active) setSelectedTicket(ticket) })
      .catch((requestError: Error) => { if (active) setError(requestError.message) })
      .finally(() => { if (active) setDetailLoading(false) })
    return () => { active = false }
  }, [selectedTicketId])

  const refresh = useCallback(() => setReloadToken((value) => value + 1), [])

  function updatePageFilter<T>(setter: (value: T) => void, value: T) {
    setPage(0)
    setter(value)
  }

  useEffect(() => {
    if (activePage !== 'tickets' || selectedTicketId !== null) return
    const timer = window.setInterval(refresh, 30_000)
    return () => window.clearInterval(timer)
  }, [refresh, activePage, selectedTicketId])

  function openTicket(ticketId: number) {
    setActivePage('tickets')
    window.history.pushState({}, '', `/tickets/${ticketId}`)
    setSelectedTicketId(ticketId)
  }

  function backToTickets() {
    setActivePage('tickets')
    window.history.pushState({}, '', '/tickets')
    setSelectedTicketId(null)
    setError('')
  }

  function navigateToTickets() {
    window.history.pushState({}, '', '/tickets')
    setActivePage('tickets')
    setSelectedTicketId(null)
    setSelectedTicket(null)
    setDetailLoading(false)
    setError('')
  }

  async function changeTicket(values: Partial<Pick<Ticket, 'status' | 'priority' | 'check_in_at' | 'departure_at'>>) {
    if (!selectedTicket) return
    setSaving(true)
    setError('')
    try {
      const updated = await updateTicket(selectedTicket.id, values)
      setSelectedTicket(updated)
      refresh()
    } catch (requestError) {
      setError((requestError as Error).message)
    } finally {
      setSaving(false)
    }
  }

  function openCreateForm() {
    setFormError('')
    setSubject('')
    setDescription('')
    setRegion('')
    setFormPriority('normal')
    setCheckInAt('')
    setDepartureAt('')
    setShowCreate(true)
  }

  async function submitTicket(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setFormError('')
    try {
      const created = await createTicket({
        subject,
        description: description.trim() || null,
        region: region.trim() || null,
        priority: formPriority,
        check_in_at: toISODateTime(checkInAt),
        departure_at: toISODateTime(departureAt),
      })
      setShowCreate(false)
      window.history.pushState({}, '', `/tickets/${created.id}`)
      setSelectedTicketId(created.id)
      setSelectedTicket(created)
      refresh()
    } catch (requestError) {
      setFormError((requestError as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/tickets" aria-label="OpsDesk home" onClick={(event) => { event.preventDefault(); navigateToTickets() }}>
          <span className="brand-mark"><Icon name="plane" size={19} /></span>
          <span>ops<span className="brand-light">desk</span></span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <div className="workspace-switcher"><span className="workspace-avatar">{user.agency_name.slice(0, 1).toUpperCase()}</span><span className="workspace-name">{user.agency_name}<small>Travel operations</small></span><Icon name="chevron" size={15} /></div>
        <div className="nav-label">MENU</div>
        <nav className="nav-list" aria-label="Main navigation">
          <a className={`nav-item ${activePage === 'insights' ? 'active' : ''}`} href="#insights" aria-label="Insights" title="Insights" aria-current={activePage === 'insights' ? 'page' : undefined} onClick={(event) => { event.preventDefault(); window.history.pushState({}, '', '/insights'); setSelectedTicketId(null); setActivePage('insights') }}><Icon name="grid" /><span>Insights</span></a>
          <a className={`nav-item ${activePage === 'tickets' ? 'active' : ''}`} href="#tickets" aria-label="Tickets" title="Tickets" aria-current={activePage === 'tickets' ? 'page' : undefined} onClick={(event) => { event.preventDefault(); navigateToTickets() }}><Icon name="file" /><span>Tickets</span></a>
          <button className="nav-item muted coming-soon-nav" type="button" disabled aria-label="Bookings, coming soon" title="Bookings, coming soon"><Icon name="plane" /><span>Bookings</span><span className="coming-soon">Coming Soon</span></button>
          <button className="nav-item muted coming-soon-nav" type="button" disabled aria-label="Travelers, coming soon" title="Travelers, coming soon"><Icon name="users" /><span>Travelers</span><span className="coming-soon">Coming Soon</span></button>
        </nav>
        <div className="sidebar-bottom">
          <button className="nav-item muted coming-soon-nav" type="button" disabled aria-label="Settings, coming soon" title="Settings, coming soon"><Icon name="settings" /><span>Settings</span><span className="coming-soon">Coming Soon</span></button>
          <div className="profile-card"><div className="profile-avatar">{user.full_name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()}</div><div className="profile-info"><strong>{user.full_name}</strong><span>{capitalize(user.role.replace('_', ' '))}</span></div></div>
        </div>
      </aside>

      <main className="main-area" id="tickets">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><Icon name="chevron" size={14} /><strong>{activePage === 'insights' ? 'Feedback & Insights' : selectedTicket ? selectedTicket.reference : 'Tickets'}</strong></div>
          <div className="topbar-actions"><label className="api-indicator"><span className={apiStatus} />{apiStatus === 'checking' ? 'Connecting' : apiStatus === 'connected' ? 'API connected' : 'API offline'}</label><span className="signed-in-user">{user.full_name}</span><button className="logout-button" onClick={onLogout}>Log out</button></div>
        </header>

        <div className="page-content">
          {activePage === 'insights' ? <InsightsDashboard user={user} /> : selectedTicketId !== null ? (
            selectedTicket ? <TicketDetails
              ticket={selectedTicket}
              currentUser={user}
              saving={saving}
              error={error}
              onBack={backToTickets}
              onChange={changeTicket}
            /> : <div className="detail-loading">{detailLoading ? 'Loading ticket…' : error || 'Ticket not found.'}<button className="back-link" onClick={backToTickets}>Back to tickets</button></div>
          ) : (
            <>
              <section className="tickets-heading"><div><div className="eyebrow">TRAVEL OPERATIONS</div><h1>Tickets</h1><p>Keep every traveler request organized from first message to resolution.</p></div><button className="primary-button mobile-create-ticket" aria-label="Create ticket" onClick={openCreateForm}><span aria-hidden="true">＋</span><span className="create-ticket-label">Create ticket</span></button></section>

              <section className="ticket-metrics" aria-label="Ticket summary">
                <Metric label="All tickets" value={summary?.total ?? '—'} icon="file" tone="blue" />
                <Metric label="Open" value={summary?.open ?? '—'} icon="grid" tone="violet" />
                <Metric label="Pending" value={summary?.pending ?? '—'} icon="bell" tone="amber" />
                <Metric label="Urgent priority" value={summary?.urgent ?? '—'} icon="arrow" tone="red" />
                {summaryError && <p className="summary-error" role="status">Ticket totals are unavailable. {summaryError}</p>}
              </section>

              <section className="ticket-table-panel">
                <div className="panel-heading"><div><h2>All tickets</h2><p>Search and filter your operations queue</p></div><span className="result-count">{loading ? 'Loading…' : `${filteredTotal} ${filteredTotal === 1 ? 'ticket' : 'tickets'} found`}</span></div>
                <div className="ticket-filters">
                  <label className="ticket-search"><Icon name="search" size={16} /><input value={search} onChange={(event) => updatePageFilter(setSearch, event.target.value)} placeholder="Search by subject, reference or details" aria-label="Search tickets" />{search && <button onClick={() => updatePageFilter(setSearch, '')} aria-label="Clear search">×</button>}</label>
                  <select value={statusFilter} onChange={(event) => updatePageFilter(setStatusFilter, event.target.value as TicketStatus | '')} aria-label="Filter by status"><option value="">All statuses</option>{statuses.map((status) => <option key={status} value={status}>{capitalize(status)}</option>)}</select>
                  <select value={priorityFilter} onChange={(event) => updatePageFilter(setPriorityFilter, event.target.value as TicketPriority | '')} aria-label="Filter by priority"><option value="">All priorities</option>{priorities.map((priority) => <option key={priority} value={priority}>{capitalize(priority)}</option>)}</select>
                  <select value={riskFilter} onChange={(event) => updatePageFilter(setRiskFilter, event.target.value as typeof riskFilter)} aria-label="Filter by SLA risk"><option value="">All SLA states</option><option value="at_risk">At risk</option><option value="breached">Breached</option></select>
                </div>
                <p className="table-scroll-hint">Scroll horizontally to view all ticket details.</p>
                <div className="table-scroll" role="region" aria-label="Ticket table. Scroll horizontally to view all columns." tabIndex={0}><table className="ticket-table"><thead><tr><th>TICKET</th><th>AGENCY</th><th>CREATED BY</th><th>PRIORITY</th><th>STATUS</th><th>SLA</th><th>CREATED</th><th /></tr></thead><tbody>
                  {loading ? <tr><td colSpan={8}><div className="empty-state" role="status">Loading tickets…</div></td></tr> : error ? <tr><td colSpan={8}><div className="empty-state error-empty" role="alert"><strong>Tickets could not be loaded</strong><p>{error}</p><button className="secondary-button" onClick={refresh}>Retry</button></div></td></tr> : tickets.map((ticket) => <tr key={ticket.id} onClick={() => openTicket(ticket.id)}><td><button className="ticket-title-cell"><strong>{ticket.subject}</strong><small>{ticket.reference}</small></button></td><td>{ticket.agency_name}</td><td>{ticket.created_by_name}</td><td><PriorityBadge priority={ticket.priority} /></td><td><StatusBadge status={ticket.status} /></td><td><SLABadge status={ticket.sla.sla_status} /></td><td>{formatDate(ticket.created_at)}</td><td><button className="row-open" aria-label={`View ${ticket.reference}`} onClick={(event) => { event.stopPropagation(); openTicket(ticket.id) }}><Icon name="chevron" size={16} /></button></td></tr>)}
                  {!loading && !error && tickets.length === 0 && <tr><td colSpan={8}><div className="empty-state"><span className="empty-icon"><Icon name="file" size={20} /></span><strong>{summary?.total === 0 ? 'Your queue is ready' : 'No tickets match these filters'}</strong><p>{summary?.total === 0 ? 'Create a ticket to start tracking a traveler request.' : 'Try changing your search or filters.'}</p>{summary?.total === 0 && <button className="primary-button compact" onClick={openCreateForm}>Create ticket</button>}</div></td></tr>}
                </tbody></table></div>
                {!loading && !error && <div className="ticket-pagination"><span>{filteredTotal === 0 ? 'No tickets to show' : `Showing ${page * pageSize + 1}–${Math.min((page + 1) * pageSize, filteredTotal)} of ${filteredTotal}`}</span><div><button className="secondary-button" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button><span>Page {page + 1} of {Math.max(1, Math.ceil(filteredTotal / pageSize))}</span><button className="secondary-button" disabled={(page + 1) * pageSize >= filteredTotal} onClick={() => setPage((value) => value + 1)}>Next</button></div></div>}
              </section>
              <footer className="footer"><span>{user.agency_name} · Travel operations</span><span>Ticket management</span><span>Signed in as {user.role.replace('_', ' ')}</span></footer>
            </>
          )}
        </div>
      </main>

      {showCreate && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowCreate(false) }}><section className="ticket-modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><header className="modal-heading"><div><span className="eyebrow">NEW REQUEST</span><h2 id="create-title">Create a ticket</h2><p>Capture the details your team needs to take action.</p></div><button className="modal-close" onClick={() => setShowCreate(false)} aria-label="Close">×</button></header><form onSubmit={submitTicket}>
        {formError && <div className="form-error" role="alert">{formError}</div>}
        <label className="form-field">Subject<input autoFocus required maxLength={240} value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="What does the traveler need help with?" /></label>
        <label className="form-field">Description <span className="optional">Optional</span><textarea maxLength={10000} rows={4} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Add relevant context, booking details or next steps" /></label>
        <label className="form-field">Region <span className="optional">Optional · used for routing expertise</span><input maxLength={80} value={region} onChange={(event) => setRegion(event.target.value)} placeholder="For example, Europe or North America" /></label>
        <div className="form-row"><label className="form-field">Booking check-in <span className="optional">Optional</span><input type="datetime-local" value={checkInAt} onChange={(event) => setCheckInAt(event.target.value)} /></label><label className="form-field">Departure <span className="optional">Optional</span><input type="datetime-local" value={departureAt} onChange={(event) => setDepartureAt(event.target.value)} /></label></div>
        <label className="form-field">Priority<select value={formPriority} onChange={(event) => setFormPriority(event.target.value as TicketPriority)}>{priorities.map((priority) => <option key={priority} value={priority}>{capitalize(priority)}</option>)}</select></label>
        <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>Cancel</button><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Creating…' : 'Create ticket'}</button></div>
      </form></section></div>}
    </div>
  )
}

function InsightsDashboard({ user }: { user: AuthUser }) {
  const today = new Date().toISOString().slice(0, 10)
  const ninetyDaysAgo = new Date(Date.now() - 89 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
  const [dateFrom, setDateFrom] = useState(ninetyDaysAgo)
  const [dateTo, setDateTo] = useState(today)
  const [agencyId, setAgencyId] = useState(user.agency_id)
  const [priority, setPriority] = useState<TicketPriority | ''>('')
  const [agencies, setAgencies] = useState<AgencyOption[]>([])
  const [retryToken, setRetryToken] = useState(0)
  const [reportState, setReportState] = useState<{
    key: string
    report: InsightsReport | null
    loading: boolean
    error: string
  }>({ key: '', report: null, loading: true, error: '' })
  const reportRequestKey = `${dateFrom}|${dateTo}|${agencyId}|${priority}|${retryToken}`
  const currentReportState = reportState.key === reportRequestKey ? reportState : null
  const report = currentReportState?.report ?? null
  const loading = !currentReportState || currentReportState.loading
  const error = currentReportState?.error ?? ''

  useEffect(() => { getAgencies().then(setAgencies).catch(() => setAgencies([])) }, [])
  useEffect(() => {
    let active = true
    setReportState({ key: reportRequestKey, report: null, loading: true, error: '' })
    getInsights({ date_from: dateFrom || undefined, date_to: dateTo || undefined, agency_id: agencyId, priority })
      .then((data) => {
        if (active) setReportState({ key: reportRequestKey, report: data, loading: false, error: '' })
      })
      .catch((requestError: Error) => {
        if (active) setReportState({ key: reportRequestKey, report: null, loading: false, error: requestError.message })
      })
      .finally(() => {
        if (active) setReportState((current) => current.key === reportRequestKey ? { ...current, loading: false } : current)
      })
    return () => { active = false }
  }, [dateFrom, dateTo, agencyId, priority, retryToken, reportRequestKey])

  const maxVolume = Math.max(1, ...(report?.volume_over_time.map((point) => point.count) ?? []))
  const maxArea = Math.max(1, ...(report?.operational_area_frequency.map((item) => item.count) ?? []))

  return <section className="insights-page">
    <div className="insights-heading"><div><span className="eyebrow">SERVICE QUALITY</span><h1>Feedback &amp; Insights</h1><p>Measured service outcomes and inferred recurring complaint themes for {user.agency_name}.</p></div><span className="measured-tag">Measured data</span></div>
    <section className="insights-filters" aria-label="Insight filters">
      <label>Date from<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
      <label>Date to<input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
      <label>Agency<select value={agencyId} onChange={(event) => setAgencyId(Number(event.target.value))}>{agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></label>
      <label>Priority<select value={priority} onChange={(event) => setPriority(event.target.value as TicketPriority | '')}><option value="">All priorities</option>{priorities.map((value) => <option key={value} value={value}>{capitalize(value)}</option>)}</select></label>
    </section>
    {loading ? <div className="insights-loading" role="status">Loading measured ticket data…</div> : error ? <div className="error-banner" role="alert"><span>{error}</span><button className="secondary-button" onClick={() => setRetryToken((value) => value + 1)}>Retry</button></div> : report && <>
      <div className="insight-metrics">
        <InsightMetric label="Tickets created" value={String(report.total_tickets)} note="In selected period" />
        <InsightMetric label="Resolved tickets" value={String(report.resolved_tickets)} note="Current resolved or closed status" />
        <InsightMetric label="Average resolution" value={report.average_resolution_hours === null ? '—' : `${report.average_resolution_hours}h`} note={`${report.resolution_time_sample_size} with resolution timestamps`} />
        <InsightMetric label="SLA breach rate" value={report.sla_breach_rate === null ? '—' : `${(report.sla_breach_rate * 100).toFixed(1)}%`} note={`${report.sla_breached_tickets} / ${report.sla_sample_size} evaluated tickets`} />
      </div>
      <div className="insights-grid">
        <section className="insights-card volume-card"><header><div><h2>Ticket volume</h2><p>Measured tickets by creation month</p></div><span className="measured-tag">Measured</span></header>
          {report.volume_over_time.length ? <div className="volume-chart" role="img" aria-label="Ticket volume by month">{report.volume_over_time.map((point) => <div className="volume-column" key={point.period}><strong>{point.count}</strong><div className="volume-track"><i style={{ height: `${Math.max(4, point.count / maxVolume * 100)}%` }} /></div><span>{point.period}</span></div>)}</div> : <InsightsEmpty>There are no tickets in this date range.</InsightsEmpty>}
        </section>
        <section className="insights-card breakdown-card"><header><div><h2>Priority breakdown</h2><p>Measured ticket count by priority</p></div><span className="measured-tag">Measured</span></header>
          {report.priority_breakdown.length ? <div className="breakdown-list">{report.priority_breakdown.map((item) => <div className="breakdown-item" key={item.label}><span>{capitalize(item.label)}</span><div><i style={{ width: `${Math.max(4, item.count / Math.max(1, report.total_tickets) * 100)}%` }} /></div><strong>{item.count}</strong></div>)}</div> : <InsightsEmpty>No priority data for this period.</InsightsEmpty>}
          <div className="mini-status">{report.status_breakdown.map((item) => <span key={item.label}>{capitalize(item.label)} <strong>{item.count}</strong></span>)}</div>
        </section>
        <section className="insights-card themes-card"><header><div><h2>Recurring complaint themes</h2><p>Local TF-IDF similarity over resolved ticket text and public conversations</p></div><span className="inferred-tag">Inferred</span></header>
          <div className="theme-disclosure">Themes are inferred patterns, not measured classifications. {report.data_quality.theme_note}</div>
          {report.recurring_themes.length ? <div className="theme-list">{report.recurring_themes.map((theme) => <article className="theme-item" key={theme.label}><div className="theme-title"><div><h3>{theme.label}</h3><span>{theme.ticket_frequency} tickets · terms: {theme.terms.join(', ')}</span></div><span className="theme-frequency">{theme.ticket_frequency}</span></div><div className="theme-examples">{theme.examples.map((example) => <blockquote key={example.ticket_id}><span>{example.reference} · {example.subject}</span><p>{example.excerpt}</p></blockquote>)}</div></article>)}</div> : <InsightsEmpty>{report.data_quality.theme_note}</InsightsEmpty>}
          <small className="theme-sample">Resolved tickets with usable text: {report.data_quality.resolved_text_sample_size}. Public conversation data available for {report.data_quality.public_conversation_ticket_count} tickets.</small>
        </section>
        <section className="insights-card area-card"><header><div><h2>Where issues occur</h2><p>Measured resolved ticket frequency by operational area</p></div><span className="measured-tag">Measured</span></header>
          {report.operational_area_frequency.length ? <div className="breakdown-list">{report.operational_area_frequency.slice(0, 7).map((item) => <div className="breakdown-item" key={item.key}><span>{item.key}</span><div><i style={{ width: `${Math.max(4, item.count / maxArea * 100)}%` }} /></div><strong>{item.count}</strong></div>)}</div> : <InsightsEmpty>Tickets do not have operational area (region) values in this period.</InsightsEmpty>}
          <div className="agency-frequency"><h3>Resolved issue frequency by agency (within your access)</h3>{report.agency_issue_frequency.length ? report.agency_issue_frequency.map((item) => <span key={item.key}>{item.key}<strong>{item.count}</strong></span>) : <InsightsEmpty>No resolved agency ticket data.</InsightsEmpty>}</div>
        </section>
      </div>
      <p className="insights-footnote">Resolution time uses recorded resolution timestamps only ({report.data_quality.resolution_time_sample_size} of {report.resolved_tickets} resolved tickets). SLA rate uses evaluated tickets only ({report.data_quality.sla_sample_size} samples).{report.data_quality.invalid_resolution_timestamp_count ? ` ${report.data_quality.invalid_resolution_timestamp_count} invalid timestamp(s) were excluded.` : ''}</p>
    </>}
  </section>
}

function InsightMetric({ label, value, note }: { label: string; value: string; note: string }) {
  return <article className="insight-metric"><span>{label}</span><strong>{value}</strong><small>{note}</small></article>
}

function InsightsEmpty({ children }: { children: ReactNode }) { return <div className="insights-empty">{children}</div> }

function Metric({ label, value, icon, tone }: { label: string; value: number | string; icon: 'file' | 'grid' | 'bell' | 'arrow'; tone: string }) {
  return <article className="ticket-metric"><div className="metric-top"><span>{label}</span><span className={`metric-icon ${tone}`}><Icon name={icon} size={17} /></span></div><strong>{value}</strong></article>
}

function PriorityBadge({ priority }: { priority: TicketPriority }) {
  return <span className={`priority-badge ${priority}`}><i />{capitalize(priority)}</span>
}

function StatusBadge({ status }: { status: TicketStatus }) {
  return <span className={`ticket-status ${status}`}><i />{capitalize(status)}</span>
}

function SLABadge({ status }: { status: Ticket['sla']['sla_status'] }) {
  const label = status === 'travel_urgent' ? 'Travel urgent' : status.replace('_', ' ')
  return <span className={`sla-badge ${status}`}>{capitalize(label)}</span>
}

function TicketDetails({ ticket, currentUser, saving, error, onBack, onChange }: {
  ticket: Ticket
  currentUser: AuthUser
  saving: boolean
  error: string
  onBack: () => void
  onChange: (values: Partial<Pick<Ticket, 'status' | 'priority'>>) => Promise<void>
}) {
  const [assignment, setAssignment] = useState<TicketAssignment | null>(null)
  const [assignmentLoading, setAssignmentLoading] = useState(true)
  const [assignmentError, setAssignmentError] = useState('')
  const [routeBusy, setRouteBusy] = useState(false)
  const [sla, setSla] = useState<SLAOverview | null>(null)
  const [slaLoading, setSlaLoading] = useState(true)
  const [slaError, setSlaError] = useState('')
  const [slaRetryToken, setSlaRetryToken] = useState(0)
  const canManage = currentUser.role === 'admin' || currentUser.role === 'escalation_manager'
  const isAssignedAgent = currentUser.role === 'agent' && assignment?.agent_id === currentUser.id
  const canEdit = canManage || isAssignedAgent
  const canLinkCases = canManage || isAssignedAgent

  useEffect(() => {
    let active = true
    setAssignmentLoading(true)
    setAssignmentError('')
    setAssignment(null)
    getCurrentAssignment(ticket.id)
      .then((current) => { if (active) setAssignment(current) })
      .catch((requestError: Error) => { if (active) setAssignmentError(requestError.message) })
      .finally(() => { if (active) setAssignmentLoading(false) })
    return () => { active = false }
  }, [ticket.id, ticket.priority, ticket.status, ticket.region])

  useEffect(() => {
    let active = true
    setSla(null)
    setSlaLoading(true)
    setSlaError('')
    const refreshSla = () => getTicketSLA(ticket.id)
      .then((result) => {
        if (active) {
          setSla(result)
          setSlaError('')
        }
      })
      .catch((requestError: Error) => { if (active) setSlaError(requestError.message) })
      .finally(() => { if (active) setSlaLoading(false) })
    void refreshSla()
    const timer = window.setInterval(refreshSla, 30_000)
    return () => { active = false; window.clearInterval(timer) }
  }, [ticket.id, ticket.updated_at, slaRetryToken])

  async function assignTicket() {
    if (!canManage) return
    setRouteBusy(true)
    setAssignmentError('')
    try {
      setAssignment(await routeTicket(ticket.id))
    } catch (requestError) {
      setAssignmentError((requestError as Error).message)
    } finally {
      setRouteBusy(false)
    }
  }

  return <section className="ticket-detail-page">
    <button className="back-link" onClick={onBack}><Icon name="chevron" size={15} /> Back to tickets</button>
    <div className="detail-heading"><div><div className="eyebrow">{ticket.reference} <span className="detail-dot">·</span> CREATED {formatDate(ticket.created_at).toUpperCase()}</div><h1>{ticket.subject}</h1><p>Agency: {ticket.agency_name} <span>·</span> Created by {ticket.created_by_name}{ticket.region && <> <span>·</span> Region: {ticket.region}</>}</p></div><StatusBadge status={ticket.status} /></div>
    {error && <div className="error-banner" role="alert">{error}</div>}
    <div className="detail-layout"><section className="detail-main-card"><div className="panel-heading"><div><h2>Ticket details</h2><p>Request information and context</p></div></div><div className="detail-description">{ticket.description || <span className="muted-copy">No description was provided.</span>}</div><div className="detail-meta"><div><span>Reference</span><strong>{ticket.reference}</strong></div><div><span>Region</span><strong>{ticket.region || 'Not specified'}</strong></div><div><span>Created</span><strong>{formatDateTime(ticket.created_at)}</strong></div><div><span>Last updated</span><strong>{formatDateTime(ticket.updated_at)}</strong></div></div></section>
      <aside className="detail-controls"><div className="panel-heading"><div><h2>Manage ticket</h2><p>{canEdit ? 'Changes save immediately' : 'Read only'}</p></div></div>{canEdit ? <><label className="form-field">Status<select disabled={saving} value={ticket.status} onChange={(event) => void onChange({ status: event.target.value as TicketStatus })}>{statuses.map((status) => <option key={status} value={status}>{capitalize(status)}</option>)}</select></label><label className="form-field">Priority<select disabled={saving} value={ticket.priority} onChange={(event) => void onChange({ priority: event.target.value as TicketPriority })}>{priorities.map((priority) => <option key={priority} value={priority}>{capitalize(priority)}</option>)}</select></label>{saving && <span className="save-hint">Saving changes…</span>}</> : <span className="routing-hint">Agents can update tickets assigned to them.</span>}
        <div className="assignment-summary"><span className="assignment-label">CURRENT ASSIGNEE</span>{assignmentLoading ? <span className="muted-copy">Checking assignment…</span> : assignment ? <><strong>{assignment.agent_name}</strong><span className="assignment-role">{capitalize(assignment.agent_role.replace('_', ' '))}{assignment.score !== null ? ` · ${assignment.score} routing points` : ''}</span><p>{assignment.explanation}</p></> : <span className="muted-copy">No active assignment</span>}</div>
        {assignment?.candidate_scores?.length ? <section className="routing-candidates"><div className="routing-candidates-heading"><strong>Eligible candidates compared</strong><span>{assignment.candidate_scores.length} available</span></div><p className="routing-candidates-note">Live scores for this ticket. Higher totals rank first; ties use lower workload, then user ID.</p>{assignment.candidate_scores.map((candidate) => <article className={`routing-candidate ${candidate.agent_id === assignment.agent_id ? 'selected' : ''}`} key={candidate.agent_id}><div className="routing-candidate-top"><div><strong>{candidate.agent_name}</strong><span>{capitalize(candidate.agent_role.replace('_', ' '))} · Available</span></div><b>{candidate.total_score}<small> pts</small></b></div><div className={`routing-region-fit ${candidate.regional_match}`}>{candidate.regional_match === 'exact' ? `Exact region match · ${candidate.regional_expertise.join(', ')}` : candidate.regional_match === 'global' ? 'Global expertise fallback' : 'No matching regional expertise'}</div><div className="routing-score-breakdown"><span>Region <b>+{candidate.region_points}</b></span><span>Priority <b>+{candidate.priority_points}</b></span><span>Workload <b>+{candidate.workload_points}</b> ({candidate.workload})</span><span>Availability <b>+{candidate.availability_points}</b></span></div>{candidate.agent_id === assignment.agent_id && <span className="routing-selected-label">Currently assigned</span>}</article>)}</section> : null}
        {assignmentError && <div className="form-error" role="alert">{assignmentError}</div>}
        {canManage && <button className="primary-button routing-button" onClick={() => void assignTicket()} disabled={routeBusy || assignmentLoading}>{routeBusy ? 'Selecting agent…' : assignment ? 'Reassign ticket' : 'Assign ticket'}</button>}
      </aside>
    </div>
    {slaLoading && !sla && <div className="sla-loading" role="status">Loading SLA information…</div>}
    {sla && <section className={`sla-panel ${sla.sla_status}`}><div className="panel-heading"><div><h2>Travel-aware SLA</h2><p>Calculated from ticket priority and any saved booking event</p></div><SLABadge status={sla.sla_status} /></div><div className="sla-clock-grid"><article><span>First response</span><strong>{sla.response_status === 'met' ? 'Responded on time' : sla.response_status === 'breached' ? 'Response SLA breached' : formatRemaining(sla.response_remaining_seconds)}</strong><small>Due {formatDateTime(sla.response_due_at)}</small></article><article><span>Resolution</span><strong>{sla.resolution_status === 'met' ? 'Resolved on time' : sla.resolution_status === 'breached' ? 'Resolution SLA breached' : formatRemaining(sla.resolution_remaining_seconds)}</strong><small>Due {formatDateTime(sla.resolution_due_at)}</small></article></div><div className={`travel-data-note ${sla.travel_data_status}`}><strong>{sla.travel_data_status === 'missing' ? 'Travel deadline unavailable' : `Travel deadline: ${sla.travel_deadline_type === 'check_in' ? 'booking check-in' : 'departure'}`}</strong><span>{sla.travel_data_status === 'missing' ? 'No check-in or departure time was provided. This is missing travel context, not an SLA breach.' : `The saved travel event is ${formatDateTime(sla.travel_deadline_at!)} and is used to cap both SLA deadlines.`}</span></div><div className="sla-history"><h3>Escalation history</h3>{sla.escalation_history.length ? sla.escalation_history.map((event) => <article key={event.id}><span className={`sla-history-dot ${event.rule_key}`} /><div><strong>{capitalize(event.rule_key)} escalation</strong><p>{event.summary}</p><small>{formatDateTime(event.triggered_at)}{event.assigned_to ? ` · Assigned to ${event.assigned_to}` : ''}</small></div></article>) : <p className="muted-copy">No SLA escalations recorded.</p>}</div></section>}
    {slaError && <div className="error-banner" role="alert"><span>{slaError}</span><button onClick={() => setSlaRetryToken((value) => value + 1)}>Retry SLA</button></div>}
    <RelatedCases ticketId={ticket.id} canLink={canLinkCases} />
  </section>
}

function RelatedCases({ ticketId, canLink }: { ticketId: number; canLink: boolean }) {
  const [matches, setMatches] = useState<RelatedTicket[]>([])
  const [loading, setLoading] = useState(true)
  const [linkingId, setLinkingId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [retryToken, setRetryToken] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setMatches([])
    setError('')
    setSuccess('')
    getRelatedTickets(ticketId)
      .then((items) => { if (active) setMatches(items) })
      .catch((requestError: Error) => { if (active) setError(requestError.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [ticketId, retryToken])

  async function linkCase(relatedId: number) {
    setLinkingId(relatedId)
    setError('')
    setSuccess('')
    try {
      await confirmTicketLink(ticketId, relatedId)
      setMatches((items) => items.map((item) => item.id === relatedId ? { ...item, is_linked: true } : item))
      setSuccess('Case linked successfully.')
      try {
        setMatches(await getRelatedTickets(ticketId))
      } catch {
        setError('The case was linked, but the suggestions could not be refreshed. Reload this panel to see the latest state.')
      }
    } catch (requestError) {
      setError((requestError as Error).message)
    } finally {
      setLinkingId(null)
    }
  }

  return <section className="related-cases-panel"><div className="panel-heading"><div><h2>Related Cases</h2><p>Suggested from matching booking references and ticket content</p></div><span className="result-count">{loading ? 'Checking…' : `${matches.length} ${matches.length === 1 ? 'match' : 'matches'}`}</span></div>
    {error && <div className="related-error" role="alert"><span>{error}</span><button className="secondary-button" onClick={() => setRetryToken((value) => value + 1)}>Retry suggestions</button></div>}
    {success && <div className="related-success" role="status">{success}</div>}
    {!canLink && !loading && matches.some((match) => !match.is_linked) && <div className="link-permission-note">Linking requires an admin or escalation manager role, or an agent assignment to this ticket.</div>}
    {!loading && !matches.length && !error && <div className="related-empty">No related tickets found for this case.</div>}
    <div className="related-list">{matches.map((match) => <article className="related-case" key={match.id}><div className="related-case-main"><div className="related-case-top"><span className="related-reference">{match.reference}</span><span className={`match-kind ${match.match_type}`}>{match.match_type === 'booking_reference' ? 'Exact booking reference' : 'Content match'}</span></div><strong>{match.subject}</strong><p>{match.explanation}</p></div><div className="related-score"><strong>{Math.round(match.similarity_score * 100)}%</strong><span>similarity</span></div>{match.is_linked ? <button className="linked-case-button" disabled aria-label={`${match.reference} is linked`}>Linked</button> : <button className="link-case-button" onClick={() => void linkCase(match.id)} disabled={linkingId !== null || !canLink} title={!canLink ? 'Linking requires an authorized role or ticket assignment.' : undefined}>{linkingId === match.id ? 'Linking…' : 'Link case'}</button>}</article>)}</div>
  </section>
}

function capitalize(value: string) { return value.charAt(0).toUpperCase() + value.slice(1) }
function ticketIdFromLocation(): number | null {
  const match = window.location.pathname.match(/^\/tickets\/(\d+)\/?$/)
  return match ? Number(match[1]) : null
}
function formatDate(value: string) { return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value)) }
function formatDateTime(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
function toISODateTime(value: string) { return value ? new Date(value).toISOString() : null }
function formatRemaining(seconds: number | null) {
  if (seconds === null) return 'Not available'
  if (seconds < 0) return `Overdue by ${formatDuration(-seconds)}`
  return `${formatDuration(seconds)} remaining`
}
function formatDuration(seconds: number) {
  const totalMinutes = Math.floor(seconds / 60)
  const days = Math.floor(totalMinutes / 1440)
  const hours = Math.floor((totalMinutes % 1440) / 60)
  const minutes = totalMinutes % 60
  return [days ? `${days}d` : '', hours ? `${hours}h` : '', `${minutes}m`].filter(Boolean).join(' ')
}

function App() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [checkingSession, setCheckingSession] = useState(true)

  useEffect(() => {
    let active = true
    const clearSession = () => {
      clearAccessToken()
      setUser(null)
      setCheckingSession(false)
    }
    window.addEventListener('opsdesk:unauthorized', clearSession)
    if (!getAccessToken()) {
      setCheckingSession(false)
    } else {
      getCurrentUser()
        .then((currentUser) => { if (active) setUser(currentUser) })
        .catch(() => { if (active) clearAccessToken() })
        .finally(() => { if (active) setCheckingSession(false) })
    }
    return () => {
      active = false
      window.removeEventListener('opsdesk:unauthorized', clearSession)
    }
  }, [])

  async function handleLogin(email: string, password: string) {
    const response = await login(email, password)
    setUser(response.user)
  }

  async function handleLogout() {
    try {
      await logout()
    } catch {
      clearAccessToken()
    }
    setUser(null)
  }

  if (checkingSession) return <div className="auth-loading">Loading your OpsDesk workspace…</div>
  if (!user) return <LoginPage onLogin={handleLogin} />
  return <TicketWorkspace key={user.id} user={user} onLogout={() => void handleLogout()} />
}

function LoginPage({ onLogin }: { onLogin: (email: string, password: string) => Promise<void> }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await onLogin(email, password)
    } catch {
      setError('Email or password was not recognized.')
    } finally {
      setSubmitting(false)
    }
  }

  return <main className="login-screen"><section className="login-brand-side"><a className="brand" href="#login"><span className="brand-mark"><Icon name="plane" size={19} /></span><span>ops<span className="brand-light">desk</span></span></a><div className="login-intro"><span className="eyebrow">TRAVEL OPERATIONS</span><h1>Welcome back to a clearer way to work.</h1><p>Bring every traveler request and operational detail into one secure workspace.</p></div><div className="login-decoration"><span className="login-orbit" /><span className="login-orbit inner" /><span className="login-plane"><Icon name="plane" size={27} /></span></div><span className="login-copyright">OpsDesk · Travel operations</span></section><section className="login-form-side"><form className="login-card" onSubmit={submit}><div className="login-mobile-brand"><span className="brand-mark"><Icon name="plane" size={18} /></span> opsdesk</div><span className="eyebrow">YOUR WORKSPACE</span><h2>Sign in to OpsDesk</h2><p>Enter your work email and password to continue.</p>{error && <div className="form-error" role="alert">{error}</div>}<label className="form-field">Work email<input type="email" required autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@agency.com" /></label><label className="form-field">Password<input type="password" required autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" /></label><button className="primary-button login-submit" type="submit" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in'}<Icon name="arrow" size={15} /></button><span className="login-security-note"><i /> Secure, agency-scoped access</span></form></section></main>
}

export default App
