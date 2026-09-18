const typeLabels: Record<string, string> = {
  diary: '日记',
  stock_diary: '股票',
  retrospective: '回顾',
  summary: '总结',
  note: '随记',
}

export const entryTypeLabel = (entryType: string) => typeLabels[entryType] ?? entryType
