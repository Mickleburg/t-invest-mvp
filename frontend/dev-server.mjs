import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=fileURLToPath(new URL('./src/',import.meta.url));
const upstream=new URL(process.env.API_UPSTREAM||'http://127.0.0.1:8003');
if(upstream.protocol!=='http:')throw Error('Use an HTTP backend on the private network');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8'};
http.createServer(async(req,res)=>{
  if(req.url.startsWith('/api/')){
    const remote=http.request(new URL(req.url,upstream),{method:req.method,headers:{...req.headers,host:upstream.host}},r=>{res.writeHead(r.statusCode,r.headers);r.pipe(res)});
    remote.setTimeout(700000,()=>remote.destroy());
    remote.on('error',()=>{if(!res.headersSent){res.writeHead(502,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'Backend unavailable'}))}else res.destroy()});
    req.pipe(remote);return;
  }
  try{
    let route=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    if(route==='/')route='/index.html';
    if(route.startsWith('/static/'))route=route.slice(7);
    const target=path.resolve(root,'.'+route);
    if(!target.startsWith(root)||!types[path.extname(target)]){res.writeHead(404);res.end();return}
    const body=await readFile(target);res.writeHead(200,{'Content-Type':types[path.extname(target)],'Cache-Control':'no-store'});res.end(body);
  }catch{res.writeHead(404);res.end()}
}).listen(Number(process.env.PORT||5173),process.env.HOST||'127.0.0.1',()=>console.log('TradeGuard frontend ready'));
