import {apiGet,queryString} from './client';import type {Page,SummaryItem} from './types'
export const getSummaries=(params:Record<string,string|number|undefined>,signal?:AbortSignal)=>apiGet<Page<SummaryItem>>(`/api/summaries${queryString(params)}`,{signal})
export const getEntrySummary=(id:string|number,signal?:AbortSignal)=>apiGet<SummaryItem>(`/api/entries/${id}/summary`,{signal})