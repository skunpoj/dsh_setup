// Pure policy functions; caller must enforce authentication and network isolation server-side.
export const MODEL = 'deepseek-v4.1-flash';
export const PROVIDER = 'litellm-cluster';
const deny = m => { throw new Error(m); };
const overrides = ['provider','model_name','api_type','api_base','api_key','base_url','baseURL','custom_llm_provider','litellm_params','fallbacks','model_list','deployment_id','azure_endpoint','http_client','http_async_client','extra_headers'];
export function authorizeRequest(method, path, body) {
 if (method === 'GET' && path === '/v1/models') return {catalogOnly:true,models:[MODEL]};
 if (method !== 'POST' || !['/v1/chat/completions','/v1/messages','/v1/messages/count_tokens'].includes(path)) deny('DSH_ROUTE_LOCKED');
 if (!body || typeof body !== 'object' || Array.isArray(body) || body.model !== MODEL) deny('DSH_MODEL_LOCKED');
 for (const k of overrides) if (Object.hasOwn(body,k)) deny('DSH_ROUTING_OVERRIDE_DENIED');
 if (body.extra_body && ['model',...overrides].some(k=>Object.hasOwn(body.extra_body,k))) deny('DSH_ROUTING_OVERRIDE_DENIED');
 return {model:MODEL};
}
export function lockSettings(input, gateway) {
 const u = new URL(gateway);
 if (!['http:','https:'].includes(u.protocol) || !/^litellm\.[a-z0-9-]+\.svc\.cluster\.local$/.test(u.hostname) || u.port !== '4000' || u.pathname !== '/v1' || u.username || u.password || u.search || u.hash) deny('DSH_OPERATOR_GATEWAY_INVALID');
 const x = structuredClone(input);
 const prior = x['llm-pi-ai']?.providers?.[PROVIDER]?.models?.find(m=>m.id===MODEL);
 x['agent-default-model']={provider:PROVIDER,model:MODEL};
 x['llm-pi-ai']={...(x['llm-pi-ai']||{}),providers:{[PROVIDER]:{displayName:'Managed internal DeepSeek',api:'openai-completions',baseURL:gateway,apiKeyEnv:'DEEPSEEK_API_KEY',models:[prior ? {...prior,id:MODEL} : {id:MODEL,name:'DeepSeek-V4.1-Flash-1017 (managed alias)',maxTokens:8192,input:['text']}]}}};
 return x;
}
export function lockProfile(input,gateway){
 if(!Array.isArray(input)) deny('DSH_PROFILE_ARRAY_REQUIRED');
 const x=structuredClone(input), provider=lockSettings({},gateway)['llm-pi-ai'];
 for(const id of ['agent-default-model','session-title-llm']) {let e=x.find(y=>y.id===id);if(!e){e={id};x.push(e);}e.config={provider:PROVIDER,model:MODEL};}
 let e=x.find(y=>y.id==='llm-pi-ai');if(!e){e={id:'llm-pi-ai',name:'@deepseek-ai/dsh-llm-pi-ai'};x.push(e);}e.config=provider;
 for(const id of ['llm-deepseek','llm-deepseek-account','ui-settings-account']){let e=x.find(y=>y.id===id);if(!e){e={id};x.push(e);}e.disabled=true;}
 return x;
}
