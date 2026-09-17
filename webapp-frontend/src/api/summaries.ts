import {apiGet,queryString} from './client';import type {EmotionListResponse,Page,SummaryItem} from './types'
export const getSummaries=(params:Record<string,string|number|undefined>,signal?:AbortSignal)=>apiGet<Page<SummaryItem>>(`/api/summaries${queryString(params)}`,{signal})
export const getEmotionLabels=(signal?:AbortSignal)=>apiGet<EmotionListResponse>('/api/summaries/emotions',{signal})
export const getEntrySummary=(id:string|number,signal?:AbortSignal)=>apiGet<SummaryItem>(`/api/entries/${id}/summary`,{signal})