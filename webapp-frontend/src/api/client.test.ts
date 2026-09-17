import {afterEach,describe,expect,it,vi} from 'vitest';import{ApiError,apiGet,queryString}from'./client'
afterEach(()=>vi.restoreAllMocks())
describe('API client',()=>{
  it('解析 FastAPI detail',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'日记不存在'}),{status:404,headers:{'Content-Type':'application/json'}})));try{await apiGet('/api/x');throw new Error('应抛出 ApiError')}catch(error){expect(error).toBeInstanceOf(ApiError);expect((error as ApiError).status).toBe(404);expect((error as ApiError).detail).toBe('日记不存在')}})
  it('构建 query 并忽略空值',()=>{expect(queryString({year:2024,q:'',month:null,page:2})).toBe('?year=2024&page=2')})
})