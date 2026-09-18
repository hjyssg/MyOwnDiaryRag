import { entryTypeOptions } from './entryTypes'

/**
 * 日记类型下拉：选项定义只有一份（`entryTypes.ts` 的 `entryTypeOptions`），浏览页 / 摘要页共用。
 *
 * 非受控 + `key={value}`：沿用筛选栏既有模式，提交 / 清除筛选后按 URL 值强制重建，回填当前生效值。
 */
export function EntryTypeFilter({ value = '' }: { value?: string }) {
  return (
    <select name="entry_type" aria-label="日记类型" key={value} defaultValue={value}>
      <option value="">全部类型</option>
      {entryTypeOptions.map(([entryType, label]) => (
        <option key={entryType} value={entryType}>
          {label}
        </option>
      ))}
    </select>
  )
}
