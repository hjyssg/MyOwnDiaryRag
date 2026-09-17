export class ApiError extends Error { constructor(public status:number, message:string, public detail?:string){super(message)} }
const base = import.meta.env.VITE_API_BASE_URL ?? ''
export async function apiGet<T>(path:string, options?:{signal?:AbortSignal}):Promise<T>{
  const response=await fetch(`${base}${path}`,{signal:options?.signal,headers:{Accept:'application/json'}})
  if(!response.ok){let detail:string|undefined;try{const body=await response.json() as {detail?:unknown};detail=typeof body.detail==='string'?body.detail:undefined}catch{detail=undefined}throw new ApiError(response.status,detail??`请求失败 (${response.status})`,detail)}
  return response.json() as Promise<T>
}
export function queryString(params:Record<string,string|number|null|undefined>){const q=new URLSearchParams();Object.entries(params).forEach(([k,v])=>{if(v!==null&&v!==undefined&&v!=='')q.set(k,String(v))});const text=q.toString();return text?`?${text}`:''}