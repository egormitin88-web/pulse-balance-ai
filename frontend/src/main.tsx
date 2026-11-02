import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type User = { id: number; email: string; full_name: string; role: 'CLIENT' | 'ADMIN' }
type Plan = { id: number; name: string; price_rub: number; duration_days: number; description: string; benefits: Record<string, unknown>; freeze_days: number; services: string[] }
type ClassItem = { id: number; service: string; service_code: string; trainer: string | null; starts_at: string; ends_at: string; capacity: number; free_places: number; status: string }
type Booking = { id: number; status: string; class: ClassItem }
type Fact = { id: number; category: string; key: string; value: string; source: string; updated_at: string }
type Conversation = { id: number; title: string; updated_at: string }
type ChatMessage = { id?: number; role: 'user' | 'assistant'; content: string }
type PendingAction = { id: string; type: 'BOOK' | 'CANCEL'; target_id: number; expires_at: string }
type Membership = { id: number; plan: Plan; starts_at: string; ends_at: string; status: string }
type Service = { id: number; code: string; name: string; duration_minutes: number }
type Trainer = { id: number; full_name: string; specialty: string }
type AuditEvent = { id: number; actor_user_id: number | null; action: string; target_type: string; target_id: string; created_at: string }

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch('/api' + path, {
    ...options,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  let data: any
  try { data = await response.json() } catch { data = {} }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить запрос')
  return data as T
}

const formatMoney = (value: number) => new Intl.NumberFormat('ru-RU').format(value) + ' ₽'
const formatDate = (value: string) => new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
const formatDay = (value: string) => new Intl.DateTimeFormat('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date(value))
const memoryLabels: Record<string, string> = {
  fitness_goal: 'Цель', monthly_budget_rub: 'Бюджет в месяц', preferred_days: 'Удобные дни',
  preferred_time: 'Удобное время', favorite_class: 'Любимое занятие', preferred_format: 'Формат',
  disliked_class: 'Не нравится', service_interest: 'Интерес', discussed_plan: 'Обсуждённый тариф',
}

function App() {
  const [page, setPage] = useState<'home' | 'schedule' | 'chat' | 'account' | 'admin'>('home')
  const [user, setUser] = useState<User | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [services, setServices] = useState<Service[]>([])
  const [trainers, setTrainers] = useState<Trainer[]>([])
  const [schedule, setSchedule] = useState<ClassItem[]>([])
  const [bookings, setBookings] = useState<Booking[]>([])
  const [membership, setMembership] = useState<Membership | null>(null)
  const [facts, setFacts] = useState<Fact[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([])
  const [chatText, setChatText] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [authMode, setAuthMode] = useState<'login' | 'register' | null>(null)
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [authName, setAuthName] = useState('')
  const [serviceFilter, setServiceFilter] = useState('')
  const [adminUsers, setAdminUsers] = useState<User[]>([])
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null)
  const [adminFacts, setAdminFacts] = useState<Fact[]>([])
  const [keyConfigured, setKeyConfigured] = useState(false)
  const [keyStorage, setKeyStorage] = useState<'system' | 'memory' | null>(null)
  const [keyValue, setKeyValue] = useState('')
  const [adminPlanId, setAdminPlanId] = useState<number | null>(null)
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([])
  const [profileName, setProfileName] = useState('')
  const [editPlanId, setEditPlanId] = useState<number | null>(null)
  const [editPlanPrice, setEditPlanPrice] = useState('')
  const [editPlanDescription, setEditPlanDescription] = useState('')
  const [newServiceId, setNewServiceId] = useState<number | null>(null)
  const [newTrainerId, setNewTrainerId] = useState<number | null>(null)
  const [newClassTime, setNewClassTime] = useState('')
  const [newClassCapacity, setNewClassCapacity] = useState('12')

  const showError = (error: unknown) => setNotice(error instanceof Error ? error.message : 'Произошла ошибка')

  const loadPublic = async () => {
    try {
      const [p, s, v, t] = await Promise.all([api<Plan[]>('/plans'), api<ClassItem[]>('/schedule'), api<Service[]>('/services'), api<Trainer[]>('/trainers')])
      setPlans(p); setSchedule(s); setServices(v); setTrainers(t)
    } catch (error) { showError(error) }
  }

  const loadPrivate = async (nextUser: User | null) => {
    try {
      const c = await api<Conversation[]>('/conversations'); setConversations(c)
      if (nextUser?.role === 'CLIENT') {
        const [m, b, f] = await Promise.all([
          api<{ membership: Membership | null }>('/membership'), api<Booking[]>('/bookings'), api<Fact[]>('/memory'),
        ]); setMembership(m.membership); setBookings(b); setFacts(f)
      } else { setMembership(null); setBookings([]); setFacts([]) }
      if (nextUser?.role === 'ADMIN') {
        const [u, k, a] = await Promise.all([api<User[]>('/admin/users'), api<{ configured: boolean; storage: 'system' | 'memory' | null }>('/admin/key'), api<AuditEvent[]>('/admin/audit')])
        setAdminUsers(u); setKeyConfigured(k.configured); setKeyStorage(k.storage); setAuditEvents(a)
      }
    } catch (error) { showError(error) }
  }

  useEffect(() => {
    api<{ user: User | null }>('/auth/me').then(({ user: u }) => { setUser(u); loadPrivate(u) }).catch(showError)
    loadPublic()
  }, [])

  const auth = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setNotice('')
    try {
      const path = authMode === 'register' ? '/auth/register' : '/auth/login'
      const u = await api<User>(path, { method: 'POST', body: JSON.stringify({ email: authEmail, password: authPassword, ...(authMode === 'register' ? { full_name: authName } : {}) }) })
      setUser(u); setAuthMode(null); setAuthPassword(''); setConversationId(null); setMessages([]); setPendingActions([])
      await loadPrivate(u)
      setPage(u.role === 'ADMIN' ? 'admin' : 'account')
    } catch (error) { showError(error) } finally { setBusy(false) }
  }

  const logout = async () => {
    try {
      await api('/auth/logout', { method: 'POST' })
      setUser(null); setMessages([]); setConversationId(null); setPendingActions([]); setPage('home')
      await loadPrivate(null)
    } catch (error) { showError(error) }
  }

  const openConversation = async (id: number) => {
    try {
      const c = await api<{ id: number; messages: ChatMessage[] }>('/conversations/' + id)
      setConversationId(c.id); setMessages(c.messages); setPendingActions([]); setPage('chat')
    } catch (error) { showError(error) }
  }

  const newConversation = () => { setConversationId(null); setMessages([]); setPendingActions([]); setPage('chat') }

  const sendChat = async (event: React.FormEvent) => {
    event.preventDefault()
    const message = chatText.trim()
    if (!message || busy) return
    setChatText(''); setBusy(true); setNotice('')
    setMessages(previous => [...previous, { role: 'user', content: message }])
    try {
      const result = await api<{ conversation_id: number; answer: string; actions: PendingAction[]; remembered: unknown[] }>('/chat', {
        method: 'POST', body: JSON.stringify({ conversation_id: conversationId, message }),
      })
      setConversationId(result.conversation_id)
      setMessages(previous => [...previous, { role: 'assistant', content: result.answer }])
      setPendingActions(result.actions)
      if (result.remembered.length) setNotice('Новое предпочтение сохранено в памяти. Его можно изменить в кабинете.')
      await loadPrivate(user)
    } catch (error) {
      setMessages(previous => previous.slice(0, -1)); setChatText(message); showError(error)
    } finally { setBusy(false) }
  }

  const confirmAction = async (action: PendingAction) => {
    setBusy(true)
    try {
      await api('/actions/' + action.id + '/confirm', { method: 'POST' })
      setPendingActions(previous => previous.filter(a => a.id !== action.id))
      setNotice(action.type === 'BOOK' ? 'Вы записаны на занятие.' : 'Запись отменена.')
      await loadPrivate(user); await loadPublic()
    } catch (error) { showError(error) } finally { setBusy(false) }
  }

  const book = async (classId: number) => {
    setBusy(true)
    try {
      await api('/bookings', { method: 'POST', body: JSON.stringify({ class_id: classId }) })
      setNotice('Вы записаны на занятие.'); await loadPrivate(user); await loadPublic()
    } catch (error) { showError(error) } finally { setBusy(false) }
  }

  const cancelBooking = async (bookingId: number) => {
    if (!window.confirm('Отменить запись на занятие?')) return
    setBusy(true)
    try {
      await api('/bookings/' + bookingId, { method: 'DELETE' })
      setNotice('Запись отменена.'); await loadPrivate(user); await loadPublic()
    } catch (error) { showError(error) } finally { setBusy(false) }
  }

  const removeFact = async (factId: number) => {
    if (!window.confirm('Удалить это предпочтение из памяти?')) return
    try { await api('/memory/' + factId, { method: 'DELETE' }); setFacts(previous => previous.filter(f => f.id !== factId)); setNotice('Предпочтение удалено.') }
    catch (error) { showError(error) }
  }

  const editFact = async (fact: Fact) => {
    const value = window.prompt('Новое значение', fact.value)
    if (!value?.trim()) return
    try {
      await api('/memory', { method: 'PUT', body: JSON.stringify({ category: fact.category, key: fact.key, value: value.trim() }) })
      setFacts(await api<Fact[]>('/memory')); setNotice('Предпочтение обновлено.')
    } catch (error) { showError(error) }
  }

  const saveKey = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true)
    try {
      const result = await api<{ configured: boolean; storage: 'system' | 'memory' }>('/admin/key', { method: 'PUT', body: JSON.stringify({ api_key: keyValue }) })
      setKeyValue(''); setKeyConfigured(result.configured); setKeyStorage(result.storage)
      setNotice(result.storage === 'memory' ? 'Ключ подключён. Он хранится только до перезапуска сервера.' : 'Ключ сохранён в системном хранилище компьютера.')
    } catch (error) { showError(error) } finally { setBusy(false) }
  }

  const removeKey = async () => {
    if (!window.confirm('Удалить ключ OpenAI из приложения?')) return
    try { await api('/admin/key', { method: 'DELETE' }); setKeyConfigured(false); setKeyStorage(null); setNotice('Ключ удалён.') }
    catch (error) { showError(error) }
  }

  const selectAdminUser = async (id: number) => {
    setSelectedUserId(id)
    setProfileName(adminUsers.find(u => u.id === id)?.full_name || '')
    try { setAdminFacts(await api<Fact[]>('/admin/users/' + id + '/memory')) }
    catch (error) { showError(error) }
  }

  const assignPlan = async () => {
    if (!selectedUserId || !adminPlanId) return
    try {
      await api('/admin/users/' + selectedUserId + '/memberships', { method: 'POST', body: JSON.stringify({ plan_id: adminPlanId }) })
      setNotice('Абонемент назначен клиенту.')
    } catch (error) { showError(error) }
  }

  const removeAdminFact = async (id: number) => {
    if (!selectedUserId) return
    try {
      await api('/admin/users/' + selectedUserId + '/memory/' + id, { method: 'DELETE' })
      setAdminFacts(previous => previous.filter(f => f.id !== id)); setNotice('Факт удалён.')
    } catch (error) { showError(error) }
  }

  const editAdminFact = async (fact: Fact) => {
    if (!selectedUserId) return
    const value = window.prompt('Исправить значение', fact.value)
    if (!value?.trim()) return
    try {
      await api('/admin/users/' + selectedUserId + '/memory', { method: 'PUT', body: JSON.stringify({ category: fact.category, key: fact.key, value: value.trim() }) })
      setAdminFacts(await api<Fact[]>('/admin/users/' + selectedUserId + '/memory')); setNotice('Память клиента обновлена.')
    } catch (error) { showError(error) }
  }

  const saveProfile = async () => {
    if (!selectedUserId || !profileName.trim()) return
    try {
      const updated = await api<User>('/admin/users/' + selectedUserId, { method: 'PATCH', body: JSON.stringify({ full_name: profileName.trim() }) })
      setAdminUsers(previous => previous.map(u => u.id === updated.id ? updated : u)); setNotice('Профиль обновлён.')
    } catch (error) { showError(error) }
  }

  const selectPlanToEdit = (id: number) => {
    setEditPlanId(id)
    const plan = plans.find(p => p.id === id)
    setEditPlanPrice(String(plan?.price_rub || ''))
    setEditPlanDescription(plan?.description || '')
  }

  const savePlan = async () => {
    if (!editPlanId) return
    try {
      await api('/admin/plans/' + editPlanId, { method: 'PATCH', body: JSON.stringify({ price_rub: Number(editPlanPrice), description: editPlanDescription, active: true }) })
      await loadPublic(); setNotice('Тариф обновлён.')
    } catch (error) { showError(error) }
  }

  const createClass = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!newServiceId || !newClassTime) return
    try {
      await api('/admin/classes', { method: 'POST', body: JSON.stringify({ service_id: newServiceId, trainer_id: newTrainerId, starts_at: newClassTime + ':00+03:00', capacity: Number(newClassCapacity) }) })
      setNewClassTime(''); await loadPublic(); setNotice('Занятие добавлено.')
    } catch (error) { showError(error) }
  }

  const filteredSchedule = schedule.filter(item => !serviceFilter || item.service_code === serviceFilter)
  const serviceCodes = Array.from(new Map(schedule.map(item => [item.service_code, item.service])).entries())

  return <div className="app-shell">
    <header className="site-header">
      <button className="brand" onClick={() => setPage('home')} aria-label="На главную"><span className="brand-mark">P</span><span>Пульс <em>&</em> Баланс<small>городской фитнес-клуб</small></span></button>
      <nav aria-label="Основная навигация">
        <button className={page === 'home' ? 'active' : ''} onClick={() => setPage('home')}>Клуб</button>
        <button className={page === 'schedule' ? 'active' : ''} onClick={() => setPage('schedule')}>Расписание</button>
        <button className={page === 'chat' ? 'active' : ''} onClick={() => setPage('chat')}>AI-консультант</button>
        {user?.role === 'CLIENT' && <button className={page === 'account' ? 'active' : ''} onClick={() => setPage('account')}>Мой кабинет</button>}
        {user?.role === 'ADMIN' && <button className={page === 'admin' ? 'active' : ''} onClick={() => setPage('admin')}>Администратор</button>}
      </nav>
      <div className="header-actions">{user ? <><span className="user-name">{user.full_name}</span><button className="text-button" onClick={logout}>Выйти</button></> : <button className="button button-small" onClick={() => setAuthMode('login')}>Войти</button>}</div>
    </header>

    {notice && <div className="notice" role="status"><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Закрыть">×</button></div>}

    {page === 'home' && <main>
      <section className="hero">
        <div className="hero-copy"><div className="eyebrow">ФИТНЕС В ВАШЕМ РИТМЕ <span className="eyebrow-line" /></div><h1>Движение, которое <em>подходит вам.</em></h1><p>Тренажёрный зал, бассейн и занятия с тренерами в одном пространстве. Наш AI-консультант поможет выбрать формат под ваши цели, бюджет и расписание.</p><div className="hero-actions"><button className="button" onClick={newConversation}>Подобрать с консультантом <span>↗</span></button><button className="button-outline" onClick={() => setPage('schedule')}>Смотреть расписание</button></div><div className="hero-stats"><div><strong>11</strong><span>направлений</span></div><div><strong>4</strong><span>тарифа</span></div><div><strong>07:00</strong><span>начало дня</span></div></div></div>
        <div className="hero-art" aria-hidden="true"><div className="hero-circle circle-one" /><div className="hero-circle circle-two" /><div className="hero-figure">✳</div><div className="hero-art-label">НАЙДИ<br />СВОЙ<br /><i>РИТМ</i></div><div className="floating-card"><span className="dot" /> Ваш маршрут к тренировкам</div></div>
      </section>
      <section className="section section-intro"><div className="section-heading"><div><span className="eyebrow">ПРОСТРАНСТВО ВОЗМОЖНОСТЕЙ</span><h2>Всё для вашего движения</h2></div><p>Выбирайте нагрузку по настроению: от спокойной практики до интенсивной тренировки.</p></div><div className="feature-grid"><article className="feature-card"><span className="feature-icon">01</span><h3>Зал</h3><p>Силовая зона, кардио и персональная работа с тренером.</p></article><article className="feature-card"><span className="feature-icon">02</span><h3>Бассейн</h3><p>Свободное плавание и аквааэробика по предварительной записи.</p></article><article className="feature-card"><span className="feature-icon">03</span><h3>Группы</h3><p>Йога, пилатес, бокс, танцы и другие занятия каждую неделю.</p></article><article className="feature-card"><span className="feature-icon">04</span><h3>Восстановление</h3><p>Сауна и растяжка после активного дня.</p></article></div></section>
      <section className="section plans-section"><div className="section-heading"><div><span className="eyebrow">АБОНЕМЕНТЫ</span><h2>Найдите свой формат</h2></div><p>Актуальные цены поступают из базы клуба. Срок каждого тарифа — 30 дней.</p></div><div className="plan-grid">{plans.map((plan, index) => <article key={plan.id} className={'plan-card ' + (index === 2 ? 'featured' : '')}><div className="plan-top"><span className="plan-number">0{index + 1} / 04</span>{index === 2 && <span className="pill">Популярный</span>}</div><h3>{plan.name}</h3><p>{plan.description}</p><div className="price">{formatMoney(plan.price_rub)} <small>/ 30 дней</small></div><div className="plan-detail">Заморозка: {plan.freeze_days ? `${plan.freeze_days} дней` : 'нет'}</div><button className="plan-link" onClick={newConversation}>Спросить о тарифе <span>→</span></button></article>)}</div></section>
      <section className="consultant-banner"><div><span className="eyebrow">ПЕРСОНАЛЬНЫЙ ПОМОЩНИК</span><h2>Расскажите о цели.<br /><em>Мы запомним важное.</em></h2><p>Консультант учитывает ваши предпочтения между визитами. Сохранённые факты всегда можно посмотреть или удалить в личном кабинете.</p><button className="button button-light" onClick={newConversation}>Начать разговор ↗</button></div><div className="banner-symbol" aria-hidden="true">✳</div></section>
      <footer><strong>Пульс & Баланс</strong><span>Москва, ул. Примерная, 14 · +7 (495) 000-14-14</span><span>Пн–пт 07:00–23:00 · Сб–вс 08:00–22:00</span></footer>
    </main>}

    {page === 'schedule' && <main className="inner-page"><div className="page-title"><span className="eyebrow">ЗАНЯТИЯ И БАССЕЙН</span><h1>Расписание</h1><p>Даты, тренеры и свободные места обновляются из базы клуба.</p></div><div className="filter-row"><button className={!serviceFilter ? 'selected' : ''} onClick={() => setServiceFilter('')}>Все направления</button>{serviceCodes.map(([code, name]) => <button key={code} className={serviceFilter === code ? 'selected' : ''} onClick={() => setServiceFilter(code)}>{name}</button>)}</div><div className="schedule-list">{filteredSchedule.map(item => <article className="class-row" key={item.id}><div className="class-date"><strong>{new Date(item.starts_at).getDate()}</strong><span>{new Intl.DateTimeFormat('ru-RU', { month: 'short' }).format(new Date(item.starts_at))}</span></div><div className="class-main"><div className="class-meta">{formatDay(item.starts_at)} · {new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date(item.starts_at))}</div><h3>{item.service}</h3><p>{item.trainer || 'Самостоятельное посещение'}</p></div><div className="class-places"><strong>{item.free_places}</strong><span>мест свободно</span></div><button className="button button-small" disabled={busy || item.free_places === 0 || !user || user.role !== 'CLIENT'} onClick={() => book(item.id)}>{!user ? 'Войдите для записи' : item.free_places === 0 ? 'Нет мест' : 'Записаться'}</button></article>)}{filteredSchedule.length === 0 && <div className="empty">На выбранное направление занятий пока нет.</div>}</div></main>}

    {page === 'chat' && <main className="chat-layout"><aside className="chat-sidebar"><div className="sidebar-top"><span className="eyebrow">ВАШИ ДИАЛОГИ</span><button onClick={newConversation}>＋ Новый чат</button></div><div className="chat-history">{conversations.map(c => <button key={c.id} className={conversationId === c.id ? 'selected' : ''} onClick={() => openConversation(c.id)}><span>◌</span>{c.title}</button>)}{!conversations.length && <p>Пока нет разговоров</p>}</div><div className="sidebar-note">{user ? 'История и предпочтения сохраняются для вашего аккаунта.' : 'Гостевой диалог доступен 24 часа в этом браузере.'}</div></aside><section className="chat-panel"><div className="chat-heading"><div className="assistant-avatar">✳</div><div><strong>AI-консультант</strong><span>Пульс & Баланс · помощь с тренировками</span></div><div className="online-dot" title="Готов к разговору" /></div><div className="messages">{messages.length === 0 && <div className="welcome-message"><div className="welcome-symbol">✳</div><h2>С чего начнём?</h2><p>Расскажите о цели или спросите о тарифах и занятиях. Я помогу подобрать подходящий ритм.</p><div className="suggestions">{['Хочу заниматься 3 раза в неделю', 'Какие есть тарифы?', 'Покажи занятия по йоге'].map(t => <button key={t} onClick={() => setChatText(t)}>{t} ↗</button>)}</div></div>}{messages.map((m, index) => <div key={m.id || index} className={'message ' + m.role}><div className="message-avatar">{m.role === 'assistant' ? '✳' : 'Я'}</div><div className="message-bubble">{m.content}</div></div>)}{busy && <div className="typing">Консультант отвечает<span>•••</span></div>}{pendingActions.map(action => <div className="action-card" key={action.id}><strong>{action.type === 'BOOK' ? 'Подтвердить запись' : 'Подтвердить отмену'}</strong><p>{action.type === 'BOOK' ? `Занятие №${action.target_id}` : `Запись №${action.target_id}`}</p><button className="button button-small" disabled={busy} onClick={() => confirmAction(action)}>Подтвердить</button></div>)}</div><form className="chat-form" onSubmit={sendChat}><input aria-label="Сообщение консультанту" value={chatText} onChange={e => setChatText(e.target.value)} placeholder="Напишите сообщение..." maxLength={4000} /><button disabled={busy || !chatText.trim()} aria-label="Отправить">↑</button></form><p className="chat-disclaimer">Консультант использует данные клуба. Медицинские вопросы обсудите со специалистом.</p></section></main>}

    {page === 'account' && user?.role === 'CLIENT' && <main className="inner-page"><div className="page-title"><span className="eyebrow">ЛИЧНЫЙ КАБИНЕТ</span><h1>Ваш ритм, {user.full_name.split(' ')[0]}</h1><p>Управляйте абонементом, записями и тем, что консультант помнит о вас.</p></div><div className="account-grid"><section className="panel"><div className="panel-heading"><span>01</span><h2>Абонемент</h2></div>{membership ? <><div className="membership-name">{membership.plan.name}</div><p>{membership.plan.description}</p><div className="info-line"><span>Действует до</span><strong>{formatDay(membership.ends_at)}</strong></div></> : <><p>Сейчас у вас нет действующего абонемента.</p><button className="button button-small" onClick={() => setPage('home')}>Посмотреть тарифы</button></>}</section><section className="panel"><div className="panel-heading"><span>02</span><h2>Мои записи</h2></div>{bookings.filter(b => b.status === 'ACTIVE').length ? bookings.filter(b => b.status === 'ACTIVE').map(b => <div className="booking-item" key={b.id}><div><strong>{b.class.service}</strong><span>{formatDate(b.class.starts_at)}</span></div><button onClick={() => cancelBooking(b.id)}>Отменить</button></div>) : <p>Активных записей пока нет.</p>}</section><section className="panel memory-panel"><div className="panel-heading"><span>03</span><h2>Что помнит консультант</h2></div><p>Эти сведения помогают отвечать лично вам. Вы можете изменить или удалить любой факт.</p>{facts.length ? facts.map(f => <div className="fact-item" key={f.id}><div><small>{memoryLabels[f.key] || f.key}</small><strong>{f.value}</strong></div><div><button onClick={() => editFact(f)} aria-label="Изменить">✎</button><button onClick={() => removeFact(f.id)} aria-label="Удалить">×</button></div></div>) : <div className="empty">Память пока пуста. Расскажите консультанту о своих целях.</div>}</section><section className="panel"><div className="panel-heading"><span>04</span><h2>История диалогов</h2></div>{conversations.length ? conversations.map(c => <button className="history-link" key={c.id} onClick={() => openConversation(c.id)}>{c.title}<span>→</span></button>) : <p>Разговоров пока нет.</p>}</section></div></main>}

    {page === 'admin' && user?.role === 'ADMIN' && <main className="inner-page">
      <div className="page-title"><span className="eyebrow">ПАНЕЛЬ УПРАВЛЕНИЯ</span><h1>Администратор</h1><p>Настройки AI, данные клиентов и расписание клуба.</p></div>
      <div className="admin-grid">
        <section className="panel key-panel">
          <div className="panel-heading"><span>01</span><h2>Подключение OpenAI</h2></div>
          <div className={'key-status ' + (keyConfigured ? 'connected' : '')}><span className="dot" />{keyConfigured ? keyStorage === 'memory' ? 'Ключ подключён до перезапуска сервера. Консультант может отвечать.' : 'Ключ сохранён. Консультант может отвечать.' : 'Ключ пока не добавлен. Чат недоступен.'}</div>
          <p>Ключ отправляется только на локальный сервер. Если системное хранилище Windows недоступно, он остаётся только в памяти до перезапуска сервера; в базу данных и исходный код не записывается. После сохранения значение не отображается.</p>
          <form onSubmit={saveKey} className="key-form"><label htmlFor="api-key">Ключ OpenAI API</label><input id="api-key" type="password" autoComplete="off" value={keyValue} onChange={e => setKeyValue(e.target.value)} placeholder="sk-..." /><div className="form-actions"><button className="button button-small" disabled={busy || !keyValue} type="submit">Сохранить ключ</button>{keyConfigured && <button className="text-button danger" type="button" onClick={removeKey}>Удалить ключ</button>}</div></form>
        </section>
        <section className="panel">
          <div className="panel-heading"><span>02</span><h2>Клиенты</h2></div>
          <div className="admin-user-list">{adminUsers.filter(u => u.role === 'CLIENT').map(u => <button key={u.id} className={selectedUserId === u.id ? 'selected' : ''} onClick={() => selectAdminUser(u.id)}><strong>{u.full_name}</strong><span>{u.email}</span></button>)}</div>
          {selectedUserId && <div className="admin-user-detail">
            <h3>Профиль клиента</h3><div className="inline-form"><input aria-label="Имя клиента" value={profileName} onChange={e => setProfileName(e.target.value)} /><button className="button button-small" onClick={saveProfile}>Сохранить</button></div>
            <h3>Память клиента</h3>{adminFacts.length ? adminFacts.map(f => <div className="fact-item" key={f.id}><div><small>{memoryLabels[f.key] || f.key}</small><strong>{f.value}</strong></div><div><button onClick={() => editAdminFact(f)}>Изменить</button><button onClick={() => removeAdminFact(f.id)}>Удалить</button></div></div>) : <p>Нет сохранённых фактов.</p>}
            <h3>Назначить абонемент</h3><div className="inline-form"><select value={adminPlanId || ''} onChange={e => setAdminPlanId(Number(e.target.value))}><option value="">Выберите тариф</option>{plans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><button className="button button-small" onClick={assignPlan} disabled={!adminPlanId}>Назначить</button></div>
          </div>}
        </section>
        <section className="panel">
          <div className="panel-heading"><span>03</span><h2>Тарифы</h2></div>
          <p>Изменённая цена сразу появится в каталоге и ответах консультанта.</p>
          <select className="admin-select" value={editPlanId || ''} onChange={e => selectPlanToEdit(Number(e.target.value))}><option value="">Выберите тариф</option>{plans.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select>
          {editPlanId && <div className="admin-form"><label>Цена, ₽<input type="number" value={editPlanPrice} onChange={e => setEditPlanPrice(e.target.value)} min="0" /></label><label>Описание<textarea value={editPlanDescription} onChange={e => setEditPlanDescription(e.target.value)} rows={3} /></label><button className="button button-small" onClick={savePlan}>Сохранить тариф</button></div>}
        </section>
        <section className="panel">
          <div className="panel-heading"><span>04</span><h2>Новое занятие</h2></div>
          <form className="admin-form" onSubmit={createClass}>
            <label>Направление<select value={newServiceId || ''} onChange={e => setNewServiceId(Number(e.target.value))} required><option value="">Выберите услугу</option>{services.filter(s => s.code !== 'gym' && s.code !== 'sauna').map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
            <label>Тренер<select value={newTrainerId || ''} onChange={e => setNewTrainerId(e.target.value ? Number(e.target.value) : null)}><option value="">Без тренера</option>{trainers.map(t => <option key={t.id} value={t.id}>{t.full_name}</option>)}</select></label>
            <label>Дата и время (Москва)<input type="datetime-local" value={newClassTime} onChange={e => setNewClassTime(e.target.value)} required /></label>
            <label>Вместимость<input type="number" min="1" max="100" value={newClassCapacity} onChange={e => setNewClassCapacity(e.target.value)} required /></label>
            <button className="button button-small">Добавить занятие</button>
          </form>
        </section>
        <section className="panel key-panel"><div className="panel-heading"><span>05</span><h2>Журнал действий</h2></div><div className="audit-list">{auditEvents.slice(0, 20).map(event => <div key={event.id}><strong>{event.action}</strong><span>{event.target_type} #{event.target_id}</span><small>{formatDate(event.created_at)}</small></div>)}</div></section>
      </div>
    </main>}

    {authMode && <div className="modal-backdrop" onClick={() => setAuthMode(null)}><div className="auth-modal" role="dialog" aria-modal="true" aria-label={authMode === 'login' ? 'Вход' : 'Регистрация'} onClick={e => e.stopPropagation()}><button className="modal-close" onClick={() => setAuthMode(null)} aria-label="Закрыть">×</button><span className="eyebrow">ВАШ АККАУНТ</span><h2>{authMode === 'login' ? 'С возвращением' : 'Начнём знакомство'}</h2><p>{authMode === 'login' ? 'Войдите, чтобы консультант вспомнил ваши предпочтения.' : 'Создайте аккаунт для личных рекомендаций и записи на занятия.'}</p><form onSubmit={auth}>{authMode === 'register' && <label>Имя и фамилия<input value={authName} onChange={e => setAuthName(e.target.value)} minLength={2} maxLength={120} required /></label>}<label>Email<input type="email" value={authEmail} onChange={e => setAuthEmail(e.target.value)} required /></label><label>Пароль<input type="password" value={authPassword} onChange={e => setAuthPassword(e.target.value)} minLength={8} required /></label><button className="button" disabled={busy}>{authMode === 'login' ? 'Войти' : 'Зарегистрироваться'}</button></form><button className="switch-auth" onClick={() => setAuthMode(authMode === 'login' ? 'register' : 'login')}>{authMode === 'login' ? 'Нет аккаунта? Зарегистрироваться' : 'Уже есть аккаунт? Войти'}</button></div></div>}
  </div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
