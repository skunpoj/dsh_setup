'use strict';
// Operator-owned local source, loaded for every session in the private worker.
// No listener, remote MCP, credentials, shell or process-execution tool.
const {spawn} = require('node:child_process');
const tools = [
  {name:'read_file', description:'Read a UTF-8 file inside this user/environment /workspace (up to 1 MiB).',
    inputSchema:{type:'object',properties:{path:{type:'string'}},required:['path'],additionalProperties:false},annotations:{readOnlyHint:true}},
  {name:'write_file', description:'Create or replace a UTF-8 file inside this private /workspace. Parent directory must exist. Up to 1 MiB; symlinks and external paths refused.',
    inputSchema:{type:'object',properties:{path:{type:'string'},content:{type:'string'}},required:['path','content'],additionalProperties:false},annotations:{readOnlyHint:false}},
  {name:'list_directory', description:'List a directory in this private /workspace (up to 2000 entries).',
    inputSchema:{type:'object',properties:{path:{type:'string'}},required:['path'],additionalProperties:false},annotations:{readOnlyHint:true}}
];
function execute(request) {
  return new Promise((resolve, reject) => {
    const child=spawn('/usr/bin/python3',['/opt/dsh/container/workspace-file-tools.py'],
      {env:{LANG:'C.UTF-8'},stdio:['pipe','pipe','pipe']});
    let output='', size=0;
    const timer=setTimeout(()=>{child.kill('SIGKILL');reject(new Error('Workspace operation timed out'));},10000);
    child.stdout.on('data',data=>{size+=data.length;if(size>2200000){child.kill('SIGKILL');reject(new Error('Workspace response too large'));}else output+=data.toString();});
    child.stderr.resume();
    child.stdin.on('error',()=>{});
    child.on('error',error=>{clearTimeout(timer);reject(error);});
    child.on('close',code=>{clearTimeout(timer);try{resolve({value:JSON.parse(output),isError:code!==0});}catch{reject(new Error('Invalid workspace operation response'));}});
    child.stdin.end(JSON.stringify(request));
  });
}
function workspaceSource() {
  return {
    id:'dsh-workspace',name:'dsh-workspace',description:'Private local workspace text files',
    async listTools(){return {result:{tools:tools.map(tool=>({...tool,preload:true}))},wasInitialized:undefined};},
    async toolCallInfo(params){return {type:'mcp',mcp_server_id:this.id,mcp_server_name:this.name,original_tool_name:params.name};},
    async callTool(params){
      if(!tools.some(tool=>tool.name===params.name))throw new Error('Unknown workspace tool');
      try{
        const result=await execute({name:params.name,arguments:params.arguments});
        return {result:{content:[{type:'text',text:JSON.stringify(result.value)}],isError:result.isError},wasInitialized:undefined};
      }catch(error){return {result:{content:[{type:'text',text:error.message}],isError:true},wasInitialized:undefined};}
    }
  };
}
module.exports={workspaceSource};
