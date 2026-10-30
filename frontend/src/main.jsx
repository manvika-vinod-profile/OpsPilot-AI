import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, AlertTriangle, CheckCircle2, CircleDot, Cpu, RefreshCw, Server, ShieldCheck, Terminal, Zap } from 'lucide-react'
import './styles.css'

const api = async (path, options) => {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) } })
  if (!response.ok) throw new Error(`Request failed (${response.status})`)
  return response.json()
}

const fmt = value => value ? new Date(value).toLocaleString() : '—'

function App() {
  const [summary, setSummary] = useState(null)
  const [services, setServices] = useState([])
  const [logs, setLogs] = useState([])
  const [incidents, setIncidents] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState('incidents')

  async function refresh() {
    try {
      const [s, a, l, i] = await Promise.all([
        api('/api/summary'), api('/api/services'), api('/api/logs?limit=40'), api('/api/incidents')
      ])
      setSummary(s); setServices(a); setLogs(l); setIncidents(i); setError('')
    } catch (e) { setError(`Cannot connect to the API: ${e.message}. Start the backend on port 8000.`) }
  }
  useEffect(() => { refresh(); const timer = setInterval(refresh, 12000); return () => clearInterval(timer) }, [])

  async function act(fn) {
    setBusy(true)
    try { await fn(); await refresh() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const openIncidents = incidents.filter(i => i.status === 'open')
  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brandmark"><Activity size={22} /></span><span>OpsPilot <b>AI</b><small>OPERATIONS CONSOLE</small></span></div>
      <div className="sideheading">WORKSPACE</div>
      <button className="nav active"><CircleDot size={17}/> Overview</button>
      <div className="sideheading second">ENVIRONMENT</div>
      <div className="sideinfo"><span className="online"/> Development environment</div>
      <div className="sidebarfoot"><ShieldCheck size={17}/> Local demo · No authentication</div>
    </aside>
    <main className="content">
      <header className="topbar"><div className="breadcrumbs">Workspace <span>/</span> Overview</div><div className="topright"><span className="live"><span className="online"/> DEMO LIVE</span><button className="iconbtn" onClick={refresh} aria-label="Refresh"><RefreshCw size={17}/></button></div></header>
      <div className="page">
        <div className="hero"><div><div className="eyebrow">SYSTEM OBSERVABILITY</div><h1>Operations Overview</h1><p>Monitor service health, inspect logs, and respond to incidents.</p></div><button className="primary" disabled={busy} onClick={() => act(() => api('/api/simulate', {method:'POST'}))}><Zap size={17}/>{busy ? 'Working...' : 'Generate test event'}</button></div>
        {error && <div className="error" role="alert">{error}</div>}
        <div className="metrics">
          <Metric label="MONITORED SERVICES" number={summary?.services ?? '—'} icon={<Server/>} note="Registered in this workspace" />
          <Metric label="HEALTHY SERVICES" number={summary?.healthy_services ?? '—'} icon={<CheckCircle2/>} note="No open incidents" good />
          <Metric label="ACTIVE INCIDENTS" number={summary?.open_incidents ?? '—'} icon={<AlertTriangle/>} note="Awaiting resolution" alert={!!summary?.open_incidents} />
          <Metric label="EVENTS / LAST HOUR" number={summary?.logs_last_hour ?? '—'} icon={<Activity/>} note="Incoming log events" />
        </div>
        <div className="columns">
          <section className="panel"><div className="paneltitle"><div><h2>Service Health</h2><p>Registered application services</p></div><span className="count">{services.length} total</span></div><div className="servicegrid">{services.map(s => <div className="service" key={s.id}><span className="serviceicon"><Cpu size={18}/></span><div><b>{s.name}</b><small>Production simulation</small></div><span className={'status ' + (s.status === 'healthy' ? 'healthy' : 'degraded')}>{s.status}</span></div>)}</div></section>
          <section className="panel"><div className="paneltitle"><div><h2>Incident Snapshot</h2><p>Detection and triage summary</p></div><span className="count">Rule based</span></div><div className="incidentStat"><div className="big">{openIncidents.length}</div><div><b>Open incidents</b><small>Triggered by ERROR / CRITICAL log events</small></div></div><div className="explain"><ShieldCheck size={18}/><div><b>Explainable diagnostics</b><p>Suggestions are generated using transparent rules. They are not AI-generated root-cause conclusions.</p></div></div></section>
        </div>
        <section className="panel full"><div className="paneltitle tableheading"><div><h2>Investigation Center</h2><p>Inspect detected incidents or raw events</p></div><div className="tabs"><button className={activeTab==='incidents'?'selected':''} onClick={()=>setActiveTab('incidents')}>Incidents ({incidents.length})</button><button className={activeTab==='logs'?'selected':''} onClick={()=>setActiveTab('logs')}>Event Logs ({logs.length})</button></div></div>
        {activeTab === 'incidents' ? <div className="tablewrap"><table><thead><tr><th>INCIDENT</th><th>SERVICE</th><th>SEVERITY</th><th>STATUS</th><th>TIME</th><th>ACTION</th></tr></thead><tbody>{incidents.map(i => <React.Fragment key={i.id}><tr><td className="titlecell">#{i.id} {i.title}</td><td>{i.service_name}</td><td><span className={'pill '+i.severity}>{i.severity}</span></td><td><span className={'pill '+i.status}>{i.status}</span></td><td>{fmt(i.created_at)}</td><td>{i.status==='open'?<button className="resolve" disabled={busy} onClick={()=>act(()=>api(`/api/incidents/${i.id}`,{method:'PATCH',body:JSON.stringify({status:'resolved'})}))}>Resolve</button>:<span className="muted">Closed</span>}</td></tr><tr className="insight"><td colSpan="6"><b>Suggested investigation:</b> {i.summary}</td></tr></React.Fragment>)}{!incidents.length&&<tr><td colSpan="6" className="empty">No incidents yet. Generate a test event.</td></tr>}</tbody></table></div> : <div className="tablewrap"><table><thead><tr><th>LEVEL</th><th>SERVICE</th><th>MESSAGE</th><th>TIMESTAMP</th></tr></thead><tbody>{logs.map(l=><tr key={l.id}><td><span className={'pill '+l.level.toLowerCase()}>{l.level}</span></td><td>{l.service_name}</td><td className="titlecell">{l.message}</td><td>{fmt(l.created_at)}</td></tr>)}{!logs.length&&<tr><td colSpan="4" className="empty">No logs found.</td></tr>}</tbody></table></div>}
        </section>
        <footer><Terminal size={14}/> OpsPilot AI v0.1 · Functional portfolio MVP · FastAPI + React + SQLite</footer>
      </div>
    </main>
  </div>
}
function Metric({ label, number, icon, note, good, alert }) { return <div className="metric"><div className="metrichead"><span>{label}</span><span className={'metricicon '+(good?'good':alert?'alert':'')}>{icon}</span></div><strong>{number}</strong><small>{note}</small></div> }

createRoot(document.getElementById('root')).render(<App />)
