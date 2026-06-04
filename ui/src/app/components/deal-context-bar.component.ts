import { Component, inject, ChangeDetectionStrategy } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RunStateService } from '../services/run-state.service';

@Component({
  selector: 'app-deal-context-bar',
  standalone: true,
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <aside class="context-bar">
      <div class="bar-inner">
        @if (state.deal(); as deal) {
          <div class="deal-name">
            <span class="deal-icon">◆</span>
            <strong>{{ deal.deal.name }}</strong>
          </div>
          <div class="stats">
            <span class="stat">
              <span class="stat-label">Loans</span>
              <span class="stat-value mono">{{ deal.portfolio.loan_count | number }}</span>
            </span>
            <span class="divider"></span>
            <span class="stat">
              <span class="stat-label">Balance</span>
              <span class="stat-value mono">€{{ formatBalance(deal.portfolio.total_balance_eur) }}</span>
            </span>
            <span class="divider"></span>
            <span class="stat">
              <span class="stat-label">Green</span>
              <span class="stat-value mono">{{ deal.green.green_label_pct }}%</span>
            </span>
          </div>
          @if (state.health(); as h) {
            <div class="model-badge badge badge-accent">
              {{ formatModel(h.model) }} · {{ h.region }}
            </div>
          }
        } @else {
          <div class="loading">Loading deal context…</div>
        }
      </div>
    </aside>
  `,
  styles: [`
    .context-bar {
      position: sticky;
      top: 0;
      z-index: 100;
      background: var(--bg-frosted);
      backdrop-filter: blur(12px) saturate(1.4);
      -webkit-backdrop-filter: blur(12px) saturate(1.4);
      border-bottom: 1px solid var(--border);
      padding: var(--sp-3) var(--sp-6);
    }
    .bar-inner {
      max-width: var(--max-width);
      margin: 0 auto;
      display: flex;
      align-items: center;
      gap: var(--sp-6);
    }
    .deal-name {
      display: flex;
      align-items: center;
      gap: var(--sp-2);
      font-size: 0.875rem;
      white-space: nowrap;
    }
    .deal-icon { color: var(--accent); font-size: 0.75rem; }
    .stats {
      display: flex;
      align-items: center;
      gap: var(--sp-4);
      margin-left: auto;
    }
    .stat {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 1px;
    }
    .stat-label {
      font-size: 0.625rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
    }
    .stat-value { font-size: 0.8125rem; }
    .divider {
      width: 1px;
      height: 24px;
      background: var(--border);
    }
    .model-badge {
      margin-left: var(--sp-4);
      font-size: 0.625rem;
    }
    .loading {
      color: var(--text-muted);
      font-size: 0.8125rem;
    }
  `],
})
export class DealContextBarComponent {
  protected state = inject(RunStateService);

  formatBalance(val: number | null): string {
    if (val == null) return '—';
    if (val >= 1_000_000_000) return (val / 1_000_000_000).toFixed(1) + 'B';
    if (val >= 1_000_000) return (val / 1_000_000).toFixed(1) + 'M';
    return val.toLocaleString();
  }

  formatModel(model: string): string {
    const last = model.split('.').pop() ?? model;
    return last.split('-').slice(0, 2).join(' ');
  }
}
