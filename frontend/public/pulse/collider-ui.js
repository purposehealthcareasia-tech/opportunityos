import {normalizeCollider,matchColliderJobs,jobMetadata,colliderRegions,colliderCurrencies,colliderSuggestions} from './collider.js';

export function createColliderFeature({getState,E,icon,allPosts,openModal,persist,render,navigate,notify}){
  let selectedTab='matches',draft=null;
  const prefs=()=>normalizeCollider(getState().collider,getState().profile);
  const option=(value,current,label=value)=>`<option value="${E(value)}" ${value===current?'selected':''}>${E(label)}</option>`;
  function entry(placement='default'){
    if(placement==='passport')return `<button type="button" class="collider-entry collider-entry-passport" data-action="navigate" data-value="collider" aria-label="Open Lynk Collider to find jobs matching your interests"><span class="collider-passport-seal" aria-hidden="true">${icon('collider')}</span><span class="collider-entry-copy"><span class="collider-passport-label">JOB DISCOVERY</span><strong>Lynk Collider</strong><small>Find work that fits you.</small></span><span class="collider-passport-arrow" aria-hidden="true">${icon('arrow')}</span></button>`;
    return `<button class="collider-entry" data-action="navigate" data-value="collider"><span class="collider-symbol">${icon('collider')}</span><span class="collider-entry-copy"><strong>Lynk Collider</strong><small>Your interests. Your next opportunity.</small></span>${icon('arrow')}</button>`;
  }
  function result({job,reasons,meta}){
    const saved=getState().saved.includes(job.id);
    return `<article class="collider-result"><div class="collider-result-top"><span class="collider-company">${E(job.org)} · Sample</span><button class="icon-button" data-action="save" data-value="${E(job.id)}" aria-label="${saved?'Unsave':'Save'} ${E(job.title)}" aria-pressed="${saved}">${icon(saved?'check':'bookmark')}</button></div><h3>${E(job.title)}</h3><p class="collider-result-pay">${E(job.pay)}</p><p class="collider-result-location">${E(job.location)} · ${E(job.detail)}</p>${reasons.length?`<details class="collider-why"><summary>${icon('spark')}Why this match</summary><ul>${reasons.map(reason=>`<li>${E(reason)}</li>`).join('')}</ul>${meta.salaryNote?`<p>${E(meta.salaryNote)}</p>`:''}<p>Source: ${E(meta.source)}. Interest overlap is not a qualification assessment.</p></details>`:`<p class="collider-why">Saved job · ${E(meta.source)}</p>`}<button class="button secondary" data-action="detail" data-value="${E(job.id)}">View opportunity ${icon('arrow')}</button></article>`;
  }
  function screen(){
    const state=getState(),p=prefs(),jobs=allPosts(state);
    const matches=matchColliderJobs(jobs,p,state);
    const saved=jobs.filter(job=>job.type==='job'&&state.saved.includes(job.id)&&!state.blocked.includes(job.author)&&!state.muted.includes(job.author)).map(job=>({job,reasons:[],meta:jobMetadata(job)}));
    const rows=selectedTab==='saved'?saved:matches;
    const salary=p.minSalary?`${p.currency} ${Number(p.minSalary).toLocaleString('en')}+ / year`:'';
    return `<div class="collider-page"><section class="collider-console"><div class="collider-console-head"><span class="collider-kicker">LYNK / COLLIDER</span>${icon('collider')}</div><h1>Find where<br>you belong next.</h1><p>Jobs shaped around your interests and ambitions.</p><div class="collider-summary">${p.interests.map(x=>`<span>${E(x)}</span>`).join('')||'<span>Add your interests</span>'}</div><div class="collider-summary-detail">${E([p.role,p.region,p.mode==='Any'?'Any work style':p.mode,salary].filter(Boolean).join(' · '))}</div><div class="collider-actions"><button class="button accent" data-action="collider-find">Find my matches ${icon('arrow')}</button><button class="button secondary" data-action="collider-preferences">Edit interests</button></div></section><p class="collider-source">${icon('file')}<span>Preview · sample jobs only. Interests and pay preferences stay in this browser.</span></p><div class="tabs" role="group" aria-label="Collider results"><button class="tab ${selectedTab==='matches'?'active':''}" data-action="collider-tab" data-value="matches" aria-pressed="${selectedTab==='matches'}">Matches</button><button class="tab ${selectedTab==='saved'?'active':''}" data-action="collider-tab" data-value="saved" aria-pressed="${selectedTab==='saved'}">Saved jobs · ${saved.length}</button></div><div class="collider-results-head"><h2>${selectedTab==='saved'?'Your shortlist':p.hasSearched?'Your matches':'Based on your interests'}</h2><span>${rows.length} ${rows.length===1?'job':'jobs'}</span></div>${rows.length?rows.map(result).join(''):`<div class="empty">${icon(selectedTab==='saved'?'bookmark':'search')}<h3>${selectedTab==='saved'?'Keep a possibility':'No sample jobs match yet'}</h3><p>${selectedTab==='saved'?'Save a job from your matches to find it here.':'Try broader interests, another region or a different pay target.'}</p><button class="button secondary" data-action="${selectedTab==='saved'?'collider-find':'collider-preferences'}">${selectedTab==='saved'?'See matches':'Edit preferences'}</button></div>`}</div>`;
  }
  function snapshot(){
    const form=document.getElementById('colliderForm');
    if(form)draft={...draft,...Object.fromEntries(new FormData(form)),includeUndisclosed:form.elements.includeUndisclosed.checked};
    return draft;
  }
  function preferences(reset=true){
    if(reset||!draft)draft={...prefs(),interests:[...prefs().interests],newInterest:''};
    const d=draft;
    openModal('Tune your Collider',`<form id="colliderForm"><p class="collider-form-intro">What would make your next opportunity worth exploring?</p><label class="field"><span>Your interests and skills · up to 8</span></label><div class="collider-interest-list">${d.interests.map(x=>`<button type="button" class="chip active" data-action="collider-remove-interest" data-value="${E(x)}" aria-label="Remove ${E(x)}">${E(x)} ×</button>`).join('')||'<p class="subtext">Choose a topic below or add your own.</p>'}</div><div class="collider-interest-add"><input class="control" name="newInterest" maxlength="40" value="${E(d.newInterest||'')}" placeholder="Add an interest…" aria-label="New interest"><button type="button" class="button secondary" data-action="collider-add-interest">Add</button></div><p class="collider-form-caption">For example: healthcare, leadership, product design or sales.</p><div class="collider-interest-list">${colliderSuggestions.filter(x=>!d.interests.some(y=>y.toLowerCase()===x.toLowerCase())).slice(0,6).map(x=>`<button type="button" class="chip" data-action="collider-add-interest" data-value="${E(x)}">+ ${E(x)}</button>`).join('')}</div><label class="field"><span>Preferred job title · optional</span><input class="control" name="role" value="${E(d.role)}" maxlength="80" placeholder="e.g. Product designer or CEO"></label><div class="collider-form-grid"><label class="field"><span>Job region</span><select class="control" name="region">${colliderRegions.map(x=>option(x,d.region)).join('')}</select></label><label class="field"><span>Work style</span><select class="control" name="mode">${['Any','Remote','Hybrid','On-site'].map(x=>option(x,d.mode)).join('')}</select></label><label class="field"><span>Target currency</span><select class="control" name="currency">${colliderCurrencies.map(x=>option(x,d.currency)).join('')}</select></label><label class="field"><span>Minimum annual pay</span><input class="control" name="minSalary" type="number" min="1" max="9999999999" step="1" inputmode="numeric" value="${E(d.minSalary)}" placeholder="Optional"></label></div><p class="collider-form-caption">Matches ranges that reach your target in the same currency. No currency conversion or salary guarantee.</p><label class="check-row"><input type="checkbox" name="includeUndisclosed" ${d.includeUndisclosed?'checked':''}><span>Include jobs without disclosed pay</span></label><div id="colliderError" class="collider-form-error" role="alert"></div><button class="button accent full" type="submit">Save interests & find jobs ${icon('arrow')}</button><p class="collider-form-caption">These preferences are private to this demo and are not added to your public Passport.</p></form>`,{type:'collider-preferences'});
  }
  function addInterest(value){
    const term=String(value||'').trim().replace(/\s+/g,' ').slice(0,40);
    if(!term)return;
    if(draft.interests.some(x=>x.toLowerCase()===term.toLowerCase())){draft.newInterest='';return;}
    if(draft.interests.length>=8)throw Error('Choose up to eight interests. Remove one to add another.');
    draft.interests.push(term);draft.newInterest='';
  }
  function handleAction(action,value){
    if(!action.startsWith('collider-'))return false;
    try{
      if(action==='collider-preferences')preferences();
      if(action==='collider-tab'){selectedTab=value==='saved'?'saved':'matches';render({keepScroll:false});}
      if(action==='collider-find'){
        if(!prefs().interests.length&&!prefs().role){preferences();return true;}
        getState().collider={...prefs(),hasSearched:true};selectedTab='matches';persist();render({keepScroll:false});notify('Matches updated from the sample catalog');
      }
      if(action==='collider-add-interest'){snapshot();addInterest(value||draft.newInterest);preferences(false);}
      if(action==='collider-remove-interest'){snapshot();draft.interests=draft.interests.filter(x=>x!==value);preferences(false);}
    }catch(error){const field=document.getElementById('colliderError');if(field)field.textContent=error.message;else notify(error.message);}
    return true;
  }
  function handleSubmit(form){
    if(form.id!=='colliderForm')return false;
    try{
      snapshot();if(draft.newInterest?.trim())addInterest(draft.newInterest);
      const next=normalizeCollider({...draft,hasSearched:true},getState().profile);
      if(!next.interests.length&&!next.role)throw Error('Add an interest or a preferred job title.');
      getState().collider=next;selectedTab='matches';persist();navigate('collider');notify('Your interests are saved. Explore your matches.');
    }catch(error){document.getElementById('colliderError').textContent=error.message;}
    return true;
  }
  return {entry,screen,handleAction,handleSubmit,reset(){draft=null;selectedTab='matches';}};
}
