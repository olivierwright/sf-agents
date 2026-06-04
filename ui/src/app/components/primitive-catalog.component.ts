import { Component, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { ApiService, PrimitiveInfo } from '../services/api.service';

@Component({
  selector: 'app-primitive-catalog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="catalog-wrapper">
      <button class="catalog-toggle" (click)="open.update((v) => !v)">
        <span class="toggle-icon">{{ open() ? '▾' : '▸' }}</span>
        Primitive Catalog
        @if (primitives().length > 0) {
          <span class="count-badge">{{ primitives().length }}</span>
        }
      </button>

      @if (open()) {
        <div class="catalog-grid" role="list">
          @for (p of primitives(); track p.name) {
            <div class="prim-card card" role="listitem">
              <div class="prim-header">
                <span class="prim-name mono">{{ p.name }}</span>
                <span class="prim-version badge badge-prim">v{{ p.version }}</span>
              </div>
              <p class="prim-capability">{{ p.capability }}</p>
              <div class="prim-io">
                <div class="io-section">
                  <span class="io-label">Inputs</span>
                  @for (entry of objectEntries(p.inputs); track entry[0]) {
                    <div class="io-row">
                      <span class="io-key mono">{{ entry[0] }}</span>
                      <span class="io-desc">{{ entry[1] }}</span>
                    </div>
                  }
                </div>
                <div class="io-section">
                  <span class="io-label">Outputs</span>
                  @for (entry of objectEntries(p.outputs); track entry[0]) {
                    <div class="io-row">
                      <span class="io-key mono">{{ entry[0] }}</span>
                      <span class="io-desc">{{ entry[1] }}</span>
                    </div>
                  }
                </div>
              </div>
            </div>
          }
        </div>
      }
    </div>
  `,
  styles: [
    `
      .catalog-wrapper {
        margin-top: var(--sp-6);
      }

      .catalog-toggle {
        display: inline-flex;
        align-items: center;
        gap: var(--sp-2);
        background: none;
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        padding: var(--sp-2) var(--sp-4);
        font-size: 0.8125rem;
        color: var(--text-secondary);
        cursor: pointer;
        transition: all var(--duration-fast) var(--ease-out);
      }
      .catalog-toggle:hover {
        border-color: var(--accent);
        color: var(--accent);
      }
      .toggle-icon {
        font-size: 0.75rem;
      }
      .count-badge {
        background: var(--bg-surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-full);
        padding: 0 var(--sp-2);
        font-size: 0.6875rem;
        font-family: var(--font-mono);
      }

      .catalog-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: var(--sp-4);
        margin-top: var(--sp-4);
        animation: fadeInUp var(--duration-md) var(--ease-out);
      }

      .prim-card {
        padding: var(--sp-4);
        text-align: left;
      }
      .prim-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: var(--sp-2);
      }
      .prim-name {
        font-size: 0.75rem;
        font-weight: 600;
        color: var(--accent);
      }
      .prim-version {
        font-size: 0.6875rem;
      }
      .prim-capability {
        font-size: 0.8rem;
        color: var(--text-secondary);
        line-height: 1.5;
        margin-bottom: var(--sp-3);
      }
      .prim-io {
        display: flex;
        flex-direction: column;
        gap: var(--sp-2);
      }
      .io-section {
        display: flex;
        flex-direction: column;
        gap: var(--sp-1);
      }
      .io-label {
        font-size: 0.6875rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--text-muted);
      }
      .io-row {
        display: grid;
        grid-template-columns: 140px 1fr;
        gap: var(--sp-2);
        font-size: 0.6875rem;
      }
      .io-key {
        color: var(--accent);
        word-break: break-all;
      }
      .io-desc {
        color: var(--text-muted);
        line-height: 1.4;
      }
    `,
  ],
})
export class PrimitiveCatalogComponent {
  private api = inject(ApiService);
  readonly open = signal(false);
  readonly primitives = signal<PrimitiveInfo[]>([]);
  readonly objectEntries = Object.entries;

  ngOnInit(): void {
    this.api.primitives().subscribe((p) => this.primitives.set(p));
  }
}
