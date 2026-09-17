export interface EntryPreview { id:number; date:string; year:number; month:number; day:number; entry_type:string; word_count:number; preview:string }
export interface EntryDetail extends EntryPreview { content:string; file_source?:string|null }
export interface Page<T> { total:number; page:number; per_page:number; pages:number; items:T[] }
export interface YearStat { year:number; entries:number; words:number }
export interface MonthStat { month:number; entries:number; words:number }
export interface OnThisDayItem { id:number; date:string; year:number; entry_type:string; word_count:number; preview:string }
export interface OnThisDayResponse { month:number; day:number; total:number; groups:{year:number;items:OnThisDayItem[]}[] }
export interface RandomDayResponse { date:string; year:number; month:number; day:number; total:number; items:OnThisDayItem[] }
export interface SummaryItem { entry_key:string|null; entry_id:number|null; entry_date:string|null; entry_type:string|null; word_count:number|null; status:'ok'|'empty'|'failed'|'missing'|'stale'; summary:string; model:string|null; generated_at:string|null }