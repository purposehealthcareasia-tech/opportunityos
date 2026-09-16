// Illustrative job inventory. No live crawling, employer connection or currency conversion.
const specs = [
  ['design','Senior product designer','Northstar Studio','maya','Product design,Prototyping,Design systems','India','Remote','INR',2800000,4200000,'Shape a thoughtful product used by growing teams.','Senior · Full-time'],
  ['frontend','Frontend engineer','Meridian Works','leena','Engineering,Frontend,React,Product','India','Hybrid','INR',2400000,3600000,'Build accessible interfaces with designers and product teams.','Mid-level · Full-time'],
  ['ai','Applied AI engineer','Signal Foundry','leena','AI,Engineering,Python,Machine learning','United States','Remote','USD',140000,190000,'Turn machine-learning experiments into useful customer experiences.','Senior · Full-time'],
  ['growth','Growth marketing manager','Fieldnotes','neha','Marketing,Growth,Analytics,Writing','United Kingdom','Hybrid','GBP',65000,85000,'Lead campaigns and help a small brand reach the right people.','Manager · Full-time'],
  ['operations','Operations manager','Common Supply','omar','Operations,Leadership,Logistics','India','On-site','INR',1800000,2600000,'Improve service delivery, team routines and operational quality.','Manager · Full-time'],
  ['finance','Finance analyst','Harbour Systems','omar','Finance,Analytics,Excel','Singapore','Hybrid','SGD',70000,95000,'Build clear forecasts and help teams understand their decisions.','Mid-level · Full-time'],
  ['health','Healthcare product manager','Carepath Labs','maya','Healthcare,Product,Leadership','India','Hybrid','INR',3000000,4500000,'Work with care teams to design better patient and provider journeys.','Senior · Full-time'],
  ['sales','Enterprise account executive','Orbit Commerce','neha','Sales,Enterprise,Customer success','United Arab Emirates','On-site','AED',240000,360000,'Develop customer relationships and lead complex account conversations.','Senior · Full-time'],
  ['director','Design director','Forma Collective','maya','Product design,Leadership,Strategy','United Kingdom','Remote','GBP',100000,140000,'Coach a design team and set direction across a growing product portfolio.','Director · Full-time'],
  ['ceo','Chief executive officer','Horizon Ventures','omar','Leadership,Strategy,Operations,Finance','Singapore','On-site','SGD',240000,340000,'Set company direction and build an accountable leadership team.','Executive · Full-time'],
  ['research','UX researcher','Openfield','ishan','Research,Product design,Psychology','Worldwide','Remote','USD',null,null,'Help a distributed team understand people and test product assumptions.','Mid-level · Full-time'],
  ['community','Community manager','Gather House','commons','Community,Writing,Events,Marketing','India','Remote','INR',1000000,1500000,'Connect a creative community through useful programs and conversations.','Mid-level · Full-time']
];
const money=(value,currency)=>new Intl.NumberFormat('en',{style:'currency',currency,maximumFractionDigits:0}).format(value);
export const colliderCatalog=specs.map(([key,title,org,author,topics,region,mode,currency,min,max,text,detail])=>({
  id:'lc-'+key,author,type:'job',title,org,text,tags:topics.split(',').slice(0,3).map(x=>x.replaceAll(' ','')),skills:topics.split(','),
  location:region+' · '+mode,remote:mode==='Remote',paid:true,pay:min===null?'Compensation not disclosed':money(min,currency)+'–'+money(max,currency)+' / year',
  deadline:'Illustrative opening · no live deadline',detail,age:'Sample',likes:0,reposts:0,comments:[],tone:'sky',
  colliderMeta:{interests:topics.split(','),region,mode,currency,min,max,source:'FYND sample catalog'}
}));
export const colliderRegions=['Anywhere','India','United States','United Kingdom','Singapore','United Arab Emirates'];
export const colliderCurrencies=['INR','USD','GBP','EUR','SGD','AED'];
export const colliderSuggestions=['Product design','Engineering','AI','Marketing','Leadership','Finance','Healthcare','Operations','Sales','Research','Community'];
const clean=value=>String(value??'').trim().replace(/\s+/g,' ');
const norm=value=>clean(value).toLocaleLowerCase();
export function initialCollider(profile={}){return {interests:(profile.skills||['Product design','Prototyping']).slice(0,6),role:'',region:'Anywhere',mode:'Any',currency:'INR',minSalary:'',includeUndisclosed:false,hasSearched:false};}
export function normalizeCollider(value,profile={}){
  const defaults=initialCollider(profile),v=value&&typeof value==='object'?value:{};
  const source=Array.isArray(v.interests)?v.interests:defaults.interests;
  const seen=new Set();
  const interests=source.map(x=>clean(x).slice(0,40)).filter(x=>{const key=norm(x);if(!key||seen.has(key))return false;seen.add(key);return true;}).slice(0,8);
  const salary=String(v.minSalary??'');
  return {interests,role:clean(v.role).slice(0,80),region:colliderRegions.includes(v.region)?v.region:'Anywhere',mode:['Any','Remote','Hybrid','On-site'].includes(v.mode)?v.mode:'Any',currency:colliderCurrencies.includes(v.currency)?v.currency:'INR',minSalary:/^\d{1,10}$/.test(salary)&&Number(salary)>0?String(Number(salary)):'',includeUndisclosed:v.includeUndisclosed===true||v.includeUndisclosed==='on',hasSearched:v.hasSearched===true};
}
const aliases={engineering:['engineer','engineering','frontend','software'],ai:['ai','machine learning','artificial intelligence'],design:['design','designer','ux'],leadership:['leadership','manager','director','executive'],healthcare:['healthcare','care','health'],ceo:['chief executive officer']};
function matchesInterest(interest,p,meta){
  const words=value=>' '+norm(value).replace(/[^\p{L}\p{N}]+/gu,' ').trim()+' ';
  const haystack=words([p.title,p.text,...(p.skills||[]),...(meta.interests||[])].join(' '));
  const key=norm(interest);
  return (aliases[key]||[key]).some(term=>haystack.includes(words(term)));
}
export function jobMetadata(p){
  if(p.colliderMeta)return p.colliderMeta;
  if(p.id==='p1')return {interests:p.skills,region:'India',mode:'Remote',currency:'INR',min:3000000,max:4500000,source:'FYND sample post'};
  if(p.id==='p6')return {interests:p.skills,region:'India',mode:'Hybrid',currency:'INR',min:216000,max:216000,source:'FYND sample post',salaryNote:'₹18,000 / month = ₹216,000 annualized'};
  return {interests:p.skills||[],region:p.location||'',mode:p.remote?'Remote':/hybrid/i.test(p.location||'')?'Hybrid':'On-site',currency:null,min:null,max:null,source:p.local?'Your local post':'FYND sample post'};
}
export function matchColliderJobs(posts,preferences,{blocked=[],muted=[]}={}){
  const p=normalizeCollider(preferences),minimum=Number(p.minSalary)||0;
  if(!p.interests.length&&!p.role)return [];
  return posts.filter(job=>job.type==='job'&&job.author!=='me'&&!blocked.includes(job.author)&&!muted.includes(job.author)).flatMap(job=>{
    const meta=jobMetadata(job),hits=p.interests.filter(x=>matchesInterest(x,job,meta));
    if(p.interests.length&&!hits.length)return [];
    const roleQuery=({ceo:'chief executive officer',cto:'chief technology officer',cfo:'chief financial officer'})[norm(p.role)]||norm(p.role);
    if(roleQuery&&!roleQuery.split(' ').every(term=>norm(job.title).includes(term)))return [];
    if(p.region!=='Anywhere'&&meta.region!=='Worldwide'&&!norm(meta.region).includes(norm(p.region)))return [];
    if(p.mode!=='Any'&&meta.mode!==p.mode)return [];
    const disclosed=Number.isFinite(meta.max)&&meta.currency;
    if(minimum&&disclosed&&(meta.currency!==p.currency||meta.max<minimum))return [];
    if(!disclosed&&!p.includeUndisclosed)return [];
    const reasons=[...hits.slice(0,3).map(x=>'Interest: '+x)];
    if(p.role)reasons.push('Title includes '+p.role);
    if(p.region!=='Anywhere')reasons.push(meta.region==='Worldwide'?'Worldwide remote listing':'Region: '+meta.region);
    if(p.mode!=='Any')reasons.push(meta.mode+' work');
    if(minimum)reasons.push(disclosed?'Published range reaches your target':'Compensation undisclosed — confirm with employer');
    return [{job,reasons,meta,order:hits.length}];
  }).sort((a,b)=>b.order-a.order||a.job.title.localeCompare(b.job.title));
}
