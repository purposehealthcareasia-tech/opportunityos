// One inventory for navigation on phones, tablets and PCs.
export function toolItems(mode='member'){
 return [['collider','globe','Lynk Collider','Find jobs for your interests'],['saved','bookmark',mode==='demo'?'Saved & interest':'Saved','Return to your opportunities'],
 ...(mode==='demo'?[['notifications','bell','Activity','Your latest updates'],['progress','chart','Progress','Review your career progress'],['research','spark','Research','Explore your research notebook']]:[]),
 ['settings','settings','Settings','Manage your account and preferences']];
}
export function desktopNavigation(view,mode,icon){
 const buttons=items=>items.map(([id,glyph,label])=>`<button class="workspace-nav ${view===id?'active':''}" data-action="navigate" data-value="${id}" aria-label="${label}" title="${label}" ${view===id?'aria-current="page"':''}>${icon(glyph)}<span>${label}</span></button>`).join('');
 return `<div class="navigation-group">${buttons([['feed','home','Feed'],['discover','search','Discover'],['inbox','mail','Inbox'],['profile','user','Passport']])}</div><div class="navigation-group"><p class="navigation-label">YOUR TOOLS</p>${buttons(toolItems(mode))}</div><button class="workspace-create" data-action="compose" aria-label="Create a post" title="Create a post">${icon('plus')}<span>Create a post</span></button>`;
}
export function toolsMarkup(mode,icon){return `<div class="tools-grid">${toolItems(mode).map(([id,glyph,label,description])=>`<button class="tool-shortcut" data-action="navigate" data-value="${id}"><span class="tool-glyph">${icon(glyph)}</span><span><strong>${label}</strong><small>${description}</small></span>${icon('arrow')}</button>`).join('')}</div>`;}
