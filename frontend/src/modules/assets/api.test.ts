import { afterEach, expect, it, vi } from "vitest"
import { getAssetDownload, getAssetPage, getAssetUnderstanding, linkAssetProduct, listAssets, resolveAssetDownloadUrl, reviewAssetFact, startAssetUnderstanding, uploadAsset } from "./api"

afterEach(()=>{vi.unstubAllGlobals();document.cookie="csrftoken=; Max-Age=0; path=/"})
const json=(value:unknown)=>new Response(JSON.stringify(value),{status:200,headers:{"Content-Type":"application/json"}})
it("generates filters and follows only an exact assets cursor",async()=>{const fetch=vi.fn().mockImplementation(()=>Promise.resolve(json({next:null,previous:null,results:[]})));vi.stubGlobal("fetch",fetch);await listAssets({type:"IMAGE",status:"READY",tag:"gear"});await getAssetPage("/api/v1/assets?cursor=next");expect(fetch.mock.calls[0][0]).toBe("/api/v1/assets?type=IMAGE&status=READY&tag=gear");expect(fetch.mock.calls[1][0]).toBe("/api/v1/assets?cursor=next");await expect(getAssetPage("https://evil.example/api/v1/assets?cursor=x")).rejects.toBeDefined()})
it("uploads multipart with NFKC-casefolded, deduplicated tags and default metadata",async()=>{document.cookie="csrftoken=token; path=/";const fetch=vi.fn().mockResolvedValue(json({id:"a1"}));vi.stubGlobal("fetch",fetch);await uploadAsset({file:new File(["x"],"gear.png"),asset_type:"IMAGE",language:"en",tags:["ＧＥＡＲ"," gear ","Straße","STRASSE",""]});const init=fetch.mock.calls[0][1] as RequestInit,body=init.body as FormData;expect(init.method).toBe("POST");expect(new Headers(init.headers).get("Content-Type")).toBeNull();expect(body.get("tags")).toBe('["gear","strasse"]');expect(body.get("metadata_json")).toBe("{}")})
it("links a product and requests a temporary download URL",async()=>{document.cookie="csrftoken=token; path=/";const fetch=vi.fn().mockResolvedValueOnce(json({id:"a1"})).mockResolvedValueOnce(json({url:"https://cdn.example/x",expires_in:60}));vi.stubGlobal("fetch",fetch);await linkAssetProduct("a1","p1");await getAssetDownload("a1");expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({product_id:"p1"});expect(fetch.mock.calls[1][0]).toBe("/api/v1/assets/a1/download-url")})
it("starts, reloads and reviews asset understanding without sending externally",async()=>{document.cookie="csrftoken=token; path=/";const payload={job:{status:"SUCCEEDED"},facts:[],warnings:[],is_partial:false,provider_label:"Fake Provider · 本地演示"};const fetch=vi.fn().mockImplementation(()=>Promise.resolve(json(payload)));vi.stubGlobal("fetch",fetch);await startAssetUnderstanding("a1","p1");await getAssetUnderstanding("a1");await reviewAssetFact("f1","APPROVE","checked");expect(fetch.mock.calls.map(call=>call[0])).toEqual(["/api/v1/assets/a1/understanding","/api/v1/assets/a1/understanding","/api/v1/assets/facts/f1/review"]);expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({product_id:"p1"});expect(JSON.parse(fetch.mock.calls[2][1].body)).toEqual({decision:"APPROVE",note:"checked"})})
it.each([
  [{url:"javascript:alert(1)",expires_in:60}],
  [{url:"//cdn.example/x",expires_in:60}],
  [{url:"https://user:secret@cdn.example/x",expires_in:60}],
  [{url:"https://cdn.example/x",expires_in:0}],
  [{url:"not a url",expires_in:60}],
  [{url:"https://other.example/x",expires_in:60}],
])("rejects unsafe or expired download metadata %#",(result)=>{
  expect(()=>resolveAssetDownloadUrl(result,["https://cdn.example"])).toThrow()
})
it("accepts an absolute http(s) URL only from the explicit origin allowlist",()=>{
  expect(resolveAssetDownloadUrl({url:"https://cdn.example/x?sig=1",expires_in:60},["https://cdn.example"]).href).toBe("https://cdn.example/x?sig=1")
})
