'use strict';
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path');
const {PackagePortal,pins,write}=require('../scripts/package_portal');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-packages-'));
try{
 const portal=new PackagePortal(root);
 for(const bad of ['six','https://example.com/a.whl','six==1;id','--index-url=evil','../x==1','six @ http://internal'])assert.throws(()=>pins(bad));
 const id=portal.create('alice','six==1.17.0','analysis');assert.equal(portal.list('bob').length,0);assert.equal(portal.list('alice')[0].id,id);
 assert.throws(()=>portal.create('alice','six==1.17.0','analysis'));
 assert.throws(()=>portal.create('bob','six==1.17.0','../alice'));
 write(path.join(root,'jobs',id,'public.json'),{state:'complete'});assert.equal(portal.create('alice','six==1.17.0','next').length,32);
 console.log('Package request ownership, pin validation, path refusal and per-owner admission passed.');
}finally{fs.rmSync(root,{recursive:true,force:true})}
