const typeLabels: Record<string, string> = {
  diary: '日记',
  stock_diary: '股票',
  retrospective: '回顾',
  summary: '总结',
  note: '随记',
}

export const entryTypeLabel = (entryType: string) => typeLabels[entryType] ?? entryType

/** 筛选下拉的类型选项（取值与 create_diary_db.sql 一致）；浏览页 / 摘要页共用这一份定义。 */
export const entryTypeOptions: [string, string][] = [
  ['diary', '普通日记'],
  ['stock_diary', '股票日记'],
  ['retrospective', '回顾'],
  ['summary', '总结'],
  ['note', '随手记'],
]
