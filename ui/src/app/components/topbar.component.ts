import { Component, inject, ChangeDetectionStrategy } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RunStateService } from '../services/run-state.service';

@Component({
  selector: 'app-topbar',
  standalone: true,
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="topbar">
      <div class="topbar-left">
        <span class="deal-diamond">◆</span>
        <span class="deal-name">Green Lion 2026-1</span>
        <span class="deal-type badge">RMBS · EUR</span>
      </div>

      @if (state.deal(); as d) {
        <div class="topbar-stats">
          <div class="tstat">
            <span class="tstat-val mono">{{ d.portfolio.loan_count | number }}</span>
            <span class="tstat-label">loans</span>
          </div>
          <div class="tsep"></div>
          <div class="tstat">
            <span class="tstat-val mono">€{{ fmtBalance(d.portfolio.total_balance_eur) }}</span>
            <span class="tstat-label">balance</span>
          </div>
          <div class="tsep"></div>
          <div class="tstat">
            <span class="tstat-val mono">{{ d.portfolio.avg_interest_rate_pct }}%</span>
            <span class="tstat-label">avg rate</span>
          </div>
          <div class="tsep"></div>
          <div class="tstat">
            <span class="tstat-val mono" style="color: var(--color-success)"
              >{{ d.green.green_label_pct }}%</span
            >
            <span class="tstat-label">green</span>
          </div>
        </div>
      }

      <div class="topbar-right">
        <div class="phase-indicator" [class]="'phase-' + state.phase()">
          <span class="phase-dot"></span>
          <span class="phase-label">{{ phaseLabel() }}</span>
        </div>
        @if (state.health(); as h) {
          <div class="model-tag mono">{{ fmtModel(h.model) }}</div>
        }
      </div>
    </header>
  `,
  styles: [
    `
      .topbar {
        display: flex;
        align-items: center;
        gap: var(--sp-6);
        padding: 0 var(--sp-6);
        height: 48px;
        background: var(--bg-surface);
        border-bottom: 1px solid var(--border);
        position: sticky;
        top: 0;
        z-index: 200;
        flex-shrink: 0;
      }
      .topbar-left {
        display: flex;
        align-items: center;
        gap: var(--sp-2);
      }
      .deal-diamond {
        color: var(--accent);
        font-size: 0.625rem;
      }
      .deal-name {
        font-weight: 600;
        font-size: 0.9375rem;
        white-space: nowrap;
      }
      .deal-type {
        font-size: 0.5625rem;
        font-family: var(--font-mono);
        background: rgba(27, 111, 107, 0.08);
        color: var(--accent);
        border: 1px solid rgba(27, 111, 107, 0.2);
        border-radius: var(--radius-sm);
        padding: 2px var(--sp-2);
      }
      .topbar-stats {
        display: flex;
        align-items: center;
        gap: var(--sp-3);
        margin-left: auto;
      }
      .tstat {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 1px;
      }
      .tstat-val {
        font-size: 0.8125rem;
        font-weight: 500;
        line-height: 1.2;
      }
      .tstat-label {
        font-size: 0.5625rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--text-muted);
      }
      .tsep {
        width: 1px;
        height: 20px;
        background: var(--border);
      }
      .topbar-right {
        display: flex;
        align-items: center;
        gap: var(--sp-4);
      }
      .model-tag {
        font-size: 0.625rem;
        color: var(--text-muted);
        white-space: nowrap;
      }
      .phase-indicator {
        display: flex;
        align-items: center;
        gap: var(--sp-2);
      }
      .phase-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
        background: var(--border);
        transition: background var(--duration-fast) var(--ease-out);
      }
      .phase-label {
        font-size: 0.6875rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }
      .phase-planning .phase-dot {
        background: var(--color-warning);
        box-shadow: 0 0 6px var(--color-warning);
        animation: pulseDot 1s ease-in-out infinite;
      }
      .phase-executing .phase-dot {
        background: var(--color-prim);
        box-shadow: 0 0 6px var(--color-prim);
        animation: pulseDot 1s ease-in-out infinite;
      }
      .phase-verifying .phase-dot {
        background: var(--accent);
      }
      .phase-done .phase-dot {
        background: var(--color-success);
      }
      .phase-error .phase-dot {
        background: var(--color-danger);
      }
      @keyframes pulseDot {
        0%,
        100% {
          opacity: 1;
        }
        50% {
          opacity: 0.4;
        }
      }
    `,
  ],
})
export class TopbarComponent {
  protected state = inject(RunStateService);

  fmtBalance(v: number | null): string {
    if (v == null) return '—';
    if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(0) + 'M';
    return v.toLocaleString();
  }

  fmtModel(m: string): string {
    // "eu.anthropic.claude-sonnet-4-20250514-v1:0" → "claude-sonnet-4"
    const parts = m.split('.');
    const last = parts[parts.length - 1] ?? m;
    const tok = last.split('-');
    return tok.slice(0, 3).join('-');
  }

  phaseLabel(): string {
    const map: Record<string, string> = {
      idle: 'READY',
      planning: 'PLANNING',
      executing: 'EXECUTING',
      verifying: 'VERIFYING',
      done: 'COMPLETE',
      error: 'ERROR',
    };
    return map[this.state.phase()] ?? this.state.phase().toUpperCase();
  }
}
