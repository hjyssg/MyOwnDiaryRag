/** 筛选栏的年份区间：超出范围视为"不筛选"，避免把脏参数发给后端 */
export const MIN_YEAR = 2000
export const MAX_YEAR = 2100

/** 归一化年份：必须是 4 位且在合法区间内，否则视为"不筛选" */
export function normalizeYear(raw: string | null): number | undefined {
  const text = (raw ?? '').trim()
  if (!/^\d{4}$/.test(text)) return undefined
  const year = Number(text)
  return year >= MIN_YEAR && year <= MAX_YEAR ? year : undefined
}

/** 归一化月份：必须在 1–12，非法输入视为"不筛选"（避免后端 422） */
export function normalizeMonth(raw: string | null): number | undefined {
  const text = (raw ?? '').trim()
  if (!/^\d{1,2}$/.test(text)) return undefined
  const month = Number(text)
  return month >= 1 && month <= 12 ? month : undefined
}

/** 从 URL query 取出可用的年 / 月 */
export function yearMonthParams(search: URLSearchParams) {
  return {
    year: normalizeYear(search.get('year')),
    month: normalizeMonth(search.get('month')),
  }
}
