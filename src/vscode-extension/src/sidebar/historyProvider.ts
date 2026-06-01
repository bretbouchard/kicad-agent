/**
 * Operation history provider for sidebar panel.
 *
 * Tracks MCP tool calls with timestamps, limiting history to a
 * configurable maximum.
 */

export interface HistoryEntry {
  tool: string;
  file: string;
  result: string;
  timestamp: Date;
  error?: string;
}

export class HistoryProvider {
  private entries: HistoryEntry[] = [];
  private readonly maxItems: number;

  constructor(maxItems: number = 100) {
    this.maxItems = maxItems;
  }

  addEntry(entry: Omit<HistoryEntry, 'timestamp'>): void {
    this.entries.push({
      ...entry,
      timestamp: new Date(),
    });

    // Keep only the most recent maxItems entries
    if (this.entries.length > this.maxItems) {
      this.entries = this.entries.slice(-this.maxItems);
    }
  }

  getEntries(): HistoryEntry[] {
    return [...this.entries];
  }

  clear(): void {
    this.entries = [];
  }

  get count(): number {
    return this.entries.length;
  }
}
