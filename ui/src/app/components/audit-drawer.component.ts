import { Component, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { RunStateService } from '../services/run-state.service';
import { ApiService } from '../services/api.service';

@Component({
  selector: 'app-audit-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="drawer-backdrop" [class.open]="isOpen()" (click)="close()"></div>
    <aside class="drawer" [class.open]="isOpen()">
      <div class="drawer-header">
        <h3>Audit Trail</h3>
        <button class="btn btn-ghost" (click)="close()">✕</button>
      </div>

      <div class="drawer-tabs">
        <button
          class="tab"
          [class.active]="activeTab() === 'events'"
          (click)="activeTab.set('events')"
        >Events</button>
        <button
          class="tab"
          [class.active]="activeTab() === 'plan'"
          (click)="activeTab.set('plan')"
        >Plan</button>
        <button
          class="tab"
          [class.active]="activeTab() === 'citations'"
          (click)="activeTab.set('citations')"
        >Citations</button>
      </div>

      <div class="drawer-body">
        @switch (activeTab()) {
          @case ('events') {
            <div class="event-list">
              @for (evt of state.events(); track $index) {
                <div class="event-item">
                  <span class="event-type badge badge-prim">{{ evt.type }}</span>
                  <pre class="event-payload mono">{{ formatPayload(evt.payload) }}</pre>
                </div>
              }
            </div>
          }
          @case ('plan') {
            <div class="plan-view">
              @if (state.dag(); as dag) {
                <pre class="plan-pre mono">{{ formatPayload(dag) }}</pre>
              } @else {
                <p class="text-muted">No plan data available.</p>
              }
            </div>
          }
          @case ('citations') {
            <div class="citations-view">
              @for (step of state.steps(); track step.step_id) {
                @if (step.citations && step.citations.length > 0) {
                  <div class="citation-group">
                    <span class="mono citation-step">{{ step.step_id }}</span>
                    @for (cite of step.citations; track $index) {
                      <div class="citation-item">
                        <span class="citation-source">{{ cite }}</span>
                      </div>
                    }
                  </div>
                }
              }
              @if (noCitations()) {
                <p class="text-muted">No citations recorded.</p>
              }
            </div>
          }
        }
      </div>
    </aside>
  `,
  styles: [`
    .drawer-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,.3);
      z-index: 200;
      opacity: 0;
      pointer-events: none;
      transition: opacity var(--duration-md) var(--ease-out);
    }
    .drawer-backdrop.open { opacity: 1; pointer-events: auto; }
    .drawer {
      position: fixed;
      top: 0;
      right: 0;
      width: min(480px, 90vw);
      height: 100vh;
      background: var(--bg-surface);
      border-left: 1px solid var(--border);
      z-index: 201;
      transform: translateX(100%);
      transition: transform var(--duration-md) var(--ease-out);
      display: flex;
      flex-direction: column;
      box-shadow: var(--shadow-lg);
    }
    .drawer.open { transform: translateX(0); }
    .drawer-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--sp-4) var(--sp-5);
      border-bottom: 1px solid var(--border);
    }
    .drawer-header h3 { font-size: 1rem; }
    .drawer-tabs {
      display: flex;
      border-bottom: 1px solid var(--border);
    }
    .tab {
      flex: 1;
      padding: var(--sp-3);
      background: none;
      border: none;
      font-family: var(--font-sans);
      font-size: 0.8125rem;
      font-weight: 500;
      color: var(--text-muted);
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: all var(--duration-fast);
    }
    .tab:hover { color: var(--text-primary); }
    .tab.active {
      color: var(--accent);
      border-bottom-color: var(--accent);
    }
    .drawer-body {
      flex: 1;
      overflow-y: auto;
      padding: var(--sp-4);
    }
    .event-list {
      display: flex;
      flex-direction: column;
      gap: var(--sp-3);
    }
    .event-item {
      padding: var(--sp-3);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
    }
    .event-type { margin-bottom: var(--sp-2); }
    .event-payload {
      font-size: 0.625rem;
      line-height: 1.5;
      white-space: pre-wrap;
      margin: var(--sp-2) 0 0;
      color: var(--text-secondary);
    }
    .plan-pre, .audit-pre {
      font-size: 0.6875rem;
      line-height: 1.5;
      white-space: pre-wrap;
    }
    .citation-group {
      margin-bottom: var(--sp-4);
    }
    .citation-step {
      font-size: 0.75rem;
      font-weight: 600;
      display: block;
      margin-bottom: var(--sp-2);
    }
    .citation-item {
      padding: var(--sp-2) var(--sp-3);
      background: var(--bg-canvas);
      border-radius: var(--radius-sm);
      margin-bottom: var(--sp-1);
      font-size: 0.75rem;
    }
  `],
})
export class AuditDrawerComponent {
  protected state = inject(RunStateService);
  private apiService = inject(ApiService);

  readonly isOpen = signal(false);
  readonly activeTab = signal<'events' | 'plan' | 'citations'>('events');

  open(): void { this.isOpen.set(true); }
  close(): void { this.isOpen.set(false); }

  noCitations(): boolean {
    return this.state.steps().every(s => !s.citations || s.citations.length === 0);
  }

  formatPayload(val: unknown): string {
    if (typeof val === 'string') return val;
    return JSON.stringify(val, null, 2);
  }
}
