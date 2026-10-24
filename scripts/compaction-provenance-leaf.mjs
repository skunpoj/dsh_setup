// Guard-only leaf: preserves existing compaction engine, instruction and framing.
import {BlockAssembler} from '@deepseek-ai/dsh-llm';
import quality from './managed_compaction_quality.cjs';
const DIRECTIVE='You are now acting as a compaction engine for this AI coding assistant.';
const hold=reason=>new quality.CompactionProvenanceError({status:'unknown',reason},[],[]);
const MAX_CHUNKS=131072,MAX_TEXT=262144,MAX_BYTES=4*1024*1024;
export default function compactionProvenanceLeaf(ctx){
 ctx.on('llm/stream',(options,next)=>{
  if(options.purpose!=='compaction')return next();
  return (async function*(){
   const messages=options.messages;
   if(!Array.isArray(messages)||messages.length===0)throw hold('Compaction guard requires visible source messages');
   const final=messages.at(-1);
   const directive=final?.role==='user'&&Array.isArray(final.content)&&final.content.some(b=>b.type==='text'&&b.text.startsWith(DIRECTIVE));
   if(!directive)throw hold('Compaction guard refuses unknown compaction input contract');
   const source=messages.slice(0,-1),chunks=[],assembler=new BlockAssembler();let text=0,bytes=0;
   for await(const chunk of next()){
    options.signal?.throwIfAborted();
    if(chunks.length>=MAX_CHUNKS)throw hold('Compaction guard chunk budget exceeded');
    const encoded=JSON.stringify(chunk);bytes+=Buffer.byteLength(encoded??'');
    if(bytes>MAX_BYTES)throw hold('Compaction guard buffered stream budget exceeded');
    if(chunk.type==='text-delta'||chunk.type==='reasoning-delta')text+=chunk.text.length;
    if(text>MAX_TEXT)throw hold('Compaction guard text budget exceeded');
    chunks.push(chunk);assembler.push(chunk);
   }
   options.signal?.throwIfAborted();
   const raw=assembler.blocks(),summary=raw.filter(b=>b.type==='text').map(b=>({type:'text',text:b.text}));
   // Preserve provider failure semantics. Only complete, textual candidates reach provenance adoption checks.
   if(!['error','aborted','max-tokens'].includes(assembler.finish.kind)&&summary.some(b=>b.text.trim()))quality.assertSummaryProvenance(source,summary,raw);
   for(const chunk of chunks){options.signal?.throwIfAborted();yield chunk;}
  })();
 },{prepend:true});
 ctx.on('compaction/summary-error',(event,next)=>quality.isProvenanceHold(event.error)?false:next(),{prepend:true});
}
