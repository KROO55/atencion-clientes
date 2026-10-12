import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

type Status = 'waiting' | 'serving' | 'completed' | 'cancelled';
interface Ticket {
  id: number; number: string; status: Status; desk_id: number | null;
  position: number | null; created_at: string; called_at: string | null;
}
interface Desk { id: number; paused: boolean; ticket: Ticket | null; }
interface State { waiting: Ticket[]; desks: Desk[]; completed: number; updated_at: string; }
interface SavedTicket { token: string; number: string; }

function readTickets(): SavedTicket[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem('queue-tickets') || '[]');
    return Array.isArray(saved) ? saved.filter(t => typeof t?.token === 'string' && typeof t?.number === 'string') : [];
  } catch { return []; }
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.component.html'
})
export class AppComponent implements OnInit, OnDestroy {
  view: 'turnos' | 'pantalla' | 'mesas' = 'turnos';
  state: State = {waiting: [], desks: [1,2,3,4].map(id => ({id, paused: false, ticket: null})), completed: 0, updated_at: ''};
  ticket: Ticket | null = null;
  token = localStorage.getItem('queue-token') || '';
  savedTickets = readTickets();
  private pendingRequestId = localStorage.getItem('queue-pending-request') || '';
  key = '';
  authenticated = false;
  error = '';
  notice = '';
  connected = false;
  busy = false;
  loading = false;
  private refreshTask?: Promise<void>;
  private operatorRequestId = '';
  private timer?: ReturnType<typeof setInterval>;
  get activeDesks(): number { return this.state.desks.filter(d => !!d.ticket).length; }
  get hasActiveTicket(): boolean { return this.ticket?.status === 'waiting' || this.ticket?.status === 'serving'; }
  trackId(_index: number, item: {id: number}): number { return item.id; }
  trackToken(_index: number, item: SavedTicket): string { return item.token; }

  ngOnInit(): void {
    void this.refresh();
    this.timer = setInterval(() => void this.refresh(), 2000);
  }
  ngOnDestroy(): void { if (this.timer) clearInterval(this.timer); }

  private async api<T>(path: string, method = 'GET', body?: unknown, operator = false): Promise<T> {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (operator) headers['Authorization'] = 'Bearer ' + this.key;
    const response = await fetch('/api' + path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(30000), cache: 'no-store'
    });
    if (!response.ok) {
      if (response.status === 401 && operator) this.authenticated = false;
      const data: {detail?: unknown} = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo completar la solicitud');
    }
    return await response.json() as T;
  }

  async refresh(force = false): Promise<void> {
    if (this.refreshTask) {
      await this.refreshTask;
      if (!force) return;
    }
    if (this.busy && !force) return;
    const task = this.loadState();
    this.refreshTask = task;
    try { await task; }
    finally { if (this.refreshTask === task) this.refreshTask = undefined; }
  }

  private async loadState(): Promise<void> {
    try {
      this.state = await this.api<State>('/state');
      this.connected = true;
      if (this.token) {
        const selectedToken = this.token;
        try {
          const selected = await this.api<Ticket>('/tickets/' + selectedToken);
          if (this.token === selectedToken) {
            this.ticket = selected;
            this.rememberTicket(selectedToken, selected.number);
          }
        }
        catch (error) { this.error = this.message(error); }
      }
    } catch { this.connected = false; }
  }

  private rememberTicket(token: string, number: string): void {
    if (!this.savedTickets.some(t => t.token === token)) {
      this.savedTickets = [{token, number}, ...this.savedTickets];
      localStorage.setItem('queue-tickets', JSON.stringify(this.savedTickets));
    }
  }

  async selectTicket(token: string): Promise<void> {
    if (this.busy) return;
    this.token = token;
    this.ticket = null;
    localStorage.setItem('queue-token', this.token);
    await this.refresh(true);
  }

  private message(error: unknown): string {
    return error instanceof Error ? error.message : 'Ocurrió un error. Intenta de nuevo.';
  }

  async takeTurn(): Promise<void> {
    if (this.busy || !this.connected) return;
    this.busy = true; this.error = ''; this.notice = '';
    try {
      // A new click creates a new ticket; retries reuse the pending request only.
      this.pendingRequestId ||= crypto.randomUUID();
      localStorage.setItem('queue-pending-request', this.pendingRequestId);
      const created = await this.api<Ticket>('/tickets', 'POST', {request_id: this.pendingRequestId});
      this.token = this.pendingRequestId;
      this.ticket = created;
      localStorage.setItem('queue-token', this.token);
      this.rememberTicket(this.token, created.number);
      this.pendingRequestId = '';
      localStorage.removeItem('queue-pending-request');
      this.notice = created.desk_id ? created.number + ' asignado a Mesa ' + created.desk_id : created.number + ' agregado a la fila de espera';
      await this.refresh(true);
    } catch (error) { this.error = this.message(error); }
    finally { this.busy = false; }
  }

  async cancel(): Promise<void> {
    if (this.busy || this.ticket?.status !== 'waiting') return;
    this.busy = true; this.error = ''; this.notice = '';
    try {
      await this.api('/tickets/' + this.token + '/cancel', 'POST');
      this.ticket = await this.api<Ticket>('/tickets/' + this.token);
      this.notice = 'Tu turno fue cancelado.';
      await this.refresh(true);
    } catch (error) { this.error = this.message(error); }
    finally { this.busy = false; }
  }

  async login(): Promise<void> {
    if (this.loading) return;
    this.loading = true; this.error = '';
    try {
      await this.api('/operator/session', 'GET', undefined, true);
      this.authenticated = true;
    } catch (error) { this.error = this.message(error); }
    finally { this.loading = false; }
  }
  logout(): void { this.key = ''; this.authenticated = false; }

  async addTurn(): Promise<void> {
    if (this.busy || !this.connected || !this.authenticated) return;
    this.busy = true; this.error = ''; this.notice = '';
    try {
      // Keep this ID on a failed request so retrying does not duplicate a turn.
      this.operatorRequestId ||= crypto.randomUUID();
      const added = await this.api<Ticket>('/tickets', 'POST', {request_id: this.operatorRequestId});
      this.operatorRequestId = '';
      this.notice = added.desk_id ? added.number + ' asignado a Mesa ' + added.desk_id : added.number + ' agregado a la fila de espera';
      await this.refresh(true);
    } catch (error) { this.error = this.message(error); }
    finally { this.busy = false; }
  }

  async deskAction(desk: Desk, action: 'next' | 'finish' | 'pause'): Promise<void> {
    if (this.busy) return;
    this.busy = true; this.error = ''; this.notice = '';
    const body = action === 'finish' ? {ticket_id: desk.ticket?.id} :
      action === 'pause' ? {paused: !desk.paused} : undefined;
    try {
      const result = await this.api<{next_ticket?: Ticket | null}>('/desks/' + desk.id + '/' + action, 'POST', body, true);
      this.notice = action === 'next' ? 'Turno llamado a mesa ' + desk.id :
        action === 'finish' ? 'Atención finalizada' + (result.next_ticket ? '. ' + result.next_ticket.number + ' asignado a Mesa ' + desk.id : '. Mesa disponible') : 'Estado de mesa actualizado';
      await this.refresh(true);
    } catch (error) { this.error = this.message(error); await this.refresh(true); }
    finally { this.busy = false; }
  }

  statusLabel(status: Status): string {
    return {waiting:'En espera', serving:'Es tu turno', completed:'Atención finalizada', cancelled:'Cancelado'}[status];
  }
}

