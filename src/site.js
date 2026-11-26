(function(){
  'use strict';
  var MF=window.MF,LANGS=MF.langs,byCode={};
  LANGS.forEach(function(l){byCode[l.code]=l});
  var cache={en:MF.en},cur='en',T=MF.en;
  function $(id){return document.getElementById(id)}
  function store(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}}
  /* Meta Pixel events (the Pixel itself is in <head>); never let tracking break the page */
  function px(kind,name,params){try{if(window.fbq)window.fbq(kind,name,params||{})}catch(e){}}
  var still=window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- menu, year, case filters ---------- */
  var b=$('burger'),m=$('menu');
  b.addEventListener('click',function(){var o=m.classList.toggle('open');b.setAttribute('aria-expanded',o)});
  m.addEventListener('click',function(e){if(e.target.tagName==='A'){m.classList.remove('open');b.setAttribute('aria-expanded','false')}});
  $('yr').textContent=new Date().getFullYear();
  var btns=document.querySelectorAll('.filters button'),cases=document.querySelectorAll('#cases .case');
  btns.forEach(function(x){x.addEventListener('click',function(){
    var f=x.dataset.f;btns.forEach(function(y){y.setAttribute('aria-pressed',y===x)});
    cases.forEach(function(c){c.hidden=!(f==='all'||c.dataset.f.split(' ').indexOf(f)>-1)});
  })});

  /* ---------- languages ---------- */
  var sel=$('lang');
  LANGS.forEach(function(l){var o=document.createElement('option');o.value=l.code;o.textContent=l.name;sel.appendChild(o)});
  function pick(){
    if(window.MF_LANG&&byCode[window.MF_LANG])return window.MF_LANG; /* chosen in <head> */
    var s=store('mf-lang');if(s&&byCode[s])return s;
    var n=navigator.languages||[navigator.language||'en'];
    for(var i=0;i<n.length;i++){var c=String(n[i]).toLowerCase().split('-')[0];if(c==='tl')c='fil';if(byCode[c])return c}
    return 'en';
  }
  function load(code){
    if(cache[code])return Promise.resolve(cache[code]);
    if(window.MF_PRE&&code===window.MF_LANG){var p=window.MF_PRE;window.MF_PRE=null;return p.then(function(d){cache[code]=d;return d})}
    return fetch(MF.i18nPath+code+'.json').then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(d){cache[code]=d;return d});
  }
  function apply(){
    var root=document.documentElement;root.lang=cur;root.dir=byCode[cur].dir||'ltr';
    document.querySelectorAll('[data-i18n]').forEach(function(el){var v=T[el.getAttribute('data-i18n')];if(v!=null)el.textContent=v});
    document.querySelectorAll('[data-i18n-html]').forEach(function(el){var v=T[el.getAttribute('data-i18n-html')];if(v!=null)el.innerHTML=v});
    document.querySelectorAll('[data-i18n-ph]').forEach(function(el){var v=T[el.getAttribute('data-i18n-ph')];if(v!=null)el.placeholder=v});
    document.querySelectorAll('[data-i18n-aria]').forEach(function(el){var v=T[el.getAttribute('data-i18n-aria')];if(v!=null)el.setAttribute('aria-label',v)});
    var h=$('hero-h1');if(h)h.classList.toggle('long',h.textContent.length>56);
    var md=document.querySelector('meta[name=description]');if(md&&T.meta_desc)md.setAttribute('content',T.meta_desc);
  }
  function setLang(code,save){
    return load(code).catch(function(){code='en';return MF.en}).then(function(d){
      cur=code;T=d;if(save)store('mf-lang',code);sel.value=code;apply();bot.reset();
    });
  }
  /* keep ?lang= in the address in step with the dropdown, so a shared link opens in the same language */
  function setUrl(code){
    try{var u=new URL(location.href);if(code==='en')u.searchParams.delete('lang');else u.searchParams.set('lang',code);history.replaceState(null,'',u);var k=document.querySelector('link[rel=canonical]');if(k)k.href=MF.siteUrl+'/'+(code==='en'?'':'?lang='+code)}catch(e){}
  }
  sel.addEventListener('change',function(){setLang(sel.value,true);setUrl(sel.value);px('trackCustom','ChangeLanguage',{lang:sel.value})});

  /* ---------- assistant ---------- */
  var bot=(function(){
    var panel=$('bot'),log=$('bot-log'),form=$('bot-form'),inp=$('bot-in'),opener=$('bot-open'),
        voiceBtn=$('bot-voice'),mic=$('bot-mic'),greeted=false;
    var synth=window.speechSynthesis,SR=window.SpeechRecognition||window.webkitSpeechRecognition;
    var voice=store('mf-voice')==='1';
    var KW={
      price:['price','pricing','cost','fee','quote','how much','charge','bei','gharama','precio','costo','cuánto','preis','kosten','kostet','fiyat','ücret','价格','费用','多少钱','presyo','magkano','料金','価格','費用','سعر','تكلفة','цен','стоим','сколько','prix','tarif','combien','preço','custo','quanto','कीमत','क़ीमत','दाम','शुल्क','prezz','비용','가격','harga','biaya','prijs','giá','chi phí','cena','koszt','ราคา','narx','qancha','baho','баа','канча'],
      contact:['contact','email','e-mail','phone','call','whatsapp','reach','mawasiliano','wasiliana','simu','contacto','kontakt','iletişim','telefon','联系','电话','kontak','連絡','問い合わせ','تواصل','اتصال','контакт','связ','téléphone','contato','संपर्क','contatt','연락','hubungi','liên hệ','ติดต่อ','aloqa','bog‘lan','telefon','байланыш'],
      services:['service','offer','what do you do','huduma','servicio','leistung','dienst','hizmet','服务','serbisyo','サービス','خدم','услуг','serviço','सेवा','serviz','서비스','layanan','dịch vụ','usług','บริการ','xizmat','кызмат'],
      process:['process','how','start','begin','jinsi','cómo','wie','nasıl','流程','怎么','paano','進め方','どう','كيف','как','comment','como','कैसे','come','어떻게','방식','bagaimana','hoe','thế nào','cách','jak','อย่างไร','วิธี','qanday','кантип'],
      work:['case','project','portfolio','example','mradi','miradi','proyecto','projekt','proje','案例','项目','proyekto','事例','実績','مشاريع','проект','кейс','projet','projeto','प्रोजेक्ट','progett','사례','프로젝트','proyek','dự án','โครงการ','ผลงาน','loyiha','долбоор'],
      about:['who','about','founder','nani','kuhusu','quién','wer','über','kim','hakkında','关于','谁','sino','誰','について','кто','о нас','qui','quem','sobre','कौन','누구','소개','siapa','tentang','over','giới thiệu','kto','ใคร','เกี่ยวกับ','kim','haqida','ким','жөнүндө'],
      greet:['hello','hi','hey','habari','hujambo','mambo','hola','hallo','merhaba','你好','kumusta','こんにちは','مرحبا','привет','здравствуйте','bonjour','olá','नमस्ते','ciao','안녕','halo','xin chào','cześć','สวัสดี','salom','assalomu','салам']
    };
    var HINT=[null,['gis','qgis','autocad','midas','staad','civil','engineer','map','drawing','structur'],['automat','n8n','workflow','spreadsheet'],['research','thesis','student','universit','academic','lectur'],['report','document','schedule','proposal','gantt'],['excel','vba','tool','mcp','connector','app'],['train','workshop','course','teach']];
    function has(q,list){return list.some(function(k){return /^[\x00-\x7f]+$/.test(k)?new RegExp('(^|[^a-z])'+k).test(q):q.indexOf(k)>-1})}
    function whichService(q){
      var best=0,bi=0;
      for(var i=1;i<=6;i++){
        var sc=0;
        HINT[i].forEach(function(w){if(q.indexOf(w)>-1)sc+=2});
        T['s'+i+'_t'].toLowerCase().split(/[\s,.&;:、，]+/).forEach(function(w){if(w.length>=5&&q.indexOf(w)>-1)sc++});
        if(sc>best){best=sc;bi=i}
      }
      return bi;
    }
    function list(prefix,n,withDesc){
      var out=[];for(var i=1;i<=n;i++)out.push((prefix==='p'?i+'. ':'• ')+T[prefix+i+'_t']+(withDesc?' — '+T[prefix+i+'_d']:''));
      return out.join('\n');
    }
    function intentOf(q){
      q=q.toLowerCase();
      if(has(q,KW.price))return 'price';
      if(has(q,KW.contact))return 'contact';
      var s=whichService(q);if(s)return 's'+s;
      if(has(q,KW.services))return 'services';
      if(has(q,KW.work))return 'work';
      if(has(q,KW.about))return 'about';
      if(has(q,KW.process))return 'process';
      if(q.split(/\s+/).length<=3&&has(q,KW.greet))return 'greet';
      return 'fallback';
    }
    function answer(intent){
      switch(intent){
        case 'price':return T.ai_price;
        case 'contact':return T.ai_contact;
        case 'services':return T.svc_h2+'\n'+list('s',6,false);
        case 'process':return T.proc_h2+'\n'+list('p',4,true);
        case 'work':return T.work_p;
        case 'about':return T.about_p;
        case 'greet':return T.ai_hello;
        case 'fallback':return T.ai_fallback;
        default:var i=intent.charAt(1);return T['s'+i+'_t']+' — '+T['s'+i+'_d']+'\n\n'+T.ai_price;
      }
    }
    /* Speech uses the voices installed on the visitor's device. Pick one that really matches the
       page language; never let an English voice read another language. */
    var warned={};
    function pickVoice(){
      var vs=synth.getVoices();if(!vs.length)return undefined;            /* list not loaded yet */
      var want=byCode[cur].speech.toLowerCase(),bases=cur==='fil'?['fil','tl']:[cur],best=null,score=0;
      vs.forEach(function(v){
        var l=String(v.lang).replace('_','-').toLowerCase(),b=l.split('-')[0],sc=0;
        if(l===want)sc=3;else if(bases.indexOf(b)>-1)sc=2;
        if(sc&&/natural|google|online|premium|enhanced/i.test(v.name))sc+=0.5;
        if(sc>score){score=sc;best=v}
      });
      return best;
    }
    function say(text){
      if(!voice||!synth)return;
      var v=pickVoice();
      if(v===null){
        if(!warned[cur]){warned[cur]=true;add(T.ai_novoice,'a note')}
        return;
      }
      synth.cancel();
      var u=new SpeechSynthesisUtterance(text.replace(/[•—]/g,' '));
      if(v){u.voice=v;u.lang=v.lang}else{u.lang=byCode[cur].speech}
      synth.speak(u);
    }
    function add(text,who){
      var d=document.createElement('div');d.className='msg '+who;d.dir='auto';d.textContent=text;
      log.appendChild(d);log.scrollTop=log.scrollHeight;return d;
    }
    function respond(text){add(text,'a');say(text)}
    var hist=[];   /* the conversation so far, sent to the server so follow-up questions make sense */
    /* q: the visitor's words; intent: built-in topic to fall back on (quick buttons) */
    function ask(q,intent){
      add(q,'u');
      var local=function(){var a=answer(intent||intentOf(q));respond(a);hist.push({role:'user',text:q},{role:'assistant',text:a})};
      if(!MF.assistantEndpoint||!window.fetch){local();return}
      /* the server answers with a language model, word by word; if it is unreachable, the built-in answers are used */
      var box=add('…','a typing'),got='',done=false;
      function finish(){
        if(done)return;done=true;
        if(!got.trim()){box.remove();local();return}
        box.classList.remove('typing');box.textContent=got.trim();say(got.trim());
        hist.push({role:'user',text:q},{role:'assistant',text:got.trim()});
      }
      fetch(MF.assistantEndpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:q,lang:cur,history:hist.slice(-6),stream:true})})
        .then(function(r){
          if(!r.ok)throw 0;
          var ct=r.headers.get('content-type')||'';
          if(ct.indexOf('application/json')>=0||!r.body||!window.TextDecoder)   /* whole reply at once */
            return r.json().then(function(d){if(!d||!d.reply)throw 0;got=String(d.reply);finish()});
          var rd=r.body.getReader(),dec=new TextDecoder();
          return (function pump(){
            return rd.read().then(function(c){
              if(c.done){got+=dec.decode();finish();return}
              got+=dec.decode(c.value,{stream:true});
              if(got.trim()){box.classList.remove('typing');box.textContent=got;log.scrollTop=log.scrollHeight}
              return pump();
            });
          })();
        })
        .catch(function(){if(got.trim())finish();else{done=true;box.remove();local()}});
    }
    function greet(){if(!greeted){greeted=true;respond(T.ai_hello)}}
    function toggle(open){
      panel.hidden=!open;opener.setAttribute('aria-expanded',open);
      if(open){greet();inp.focus()}else{if(synth)synth.cancel();opener.focus()}
    }
    opener.addEventListener('click',function(){if(panel.hidden)px('trackCustom','OpenAssistant',{lang:cur});toggle(panel.hidden)});
    $('bot-close').addEventListener('click',function(){toggle(false)});
    panel.addEventListener('keydown',function(e){if(e.key==='Escape')toggle(false)});
    form.addEventListener('submit',function(e){e.preventDefault();var q=inp.value.trim();if(!q)return;inp.value='';ask(q)});
    $('bot-chips').addEventListener('click',function(e){
      var t=e.target.closest('button');if(!t)return;ask(t.textContent,t.dataset.intent);
    });
    if(synth){
      synth.getVoices();if('onvoiceschanged' in synth)synth.onvoiceschanged=function(){synth.getVoices()};
      voiceBtn.hidden=false;voiceBtn.setAttribute('aria-pressed',voice);
      voiceBtn.addEventListener('click',function(){
        voice=!voice;store('mf-voice',voice?'1':'0');voiceBtn.setAttribute('aria-pressed',voice);
        if(!voice)synth.cancel();else{var all=log.querySelectorAll('.msg.a:not(.note)'),last=all[all.length-1];if(last)say(last.textContent)}
      });
    }
    if(SR){
      mic.hidden=false;
      mic.addEventListener('click',function(){
        var r=new SR();r.lang=byCode[cur].speech;r.interimResults=false;mic.classList.add('on');
        r.onresult=function(e){var t=e.results[0][0].transcript;if(t)ask(t)};
        r.onend=r.onerror=function(){mic.classList.remove('on')};
        try{r.start()}catch(err){mic.classList.remove('on')}
      });
    }
    return {reset:function(){log.textContent='';greeted=false;hist=[];if(synth)synth.cancel();if(!panel.hidden)greet()}};
  })();

  /* ---------- contact form ---------- */
  var cform=$('cform'),st=$('f-status'),send=$('f-send');
  cform.addEventListener('submit',function(e){
    e.preventDefault();st.className='status full';
    var n=cform.name.value.trim(),em=cform.email.value.trim(),msg=cform.message.value.trim();
    if(!n||!msg||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em)){st.textContent=T.f_invalid;st.classList.add('err');return}
    if(cform.website.value){st.textContent=T.f_ok;return}
    if(!/mindfreedom\.co\.tz$/.test(location.hostname)){st.textContent='Preview only: on mindfreedom.co.tz this sends to info@mindfreedom.co.tz.';st.classList.add('ok');return}
    send.disabled=true;send.textContent='…';
    var fd=new FormData(cform);fd.delete('website');
    fd.append('_subject','Website enquiry: '+cform.topic.value+' - '+n);fd.append('language',byCode[cur].name);
    fd.append('_template','table');fd.append('_captcha','false');
    fetch('https://formsubmit.co/ajax/info@mindfreedom.co.tz',{method:'POST',headers:{'Accept':'application/json'},body:fd}).then(function(r){return r.json()}).then(function(d){
      if(d&&(d.success===true||d.success==='true')){px('track','Lead',{content_category:cform.topic.value,lang:cur});cform.reset();st.textContent=T.f_ok;st.classList.add('ok')}
      else throw 0;
    }).catch(function(){st.textContent=T.f_err;st.classList.add('err')})
    .finally(function(){send.disabled=false;send.textContent=T.f_send});
  });

  /* ---------- hero network: strands weaving between node columns, as in the logo ---------- */
  var cv=$('net'),cx=cv.getContext('2d'),W,H,dpr=Math.min(window.devicePixelRatio||1,2);
  var cols=['#17BFB3','#7C6CF0','#3A8DF0'];
  function size(){W=cv.clientWidth;H=cv.clientHeight;cv.width=W*dpr;cv.height=H*dpr;cx.setTransform(dpr,0,0,dpr,0,0)}
  function draw(t){
    cx.clearRect(0,0,W,H);
    var lanes=5,x0=W*0.35,span=W*0.7,n=6,step=span/n,py=0;
    for(var k=0;k<lanes;k++){
      var y=H*(0.18+k*0.16);
      for(var s=0;s<2;s++){
        cx.beginPath();cx.lineWidth=2.4;cx.strokeStyle=cols[(k+s)%3];cx.globalAlpha=.75;
        for(var i=0;i<=n;i++){
          var x=x0+i*step,yy=y+(i%2===s?-1:1)*H*0.06*Math.sin(t/2200+k+i*.6);
          if(i===0)cx.moveTo(x,yy);else{var px=x-step;cx.bezierCurveTo(px+step/2,py,px+step/2,yy,x,yy)}
          py=yy;
        }
        cx.stroke();
      }
      for(var j=0;j<=n;j+=2){cx.globalAlpha=1;cx.fillStyle=j%4?'#7C6CF0':'#17BFB3';cx.beginPath();cx.arc(x0+j*step,y,4,0,7);cx.fill()}
    }
    cx.globalAlpha=1;
  }
  function loop(t){draw(t);if(!still)requestAnimationFrame(loop)}
  size();window.addEventListener('resize',function(){size();draw(performance.now())});
  loop(0);

  /* ---------- Pixel: case studies seen (once per visit) ---------- */
  (function(){
    var w=$('work');if(!w||!('IntersectionObserver' in window))return;
    var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){px('track','ViewContent',{content_name:'Case studies',lang:cur});io.disconnect()}})},{threshold:.25});
    io.observe(w);
  })();

  /* ---------- start ---------- */
  var first=pick();sel.value=first;
  function show(){document.documentElement.classList.remove('mf-wait')}
  if(first!=='en')setLang(first,false).then(show,show);else show();
})();
