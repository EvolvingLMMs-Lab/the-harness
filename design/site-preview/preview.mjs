/** Local preview uses the same byte-range contract as production static hosting. */
import {createServer} from 'node:http';
import {createReadStream} from 'node:fs';
import {stat} from 'node:fs/promises';
import {resolve,extname,sep} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const defaultRoot=fileURLToPath(new URL('../../docs/dist/',import.meta.url));
export function createPreviewServer(directory=defaultRoot){
  const root=resolve(directory);
  return createServer(async(req,res)=>{
    try{
      if(!['GET','HEAD'].includes(req.method)){res.writeHead(405);res.end();return;}
      let path=resolve(root,'.'+decodeURIComponent(new URL(req.url,'http://localhost').pathname));
      if(path!==root&&!path.startsWith(root+sep)){res.writeHead(403);res.end();return;}
      let info=await stat(path);
      if(info.isDirectory()){path=resolve(path,'index.html');info=await stat(path);}
      const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css','.mp4':'video/mp4','.jpg':'image/jpeg','.png':'image/png','.svg':'image/svg+xml','.ttf':'font/ttf','.woff2':'font/woff2','.json':'application/json'};
      res.setHeader('Content-Type',types[extname(path)]||'application/octet-stream');
      res.setHeader('Accept-Ranges','bytes');res.setHeader('Cache-Control','no-store');
      let start=0,end=info.size-1,status=200;
      if(req.headers.range){
        const match=/^bytes=(\d*)-(\d*)$/.exec(req.headers.range);
        if(!match||(!match[1]&&!match[2])){res.writeHead(416,{'Content-Range':`bytes */${info.size}`});res.end();return;}
        start=match[1]?Number(match[1]):Math.max(0,info.size-Number(match[2]));
        end=match[1]&&match[2]?Math.min(Number(match[2]),end):end;
        if(start>end||start>=info.size){res.writeHead(416,{'Content-Range':`bytes */${info.size}`});res.end();return;}
        status=206;res.setHeader('Content-Range',`bytes ${start}-${end}/${info.size}`);
      }
      res.writeHead(status,{'Content-Length':Math.max(0,end-start+1)});
      if(req.method==='HEAD'||info.size===0){res.end();return;}
      const stream=createReadStream(path,{start,end});stream.on('error',()=>res.destroy());
      res.on('close',()=>stream.destroy());stream.pipe(res);
    }catch{if(!res.headersSent)res.writeHead(404);res.end();}
  });
}
if(process.argv[1]&&pathToFileURL(resolve(process.argv[1])).href===import.meta.url){
  const port=Number(process.argv[2]||8840);
  createPreviewServer().listen(port,'127.0.0.1',()=>console.log(`http://127.0.0.1:${port}/zh-cn/`));
}
