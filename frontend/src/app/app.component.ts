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
  key = '';
  authenticated = false;
  error = '';
  notice = '';
  connected = false;
  busy = false;
  loading = false;
  private polling = false;
  private timer?: ReturnType<typeof setInterval>;
  get activeDesks(): number { return this.state.desks.filter(d => !!d.ticket).length; }
  get hasActiveTicket(): boolean { return this.ticket?.status === 'waiting' || this.ticket?.status === 'serving'; }

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
      signal: AbortSignal.timeout(10000)
    });
    if (!response.ok) {
      if (response.status === 401 && operator) this.authenticated = false;
      const data: {detail?: unknown} = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo completar la solicitud');
    }
    return await response.json() as T;
  }

  async refresh(): Promise<void> {
    if (this.polling) return;
    this.polling = true;
    try {
      this.state = await this.api<State>('/state');
      this.connected = true;
      if (this.token) {
        try { this.ticket = await this.api<Ticket>('/tickets/' + this.token); }
        catch (error) { this.error = this.message(error); }
      }
    } catch { this.connected = false; }
    finally { this.polling = false; }
  }

  private message(error: unknown): string {
    return error instanceof Error ? error.message : 'Ocurrió un error. Intenta de nuevo.';
  }

  async takeTurn(): Promise<void> {
    if (this.busy || !this.connected || this.hasActiveTicket) return;
    this.busy = true; this.error = ''; this.notice = '';
    try {
      // Persist before sending; a retry after a lost response cannot create a second ticket.
      if (!this.token || this.ticket?.status === 'completed' || this.ticket?.status === 'cancelled') {
        this.token = crypto.randomUUID();
        localStorage.setItem('queue-token', this.token);
      }
      this.ticket = await this.api<Ticket>('/tickets', 'POST', {request_id: this.token});
      this.notice = 'Tu turno está registrado. Sigue su estado aquí.';
      await this.refresh();
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
      await this.refresh();
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

  async deskAction(desk: Desk, action: 'next' | 'finish' | 'pause'): Promise<void> {
    if (this.busy) return;
    this.busy = true; this.error = ''; this.notice = '';
    const body = action === 'finish' ? {ticket_id: desk.ticket?.id} :
      action === 'pause' ? {paused: !desk.paused} : undefined;
    try {
      await this.api('/desks/' + desk.id + '/' + action, 'POST', body, true);
      this.notice = action === 'next' ? 'Turno llamado a mesa ' + desk.id :
        action === 'finish' ? 'Atención finalizada' : 'Estado de mesa actualizado';
      await this.refresh();
    } catch (error) { this.error = this.message(error); await this.refresh(); }
    finally { this.busy = false; }
  }

  statusLabel(status: Status): string {
    return {waiting:'En espera', serving:'Es tu turno', completed:'Atención finalizada', cancelled:'Cancelado'}[status];
  }
}
