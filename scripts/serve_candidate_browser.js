// Executed only inside a disposable candidate container by test_candidate_browser.js.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http');
const {spawn,spawnSync}=require('node:child_process');
const home=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-browser-'));
fs.cpSync('/opt/dsh/seed/dsh-home',home,{recursive:true});
const port=Number(process.env.DSH_BROWSER_PORT||31998), mockPort=port+1;
// Rewrite only copied synthetic state; the image seed and managed files stay intact.
function rewrite(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
 const file=path.join(dir,entry.name);if(entry.isDirectory())rewrite(file);
 else if(/\.ya?ml$/.test(entry.name))fs.writeFileSync(file,fs.readFileSync(file,'utf8').replaceAll('http://litellm.llm.svc.cluster.local:4000',`http://127.0.0.1:${mockPort}`));
}}
rewrite(home);
let modelRequests=0,child;
const mock=http.createServer((_req,res)=>{modelRequests++;res.writeHead(503,{'content-type':'application/json'});res.end('{"error":"inference forbidden in browser qualification"}');});
mock.listen(mockPort,'127.0.0.1',()=>{
 const env={PATH:process.env.PATH,HOME:home,DSH_HOME:home,LANG:'C.UTF-8',DEEPSEEK_API_KEY:'synthetic-browser-no-inference',DSH_MANAGED_TRANSPORT:'0',NARB_NATIVE_CACHE_DIR:'/native-cache',NODE_OPTIONS:''};
 // The reviewed native loader materializes its .node module in its cache and
 // requires that copy. Keep only this bounded cache executable; /tmp is unchanged.
 const native=spawnSync(process.execPath,['-e',`try { require(require.resolve('node-addon-require-builtin',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']})); } catch(error) { console.error(require('node:util').inspect(error,{depth:null,colors:false}));process.exit(1); }`],{env,encoding:'utf8',timeout:15000});
 if(native.status!==0){console.error(JSON.stringify({nativePreflightFailed:true,error:(native.stderr||native.error?.message||'Unknown native loader failure').slice(-16000),modelRequests}));mock.close();process.exitCode=1;return;}
 child=spawn('dsh',['web','--host','127.0.0.1','--port',String(port),'--no-open','--trusted-host','dsh-ci.test'],{env,stdio:['ignore','pipe','pipe']});
 let buffer='',reported=false;
 const collect=b=>{buffer=(buffer+b.toString()).slice(-32000);const match=buffer.match(/token=([A-Za-z0-9_-]+)/);if(match&&!reported){reported=true;console.log(JSON.stringify({browserReady:true,token:match[1]}));}};
 child.stdout.on('data',collect);child.stderr.on('data',collect);
 child.on('error',error=>console.error(JSON.stringify({startupError:error.message})));
 child.on('exit',code=>{console.log(JSON.stringify({modelRequests,childExit:code,...(!reported?{startupLog:buffer.replace(/token[=:]\s*[A-Za-z0-9_-]+/gi,'token=[REDACTED]').replace(/synthetic-browser-no-inference/g,'[SYNTHETIC KEY REDACTED]').slice(-12000)}:{})}));mock.close();process.exitCode=code||0;});
});
process.on('SIGTERM',()=>{console.log(JSON.stringify({modelRequests}));child?.kill('SIGTERM');setTimeout(()=>process.exit(modelRequests?1:0),1500).unref();});
setTimeout(()=>{console.error('Disposable browser server deadline exceeded');child?.kill('SIGTERM');process.exit(1);},180000).unref();
