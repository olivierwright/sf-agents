import { Component, inject, signal, computed, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RunStateService } from '../services/run-state.service';
import { UseCaseInfo } from '../services/api.service';
import { PrimitiveCatalogComponent } from './primitive-catalog.component';

const STRATEGIES = [
  {
    id: 'thorough',
    label: 'Thorough',
    hint: 'Maximum coverage — LLM selects all relevant primitives',
  },
  {
    id: 'minimal',
    label: 'Minimal',
    hint: 'Fewest steps that still produce a cited, verified answer',
  },
  {
    id: 'parallel_first',
    label: 'Parallel First',
    hint: 'Annotates DAG with parallel wave groupings',
  },
];

@Component({
  selector: 'app-ask-panel',
  standalone: true,
  imports: [FormsModule, PrimitiveCatalogComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="ask-panel" [class.collapsed]="state.isRunning()">
      @if (!state.isRunning()) {
        <div class="hero">
          <h1 class="hero-title">
            <span class="hero-accent">Green Lion 2026-1</span>
            <br />Structured Finance Analysis
          </h1>
          <p class="hero-sub">Ask anything about this deal — or pick an analysis template below.</p>
        </div>

        <!-- Use-case inspiration chips -->
        <div class="use-case-chips">
          @for (uc of state.useCases(); track uc.id) {
            <button
              class="chip"
              [class.active]="activeUseCaseId() === uc.id"
              (click)="selectUseCase(uc)"
              [title]="uc.description"
            >
              <span class="chip-icon">{{ categoryIcon(uc.category) }}</span>
              <span class="chip-label">{{ uc.label }}</span>
            </button>
          }
        </div>

        <!-- Free-form question input -->
        <div class="question-box">
          <textarea
            class="question-input"
            placeholder="What would you like to investigate? e.g. 'How does the prospectus define arrears?'"
            [ngModel]="questionText()"
            (ngModelChange)="onQuestionChange($event)"
            rows="3"
          ></textarea>
        </div>

        <!-- Strategy selector + run button -->
        <div class="controls-row">
          <div class="strategy-group">
            <label class="strategy-label">Strategy</label>
            <div class="strategy-pills">
              @for (s of strategies; track s.id) {
                <button
                  class="strategy-pill"
                  [class.active]="strategy() === s.id"
                  (click)="strategy.set(s.id)"
                  [title]="s.hint"
                >
                  {{ s.label }}
                </button>
              }
            </div>
          </div>

          <button class="btn btn-primary run-btn" [disabled]="!canRun()" (click)="launchRun()">
            <span class="run-icon">▶</span>
            Run Analysis
          </button>
        </div>

        <!-- Primitive catalog browser -->
        <app-primitive-catalog />
      } @else {
        <div class="running-mini">
          <span class="badge badge-accent">Running</span>
          <span class="running-label">{{ truncate(state.activeQuestion(), 60) }}</span>
          <span class="running-strategy mono">{{ state.activeStrategy() }}</span>
        </div>
      }
    </section>
  `,
  styles: [
    `
      .ask-panel {
        padding: var(--sp-12) var(--sp-8);
        text-align: center;
        animation: fadeInUp var(--duration-slow) var(--ease-out);
      }
      .ask-panel.collapsed {
        padding: var(--sp-4) var(--sp-8);
      }
      .hero {
        margin-bottom: var(--sp-8);
      }
      .hero-title {
        font-family: var(--font-display);
        font-weight: 400;
        font-style: italic;
        font-size: 2.25rem;
        line-height: 1.2;
        color: var(--text-primary);
      }
      .hero-accent {
        color: var(--accent);
      }
      .hero-sub {
        margin-top: var(--sp-3);
        color: var(--text-secondary);
        font-size: 1rem;
      }

      .use-case-chips {
        display: flex;
        justify-content: center;
        gap: var(--sp-2);
        flex-wrap: wrap;
        margin-bottom: var(--sp-5);
      }
      .chip {
        display: inline-flex;
        align-items: center;
        gap: var(--sp-2);
        padding: var(--sp-2) var(--sp-4);
        border: 1px solid var(--border);
        border-radius: var(--radius-full);
        background: var(--bg-surface);
        font-family: var(--font-sans);
        font-size: 0.8125rem;
        cursor: pointer;
        transition: all var(--duration-fast) var(--ease-out);
      }
      .chip:hover {
        border-color: var(--accent);
        box-shadow: var(--shadow-sm);
      }
      .chip.active {
        background: var(--accent);
        color: #fff;
        border-color: var(--accent);
      }
      .chip-icon {
        font-size: 0.9rem;
      }

      .question-box {
        max-width: 700px;
        margin: 0 auto var(--sp-5);
      }
      .question-input {
        width: 100%;
        padding: var(--sp-4);
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        background: var(--bg-surface);
        font-family: var(--font-sans);
        font-size: 0.9375rem;
        color: var(--text-primary);
        resize: vertical;
        transition: border-color var(--duration-fast) var(--ease-out);
        box-sizing: border-box;
      }
      .question-input:focus {
        outline: none;
        border-color: var(--accent);
        box-shadow: 0 0 0 3px rgba(27, 111, 107, 0.1);
      }
      .question-input::placeholder {
        color: var(--text-muted);
      }

      .controls-row {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--sp-6);
        flex-wrap: wrap;
        margin-bottom: var(--sp-5);
      }
      .strategy-group {
        display: flex;
        align-items: center;
        gap: var(--sp-3);
      }
      .strategy-label {
        font-size: 0.8125rem;
        color: var(--text-secondary);
      }
      .strategy-pills {
        display: flex;
        gap: var(--sp-1);
      }
      .strategy-pill {
        padding: var(--sp-2) var(--sp-3);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        background: var(--bg-surface);
        font-size: 0.8125rem;
        cursor: pointer;
        transition: all var(--duration-fast) var(--ease-out);
      }
      .strategy-pill.active {
        background: var(--accent);
        color: #fff;
        border-color: var(--accent);
      }
      .strategy-pill:not(.active):hover {
        border-color: var(--accent);
      }

      .run-btn {
        padding: var(--sp-3) var(--sp-8);
        font-size: 0.9375rem;
        font-weight: 600;
      }
      .run-icon {
        font-size: 0.7rem;
        margin-right: var(--sp-1);
      }

      .running-mini {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--sp-3);
      }
      .running-label {
        font-weight: 500;
        color: var(--text-primary);
        font-size: 0.875rem;
      }
      .running-strategy {
        font-size: 0.75rem;
        color: var(--text-muted);
      }
    `,
  ],
})
export class AskPanelComponent {
  protected state = inject(RunStateService);
  protected strategies = STRATEGIES;

  readonly questionText = signal('');
  readonly strategy = signal<string>('thorough');
  readonly activeUseCaseId = signal<string | null>(null);

  readonly canRun = computed(() => this.questionText().trim().length > 0);

  selectUseCase(uc: UseCaseInfo): void {
    this.activeUseCaseId.set(uc.id);
    this.questionText.set(uc.example_question);
  }

  onQuestionChange(value: string): void {
    this.questionText.set(value);
    const active = this.state.useCases().find((uc) => uc.example_question === value);
    this.activeUseCaseId.set(active?.id ?? null);
  }

  launchRun(): void {
    const q = this.questionText().trim();
    if (!q) return;
    this.state.startQuestion(q, this.strategy());
  }

  categoryIcon(category: string): string {
    const icons: Record<string, string> = {
      documentation: '📋',
      esg: '🌱',
      performance: '📈',
      compliance: '⚖️',
      structure: '🏗️',
      ratings: '⭐',
    };
    return icons[category] ?? '🔍';
  }

  truncate(value: string, limit: number): string {
    if (!value) return '';
    return value.length > limit ? value.slice(0, limit) + '…' : value;
  }
}
