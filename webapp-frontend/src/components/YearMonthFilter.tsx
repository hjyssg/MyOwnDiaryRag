/** 年 / 月筛选：保持为简单文本输入，提交时由 URL 参数校验统一处理。 */
export function YearMonthFilter({ year = '', month = '' }: { year?: string; month?: string }) {
  return (
    <>
      <input
        name="year"
        type="text"
        placeholder="年份，如 2024"
        aria-label="年份"
        defaultValue={year}
      />
      <input
        name="month"
        type="text"
        placeholder="月份，如 9"
        aria-label="月份"
        defaultValue={month}
      />
    </>
  )
}
