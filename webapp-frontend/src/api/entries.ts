import {apiGet,queryString} from './client'; import type {EntryDetail,EntryPreview,MonthStat,OnThisDayResponse,Page,RandomDayResponse,YearStat} from './types'
export const getYears=(signal?:AbortSignal)=>apiGet<YearStat[]>('/api/years',{signal})
export const getMonths=(year:number,signal?:AbortSignal)=>apiGet<MonthStat[]>(`/api/months?year=${year}`,{signal})
export const getEntries=(params:Record<string,string|number|undefined>,signal?:AbortSignal)=>apiGet<Page<EntryPreview>>(`/api/entries${queryString(params)}`,{signal})
export const getEntry=(id:string|number,signal?:AbortSignal)=>apiGet<EntryDetail>(`/api/entries/${id}`,{signal})
export const getOnThisDay=(month:number,day:number,signal?:AbortSignal)=>apiGet<OnThisDayResponse>(`/api/on-this-day?month=${month}&day=${day}`,{signal})
export const getRandom=(signal?:AbortSignal)=>apiGet<RandomDayResponse>('/api/random',{signal})