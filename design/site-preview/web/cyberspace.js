import * as THREE from 'three';
// A real perspective point-cloud city, rendered independently of the anatomy.
const canvas=document.createElement('canvas');canvas.id='cyberspace';canvas.setAttribute('aria-hidden','true');document.body.prepend(canvas);
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let renderer,frame=0,elapsed=0,last=0,day=false;
try {
 renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:false,powerPreference:'low-power'});
 renderer.setPixelRatio(1);
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(53,1,.1,140);
 const positions=[],seeds=[];let state=43;
 const random=()=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state/4294967296};
 const dot=(x,y,z)=>{positions.push(x,y,z);seeds.push(random())};
 for(let ix=-7;ix<=7;ix++)for(let iz=-10;iz<=5;iz++){
   if(random()<.26)continue;
   const x=ix*4.8,z=iz*4.8,w=1.5+random()*1.5,d=1.5+random()*1.8,h=.6+Math.pow(random(),2)*12;
   const step=.28;
   for(let y=0;y<h;y+=step){
    for(let a=0;a<w;a+=step){if(random()>.12)dot(x+a,y,z);if(random()>.12)dot(x+a,y,z+d)}
    for(let a=0;a<d;a+=step){if(random()>.12)dot(x,y,z+a);if(random()>.12)dot(x+w,y,z+a)}
   }
   for(let a=0;a<w;a+=step)for(let b=0;b<d;b+=step)dot(x+a,h,z+b);
   // Vertical data filaments: denser edges break up into drifting light bands.
   for(let y=0;y<h;y+=.13){dot(x,y,z);dot(x+w,y,z+d)}
 }
 for(let x=-38;x<38;x+=.65)for(let z=-53;z<30;z+=.65){if(random()<.30)dot(x,-.08,z)}
 const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setAttribute('seed',new THREE.Float32BufferAttribute(seeds,1));
 const material=new THREE.ShaderMaterial({transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
 uniforms:{time:{value:0},ink:{value:new THREE.Color('#38cbd7')},opacity:{value:.65},ratio:{value:renderer.getPixelRatio()}},
 vertexShader:`attribute float seed;uniform float time;uniform float ratio;varying float intensity;varying float distanceFade;void main(){vec3 p=position;float scan=pow(max(0.,sin(p.y*.42-time*.34+floor(p.z/4.8)*.7)),14.);intensity=.48+seed*.6+scan*.9;vec4 mv=modelViewMatrix*vec4(p,1.);distanceFade=1.-smoothstep(28.,95.,-mv.z);gl_PointSize=clamp(90./max(1.,-mv.z),1.,3.2)*ratio;gl_Position=projectionMatrix*mv;}`,
 fragmentShader:`uniform vec3 ink;uniform float opacity;varying float intensity;varying float distanceFade;void main(){float r=length(gl_PointCoord-.5);if(r>.5)discard;gl_FragColor=vec4(ink,intensity*distanceFade*opacity*(1.-r*.8));}`});
 scene.add(new THREE.Points(geometry,material));
 const resize=()=>{renderer.setSize(innerWidth,innerHeight);camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();draw()};
 function draw(){camera.position.set(15+Math.sin(elapsed*.035)*3,19+Math.sin(elapsed*.027)*1.5,27+Math.cos(elapsed*.025)*2);camera.lookAt(-3,0,-12);material.uniforms.time.value=elapsed;renderer.render(scene,camera);canvas.dataset.ready='true'}
 function tick(now){frame=0;if(document.hidden||!document.hasFocus()||reduced.matches)return;if(now-last>=50){elapsed+=Math.min((now-last)/1000,.06);last=now;draw()}frame=requestAnimationFrame(tick)}
 const start=()=>{cancelAnimationFrame(frame);last=performance.now();if(!document.hidden&&document.hasFocus()&&!reduced.matches)frame=requestAnimationFrame(tick);else draw()};
 // At night the points sit a step deeper and dimmer than the cyan of the text, so the
 // copy in front of them stays readable.
 const theme=()=>{day=document.body.classList.contains('pearl');material.uniforms.ink.value.set(day?'#167e96':'#2893a5');material.uniforms.opacity.value=day?.58:.8;material.blending=day?THREE.NormalBlending:THREE.AdditiveBlending;material.needsUpdate=true;draw()};
 addEventListener('resize',resize);addEventListener('focus',start);addEventListener('blur',start);document.addEventListener('harness-theme',theme);document.addEventListener('visibilitychange',start);reduced.addEventListener('change',start);
 canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();cancelAnimationFrame(frame);canvas.style.display='none'});
 addEventListener('pagehide',event=>{cancelAnimationFrame(frame);if(!event.persisted){geometry.dispose();material.dispose();renderer.dispose()}});
 addEventListener('pageshow',event=>{if(event.persisted){theme();start()}});
 resize();theme();start();
}catch(error){canvas.remove();console.warn('Cyberspace background unavailable',error)}
