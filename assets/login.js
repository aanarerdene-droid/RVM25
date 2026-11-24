(()=>{
 let mode='login';
 const form=document.getElementById('authForm'),error=document.getElementById('authError'),submit=document.getElementById('authSubmit');
 const fileMessage='Accounts need the XOT17 server. Start the server and open its web address instead of a local file.';
 function tab(next){mode=next;document.getElementById('loginTab').setAttribute('aria-pressed',String(mode==='login'));document.getElementById('registerTab').setAttribute('aria-pressed',String(mode==='register'));form.elements.password.autocomplete=mode==='login'?'current-password':'new-password';submit.textContent=mode==='login'?'LOGIN':'CREATE ACCOUNT';error.textContent=location.protocol==='file:'?fileMessage:''}
 document.getElementById('loginTab').onclick=()=>tab('login');document.getElementById('registerTab').onclick=()=>tab('register');
 if(location.protocol==='file:')error.textContent=fileMessage;
 form.addEventListener('submit',async e=>{e.preventDefault();error.textContent='';if(location.protocol==='file:'){error.textContent=fileMessage;return}submit.disabled=true;try{
  const res=await fetch('/api/auth/'+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:form.elements.email.value,password:form.elements.password.value})});
  let data;try{data=await res.json()}catch{throw Error('The account service returned an unexpected response. Check that the XOT17 server is running.');}
  if(!res.ok)throw Error(data.error||`Account request failed (${res.status}).`);
  if(mode==='register')try{sessionStorage.setItem('xot17-open-avatar','1')}catch{}
  const target=String(data.role||'').toUpperCase()==='ADMIN'?'/admin':'/';location.assign(target);
 }catch(err){error.textContent=err instanceof TypeError?'Cannot reach the account server. Check your connection and make sure the XOT17 server is running.':(err.message||'Could not reach the account server.');window.RvmI18n?.translate();submit.disabled=false}});
})();
